"""Suhbat xotirasi (conversation memory) uchun testlar (v11).

Sinovdan o'tkazadi:
  * `get_context_history` — xronologik tartib, faqat user/assistant
  * `clear_history` — kontekstni tozalash
  * `GeminiPool.generate(history=...)` — tarixni `contents` ga to'g'ri qo'shish
  * Rollar mapping: assistant -> model, user -> user
  * Kontekst uzluksizligi: ketma-ket xabarlar bir-biriga bog'lanishi
  * Menyu: "🔄 Suhbatni tozalash" tugmasi va `menu:reset` handleri
  * `/reset` buyrug'i mavjudligi
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("BOT_TOKEN", "123456:TEST_DUMMY_TOKEN")
os.environ.setdefault("GEMINI_API_KEYS", "dummy_key_1,dummy_key_2")
os.environ.setdefault("ADMIN_ID", "883800311")
os.environ.setdefault("ADMIN_USERNAME", "Husan_Dilmurodov")

import bot  # noqa: E402
from database import Database  # noqa: E402
from gemini_pool import GeminiPool  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


# --------------------------------------------------------------------------- #
# 1) Baza: get_context_history
# --------------------------------------------------------------------------- #
async def test_context_history() -> None:
    print("\n[1] Baza — get_context_history")
    tmp = tempfile.mktemp(suffix=".db")
    db = Database(tmp)
    await db.connect()
    try:
        uid = 111
        await db.upsert_user(uid, "tester", "Test")
        # 4 ta qatlam yozamiz
        await db.add_history(uid, "user", "misol ishlab ber", source="ai")
        await db.add_history(uid, "assistant", "Mana misol: 2+2=4", source="ai")
        await db.add_history(uid, "user", "tahlil qilib ber", source="ai")
        await db.add_history(uid, "assistant", "Tahlil: ...", source="ai")

        ctx = await db.get_context_history(uid, limit=6)
        check("kontekst 4 ta qatlam", len(ctx) == 4, f"len={len(ctx)}")
        check("xronologik: birinchi = user 'misol ishlab ber'",
              ctx[0]["role"] == "user" and "misol" in ctx[0]["text"])
        check("xronologik: oxirgi = assistant 'Tahlil'",
              ctx[-1]["role"] == "assistant" and "Tahlil" in ctx[-1]["text"])
        check("rollar to'g'ri (user/assistant)",
              [c["role"] for c in ctx] == ["user", "assistant", "user", "assistant"])

        # limit ishlashi
        ctx2 = await db.get_context_history(uid, limit=2)
        check("limit=2 -> oxirgi 2 ta", len(ctx2) == 2, f"len={len(ctx2)}")
        check("limit=2 xronologik tartibda",
              ctx2[0]["role"] == "user" and ctx2[1]["role"] == "assistant")

        # clear_history
        await db.clear_history(uid)
        ctx3 = await db.get_context_history(uid, limit=6)
        check("clear_history -> bo'sh", len(ctx3) == 0, f"len={len(ctx3)}")

        # boshqa foydalanuvchi aralashmasligi
        await db.add_history(uid, "user", "A xabari", source="ai")
        await db.upsert_user(999, "other", "Other")
        await db.add_history(999, "user", "B xabari", source="ai")
        ctxA = await db.get_context_history(uid, limit=6)
        check("foydalanuvchilar aralashmaydi",
              len(ctxA) == 1 and "A xabari" in ctxA[0]["text"])
    finally:
        await db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# 2) GeminiPool — history payload
# --------------------------------------------------------------------------- #
async def test_pool_history_payload() -> None:
    print("\n[2] GeminiPool — history payload")
    pool = GeminiPool(
        keys=["k1"], models=["m1"], base_url="https://example.invalid"
    )
    captured: dict = {}

    async def fake_post(key, path, payload):
        captured["payload"] = payload
        return {"candidates": [{"content": {"parts": [{"text": "javob"}]}}]}

    pool._post = fake_post  # type: ignore[assignment]

    history = [
        {"role": "user", "text": "misol ishlab ber"},
        {"role": "assistant", "text": "Mana misol: 2+2=4"},
    ]
    out = await pool.generate("tahlil qil", history=history)
    check("javob qaytdi", out == "javob", repr(out))

    contents = captured["payload"]["contents"]
    check("contents 3 ta (2 tarix + 1 joriy)", len(contents) == 3, f"len={len(contents)}")
    check("1-qatlam role=user", contents[0]["role"] == "user")
    check("2-qatlam role=model (assistant->model)", contents[1]["role"] == "model")
    check("2-qatlam matni to'g'ri",
          contents[1]["parts"][0]["text"] == "Mana misol: 2+2=4")
    check("3-qatlam (joriy) role=user", contents[2]["role"] == "user")
    check("3-qatlam matni = joriy so'rov",
          contents[2]["parts"][0]["text"] == "tahlil qil")

    # history yo'q bo'lsa — faqat 1 ta
    captured.clear()
    await pool.generate("salom")
    check("history yo'q -> 1 ta content",
          len(captured["payload"]["contents"]) == 1)

    # bo'sh matnli qatlamlar tashlanadi
    captured.clear()
    await pool.generate("x", history=[{"role": "user", "text": ""},
                                      {"role": "user", "text": "  "}])
    check("bo'sh qatlamlar tashlanadi",
          len(captured["payload"]["contents"]) == 1)

    # 'model' roli ham qabul qilinadi
    captured.clear()
    await pool.generate("x", history=[{"role": "model", "text": "eski javob"}])
    check("'model' roli -> model",
          captured["payload"]["contents"][0]["role"] == "model")


# --------------------------------------------------------------------------- #
# 3) Kontekst uzluksizligi (haqiqiy oqim simulyatsiyasi)
# --------------------------------------------------------------------------- #
async def test_context_continuity() -> None:
    print("\n[3] Kontekst uzluksizligi — ketma-ket xabarlar")
    tmp = tempfile.mktemp(suffix=".db")
    db = Database(tmp)
    await db.connect()
    try:
        uid = 222
        await db.upsert_user(uid, "tester2", "Test2")

        # 1-xabar: "misol ishlab ber"
        ctx1 = await db.get_context_history(uid, limit=6)
        check("1-xabar: kontekst bo'sh", len(ctx1) == 0)
        await db.add_history(uid, "user", "misol ishlab ber", source="ai")
        await db.add_history(uid, "assistant", "Mana misol: 5x5=25", source="ai")

        # 2-xabar: "tahlil qilib ber" — kontekstda 1-misol bo'lishi kerak
        ctx2 = await db.get_context_history(uid, limit=6)
        check("2-xabar: kontekstda 2 ta qatlam", len(ctx2) == 2, f"len={len(ctx2)}")
        joined = " ".join(c["text"] for c in ctx2)
        check("2-xabar: oldingi misol kontekstda bor", "5x5=25" in joined)
        check("2-xabar: oldingi so'rov kontekstda bor", "misol ishlab ber" in joined)

        # 3-xabar: "davom et" — endi 4 ta qatlam
        await db.add_history(uid, "user", "tahlil qilib ber", source="ai")
        await db.add_history(uid, "assistant", "Tahlil: 5x5=25 ...", source="ai")
        ctx3 = await db.get_context_history(uid, limit=6)
        check("3-xabar: kontekstda 4 ta qatlam", len(ctx3) == 4, f"len={len(ctx3)}")
        check("3-xabar: eng eski qatlam saqlanib qolgan",
              "misol ishlab ber" in ctx3[0]["text"])

        # HISTORY_CONTEXT_SIZE chegarasi
        check("HISTORY_CONTEXT_SIZE config'da bor",
              hasattr(bot.config, "HISTORY_CONTEXT_SIZE"))
        check("HISTORY_CONTEXT_SIZE > 0", bot.config.HISTORY_CONTEXT_SIZE > 0)
    finally:
        await db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# 4) Menyu va handlerlar
# --------------------------------------------------------------------------- #
def test_menu_and_handlers() -> None:
    print("\n[4] Menyu va handlerlar")
    kb = bot.main_menu_kb()
    texts = [b.text for row in kb.inline_keyboard for b in row]
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("menyuda '🔄 Suhbatni tozalash' bor",
          any("Suhbatni tozalash" in t for t in texts), str(texts))
    check("callback_data 'menu:reset' bor", "menu:reset" in datas, str(datas))

    # handler mavjudligi
    check("on_menu_reset handleri bor", hasattr(bot, "on_menu_reset"))
    check("cmd_reset handleri bor", hasattr(bot, "cmd_reset"))

    # SYSTEM_PROMPT kontekst haqida gapiradi
    sp = bot.SYSTEM_PROMPT
    check("SYSTEM_PROMPT suhbat xotirasini eslatadi",
          "SUHBAT XOTIRASI" in sp or "xotira" in sp.lower())
    check("SYSTEM_PROMPT 'davom et' ni qamraydi", "davom et" in sp)
    check("SYSTEM_PROMPT 'tahlil qil' ni qamraydi", "tahlil qil" in sp)

    # _ask_gemini endi matn qaytaradi
    import inspect
    src = inspect.getsource(bot._ask_gemini)
    check("_ask_gemini javobni qaytaradi (return answer)", "return answer" in src)


# --------------------------------------------------------------------------- #
# 5) Haqiqiy Gemini bilan kontekst (ixtiyoriy — kalit bo'lsa)
# --------------------------------------------------------------------------- #
async def test_real_gemini_context() -> None:
    print("\n[5] Haqiqiy Gemini — kontekst eslab qolishi (ixtiyoriy)")
    keys = [k for k in bot.config.GEMINI_API_KEYS if not k.startswith("dummy")]
    if not keys:
        print("  ⏭  Haqiqiy kalit yo'q — o'tkazib yuborildi")
        return
    pool = GeminiPool(
        keys=keys,
        models=bot.config.GEMINI_MODELS,
        base_url=bot.config.GEMINI_BASE_URL,
        timeout=bot.config.REQUEST_TIMEOUT,
    )
    await pool.start()
    try:
        # 1) misol ber
        a1 = await pool.generate(
            "5x5 nechaga teng? Faqat javobni yoz.",
            system_instruction=bot.SYSTEM_PROMPT,
        )
        check("1-javob olindi", bool(a1), repr(a1[:60]))
        # 2) kontekst bilan "tahlil qil"
        hist = [
            {"role": "user", "text": "5x5 nechaga teng? Faqat javobni yoz."},
            {"role": "assistant", "text": a1},
        ]
        a2 = await pool.generate(
            "Shu javobni tahlil qil, qanday hisoblaganingni tushuntir.",
            system_instruction=bot.SYSTEM_PROMPT,
            history=hist,
        )
        check("2-javob olindi (kontekst bilan)", bool(a2), repr(a2[:60]))
        check("2-javob oldingi mavzuga bog'liq (25 yoki 5x5)",
              ("25" in a2) or ("5" in a2), repr(a2[:120]))
    except Exception as exc:  # noqa: BLE001
        check("Haqiqiy Gemini sinovi", False, str(exc)[:150])
    finally:
        await pool.close()


async def main() -> None:
    await test_context_history()
    await test_pool_history_payload()
    await test_context_continuity()
    test_menu_and_handlers()
    await test_real_gemini_context()
    print(f"\n{'='*50}")
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print(f"{'='*50}")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
