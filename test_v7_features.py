"""AI Manager Bot v7 — yangi funksiyalar uchun integratsiya sinovlari.

Tekshiriladi:
  1. "Test qo'shish" bo'limi — admin kod + sarlavha + savollar + javoblar bilan test qo'shadi
  2. Band / yaroqsiz kod validatsiyasi
  3. Test ishlaganlar statistikasi — kim nechta test ishlagani (leaderboard)
  4. Test kodini yuborib testni boshlash (kod -> savollar)
  5. Natija tahlili (analyze_result_with_ai) xatoga chidamliligi
  6. Callback handlerlar haqiqiy chaqiruvda ishlaydi + admin ruxsati

Ishga tushirish:
    python test_v7_features.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.update({
    "BOT_TOKEN": "123456:TESTTOKEN",
    "GEMINI_API_KEYS": "testkey1,testkey2",
    "GEMINI_MODELS": "gemini-3.5-flash-lite",
    "DB_PATH": "test_v7.db",
    "ENABLE_SUB_GATE": "false",
    "ENABLE_HEALTH_SERVER": "false",
    "PORT": "0",
    "BACKUP_ENABLED": "false",
})

import bot as B  # noqa: E402
from database import Database  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}" + (f" -- {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" -- {extra}" if extra else ""))


class FakeUser:
    def __init__(self, uid, uname=None, fn="Test"):
        self.id, self.username, self.first_name = uid, uname, fn


class FakeMsg:
    """Minimal Message — faqat ishlatiladigan maydonlar."""

    def __init__(self, uid, text, uname="husan"):
        self.from_user = FakeUser(uid, uname)
        self.text = text
        self.sent: list[str] = []

    async def answer(self, text, **kw):
        self.sent.append(text)
        return self

    async def edit_text(self, text, **kw):
        self.sent.append(text)
        return self


class FakeCB:
    """Minimal CallbackQuery — handlerlarni haqiqiy chaqirish uchun."""

    def __init__(self, uid, data, uname="husan"):
        self.from_user = FakeUser(uid, uname)
        self.data = data
        self.message = FakeMsg(uid, "", uname)
        self.answers: list[object] = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)
        return True


async def main() -> None:
    db_path = Path("test_v7.db")
    for p in (db_path, Path("test_v7.db-wal"), Path("test_v7.db-shm")):
        p.unlink(missing_ok=True)

    B.db = Database(str(db_path))
    await B.db.connect()
    B.config.ADMIN_IDS = [999]
    B.config.ADMIN_USERNAMES = ["husan"]
    uid = 999
    await B.db.upsert_user(uid, "husan", "Husan")

    # ---------------- 1) Test qo'shish oqimi ----------------
    print("\n[1] Test qo'shish oqimi (handle_test_add2)")
    state = {"subject": "math", "step": "code", "code": "", "title": "", "questions": []}
    await B.db.set_user_state(uid, "test_add2", state)
    m = FakeMsg(uid, "ALG-1")

    await B.handle_test_add2(m, state, "ALG-1")
    st = await B.db.get_user_state(uid)
    state = st["data"]
    check("kod qabul qilindi", state.get("code") == "ALG-1", f"step={state['step']}")

    await B.handle_test_add2(m, state, "Algebra asoslari")
    st = await B.db.get_user_state(uid)
    state = st["data"]
    check("sarlavha qabul qilindi", state.get("title") == "Algebra asoslari", f"step={state['step']}")

    qs_text = "2+2 nechaga teng?\n3\n4\n5\n6\n\n5x5 nechaga teng?\n20\n25\n30\n35"
    await B.handle_test_add2(m, state, qs_text)
    st = await B.db.get_user_state(uid)
    state = st["data"]
    check("savollar ajratildi", len(state.get("questions") or []) == 2, f"step={state['step']}")

    await B.handle_test_add2(m, state, "ba")
    st = await B.db.get_user_state(uid)
    check("state tozalandi", st is None)

    t = await B.db.get_test_by_code("ALG-1")
    check("bazada mavjud", t is not None)
    if t:
        check("nomi to'g'ri", t["title"] == "Algebra asoslari")
        check("savollar soni 2", len(t["questions"]) == 2)
        check("javoblar kaliti 'ba'", t["answers"] == "ba")

    # ---------------- 2) Band / yaroqsiz kod ----------------
    print("\n[2] Kod validatsiyasi")
    st2 = {"subject": "math", "step": "code", "code": "", "title": "", "questions": []}
    await B.db.set_user_state(uid, "test_add2", st2)
    m2 = FakeMsg(uid, "ALG-1")
    await B.handle_test_add2(m2, st2, "ALG-1")
    check("band kod rad etildi", "band" in m2.sent[-1].lower(), m2.sent[-1][:60])

    st3 = {"subject": "math", "step": "code", "code": "", "title": "", "questions": []}
    await B.db.set_user_state(uid, "test_add2", st3)
    m3 = FakeMsg(uid, "a")
    await B.handle_test_add2(m3, st3, "a")
    check("juda qisqa kod rad etildi", "belgi" in m3.sent[-1].lower())
    await B.db.clear_user_state(uid)

    # ---------------- 3) Leaderboard ----------------
    print("\n[3] Test ishlaganlar statistikasi (leaderboard)")
    for u_id, uname, fname in ((101, "alice", "Alice"), (202, "bob", "Bob"), (303, None, "Dilnoza")):
        await B.db.upsert_user(u_id, uname, fname)

    await B.db.record_submission(101, "ALG-1", "math", "ab", 2, 2, [{"i": 1, "ok": True}, {"i": 2, "ok": True}])
    await B.db.record_submission(202, "ALG-1", "math", "aa", 1, 2, [{"i": 1, "ok": True}, {"i": 2, "ok": False}])
    await B.db.record_submission(202, "ALG-1", "math", "bb", 0, 2, [{"i": 1, "ok": False}, {"i": 2, "ok": False}])
    await B.db.record_submission(202, "ALG-1", "math", "ab", 2, 2, [{"i": 1, "ok": True}, {"i": 2, "ok": True}])
    await B.db.record_submission(303, "ALG-1", "math", "ab", 2, 2, [{"i": 1, "ok": True}, {"i": 2, "ok": True}])

    takers = await B.db.count_test_takers()
    check("test ishlaganlar soni = 3", takers == 3, f"({takers})")
    check("bob 3 ta test ishlagan", await B.db.user_test_count(202) == 3)

    lb = await B.db.test_leaderboard(50)
    check("leaderboard 3 qator", len(lb) == 3, f"({len(lb)})")
    check("eng ko'p ishlagan birinchi", bool(lb) and int(lb[0]["tests_taken"]) == 3)
    check("username bilan bog'landi", bool(lb) and lb[0].get("username") == "bob")
    check("jami to'g'ri javoblar hisoblandi", bool(lb) and int(lb[0]["total_correct"]) == 3)
    print("    leaderboard:")
    for i, r in enumerate(lb, 1):
        uname = f"@{r['username']}" if r.get("username") else (r.get("first_name") or "nomalum")
        print(f"      {i}. {uname} -- {r['tests_taken']} ta test "
              f"({r['total_correct']}/{r['total_questions']})")

    # ---------------- 4) Test kodini yuborish ----------------
    print("\n[4] Test kodini yuborib boshlash (handle_test_code)")
    m4 = FakeMsg(202, "ALG-1")
    await B.handle_test_code(m4, "ALG-1")
    sent = m4.sent[-1] if m4.sent else ""
    check("savollar yuborildi", "2+2" in sent and "5x5" in sent)
    check("javob formati ko'rsatildi", "harf" in sent)
    st4 = await B.db.get_user_state(202)
    check("javob kutish holatiga o'tdi", bool(st4) and st4["state"] == "test_answers")

    # ---------------- 5) Natija tahlili ----------------
    print("\n[5] Natija tahlili (analyze_result_with_ai)")
    r_all_ok = await B.analyze_result_with_ai(
        "math", "Algebra", 2, 2,
        [{"i": 1, "ok": True}, {"i": 2, "ok": True}],
        [{"q": "2+2?"}, {"q": "5x5?"}],
    )
    check("hammasi to'g'ri -> tahlil yo'q (None)", r_all_ok is None)

    r_bad = await B.analyze_result_with_ai(
        "math", "Algebra", 1, 2,
        [{"i": 1, "user": "b", "correct": "a", "ok": False}, {"i": 2, "user": "a", "correct": "b", "ok": True}],
        [{"q": "2+2?"}, {"q": "5x5?"}],
    )
    check("AI ishlamasa -> xato ushlanadi, None qaytadi", r_bad is None, f"tip={type(r_bad).__name__}")

    r_pdf = await B.analyze_result_with_ai(
        "umumiy", "PDF test", 0, 1,
        [{"i": "1", "user": "b", "correct": "a", "ok": False}],
        [{"q": "Savol matni (A, B)"}],
    )
    check("PDF detal formati qabul qilindi", r_pdf is None)

    # ---------------- 6) Callback handlerlar haqiqiy chaqiruvda ----------------
    print("\n[6] Callback handlerlar haqiqiy chaqiruvda ishlaydi")
    cb = FakeCB(uid, "menu:testadd")
    await B.on_menu_testadd(cb)
    check("menu:testadd -> fan tanlash chiqdi", bool(cb.message.sent) and "fandan" in cb.message.sent[-1])

    cb2 = FakeCB(uid, "tadd:sub:physics")
    await B.on_tadd_subject(cb2)
    stt = await B.db.get_user_state(uid)
    check("tadd:sub:physics -> holat boshlandi",
          bool(stt) and stt["state"] == "test_add2" and stt["data"]["subject"] == "physics")
    check("kod so'raldi", "kodini" in cb2.message.sent[-1].lower())
    await B.db.clear_user_state(uid)

    cb3 = FakeCB(uid, "stats:testtakers")
    await B.on_stats_testtakers(cb3)
    out = cb3.message.sent[-1] if cb3.message.sent else ""
    check("stats:testtakers -> ro'yxat chiqdi", "Test ishlaganlar" in out)
    check("bob ro'yxatda ko'rindi", "@bob" in out)
    check("nechta test ishlagani ko'rindi", "3" in out)
    check("foydalanuvchi ID ko'rindi", "202" in out)

    await B.db.upsert_user(555, "oddiy", "Oddiy")
    cb4 = FakeCB(555, "menu:testadd", uname="oddiy")
    await B.on_menu_testadd(cb4)
    check("admin bo'lmagan rad etildi",
          "faqat admin" in (cb4.message.sent[-1] if cb4.message.sent else "").lower())

    await B.db.close()

    print(f"\n===== NATIJA: {PASS} o'tdi, {FAIL} yiqildi =====")
    for p in (db_path, Path("test_v7.db-wal"), Path("test_v7.db-shm")):
        p.unlink(missing_ok=True)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
