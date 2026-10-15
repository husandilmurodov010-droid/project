"""PDF test tizimi uchun testlar (v5).

Sinovdan o'tkazadi:
  * PDF matnidan savollarni ajratish (test + ochiq savollar)
  * Javob kiritmasini tahlil qilish ('abcdba', '36a)2.3')
  * Javoblarni tekshirish va xatolarni aniqlash
  * Baza: pdf_tests jadvali (qo'shish, olish, kod bandligi)
  * Haqiqiy PDF yaratib, matn ajratish (pypdf)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# bot.py modul darajasida GeminiPool va config.validate() ni ishga tushiradi —
# sinov uchun soxta (dummy) env o'zgaruvchilar o'rnatamiz.
os.environ.setdefault("BOT_TOKEN", "123456:TEST_DUMMY_TOKEN")
os.environ.setdefault("GEMINI_API_KEYS", "dummy_key_1,dummy_key_2")
os.environ.setdefault("ADMIN_ID", "883800311")
os.environ.setdefault("ADMIN_USERNAME", "Husan_Dilmurodov")

import bot  # noqa: E402
from database import Database  # noqa: E402

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
# 1) Savollarni ajratish
# --------------------------------------------------------------------------- #
def test_parse_questions() -> None:
    print("\n[1] PDF matnidan savollarni ajratish")
    text = """Matematika testi
