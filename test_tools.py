"""v4 sinovlari: Tools menyusi (2 tugma), savol qo'shish, kanal boshqaruvi.

Ishga tushirish:  python3 test_tools.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("GEMINI_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("ADMIN_USERNAME", "Husan_Dilmurodov")

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
    import config
    from database import Database

    print("\n=== 1) Tools menyusi: faqat 2 ta tugma ===")
    import bot as botmod

    kb = botmod.tools_kb()
    buttons = [b.text for row in kb.inline_keyboard for b in row]
    # Navigatsiya tugmalarini ("Orqaga" / "Asosiy menyu") hisobga olmaymiz
    action_buttons = [
        b for b in buttons if "Orqaga" not in b and "menyu" not in b.lower()
    ]
    check("Tools'da 2 ta amal tugmasi", len(action_buttons) == 2,
          f"(topildi: {action_buttons})")
    check("«Savol qo'shish» bor", any("Savol qo'shish" in b for b in action_buttons))
    check("«Kanalga ulash» bor", any("Kanalga ulash" in b for b in action_buttons))
    check("eski «Ovozli rejim» yo'q", not any("Ovozli rejim" in b for b in buttons))
    check("eski «Rasm» yo'q", not any("Rasm" in b for b in action_buttons))
    check("eski «Savollar banki» yo'q", not any("Savollar banki" in b for b in action_buttons))

    print("\n=== 2) Kanal klaviaturasi ===")
    ckb = botmod.channel_kb()
    cbtns = [b.text for row in ckb.inline_keyboard for b in row]
    check("«Kanal ulash» bor", any("Kanal ulash" in b for b in cbtns))
    check("«Kanalga post» bor", any("Kanalga post" in b for b in cbtns))
    check("«Post rejalashtirish» bor", any("rejalashtirish" in b for b in cbtns))

    print("\n=== 3) Savol qo'shish klaviaturalari ===")
    qkb = botmod.qadd_type_kb()
    qbtns = [b.text for row in qkb.inline_keyboard for b in row]
    for name in ("IELTS Speaking", "IELTS Writing", "Matematika", "Fizika"):
        check(f"«{name}» turi bor", any(name in b for b in qbtns))

    print("\n=== 4) Baza: yangi jadvallar ===")
    tmp = tempfile.mktemp(suffix=".db")
    db = Database(tmp)
    await db.connect()
    cur = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {r["name"] for r in await cur.fetchall()}
    for t in ("channels", "scheduled_posts", "ielts_speaking_questions",
              "ielts_writing_tasks", "math_tests", "physics_tests",
              "test_codes", "test_submissions", "pending_approvals",
              "reminders", "question_bank"):
        check(f"jadval: {t}", t in tables)

    print("\n=== 5) Kanal CRUD ===")
    await db.add_channel(111, -1001234567890, "Test kanal", "test_kanal")
    ch = await db.get_channel(-1001234567890)
    check("kanal qo'shildi", ch is not None and ch["title"] == "Test kanal")
    check("kanal username", ch["username"] == "test_kanal")
    check("kanal soni = 1", await db.count_channels() == 1)
    rows = await db.list_channels(111)
    check("kanal ro'yxati", len(rows) == 1)
    # Upsert (qayta ulash)
    await db.add_channel(111, -1001234567890, "Yangi nom", "test_kanal")
    ch2 = await db.get_channel(-1001234567890)
    check("kanal upsert (nom yangilandi)", ch2["title"] == "Yangi nom")
    check("kanal soni hali 1", await db.count_channels() == 1)

    print("\n=== 6) Rejalashtirilgan postlar ===")
    now = time.time()
    pid = await db.add_scheduled_post(-1001234567890, "Salom kanal", now - 1,
                                      created_by=111)
    check("post qo'shildi", pid > 0)
    due = await db.get_due_scheduled_posts()
    check("muddati kelgan post topildi", len(due) == 1 and due[0]["text"] == "Salom kanal")
    await db.mark_post_sent(pid)
    due2 = await db.get_due_scheduled_posts()
    check("yuborilgach ro'yxatdan chiqdi", len(due2) == 0)
    # Takrorlanuvchi post
    pid2 = await db.add_scheduled_post(-1001234567890, "Har kuni", now - 1,
                                       repeat_minutes=1440, created_by=111)
    await db.reschedule_post(pid2, now + 86400)
    pend = await db.list_scheduled_posts(-1001234567890, only_pending=True)
    check("takrorlanuvchi post qayta rejalashtirildi", len(pend) == 1)
    await db.delete_scheduled_post(pid2)
    pend2 = await db.list_scheduled_posts(-1001234567890, only_pending=True)
    check("post o'chirildi", len(pend2) == 0)

    print("\n=== 7) Savol qo'shish (Speaking/Writing) ===")
    sid = await db.add_speaking_question(1, "What is your hobby?", topic="hobby")
    check("Speaking Part 1 savoli qo'shildi", sid > 0)
    sid2 = await db.add_speaking_question(
        2, "Describe a book", cue_card="Describe a book",
        bullets=["what", "why"], prep_seconds=60, speak_seconds=120)
    check("Speaking Part 2 cue card qo'shildi", sid2 > 0)
    sp = await db.get_speaking_questions(2, limit=1)
    check("Part 2 bullets saqlandi", sp and sp[0]["bullets"] == ["what", "why"])
    wid = await db.add_writing_task(2, "Some people think...", min_words=250)
    check("Writing Task 2 qo'shildi", wid > 0)
    wt = await db.get_writing_tasks(2, limit=1)
    check("Writing min_words", wt and wt[0]["min_words"] == 250)

    print("\n=== 8) Admin ruxsat oqimi (addq) ===")
    aid = await db.create_pending_approval(
        999, "addq", {"username": "testuser", "first_name": "Test", "user_id": 999})
    check("ruxsat so'rovi yaratildi", aid > 0)
    appr = await db.get_pending_approval(aid)
    check("so'rov holati pending", appr and appr["status"] == "pending")
    check("so'rov subject=addq", appr["subject"] == "addq")
    check("payload username", appr["payload"]["username"] == "testuser")
    await db.set_approval_status(aid, "approved", 111)
    appr2 = await db.get_pending_approval(aid)
    check("so'rov tasdiqlandi", appr2["status"] == "approved")
    # Tasdiqlangach admin sifatida ro'yxatga olish
    await db.register_admin(999, "testuser")
    admins = await db.get_registered_admins()
    check("foydalanuvchi admin bo'ldi", 999 in admins)

    print("\n=== 9) Test qo'shish oqimi (math) ===")
    code = await db.next_test_code("math")
    check("math kodi MATH- prefiksli", code.startswith("MATH-"))
    await db.add_test("math", code, "Algebra", [{"q": "2+2?", "options": ["3", "4"]}],
                      "b", created_by=111)
    t = await db.get_test_by_code(code)
    check("test bazaga qo'shildi", t is not None and t["title"] == "Algebra")
    check("test javoblari saqlandi", t["answers"] == "b")

    print("\n=== 10) Javob tekshirish (abcdfdddd) ===")
    correct, detail = botmod.check_answers("abcdfdddd", "abcdfdddd")
    check("to'liq to'g'ri = 9", correct == 9)
    correct2, detail2 = botmod.check_answers("abcdxxxx", "abcdfdddd")
    check("qisman to'g'ri = 4", correct2 == 4)
    check("xatolar tahlili uzunligi", len(detail2) == 9)
    check("5-savol xato", detail2[4]["ok"] is False)

    print("\n=== 11) Vaqt tahlili (post rejalashtirish) ===")
    ts = botmod.parse_reminder_time("+2h")
    check("+2h tahlil qilindi", ts is not None and ts > time.time())
    ts2 = botmod.parse_reminder_time("09:30")
    check("09:30 tahlil qilindi", ts2 is not None)
    ts3 = botmod.parse_reminder_time("2026-10-20 14:00")
    check("aniq sana tahlil qilindi", ts3 is not None)
    check("noto'g'ri vaqt = None", botmod.parse_reminder_time("salom") is None)

    print("\n=== 12) Admin tekshiruvi ===")
    check("username bo'yicha admin", config.is_admin(1, "Husan_Dilmurodov"))
    check("begona foydalanuvchi admin emas", not config.is_admin(1, "boshqa"))

    await db.close()
    try:
        os.remove(tmp)
    except OSError:
        pass

    print(f"\n{'=' * 50}")
    print(f"NATIJA: {PASS} o'tdi, {FAIL} muvaffaqiyatsiz")
    print(f"{'=' * 50}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
