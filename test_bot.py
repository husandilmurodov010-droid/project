"""AI Manager Bot v3 — integratsiya sinovlari.

Ishga tushirish:
    python test_bot.py

Sinovlar:
  1. Ma'lumotlar bazasi sxemasi (barcha jadvallar)
  2. JSON bazalarni yuklash (tezkor javoblar, quiz, IELTS, math, physics)
  3. Tezkor javob tizimi (tezlik + moslik)
  4. Soha aniqlash
  5. Test kod tizimi (MATH-0001 / PHY-0001)
  6. Javob tekshirish ('abcdfdddd' formati)
  7. Admin ruxsat oqimi (pending_approvals)
  8. Eslatma vaqtini tahlil qilish
  9. Gemini API (haqiqiy so'rov)
 10. Telegram getMe (haqiqiy so'rov)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Test uchun vaqtinchalik DB
os.environ.setdefault("DB_PATH", "test_bot.db")

import config  # noqa: E402
from database import Database  # noqa: E402
from gemini_pool import GeminiPool  # noqa: E402

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


# --------------------------------------------------------------------------- #
# bot.py dan sof funksiyalarni import qilish (bot ishga tushmasdan)
# --------------------------------------------------------------------------- #
def import_bot_helpers():
    """bot.py dagi sof funksiyalarni ajratib oladi (Bot obyektisiz)."""
    import importlib.util

    # bot.py ni import qilish Bot() ni yaratadi — token kerak.
    # Shuning uchun funksiyalarni to'g'ridan-to'g'ri modul sifatida yuklaymiz.
    spec = importlib.util.spec_from_file_location("botmod", "bot.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        return None
    return mod


async def main() -> None:
    print("=" * 70)
    print("AI Manager Bot v3 — integratsiya sinovlari")
    print("=" * 70)

    # ------------------------------------------------------------------ #
    print("\n[1] Ma'lumotlar bazasi sxemasi")
    db = Database("test_bot.db")
    if Path("test_bot.db").exists():
        Path("test_bot.db").unlink()
    await db.connect()

    cur = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {r["name"] for r in await cur.fetchall()}
    expected = {
        "users", "chat_history", "instant_replies", "quiz_questions",
        "quiz_sessions", "quiz_results", "stats",
        "ielts_speaking_questions", "ielts_writing_tasks",
        "math_tests", "physics_tests", "test_codes", "test_submissions",
        "pending_approvals", "reminders", "question_bank", "user_states", "admins",
    }
    missing = expected - tables
    check("Barcha 18 jadval mavjud", not missing, f"yetishmayapti: {missing}" if missing else "")

    # ------------------------------------------------------------------ #
    print("\n[2] JSON bazalarni yuklash")
    # Tezkor javoblar
    p = Path(config.INSTANT_REPLIES_FILE)
    data = json.loads(p.read_text(encoding="utf-8"))
    n_inst = await db.load_instant_replies(data.get("replies", data))
    check("Tezkor javoblar yuklandi", n_inst > 0, f"{n_inst} ta")

    # Quiz
    p = Path(config.QUIZ_DATA_FILE)
    data = json.loads(p.read_text(encoding="utf-8"))
    n_quiz = await db.load_quiz_questions(data.get("questions", data))
    check("Quiz savollari yuklandi", n_quiz > 0, f"{n_quiz} ta")

    # IELTS Speaking
    p = Path(config.IELTS_SPEAKING_FILE)
    data = json.loads(p.read_text(encoding="utf-8"))
    n_sp = await db.load_ielts_speaking(data.get("questions", data))
    check("IELTS Speaking savollari yuklandi", n_sp > 0, f"{n_sp} ta")
    for part in (1, 2, 3):
        c = await db.count_speaking(part)
        check(f"  Part {part} savollari", c > 0, f"{c} ta")

    # IELTS Writing
    p = Path(config.IELTS_WRITING_FILE)
    data = json.loads(p.read_text(encoding="utf-8"))
    n_wr = await db.load_ielts_writing(data.get("tasks", data))
    check("IELTS Writing topshiriqlari yuklandi", n_wr > 0, f"{n_wr} ta")

    # Math tests
    p = Path(config.MATH_TESTS_FILE)
    data = json.loads(p.read_text(encoding="utf-8"))
    for t in data.get("tests", data):
        await db.add_test("math", t["code"], t["title"], t["questions"], t["answers"])
    n_math = await db.count_tests("math")
    check("Matematika testlari yuklandi", n_math > 0, f"{n_math} ta")

    # Physics tests
    p = Path(config.PHYSICS_TESTS_FILE)
    data = json.loads(p.read_text(encoding="utf-8"))
    for t in data.get("tests", data):
        await db.add_test("physics", t["code"], t["title"], t["questions"], t["answers"])
    n_phys = await db.count_tests("physics")
    check("Fizika testlari yuklandi", n_phys > 0, f"{n_phys} ta")

    # ------------------------------------------------------------------ #
    print("\n[3] Tezkor javob tizimi (tezlik)")
    # Aniq moslik
    t0 = time.perf_counter()
    hit = await db.get_instant_reply("salom")
    dt = (time.perf_counter() - t0) * 1000
    check("'salom' tezkor javobi topildi", hit is not None, f"{dt:.2f} ms")
    check("Tezlik 100 ms dan kam", dt < 100, f"{dt:.2f} ms")

    # Normallashtirish + ibora mosligi
    import re
    _PUNCT = re.compile(r"[^\w\s'ʻʼ’]", flags=re.UNICODE)
    _SPACES = re.compile(r"\s+", flags=re.UNICODE)

    def normalize(text: str) -> str:
        text = (text or "").lower().strip()
        text = _PUNCT.sub(" ", text)
        text = _SPACES.sub(" ", text)
        return text.strip()

    norm = normalize("Salom!!!")
    hit2 = await db.get_instant_reply(norm)
    check("'Salom!!!' normallashtirilib topildi", hit2 is not None)

    # ------------------------------------------------------------------ #
    print("\n[4] Soha aniqlash")
    TOPIC_KEYWORDS = {
        "matematika": ["matematika", "algebra", "tenglama", "misol"],
        "fizika": ["fizika", "kuch", "tezlik", "energiya"],
        "tarix": ["tarix", "amir temur", "bobur"],
        "dasturlash": ["dasturlash", "python", "kod"],
    }
    _ARITH = re.compile(r"\d+\s*[\+\-*/x×÷]\s*\d+")

    def detect_topic(text: str):
        n = normalize(text)
        if not n:
            return None
        if _ARITH.search(n):
            return "matematika"
        for topic, words in TOPIC_KEYWORDS.items():
            for w in words:
                if re.search(rf"(^|\s){re.escape(w)}", n):
                    return topic
        return None

    cases = [
        ("12 x 8 nechaga teng", "matematika"),
        ("fizika masalasini yechib ber", "fizika"),
        ("Amir Temur haqida aytib ber", "tarix"),
        ("python dasturlash nima", "dasturlash"),
    ]
    for text, expected_topic in cases:
        got = detect_topic(text)
        check(f"'{text[:30]}' -> {expected_topic}", got == expected_topic, f"olindi: {got}")

    # ------------------------------------------------------------------ #
    print("\n[5] Test kod tizimi")
    code = await db.next_test_code("math")
    check("Yangi math kodi MATH- prefiksi bilan", code.startswith("MATH-"), code)
    code2 = await db.next_test_code("physics")
    check("Yangi physics kodi PHY- prefiksi bilan", code2.startswith("PHY-"), code2)

    test = await db.get_test_by_code("MATH-0001")
    check("MATH-0001 kodi topildi", test is not None)
    if test:
        check("Test savollari mavjud", len(test["questions"]) > 0,
              f"{len(test['questions'])} ta")
        check("Test javoblari mavjud", bool(test["answers"]), test["answers"])

    # ------------------------------------------------------------------ #
    print("\n[6] Javob tekshirish ('abcdfdddd' formati)")

    def check_answers(user_answers: str, correct: str):
        ua = re.sub(r"[^a-d]", "", (user_answers or "").lower())
        ca = re.sub(r"[^a-d]", "", (correct or "").lower())
        total = len(ca)
        detail = []
        correct_count = 0
        for i in range(total):
            u = ua[i] if i < len(ua) else "-"
            c = ca[i]
            ok = u == c
            if ok:
                correct_count += 1
            detail.append({"i": i + 1, "user": u, "correct": c, "ok": ok})
        return correct_count, detail

    # MATH-0001 javoblari: bbcbb
    c, d = check_answers("bbcbb", "bbcbb")
    check("To'liq to'g'ri javob", c == 5, f"{c}/5")
    c, d = check_answers("abcbb", "bbcbb")
    check("Bitta xato aniqlanadi", c == 4, f"{c}/5")
    c, d = check_answers("aaaaa", "bbcbb")
    check("Barcha xato aniqlanadi", c == 0, f"{c}/5")
    # Format tozalash (bo'sh joy, katta harf)
    c, d = check_answers("B B C B B", "bbcbb")
    check("Format tozalanadi (bo'sh joy/katta harf)", c == 5, f"{c}/5")

    # ------------------------------------------------------------------ #
    print("\n[7] Admin ruxsat oqimi")
    payload = {
        "title": "Sinov testi",
        "questions": [{"q": "1+1?", "options": ["1", "2", "3", "4"]}],
        "answers": "b",
    }
    aid = await db.create_pending_approval(999, "math", payload)
    check("Pending approval yaratildi", aid > 0, f"id={aid}")
    appr = await db.get_pending_approval(aid)
    check("Pending approval o'qildi", appr is not None and appr["status"] == "pending")
    check("Payload to'g'ri saqlandi", appr["payload"]["title"] == "Sinov testi")

    await db.set_approval_status(aid, "approved", 111)
    appr2 = await db.get_pending_approval(aid)
    check("Status 'approved' ga o'zgardi", appr2["status"] == "approved")
    check("decided_by saqlandi", appr2["decided_by"] == 111)

    # ------------------------------------------------------------------ #
    print("\n[8] Eslatma vaqtini tahlil qilish")
    from datetime import datetime, timedelta

    def parse_reminder_time(s: str):
        s = (s or "").strip().lower()
        now = datetime.now()
        m = re.fullmatch(r"\+(\d+)\s*(m|min|h|soat|d|kun)", s)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if unit in ("m", "min"):
                return (now + timedelta(minutes=n)).timestamp()
            if unit in ("h", "soat"):
                return (now + timedelta(hours=n)).timestamp()
            return (now + timedelta(days=n)).timestamp()
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target.timestamp()
        for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).timestamp()
            except ValueError:
                continue
        return None

    check("'+30m' tahlil qilindi", parse_reminder_time("+30m") is not None)
    check("'+2h' tahlil qilindi", parse_reminder_time("+2h") is not None)
    check("'+1d' tahlil qilindi", parse_reminder_time("+1d") is not None)
    check("'09:30' tahlil qilindi", parse_reminder_time("09:30") is not None)
    check("'2026-10-20 14:00' tahlil qilindi",
          parse_reminder_time("2026-10-20 14:00") is not None)
    check("Noto'g'ri format rad etildi", parse_reminder_time("ertaga") is None)

    # Eslatma saqlash
    rid = await db.add_reminder(999, "Sinov eslatmasi", time.time() - 1)
    due = await db.get_due_reminders()
    check("Muddati kelgan eslatma topildi", any(r["id"] == rid for r in due))
    await db.mark_reminder_sent(rid)
    due2 = await db.get_due_reminders()
    check("Yuborilgan eslatma ro'yxatdan chiqdi", not any(r["id"] == rid for r in due2))

    # ------------------------------------------------------------------ #
    print("\n[9] Savollar banki")
    qid = await db.add_question_bank(999, "matematika", "2+2 nechaga teng?", "4")
    check("Savol bankka qo'shildi", qid > 0)
    found = await db.search_question_bank("2+2")
    check("Savol qidiruvda topildi", len(found) > 0)

    # ------------------------------------------------------------------ #
    print("\n[10] Foydalanuvchi holati (user_states)")
    await db.set_user_state(999, "test_add", {"subject": "math", "step": "title"})
    st = await db.get_user_state(999)
    check("Holat saqlandi", st is not None and st["state"] == "test_add")
    check("Holat ma'lumoti to'g'ri", st["data"]["subject"] == "math")
    await db.clear_user_state(999)
    st2 = await db.get_user_state(999)
    check("Holat tozalandi", st2 is None)

    # ------------------------------------------------------------------ #
    print("\n[11] Admin reyestri")
    await db.register_admin(12345, "Husan_Dilmurodov")
    admins = await db.get_registered_admins()
    check("Admin bazaga yozildi", 12345 in admins)
    check("config.is_admin username bo'yicha ishlaydi",
          config.is_admin(0, "Husan_Dilmurodov"))
    check("config.is_admin begona uchun False",
          not config.is_admin(0, "boshqa_odam"))

    # ------------------------------------------------------------------ #
    print("\n[12] Gemini API (haqiqiy so'rov)")
    pool = GeminiPool(
        keys=config.GEMINI_API_KEYS,
        models=config.GEMINI_MODELS,
        base_url=config.GEMINI_BASE_URL,
        timeout=config.REQUEST_TIMEOUT,
    )
    await pool.start()
    try:
        ans = await pool.generate("Faqat 'SALOM' so'zini yoz, boshqa hech narsa.")
        check("Gemini javob berdi", bool(ans), repr(ans[:60]))
    except Exception as exc:  # noqa: BLE001
        check("Gemini javob berdi", False, str(exc)[:120])
    finally:
        await pool.close()

    # ------------------------------------------------------------------ #
    print("\n[13] Telegram getMe (haqiqiy so'rov)")
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getMe"
            async with s.get(url) as r:
                data = await r.json()
        ok = data.get("ok")
        uname = data.get("result", {}).get("username", "")
        check("getMe muvaffaqiyatli", bool(ok), f"@{uname}")
        check("Bot username to'g'ri", uname == "AIManagerProBot", f"@{uname}")
    except Exception as exc:  # noqa: BLE001
        check("getMe muvaffaqiyatli", False, str(exc)[:120])

    # ------------------------------------------------------------------ #
    await db.close()
    if Path("test_bot.db").exists():
        Path("test_bot.db").unlink()
    for suffix in ("-wal", "-shm"):
        f = Path(f"test_bot.db{suffix}")
        if f.exists():
            f.unlink()

    print("\n" + "=" * 70)
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
