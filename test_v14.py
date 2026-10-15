"""v14 testi — ikkita o'zgarishni tekshiradi.

1) «🔄 Suhbatni tozalash» — FAQAT shu foydalanuvchining suhbat tarixini
   o'chiradi; boshqa foydalanuvchilarniki tegilmaydi.
2) «⬅️ Bosh menyu» va «🏠 Asosiy menyu» dublikati olib tashlandi — endi
   hamma joyda yagona «🏠 Asosiy menyu» ishlatiladi.

Ishga tushirish:  timeout 90 python test_v14.py
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN_FOR_IMPORT_ONLY")
os.environ.setdefault("GEMINI_API_KEYS", "test-key-import-only")
os.environ.setdefault("ENABLE_SUB_GATE", "false")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "v14_test.db"))
os.environ.setdefault("ENABLE_VOICE", "false")

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


async def main() -> None:
    import bot as B
    import config

    nav = ["nav:back", "menu:main"]

    # ------------------------------------------------------------------ #
    print("\n[1] Klaviatura quruvchilari — dublikat yo'q, nav tugmalari bor")
    builders = {
        "speaking_kb": B.speaking_kb(),
        "writing_kb": B.writing_kb(),
        "subject_kb": B.subject_kb("math"),
        "tools_kb": B.tools_kb(),
        "qadd_type_kb": B.qadd_type_kb(),
        "qadd_speaking_part_kb": B.qadd_speaking_part_kb(),
        "qadd_writing_task_kb": B.qadd_writing_task_kb(),
        "channel_kb": B.channel_kb(),
        "reminders_kb": B.reminders_kb(),
        "stats_admin_kb": B.stats_admin_kb(),
        "testadd_subject_kb": B.testadd_subject_kb(),
    }
    for name, markup in builders.items():
        texts = [b.text for row in markup.inline_keyboard for b in row]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        # _with_back dan keyingi holat
        wrapped = B._with_back(markup)
        wcbs = [b.callback_data for row in wrapped.inline_keyboard for b in row]
        wtexts = [b.text for row in wrapped.inline_keyboard for b in row]
        check(f"{name}: 'Bosh menyu' yo'q", not any("Bosh menyu" in t for t in texts),
              f"({[t for t in texts if 'Bosh menyu' in t]})")
        check(f"{name}: nav:back bor", "nav:back" in wcbs)
        check(f"{name}: menu:main bor", "menu:main" in wcbs)
        check(f"{name}: nav tugmalari takrorlanmaydi",
              wcbs.count("nav:back") == 1 and wcbs.count("menu:main") == 1,
              f"(back={wcbs.count('nav:back')}, main={wcbs.count('menu:main')})")
        check(f"{name}: 'Asosiy menyu' yagona nomlanish",
              wtexts.count("🏠 Asosiy menyu") == 1,
              f"(={wtexts.count('🏠 Asosiy menyu')})")

    # Asosiy menyu o'ziga nav tugmasini qo'shmaydi
    mm = B.main_menu_kb(False)
    wmm = B._with_back(mm)
    wcbs = [b.callback_data for row in wmm.inline_keyboard for b in row]
    check("main_menu_kb: ortiqcha tugma qo'shilmaydi",
          "nav:back" not in wcbs and wcbs.count("menu:main") == 0)

    # back_kb aynan 2 ta tugma
    bk = B.back_kb()
    bcbs = [b.callback_data for row in bk.inline_keyboard for b in row]
    check("back_kb: aynan 2 ta tugma", bcbs == nav, f"({bcbs})")

    # ------------------------------------------------------------------ #
    print("\n[2] 'Bosh menyu' matni kodda qolmagan")
    src = open("bot.py", encoding="utf-8").read()
    check("bot.py: '⬅️ Bosh menyu' yo'q", "⬅️ Bosh menyu" not in src)
    check("bot.py: '🏠 Bosh menyu' yo'q", "🏠 Bosh menyu" not in src)
    check("bot.py: 'Asosiy menyu' mavjud", "🏠 Asosiy menyu" in src)
    check("bot.py: BTN_MAIN = '🏠 Asosiy menyu'", B.BTN_MAIN == "🏠 Asosiy menyu",
          f"({B.BTN_MAIN!r})")

    # ------------------------------------------------------------------ #
    print("\n[3] Suhbat tozalash — FAQAT shu foydalanuvchi")
    db = B.db
    await db.connect()

    U1, U2 = 111001, 111002
    # chat_history -> users ga FK bog'langan, shuning uchun avval user yozamiz
    await db.upsert_user(U1, "u1test", "U1")
    await db.upsert_user(U2, "u2test", "U2")
    await db.add_history(U1, "user", "U1 savol 1")
    await db.add_history(U1, "assistant", "U1 javob 1")
    await db.add_history(U1, "user", "U1 savol 2")
    await db.add_history(U2, "user", "U2 savol 1")
    await db.add_history(U2, "assistant", "U2 javob 1")

    h1_before = await db.get_history(U1, limit=50)
    h2_before = await db.get_history(U2, limit=50)
    check("U1 tarixi yozildi", len(h1_before) == 3, f"({len(h1_before)})")
    check("U2 tarixi yozildi", len(h2_before) == 2, f"({len(h2_before)})")

    # U1 ning holati ham o'rnatiladi
    await db.set_user_state(U1, "ai_chat", {})
    st_before = await db.get_user_state(U1)
    check("U1 holati o'rnatildi", st_before is not None)

    removed = await B._reset_my_conversation(U1)
    check("_reset_my_conversation o'chirilgan sonni qaytaradi", removed == 3,
          f"({removed})")

    h1_after = await db.get_history(U1, limit=50)
    h2_after = await db.get_history(U2, limit=50)
    check("U1 tarixi tozalandi", len(h1_after) == 0, f"({len(h1_after)})")
    check("U2 tarixi TEGILMADI", len(h2_after) == 2, f"({len(h2_after)})")
    check("U2 ning matni o'zgarmagan",
          [r["text"] for r in h2_after] == ["U2 javob 1", "U2 savol 1"],
          f"({[r['text'] for r in h2_after]})")

    st_after = await db.get_user_state(U1)
    check("U1 holati tozalandi", st_after is None)
    st2 = await db.get_user_state(U2)
    check("U2 holati yo'q (tegilmagan)", st2 is None)

    # U1 yangi suhbatni toza boshlaydi
    await db.add_history(U1, "user", "yangi suhbat")
    h1_fresh = await db.get_history(U1, limit=50)
    check("U1 toza holatdan boshlaydi (faqat 1 yangi qatlam)",
          len(h1_fresh) == 1, f"({len(h1_fresh)})")

    # navigatsiya tarixi ham tozalanadi
    B._nav_stack[U1] = [{"text": "ekran", "markup": None}]
    await B._reset_my_conversation(U1)
    check("U1 navigatsiya tarixi tozalandi", U1 not in B._nav_stack)
    check("U2 navigatsiya tarixi tegilmadi (yo'q bo'lsa ham)",
          U2 not in B._nav_stack)

    # clear_conversation to'g'ridan-to'g'ri
    await db.add_history(U2, "user", "yana")
    n2 = await db.clear_conversation(U2)
    check("clear_conversation(U2) son qaytaradi", n2 == 3, f"({n2})")
    check("U2 ham endi toza", len(await db.get_history(U2, limit=50)) == 0)

    print(f"\n{'='*52}\n  NATIJA: {PASS} o'tdi, {FAIL} xato\n{'='*52}")
    await db.close()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