1) 2+2 nechaga teng?
A) 3
B) 4
C) 5
D) 6
2) 5x5 nechaga teng?
A) 20
B) 25
C) 30
D) 35
36) Hisoblang:
a) 1.5 + 0.8
b) 3.2 - 0.9
"""
    qs = bot.parse_pdf_questions(text)
    check("savollar topildi", len(qs) == 4, f"len={len(qs)}")
    mc = [q for q in qs if q["type"] == "mc"]
    op = [q for q in qs if q["type"] == "open"]
    check("2 ta test savoli", len(mc) == 2, f"mc={len(mc)}")
    check("2 ta ochiq savol", len(op) == 2, f"op={len(op)}")
    check("1-savol matni", mc[0]["q"] == "2+2 nechaga teng?", mc[0]["q"])
    check("1-savol 4 variant", len(mc[0]["options"]) == 4, str(mc[0]["options"]))
    check("1-savol B varianti", mc[0]["options"][1] == "4", str(mc[0]["options"]))
    check("ochiq kalit 36a", op[0]["key"] == "36a", op[0]["key"])
    check("ochiq kalit 36b", op[1]["key"] == "36b", op[1]["key"])


# --------------------------------------------------------------------------- #
# 2) Javob kiritmasini tahlil qilish
# --------------------------------------------------------------------------- #
def test_parse_answers() -> None:
    print("\n[2] Javob kiritmasini tahlil qilish")
    qs = [
        {"n": 1, "key": "1", "q": "a", "options": ["x", "y"], "type": "mc"},
        {"n": 2, "key": "2", "q": "b", "options": ["x", "y"], "type": "mc"},
        {"n": 36, "key": "36a", "q": "c", "options": [], "type": "open"},
        {"n": 36, "key": "36b", "q": "d", "options": [], "type": "open"},
    ]
    a = bot.parse_answer_input("ba 36a)2.3 36b)4.5", qs)
    check("test javobi 1", a.get("1") == "b", str(a))
    check("test javobi 2", a.get("2") == "a", str(a))
    check("ochiq 36a", a.get("36a") == "2.3", str(a))
    check("ochiq 36b", a.get("36b") == "4.5", str(a))

    b = bot.parse_answer_input("36)2.3", qs)
    check("ochiq faqat raqam", b.get("36") == "2.3", str(b))

    c = bot.parse_answer_input("AB", qs)
    check("katta harflar kichraytirildi", c.get("1") == "a" and c.get("2") == "b", str(c))


# --------------------------------------------------------------------------- #
# 3) Javoblarni tekshirish
# --------------------------------------------------------------------------- #
def test_check_answers() -> None:
    print("\n[3] Javoblarni tekshirish va xatolar")
    test = {
        "questions": [
            {"n": 1, "key": "1", "q": "2+2", "options": ["3", "4"], "type": "mc"},
            {"n": 2, "key": "2", "q": "5x5", "options": ["20", "25"], "type": "mc"},
            {"n": 36, "key": "36a", "q": "hisob (a)", "options": [], "type": "open"},
        ],
        "answers": {"1": "b", "2": "b", "36a": "2.3"},
    }
    correct, total, detail = bot.check_pdf_answers("bb 36a)2.3", test)
    check("hammasi to'g'ri", correct == 3 and total == 3, f"{correct}/{total}")

    correct, total, detail = bot.check_pdf_answers("ab 36a)9.9", test)
    check("2 ta xato", correct == 1 and total == 3, f"{correct}/{total}")
    wrong = [d for d in detail if not d["ok"]]
    check("xato savollar aniqlandi", len(wrong) == 2, str(wrong))
    check("xato 1-savol", wrong[0]["key"] == "1", str(wrong[0]))
    check("xato 36a", wrong[1]["key"] == "36a", str(wrong[1]))

    result = bot.format_pdf_result("12345", "Test", correct, total, detail)
    check("natijada xato ko'rsatilgan", "Xatolar" in result, result[:80])
    check("natijada foiz bor", "%" in result, result[:80])


# --------------------------------------------------------------------------- #
# 4) Baza
# --------------------------------------------------------------------------- #
async def test_db() -> None:
    print("\n[4] Baza: pdf_tests jadvali")
    tmp = tempfile.mktemp(suffix=".db")
    db = Database(tmp)
    await db.connect()

    qs = [{"n": 1, "key": "1", "q": "2+2", "options": ["3", "4"], "type": "mc"}]
    ans = {"1": "b"}
    await db.add_pdf_test("12345", "Algebra", qs, ans, subject="math", created_by=1)

    t = await db.get_pdf_test_by_code("12345")
    check("test olindi", t is not None)
    check("kod to'g'ri", t and t["code"] == "12345", str(t and t["code"]))
    check("savollar JSON", t and t["questions"][0]["q"] == "2+2", str(t and t["questions"]))
    check("javoblar JSON", t and t["answers"]["1"] == "b", str(t and t["answers"]))
    check("kod mavjud", await db.pdf_test_code_exists("12345"))
    check("kod yo'q", not await db.pdf_test_code_exists("99999"))
    check("sanoq 1", await db.count_pdf_tests() == 1)
    check("ro'yxat", len(await db.list_pdf_tests()) == 1)

    await db.delete_pdf_test("12345")
    check("o'chirildi", await db.count_pdf_tests() == 0)

    await db.close()
    os.unlink(tmp)


# --------------------------------------------------------------------------- #
# 5) Haqiqiy PDF
# --------------------------------------------------------------------------- #
def test_real_pdf() -> None:
    print("\n[5] Haqiqiy PDF yaratib, matn ajratish")
    try:
        from pypdf import PdfWriter
    except Exception as exc:  # noqa: BLE001
        check("pypdf mavjud", False, str(exc))
        return

    # pypdf matn yozishni qo'llamaydi — reportlab bo'lsa ishlatamiz
    try:
        from reportlab.pdfgen import canvas
    except Exception:
        print("  ⏭ reportlab yo'q — PDF yaratish o'tkazib yuborildi")
        return

    tmp = tempfile.mktemp(suffix=".pdf")
    c = canvas.Canvas(tmp)
    c.drawString(72, 720, "1) 2+2 nechaga teng?")
    c.drawString(72, 700, "A) 3")
    c.drawString(72, 680, "B) 4")
    c.drawString(72, 660, "36) Hisoblang:")
    c.drawString(72, 640, "a) 1.5 + 0.8")
    c.save()

    with open(tmp, "rb") as f:
        data = f.read()
    text = bot.extract_pdf_text(data)
    check("PDF matni olindi", len(text.strip()) > 0, repr(text[:60]))
    qs = bot.parse_pdf_questions(text)
    check("PDF dan savollar topildi", len(qs) >= 1, f"len={len(qs)}")
    os.unlink(tmp)


async def main() -> None:
    test_parse_questions()
    test_parse_answers()
    test_check_answers()
    await test_db()
    test_real_pdf()
    print(f"\n{'='*50}")
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print(f"{'='*50}")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
