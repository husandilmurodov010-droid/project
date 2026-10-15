"""v13 yangi funksiyalari uchun testlar.

Sinovdan o'tkazadi:
  * Pastdagi doimiy reply-keyboard paneli (Start / Asosiy menyu / Eslatma / Reset / Kanal)
  * Majburiy kanal (subscription gate) — getChatMember tekshiruvi va «Tekshirish» oqimi
  * Tabiiy tildagi eslatma tahlili ("ertaga soat 12 da ...")
  * Asosiy menyuda quizlar va AI bo'limlari mavjudligi
  * Tools bo'limida eski tugmalar yo'qligi
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "123456:TEST_DUMMY_TOKEN")
os.environ.setdefault("GEMINI_API_KEYS", "dummy_key_1,dummy_key_2")
os.environ.setdefault("ADMIN_ID", "883800311")
os.environ.setdefault("ADMIN_USERNAME", "Husan_Dilmurodov")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot as B  # noqa: E402
import config  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {extra}" if extra else ""))


async def main() -> None:
    print("=" * 70)
    print("AI Manager Bot v13 — yangi funksiyalar sinovi")
    print("=" * 70)

    # ---------------------------------------------------------------- #
    print("\n[1] Pastdagi doimiy panel (reply keyboard)")
    kb = B.main_reply_kb()
    texts = [b.text for row in kb.keyboard for b in row]
    check("Panel turi ReplyKeyboardMarkup", type(kb).__name__ == "ReplyKeyboardMarkup")
    check("resize_keyboard yoqilgan", getattr(kb, "resize_keyboard", False) is True)
    check("is_persistent yoqilgan", getattr(kb, "is_persistent", False) is True)
    check("«Start» tugmasi bor", any("Start" in t for t in texts))
    check("«Asosiy menyu» tugmasi bor", any("Asosiy menyu" in t for t in texts))
    check("«Suhbatni tozalash» tugmasi bor", any("tozalash" in t for t in texts))
    check("«Kanalga ulanish» tugmasi bor", any("Kanalga" in t for t in texts))
    check("Kamida 4 tugma", len(texts) >= 4, f"{len(texts)} ta")

    # ---------------------------------------------------------------- #
    print("\n[2] Majburiy kanal (subscription gate) sozlamalari")
    check("ENABLE_SUB_GATE yoqilgan", config.ENABLE_SUB_GATE is True)
    check("Kanal URL to'g'ri",
          config.REQUIRED_CHANNEL_URL == "https://t.me/matmilliysertifikat",
          config.REQUIRED_CHANNEL_URL)
    check("Kanal ID (@username)",
          config.REQUIRED_CHANNEL_ID == "@matmilliysertifikat",
          config.REQUIRED_CHANNEL_ID)

    # Klaviatura
    gkb = B.sub_gate_kb()
    gtexts = [b.text for row in gkb.inline_keyboard for b in row]
    check("Gate'da «Kanalga ulanish» URL tugmasi bor", any("Kanalga ulanish" in t for t in gtexts))
    check("Gate'da «Tekshirish» tugmasi bor", any("Tekshirish" in t for t in gtexts))

    # getChatMember mantiqi (bot chaqiruvini soxtalashtiramiz)
    async def make_member(status: str):
        class M:
            pass
        m = M()
        m.status = status
        return m

    orig = B.bot.get_chat_member

    async def fake_member(chat_id, user_id):
        return await make_member("member")

    async def fake_left(chat_id, user_id):
        return await make_member("left")

    B.bot.get_chat_member = fake_member
    check("A'zo bo'lsa — is_subscribed True", await B.is_subscribed(999999) is True)
    B.bot.get_chat_member = fake_left
    check("A'zo bo'lmasa — is_subscribed False", await B.is_subscribed(999999) is False)
    check("Admin har doim True (gate'siz)", await B.is_subscribed(config.ADMIN_IDS[0]) is True)
    B.bot.get_chat_member = orig

    # ---------------------------------------------------------------- #
    print("\n[3] Tabiiy tildagi eslatma tahlili")
    now = datetime.now()

    r = B.parse_reminder_natural("ertaga soat 12 da matematika darsini takrorlash")
    check("«ertaga soat 12 da ...» tahlil qilindi", r is not None, str(r))
    if r:
        body, ts = r
        dt = datetime.fromtimestamp(ts)
        check("Ertaga (kun +1)", dt.date() == (now + timedelta(days=1)).date(), str(dt.date()))
        check("Soat 12", dt.hour == 12, f"hour={dt.hour}")
        check("Matn tozalandi", "matematika" in body, body)

    r2 = B.parse_reminder_natural("30 daqiqadan keyin suv ichish")
    check("«30 daqiqadan keyin ...» tahlil qilindi", r2 is not None, str(r2))
    if r2:
        _b, ts2 = r2
        diff = abs(ts2 - now.timestamp() - 30 * 60)
        check("~30 daqiqa keyin", diff < 90, f"diff={diff:.0f}s")

    r3 = B.parse_reminder_natural("2 soatdan so'ng dori ichish")
    check("«2 soatdan so'ng ...» tahlil qilindi", r3 is not None, str(r3))

    r4 = B.parse_reminder_natural("bugun kechqurun soat 20 da uchrashuv")
    check("«kechqurun soat 20 da ...» tahlil qilindi", r4 is not None, str(r4))
    if r4:
        _b4, ts4 = r4
        check("Kechqurun -> 20:00", datetime.fromtimestamp(ts4).hour == 20)

    check("Vaqtsiz matn = None", B.parse_reminder_natural("oddiy savol beraman") is None)

    # looks_like_reminder
    check("Intent: «soat 12 da ... qilaman» True",
          B.looks_like_reminder("ertaga soat 12 da dars qilaman") is True)
    check("Intent: oddiy savol False",
          B.looks_like_reminder("Python nima?") is False)

    # ---------------------------------------------------------------- #
    print("\n[4] Asosiy menyu — kerakli bo'limlar")
    mkb = B.main_menu_kb()
    mtexts = [b.text for b in [bb for row in mkb.inline_keyboard for bb in row]]
    check("AI bilan ishlash bor", any("AI bilan ishlash" in t for t in mtexts))
    check("Testlar (quiz) bor", any("Testlar" in t for t in mtexts))
    check("IELTS Speaking bor", any("Speaking" in t for t in mtexts))
    check("IELTS Writing bor", any("Writing" in t for t in mtexts))
    check("Matematika bor", any("Matematika" in t for t in mtexts))
    check("Fizika bor", any("Fizika" in t for t in mtexts))
    check("Suhbatni tozalash (reset) bor", any("tozalash" in t for t in mtexts))

    # ---------------------------------------------------------------- #
    print("\n[5] Tools — eski tugmalar olib tashlangan")
    tkb = B.tools_kb()
    ttexts = [b.text for b in [bb for row in tkb.inline_keyboard for bb in row]]
    check("«Ovozli rejim» yo'q", not any("Ovozli rejim" in t for t in ttexts))
    check("«Rasm» tugmasi yo'q", not any(t.strip() == "🖼 Rasm" for t in ttexts))
    check("«Savollar banki» yo'q", not any("Savollar banki" in t for t in ttexts))

    # ---------------------------------------------------------------- #
    print("\n" + "=" * 70)
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
