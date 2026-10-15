"""AI Manager Bot v3 — aiogram 3 + Gemini (ko'p kalitli pool).

Bo'limlar (asosiy menyu):
  🎤 IELTS Speaking  — Part 1/2/3 savollari + ovozli xabar baholash
  ✍️ IELTS Writing   — Task 1/2 + insho baholash
  ➗ Matematika      — misol yechish + testlar (kod tizimi, admin ruxsati)
  ⚛️ Fizika          — misol yechish + testlar (kod tizimi, admin ruxsati)
  🧰 Vositalar       — ovoz rejimi, rasm, savollar banki, eslatmalar

Buyruqlar:
  /start /menu /help  — yordam va menyu
  /quiz               — soha bo'yicha test (inline tugmalar)
  /stats              — statistika
  /history            — suhbat tarixi
  /lang               — til tanlash (uz/en/ru)
  /bank [so'z]        — savollar banki
  /manga <nom>        — manga haqida
  /recommend <janr>   — tavsiya
  /image <prompt>     — rasm generatsiyasi (Imagen)
  rasm yuborish       — panelni tahlil qilish (vision)
  ovozli xabar        — matnga o'girish + baholash
  erkin matn          — HAMMA soha bo'yicha AI javob
  tezkor javoblar     — salom/rahmat kabi so'zlarga AI'siz, darhol javob

Arxitektura:
  * 5 ta Gemini kalit — round-robin + failover + cooldown (gemini_pool.py)
  * Model zaxira zanjiri (fallback)
  * SQLite ma'lumotlar bazasi (database.py)
  * 24/7: auto-restart (run.sh / systemd / Docker)
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import backup as backup_mod
import config
import health_server
import watchdog
from database import Database
from gemini_pool import AllKeysFailedError, GeminiPool

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)

logger = logging.getLogger()
logger.setLevel(config.LOG_LEVEL)

_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(_fmt)
logger.addHandler(_console)

_file = RotatingFileHandler(
    Path(config.LOG_DIR) / "bot.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file.setFormatter(_fmt)
logger.addHandler(_file)

log = logging.getLogger("bot")

# --------------------------------------------------------------------------- #
# Gemini + DB
# --------------------------------------------------------------------------- #
pool = GeminiPool(
    keys=config.GEMINI_API_KEYS,
    models=config.GEMINI_MODELS,
    base_url=config.GEMINI_BASE_URL,
    timeout=config.REQUEST_TIMEOUT,
    max_retries_per_key=config.MAX_RETRIES_PER_KEY,
    cooldown_seconds=config.COOLDOWN_SECONDS,
)

db = Database(config.DB_PATH)

# Render bepul tarifida disk vaqtinchalik — baza GitHub Gist'ga zaxiralanadi.
backup_mgr = backup_mod.BackupManager(
    db_path=config.DB_PATH,
    token=config.GITHUB_TOKEN if config.BACKUP_ENABLED else "",
    gist_id=config.GIST_ID,
    interval=config.BACKUP_INTERVAL_SECONDS,
    restore_on_start=config.RESTORE_ON_START,
)

# --------------------------------------------------------------------------- #
# System promptlar
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "Sen 'AI Manager' — HAMMA soha bo'yicha bilimli, xushmuomala AI yordamchisan. "
    "Foydalanuvchi qaysi tilda yozsa, o'sha tilda javob ber (odatda o'zbek tili). "
    "Sohalarni qamrab olasan: matematika, fizika, tarix, ingliz tili, dasturlash, "
    "tibbiyot, biznes, fan, geografiya, adabiyot, manga/anime, umumiy bilim va boshqalar. "
    "MUHIM — SUHBAT XOTIRASI: senga oldingi suhbat qatlamlari (foydalanuvchi va sen "
    "yozgan xabarlar) beriladi. Har bir yangi javobni OLDINGI gaplarga bog'lab ber. "
    "Agar foydalanuvchi 'tahlil qil', 'davom et', 'shuni ishlab ber', 'yana', "
    "'tushuntir' kabi so'rov yozsa — bu oldingi mavzuga ishora; yangidan boshlamang "
    "va allaqachon berilgan misolni qaytadan so'ramang. Oldingi javobingda misol "
    "bergan bo'lsang, endi o'sha misolga tayanib davom et. Faqat foydalanuvchi aniq "
    "yangi mavzu boshlasa yoki 'reset' qilsa, kontekstni tashlab yangidan boshlaysan. "
    "Javoblaring aniq, qisqa va foydali bo'lsin; kerak bo'lsa misol va qadamlar bilan "
    "tushuntir. Ma'lumot ishonchsiz bo'lsa, buni ochiq ayt. Javobni chiroyli, "
    "o'qishga qulay formatda yoz."
)

SPEAKING_EXAMINER_PROMPT = (
    "Sen tajribali IELTS Speaking imtihonchisisan. Foydalanuvchi bergan javobni "
    "(matn yoki ovoz transkripti) IELTS mezonlari bo'yicha baholaysan: "
    "Fluency & Coherence, Lexical Resource, Grammatical Range & Accuracy, Pronunciation. "
    "Har bir mezon uchun 0-9 ball (0.5 qadam bilan) va umumiy band score ber. "
    "Javobni aynan quyidagi formatda yoz (o'zbek tilida izoh bilan):\n"
    "🎤 Transkript: <javob matni>\n"
    "📊 Baholar:\n"
    "• Fluency & Coherence: X.X\n"
    "• Lexical Resource: X.X\n"
    "• Grammatical Range & Accuracy: X.X\n"
    "• Pronunciation: X.X\n"
    "🏆 Umumiy band: X.X\n"
    "✅ Kuchli tomonlar: ...\n"
    "❌ Xatolar: ...\n"
    "💡 Yaxshilash bo'yicha maslahat: ..."
)

WRITING_EXAMINER_PROMPT = (
    "Sen tajribali IELTS Writing imtihonchisisan. Foydalanuvchi inshosini "
    "IELTS mezonlari bo'yicha baholaysan: Task Achievement/Response, "
    "Coherence & Cohesion, Lexical Resource, Grammatical Range & Accuracy. "
    "Har biri uchun 0-9 ball (0.5 qadam) va umumiy band score ber. So'z sonini ham tekshir. "
    "Javobni aynan quyidagi formatda yoz (o'zbek tilida izoh bilan):\n"
    "📝 So'z soni: N\n"
    "📊 Baholar:\n"
    "• Task Achievement/Response: X.X\n"
    "• Coherence & Cohesion: X.X\n"
    "• Lexical Resource: X.X\n"
    "• Grammatical Range & Accuracy: X.X\n"
    "🏆 Umumiy band: X.X\n"
    "❌ Xatolar tahlili: ...\n"
    "✅ Yaxshilangan namuna (qisqa): ..."
)

MATH_SOLVER_PROMPT = (
    "Sen matematika o'qituvchisisan. Foydalanuvchi bergan misolni QADAM-BAQADAM "
    "yechib ber. Har bir qadamni tushuntir, kerakli formulalarni yoz, oxirida "
    "javobni aniq ko'rsat. O'zbek tilida, tushunarli qilib yoz."
)

PHYSICS_SOLVER_PROMPT = (
    "Sen fizika o'qituvchisisan. Foydalanuvchi bergan masalani QADAM-BAQADAM "
    "yechib ber. Berilganlar, formulalar, hisoblash va javobni aniq ko'rsat. "
    "O'zbek tilida, tushunarli qilib yoz."
)

# --------------------------------------------------------------------------- #
# Bot / Dispatcher
# --------------------------------------------------------------------------- #
bot = Bot(
    token=config.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
)
dp = Dispatcher()

# --------------------------------------------------------------------------- #
# Yordamchi funksiyalar
# --------------------------------------------------------------------------- #
_PUNCT = re.compile(r"[^\w\s'ʻʼ’]", flags=re.UNICODE)
_SPACES = re.compile(r"\s+", flags=re.UNICODE)
_TEST_CODE_RE = re.compile(r"^(MATH|PHY)-\d{1,4}$", re.IGNORECASE)


def normalize(text: str) -> str:
    """Matnni solishtirish uchun normallashtiradi (kichik harf, tinish belgilarisiz)."""
    text = (text or "").lower().strip()
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text)
    return text.strip()


def esc(s: object) -> str:
    return html.escape(str(s))


# Sohani aniqlash uchun kalit so'zlar
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "matematika": ["matematika", "algebra", "geometriya", "tenglama", "integral",
                   "hosila", "kasr", "foiz", "hisob", "son", "misol", "arifmetika"],
    "fizika": ["fizika", "kuch", "tezlik", "energiya", "nyuton", "joul", "vatt",
               "atom", "gravitatsiya", "tezlanish", "massa", "zaryad", "tok"],
    "tarix": ["tarix", "tarixiy", "amir temur", "temur", "bobur", "mustaqillik",
              "urush", "sana", "sulola", "imperiya", "xiva", "buxoro", "samarqand"],
    "ingliz tili": ["ingliz", "english", "grammatika", "tarjima", "translate",
                    "so'z", "tense", "verb", "preposition", "ielts", "toefl"],
    "dasturlash": ["dasturlash", "kod", "python", "javascript", "java", "html",
                   "css", "algoritm", "funksiya", "xato", "bug", "api", "sql",
                   "programma", "dastur", "git"],
    "tibbiyot": ["tibbiyot", "shifokor", "kasallik", "dori", "sog'liq", "yurak",
                 "qon", "virus", "infeksiya", "vitamin", "organ", "tana"],
    "biznes": ["biznes", "marketing", "startup", "foyda", "savdo", "mijoz",
               "investitsiya", "kpi", "strategiya", "kompaniya", "bozor", "soliq"],
    "fan": ["kimyo", "biologiya", "molekula", "quyosh", "sayyora", "fotosintez",
            "reaksiya", "fan", "suv", "formula", "element", "kislorod", "vodorod",
            "tajriba"],
    "geografiya": ["geografiya", "davlat", "poytaxt", "okean", "dengiz", "qit'a",
                   "daryo", "tog'", "iqlim", "xarita", "shahar", "viloyat"],
    "adabiyot": ["adabiyot", "roman", "she'r", "shoir", "yozuvchi", "asar",
                 "doston", "qissa", "navoiy", "qodiriy", "kitob", "muallif"],
    "manga": ["manga", "anime", "naruto", "one piece", "bleach", "otaku",
              "panel", "janr", "personaj", "seinen", "shonen"],
    "umumiy bilim": ["umumiy", "bilim", "savol", "nima", "kim", "qachon", "qayerda"],
}

# Arifmetik ifoda (masalan "12 x 8", "5 + 3") — matematika
_ARITH = re.compile(r"\d+\s*[\+\-*/x×÷]\s*\d+")


def detect_topic(text: str) -> str | None:
    """Matndan sohani aniqlaydi (so'z boshi bo'yicha moslik)."""
    norm = normalize(text)
    if not norm:
        return None
    if _ARITH.search(norm):
        return "matematika"
    for topic, words in TOPIC_KEYWORDS.items():
        for w in words:
            if re.search(rf"(^|\s){re.escape(w)}", norm):
                return topic
    return None


async def find_instant_reply(text: str) -> dict | None:
    """Tezkor javobni topadi: avval aniq moslik, keyin qisqa xabarlar uchun ibora."""
    if not config.ENABLE_INSTANT_REPLIES:
        return None
    if (text or "").strip().startswith("/"):
        return None
    norm = normalize(text)
    if not norm:
        return None

    hit = await db.get_instant_reply(norm)
    if hit:
        return hit

    if len(norm) <= config.INSTANT_MAX_LEN:
        cur = await db.db.execute(
            "SELECT * FROM instant_replies ORDER BY priority DESC, LENGTH(keyword) DESC"
        )
        rows = await cur.fetchall()
        for row in rows:
            kw = row["keyword"]
            if re.search(rf"(^|\s){re.escape(kw)}(\s|$)", norm):
                await db.db.execute(
                    "UPDATE instant_replies SET hits = hits + 1 WHERE id = ?", (row["id"],)
                )
                await db.db.commit()
                return dict(row)
    return None


async def _typing(message: Message) -> None:
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:  # noqa: BLE001
        pass


def _split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


async def _safe_send(message: Message, text: str) -> None:
    """Markdown buzilsa, oddiy matn sifatida qayta yuboradi."""
    if not text:
        text = "🤔 Javob bo'sh chiqdi. Savolni boshqacha yozib ko'ring."
    for chunk in _split(text, 4000):
        try:
            await message.answer(chunk)
        except Exception:  # noqa: BLE001
            await message.answer(chunk, parse_mode=None)


async def _ask_gemini(message: Message, prompt: str, **kwargs) -> str | None:
    """Gemini'ga so'rov yuborib, javobni xavfsiz yuboradi va matnini qaytaradi."""
    await _typing(message)
    try:
        answer = await pool.generate(prompt, system_instruction=SYSTEM_PROMPT, **kwargs)
    except AllKeysFailedError as exc:
        log.error("Gemini xatosi: %s", exc)
        await message.answer(
            "⚠️ Hozircha AI xizmatiga ulanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
        return None
    except Exception as exc:  # noqa: BLE001
        log.exception("Kutilmagan xato: %s", exc)
        await message.answer("⚠️ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
        return None

    await _safe_send(message, answer)
    return answer


async def _ask_gemini_custom(
    message: Message, prompt: str, system_instruction: str, **kwargs
) -> str | None:
    """Maxsus system prompt bilan so'rov; javob matnini qaytaradi."""
    await _typing(message)
    try:
        return await pool.generate(prompt, system_instruction=system_instruction, **kwargs)
    except AllKeysFailedError as exc:
        log.error("Gemini xatosi: %s", exc)
        await message.answer(
            "⚠️ Hozircha AI xizmatiga ulanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Kutilmagan xato: %s", exc)
        await message.answer("⚠️ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
    return None


async def get_admin_ids() -> list[int]:
    """Admin ID lar: .env dagi + botga /start yuborgan adminlar."""
    ids = set(config.ADMIN_IDS)
    ids.update(await db.get_registered_admins())
    return list(ids)


# --------------------------------------------------------------------------- #
# Klaviaturalar
# --------------------------------------------------------------------------- #
def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎤 IELTS Speaking", callback_data="menu:speaking")
    kb.button(text="✍️ IELTS Writing", callback_data="menu:writing")
    kb.button(text="➗ Matematika", callback_data="menu:math")
    kb.button(text="⚛️ Fizika", callback_data="menu:physics")
    kb.button(text="🧰 Vositalar", callback_data="menu:tools")
    kb.button(text="📄 PDF testlarni tekshirish", callback_data="menu:pdftest")
    kb.button(text="🎯 Testlar (umumiy)", callback_data="menu:quiz")
    kb.button(text="🔄 Suhbatni tozalash", callback_data="menu:reset")
    kb.adjust(2, 2, 1, 1, 1, 1)
    return kb.as_markup()


def speaking_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Part 1 — oddiy savollar", callback_data="sp:part:1")
    kb.button(text="Part 2 — cue card", callback_data="sp:part:2")
    kb.button(text="Part 3 — muhokama", callback_data="sp:part:3")
    kb.button(text="⬅️ Orqaga", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def writing_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Task 1 — grafik/xat", callback_data="wr:task:1")
    kb.button(text="Task 2 — insho", callback_data="wr:task:2")
    kb.button(text="⬅️ Orqaga", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def subject_kb(subject: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Misol yechilishi", callback_data=f"sub:{subject}:solve")
    kb.button(text="🎯 Testlar", callback_data=f"sub:{subject}:list")
    kb.button(text="➕ Test qo'shish", callback_data=f"sub:{subject}:add")
    kb.button(text="⬅️ Orqaga", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def tools_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Savol qo'shish", callback_data="tools:addq")
    kb.button(text="📢 Kanalga ulash", callback_data="tools:channel")
    kb.button(text="⬅️ Orqaga", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def qadd_type_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎤 IELTS Speaking", callback_data="qadd:type:speaking")
    kb.button(text="✍️ IELTS Writing", callback_data="qadd:type:writing")
    kb.button(text="➗ Matematika", callback_data="qadd:type:math")
    kb.button(text="⚛️ Fizika", callback_data="qadd:type:phys")
    kb.button(text="📄 PDF dan test", callback_data="qadd:type:pdf")
    kb.button(text="⬅️ Orqaga", callback_data="menu:tools")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def qadd_speaking_part_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Part 1", callback_data="qadd:sp:1")
    kb.button(text="Part 2", callback_data="qadd:sp:2")
    kb.button(text="Part 3", callback_data="qadd:sp:3")
    kb.button(text="⬅️ Orqaga", callback_data="tools:addq")
    kb.adjust(3, 1)
    return kb.as_markup()


def qadd_writing_task_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Task 1", callback_data="qadd:wr:1")
    kb.button(text="Task 2", callback_data="qadd:wr:2")
    kb.button(text="⬅️ Orqaga", callback_data="tools:addq")
    kb.adjust(2, 1)
    return kb.as_markup()


def channel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Kanal ulash", callback_data="chan:connect")
    kb.button(text="📋 Kanallarim", callback_data="chan:list")
    kb.button(text="✍️ Kanalga post", callback_data="chan:post")
    kb.button(text="🗓 Post rejalashtirish", callback_data="chan:schedule")
    kb.button(text="⬅️ Orqaga", callback_data="menu:tools")
    kb.adjust(1)
    return kb.as_markup()


def reminders_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Yangi eslatma", callback_data="tools:rem_new")
    kb.button(text="📋 Mening eslatmalarim", callback_data="tools:rem_list")
    kb.button(text="⬅️ Orqaga", callback_data="menu:tools")
    kb.adjust(1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
# Test (quiz) yordamchilari
# --------------------------------------------------------------------------- #
async def send_question(chat_id: int, user_id: int) -> None:
    sess = await db.get_quiz_session(user_id)
    if not sess:
        return
    idx = sess["current"]
    qids = sess["question_ids"]
    if idx >= len(qids):
        await finish_quiz(chat_id, user_id)
        return

    q = await db.get_question(qids[idx])
    if not q:
        await finish_quiz(chat_id, user_id)
        return

    kb = InlineKeyboardBuilder()
    for i, opt in enumerate(q["options"]):
        kb.button(text=f"{chr(65 + i)}. {opt}", callback_data=f"q:{q['id']}:{i}")
    kb.adjust(1)

    text = (
        f"🎯 <b>Savol {idx + 1}/{len(qids)}</b>  ·  {esc(q['topic'])}\n\n"
        f"{esc(q['question'])}"
    )
    await bot.send_message(chat_id, text, reply_markup=kb.as_markup(), parse_mode="HTML")


async def finish_quiz(chat_id: int, user_id: int) -> None:
    res = await db.finish_quiz(user_id)
    if not res:
        return
    score, total = res["score"], res["total"]
    pct = round(score / total * 100) if total else 0

    if pct >= 80:
        verdict = "🏆 Ajoyib natija!"
    elif pct >= 50:
        verdict = "👍 Yaxshi, davom eting!"
    else:
        verdict = "📚 Yana mashq qilish kerak."

    lines = [
        "🏁 <b>Test yakunlandi!</b>",
        f"📊 Natija: <b>{score}/{total}</b> ({pct}%)",
        verdict,
    ]

    wrong = [a for a in res["answers"] if not a["correct"]]
    if wrong:
        lines.append("\n❌ <b>Xatolar tahlili:</b>")
        for a in wrong:
            q = await db.get_question(a["q"])
            if q:
                lines.append(
                    f"• {esc(q['question'])}\n"
                    f"  ✅ To'g'ri javob: <b>{esc(q['options'][q['answer']])}</b>"
                )
    else:
        lines.append("\n🎉 Barcha savollarga to'g'ri javob berdingiz!")

    lines.append("\n🔁 Yana o'tash uchun: /quiz")
    await bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


# --------------------------------------------------------------------------- #
# Test kod tizimi yordamchilari
# --------------------------------------------------------------------------- #
def check_answers(user_answers: str, correct: str) -> tuple[int, list[dict]]:
    """Foydalanuvchi javoblarini ('abcdfdddd') to'g'ri javoblar bilan solishtiradi."""
    ua = re.sub(r"[^a-f]", "", (user_answers or "").lower())
    ca = re.sub(r"[^a-f]", "", (correct or "").lower())
    total = len(ca)
    detail: list[dict] = []
    correct_count = 0
    for i in range(total):
        u = ua[i] if i < len(ua) else "-"
        c = ca[i]
        ok = u == c
        if ok:
            correct_count += 1
        detail.append({"i": i + 1, "user": u, "correct": c, "ok": ok})
    return correct_count, detail


def format_test_result(code: str, title: str, correct: int, total: int,
                       detail: list[dict], questions: list[dict]) -> str:
    pct = round(correct / total * 100) if total else 0
    if pct >= 80:
        verdict = "🏆 Ajoyib!"
    elif pct >= 50:
        verdict = "👍 Yaxshi!"
    else:
        verdict = "📚 Yana mashq qiling."

    lines = [
        f"🏁 <b>{esc(code)}</b> — {esc(title)}",
        f"📊 Natija: <b>{correct}/{total}</b> ({pct}%)  {verdict}",
    ]
    wrong = [d for d in detail if not d["ok"]]
    if wrong:
        lines.append("\n❌ <b>Xatolar:</b>")
        for d in wrong:
            idx = d["i"] - 1
            qtext = ""
            if 0 <= idx < len(questions):
                qtext = questions[idx].get("q", "")
            lines.append(
                f"• {d['i']}. {esc(qtext)}\n"
                f"  Siz: <b>{esc(d['user'].upper())}</b> · "
                f"To'g'ri: <b>{esc(d['correct'].upper())}</b>"
            )
    else:
        lines.append("\n🎉 Barcha javoblar to'g'ri!")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# PDF test yordamchilari
# --------------------------------------------------------------------------- #
_MC_OPT_RE = re.compile(r"^\s*([A-F])[\)\.]\s*(.+)$")
_OPEN_SUB_RE = re.compile(r"^\s*([a-f])[\)\.]\s*(.+)$")
_Q_LINE_RE = re.compile(r"^\s*(\d{1,3})\s*[\)\.]\s*(.+)$")
_ANS_TOKEN_RE = re.compile(r"^(\d{1,3})([a-fA-F])?\)(.+)$")


def extract_pdf_text(data: bytes) -> str:
    """PDF baytlaridan matn ajratadi (pypdf)."""
    try:
        import io

        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        log.error("pypdf import xatosi: %s", exc)
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        log.error("PDF o'qishda xato: %s", exc)
        return ""


def parse_pdf_questions(text: str) -> list[dict]:
    """PDF matnidan savollarni ajratadi.

    Formatlar:
      * Test (MC):  ``1) Savol`` + ``A) variant`` ``B) variant`` ...
      * Ochiq:      ``36) Savol`` + ``a) ...`` ``b) ...``  -> kalitlar ``36a``, ``36b``
    """
    questions: list[dict] = []
    cur: dict | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m_mc = _MC_OPT_RE.match(line)
        if m_mc and cur is not None and cur["type"] == "mc":
            cur["options"].append(m_mc.group(2).strip())
            continue
        m_sub = _OPEN_SUB_RE.match(line)
        if m_sub and cur is not None:
            if cur["type"] == "mc" and not cur["options"]:
                cur["type"] = "open"
            if cur["type"] == "open":
                letter = m_sub.group(1).lower()
                questions.append({
                    "n": cur["n"],
                    "key": f"{cur['n']}{letter}",
                    "q": f"{cur['q']} ({letter})",
                    "options": [],
                    "type": "open",
                })
                continue
        m_q = _Q_LINE_RE.match(line)
        if m_q:
            if cur is not None and cur["type"] == "mc":
                questions.append(cur)
            cur = {
                "n": int(m_q.group(1)),
                "key": str(int(m_q.group(1))),
                "q": m_q.group(2).strip(),
                "options": [],
                "type": "mc",
            }
            continue
        if cur is not None:
            if cur["options"]:
                cur["options"][-1] += " " + line
            else:
                cur["q"] += " " + line
    if cur is not None and cur["type"] == "mc":
        questions.append(cur)
    for q in questions:
        if q["type"] == "mc" and not q["options"]:
            q["type"] = "open"
    return questions[: config.PDF_MAX_QUESTIONS]


def parse_answer_input(text: str, questions: list[dict]) -> dict[str, str]:
    """Javob kiritmasini tahlil qiladi (admin kaliti ham, foydalanuvchi javobi ham).

    Qo'llab-quvvatlanadi:
      * ``abcdba``      — test (MC) javoblari ketma-ketligi
      * ``36a)2.3``     — ochiq savol javobi (savol raqami + variant harfi)
      * ``36)2.3``      — ochiq savol javobi (faqat raqam)
    """
    answers: dict[str, str] = {}
    mc_seq = ""
    for token in re.split(r"[\s,;]+", (text or "").strip()):
        if not token:
            continue
        m = _ANS_TOKEN_RE.match(token)
        if m:
            num = int(m.group(1))
            letter = (m.group(2) or "").lower()
            answers[f"{num}{letter}"] = m.group(3).strip()
            continue
        if re.fullmatch(r"[a-fA-F]+", token):
            mc_seq += token.lower()
    mc_questions = [q for q in questions if q.get("type") == "mc"]
    for i, q in enumerate(mc_questions):
        if i < len(mc_seq):
            answers[q["key"]] = mc_seq[i]
    return answers


def check_pdf_answers(user_input: str, test: dict) -> tuple[int, int, list[dict]]:
    """PDF test javoblarini to'g'ri kalit bilan solishtiradi.

    Qaytaradi: ``(to'g'ri_soni, jami, tafsilotlar)``.
    """
    questions = test["questions"]
    correct_map = test["answers"]
    parsed = parse_answer_input(user_input, questions)

    detail: list[dict] = []
    correct_count = 0
    for q in questions:
        key = q["key"]
        u = str(parsed.get(key, "-")).strip()
        c = str(correct_map.get(key, "")).strip()
        ok = bool(c) and u.lower() == c.lower()
        if ok:
            correct_count += 1
        detail.append({
            "key": key, "n": q.get("n"), "q": q.get("q", ""),
            "user": u, "correct": c, "ok": ok, "type": q.get("type"),
        })
    return correct_count, len(questions), detail


def format_pdf_result(code: str, title: str, correct: int, total: int,
                      detail: list[dict]) -> str:
    pct = round(correct / total * 100) if total else 0
    if pct >= 80:
        verdict = "🏆 Ajoyib!"
    elif pct >= 50:
        verdict = "👍 Yaxshi!"
    else:
        verdict = "📚 Yana mashq qiling."

    lines = [
        f"🏁 <b>{esc(code)}</b> — {esc(title)}",
        f"📊 Natija: <b>{correct}/{total}</b> ({pct}%)  {verdict}",
    ]
    wrong = [d for d in detail if not d["ok"]]
    if wrong:
        lines.append("\n❌ <b>Xatolar:</b>")
        for d in wrong:
            lines.append(
                f"• <b>{esc(d['key'])}</b>. {esc(d['q'])}\n"
                f"  Siz: <b>{esc(d['user'])}</b> · To'g'ri: <b>{esc(d['correct'])}</b>"
            )
    else:
        lines.append("\n🎉 Barcha javoblar to'g'ri!")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Eslatma vaqtini tahlil qilish
# --------------------------------------------------------------------------- #
def parse_reminder_time(s: str) -> float | None:
    """Vaqtni tahlil qiladi: '+30m', '+2h', '+1d', 'HH:MM', 'YYYY-MM-DD HH:MM'."""
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


# --------------------------------------------------------------------------- #
# Handlers — buyruqlar
# --------------------------------------------------------------------------- #
@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
        if config.is_admin(u.id, u.username):
            await db.register_admin(u.id)
    name = u.first_name if u else "do'stim"
    await message.answer(
        f"👋 Salom, *{name}*!\n\n"
        "Men *AI Manager* — HAMMA soha bo'yicha AI yordamchingizman.\n\n"
        "Quyidagi bo'limlardan birini tanlang 👇",
        reply_markup=main_menu_kb(),
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
    await message.answer("🏠 *Asosiy menyu* — bo'limni tanlang:", reply_markup=main_menu_kb())


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "ℹ️ *AI Manager — yordam*\n\n"
        "🏠 *Bo'limlar (menyu):*\n"
        "🎤 IELTS Speaking — Part 1/2/3, ovozli javobni baholash\n"
        "✍️ IELTS Writing — Task 1/2, inshoni baholash\n"
        "➗ Matematika — misol yechish + testlar\n"
        "⚛️ Fizika — misol yechish + testlar\n"
        "🧰 Vositalar — savol qo'shish, kanal boshqaruvi\n\n"
        "🎯 *Buyruqlar:*\n"
        "`/menu` — asosiy menyu\n"
        "`/quiz` — soha bo'yicha test\n"
        "`/stats` — statistika\n"
        "`/history` — suhbat tarixi\n"
        "`/reset` — suhbatni tozalash (yangi suhbat)\n"
        "`/lang` — til (uz/en/ru)\n"
        "`/bank [so'z]` — savollar banki\n"
        "`/manga Naruto` — manga haqida\n"
        "`/image <tavsif>` — rasm yaratish\n\n"
        "🧠 *Suhbat xotirasi:* bot oldingi gaplaringizni eslab qoladi. "
        "«tahlil qil», «davom et», «shuni ishlab ber» kabi so'rovlar oldingi "
        "mavzuga tayanadi. Yangidan boshlash uchun: /reset\n\n"
        "📢 *Kanal boshqaruvi (admin):*\n"
        "🧰 Vositalar → 📢 Kanalga ulash → kanal ulash, post joylash, "
        "post rejalashtirish.\n\n"
        "📝 *Test kod tizimi:*\n"
        "Test kodini yuboring (masalan `MATH-0001`), so'ng javoblarni "
        "`abcdfdddd` ko'rinishida yuboring.\n\n"
        "💬 Har qanday sohada savol yozing — javob beraman.\n"
        "⚡ salom/rahmat kabi so'zlarga AI'siz, darhol javob beraman."
    )


@dp.message(Command("quiz"))
async def cmd_quiz(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)

    topics = await db.get_topics()
    if not topics:
        await message.answer("⚠️ Test savollari bazasi bo'sh.")
        return

    kb = InlineKeyboardBuilder()
    for t in topics:
        n = await db.count_questions(t)
        kb.button(text=f"{t} ({n})", callback_data=f"topic:{t}")
    kb.adjust(2)

    await message.answer("🎯 *Test o'tash*\n\nQaysi sohadan boshlaymiz?", reply_markup=kb.as_markup())


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)

    users = await db.count_users()
    msgs = await db.count_messages()
    instant = await db.count_instant_replies()
    questions = await db.count_questions()
    all_stats = await db.get_all_stats()
    top = await db.top_topics(5)
    results = await db.get_quiz_results(u.id, 3) if u else []
    math_n = await db.count_tests("math")
    phys_n = await db.count_tests("physics")
    bank_n = await db.count_question_bank()

    lines = [
        "📊 *Statistika*\n",
        f"👥 Foydalanuvchilar: *{users}*",
        f"💬 Jami xabarlar: *{msgs}*",
        f"⚡ Tezkor javoblar bazasi: *{instant}*",
        f"🎯 Test savollari: *{questions}*",
        f"➗ Matematika testlari: *{math_n}*",
        f"⚛️ Fizika testlari: *{phys_n}*",
        f"📚 Savollar banki: *{bank_n}*",
        f"🤖 AI so'rovlar: *{all_stats.get('ai_requests', 0)}*",
        f"⚡ Tezkor javoblar (ishlatilgan): *{all_stats.get('instant_hits', 0)}*",
        f"🏁 O'tilgan testlar: *{all_stats.get('quizzes_taken', 0)}*",
    ]

    if top:
        lines.append("\n🔥 *Eng ko'p so'ralgan sohalar:*")
        for topic, cnt in top:
            lines.append(f"• {topic} — {cnt}")

    if results:
        lines.append("\n🕘 *Sizning oxirgi testlaringiz:*")
        for r in results:
            lines.append(f"• {r['topic']}: {r['score']}/{r['total']}")

    await message.answer("\n".join(lines))


@dp.message(Command("history"))
async def cmd_history(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await db.upsert_user(u.id, u.username, u.first_name)
    rows = await db.get_history(u.id, limit=10)
    if not rows:
        await message.answer("🕘 Hozircha suhbat tarixi bo'sh. Savol yozing!")
        return

    lines = ["🕘 *Oxirgi suhbatlaringiz:*\n"]
    for r in reversed(rows):
        who = "👤" if r["role"] == "user" else "🤖"
        txt = r["text"].replace("\n", " ")
        if len(txt) > 120:
            txt = txt[:120] + "…"
        lines.append(f"{who} {txt}")

    lines.append("\n🗑 Tozalash uchun: /clearhistory")
    await message.answer("\n".join(lines))


@dp.message(Command("clearhistory"))
async def cmd_clear_history(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await db.clear_history(u.id)
    await message.answer("🗑 Suhbat tarixi tozalandi.")


@dp.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Suhbatni tozalab, yangi suhbat boshlaydi (kontekstni unutadi)."""
    u = message.from_user
    if not u:
        return
    await db.clear_history(u.id)
    await message.answer(
        "🔄 *Suhbat tozalandi.* Yangi suhbat boshlandi — endi bot oldingi "
        "gaplarni eslab qolmaydi.",
        reply_markup=main_menu_kb(),
    )


@dp.message(Command("lang"))
async def cmd_lang(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇿 O'zbek", callback_data="lang:uz")
    kb.button(text="🇬🇧 English", callback_data="lang:en")
    kb.button(text="🇷🇺 Русский", callback_data="lang:ru")
    kb.adjust(3)
    await message.answer("🌐 *Tilni tanlang:*", reply_markup=kb.as_markup())


@dp.message(Command("bank"))
async def cmd_bank(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
    query = (message.text or "").partition(" ")[2].strip()
    rows = await db.search_question_bank(query or None, limit=10)
    if not rows:
        await message.answer(
            "📚 Savollar banki bo'sh yoki natija topilmadi.\n"
            "Savol bersangiz, javoblar avtomatik bankka saqlanadi."
        )
        return
    lines = ["📚 *Savollar banki:*\n"]
    for r in rows:
        q = r["question"].replace("\n", " ")[:100]
        lines.append(f"• [{r['subject']}] {q}")
    lines.append("\n🔎 Qidirish: `/bank so'z`")
    await message.answer("\n".join(lines))


@dp.message(Command("manga"))
async def cmd_manga(message: Message) -> None:
    title = (message.text or "").partition(" ")[2].strip()
    if not title:
        await message.answer("✍️ Foydalanish: `/manga Naruto`")
        return
    prompt = (
        f"Quyidagi manga haqida batafsil ma'lumot ber: **{title}**.\n"
        "Format:\n📖 Nomi va muallifi\n🎭 Janr\n📝 Qisqa syujet (3-5 gap)\n"
        "👥 Asosiy personajlar\n⭐ Nega o'qishga arziydi\n🔗 O'xshash asarlar"
    )
    await _ask_gemini(message, prompt)


@dp.message(Command("recommend"))
async def cmd_recommend(message: Message) -> None:
    genre = (message.text or "").partition(" ")[2].strip() or "umumiy"
    prompt = (
        f"'{genre}' janridagi 5 ta ajoyib manga tavsiya qil. "
        "Har biri uchun: nomi, muallifi, 1-2 gaplik tavsif va nima uchun mos kelishini yoz."
    )
    await _ask_gemini(message, prompt)


@dp.message(Command("image"))
async def cmd_image(message: Message) -> None:
    prompt = (message.text or "").partition(" ")[2].strip()
    if not prompt:
        await message.answer("✍️ Foydalanish: `/image kiberpank manga qahramoni`")
        return
    if not config.ENABLE_IMAGE_GEN:
        await message.answer("🖼 Rasm generatsiyasi o'chirilgan.")
        return

    await _typing(message)
    try:
        images = await pool.generate_image(prompt, count=1)
    except AllKeysFailedError as exc:
        log.error("Rasm xatosi: %s", exc)
        await message.answer(
            "⚠️ Rasm yaratib bo'lmadi. Imagen modeli hisobingizda yoqilmagan bo'lishi mumkin."
        )
        return

    for img in images:
        await message.answer_photo(BufferedInputFile(img, filename="image.png"))


# --------------------------------------------------------------------------- #
# Handlers — asosiy menyu callbacklari
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "menu:main")
async def on_menu_main(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        await cb.message.edit_text("🏠 *Asosiy menyu* — bo'limni tanlang:",
                                   reply_markup=main_menu_kb())
    except Exception:  # noqa: BLE001
        await cb.message.answer("🏠 *Asosiy menyu*:", reply_markup=main_menu_kb())


@dp.callback_query(F.data == "menu:reset")
async def on_menu_reset(cb: CallbackQuery) -> None:
    """Suhbat tarixini tozalab, yangi suhbat boshlaydi."""
    await cb.answer("Suhbat tozalandi")
    await db.clear_history(cb.from_user.id)
    try:
        await cb.message.edit_text(
            "🔄 *Suhbat tozalandi.* Yangi suhbat boshlandi — endi bot oldingi "
            "gaplarni eslab qolmaydi.\n\n🏠 *Asosiy menyu* — bo'limni tanlang:",
            reply_markup=main_menu_kb(),
        )
    except Exception:  # noqa: BLE001
        await cb.message.answer(
            "🔄 Suhbat tozalandi. Yangi suhbat boshlandi.",
            reply_markup=main_menu_kb(),
        )


@dp.callback_query(F.data == "menu:speaking")
async def on_menu_speaking(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "🎤 *IELTS Speaking*\n\nQuestion type ni tanlang:",
        reply_markup=speaking_kb(),
    )


@dp.callback_query(F.data == "menu:writing")
async def on_menu_writing(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "✍️ *IELTS Writing*\n\nTask ni tanlang:",
        reply_markup=writing_kb(),
    )


@dp.callback_query(F.data == "menu:math")
async def on_menu_math(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "➗ *Matematika*\n\nBo'limni tanlang:",
        reply_markup=subject_kb("math"),
    )


@dp.callback_query(F.data == "menu:physics")
async def on_menu_physics(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "⚛️ *Fizika*\n\nBo'limni tanlang:",
        reply_markup=subject_kb("phys"),
    )


@dp.callback_query(F.data == "menu:tools")
async def on_menu_tools(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "🧰 *Vositalar*\n\nBo'limni tanlang:",
        reply_markup=tools_kb(),
    )


@dp.callback_query(F.data == "menu:pdftest")
async def on_menu_pdftest(cb: CallbackQuery) -> None:
    """PDF testlarni tekshirish: test kodini so'raydi."""
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "pdf_answers_code", {})
    await cb.message.edit_text(
        "📄 *PDF testlarni tekshirish*\n\n"
        "Test kodini kiriting:\n\n"
        "Misol: `12345`",
        reply_markup=InlineKeyboardBuilder().button(
            text="⬅️ Orqaga", callback_data="menu:main"
        ).as_markup(),
    )


@dp.callback_query(F.data == "menu:quiz")
async def on_menu_quiz(cb: CallbackQuery) -> None:
    await cb.answer()
    topics = await db.get_topics()
    if not topics:
        await cb.message.answer("⚠️ Test savollari bazasi bo'sh.")
        return
    kb = InlineKeyboardBuilder()
    for t in topics:
        n = await db.count_questions(t)
        kb.button(text=f"{t} ({n})", callback_data=f"topic:{t}")
    kb.adjust(2)
    await cb.message.edit_text("🎯 *Test o'tash*\n\nQaysi sohadan boshlaymiz?",
                               reply_markup=kb.as_markup())


# --------------------------------------------------------------------------- #
# Handlers — IELTS Speaking
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("sp:part:"))
async def on_speaking_part(cb: CallbackQuery) -> None:
    part = int(cb.data.split(":")[2])
    user_id = cb.from_user.id
    qs = await db.get_speaking_questions(part, limit=1)
    if not qs:
        await cb.answer("Bu part uchun savollar topilmadi.", show_alert=True)
        return
    q = qs[0]
    await cb.answer()

    if part == 2:
        bullets = "\n".join(f"• {b}" for b in q["bullets"])
        text = (
            f"🎤 *IELTS Speaking — Part 2 (Cue Card)*\n\n"
            f"*{esc(q['cue_card'] or q['question'])}*\n\n"
            f"{esc(bullets)}\n\n"
            f"⏱ Tayyorgarlik: *{q['prep_seconds'] or 60} soniya*\n"
            f"🗣 Javob: *{q['speak_seconds'] or 120} soniya*\n\n"
            "Tayyor bo'lgach, javobingizni *ovozli xabar* qilib yuboring "
            "(yoki matn yozing) — baholayman."
        )
    else:
        text = (
            f"🎤 *IELTS Speaking — Part {part}*\n\n"
            f"❓ {esc(q['question'])}\n\n"
            "Javobingizni *ovozli xabar* qilib yuboring (yoki matn yozing) — "
            "IELTS mezonlari bo'yicha baholayman."
        )

    await db.set_user_state(user_id, "speaking", {
        "part": part, "question": q["question"], "cue_card": q.get("cue_card", "")
    })
    try:
        await cb.message.edit_text(text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, parse_mode="HTML")


async def assess_speaking(message: Message, state: dict, transcript: str) -> None:
    part = state.get("part", 1)
    question = state.get("question", "")
    prompt = (
        f"Part: {part}\nSavol: {question}\n\n"
        f"Foydalanuvchi javobi:\n{transcript}\n\n"
        "Yuqoridagi javobni IELTS Speaking mezonlari bo'yicha baholang."
    )
    answer = await _ask_gemini_custom(message, prompt, SPEAKING_EXAMINER_PROMPT)
    if answer:
        await _safe_send(message, answer)
    await db.clear_user_state(message.from_user.id)


# --------------------------------------------------------------------------- #
# Handlers — IELTS Writing
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("wr:task:"))
async def on_writing_task(cb: CallbackQuery) -> None:
    task = int(cb.data.split(":")[2])
    user_id = cb.from_user.id
    tasks = await db.get_writing_tasks(task, limit=1)
    if not tasks:
        await cb.answer("Bu task uchun topshiriqlar topilmadi.", show_alert=True)
        return
    t = tasks[0]
    await cb.answer()
    minw = t["min_words"] or (150 if task == 1 else 250)
    text = (
        f"✍️ *IELTS Writing — Task {task}*\n\n"
        f"📄 {esc(t['prompt'])}\n\n"
        f"📏 Kamida *{minw}* so'z yozing.\n\n"
        "Inshoni shu chatga yuboring — IELTS mezonlari bo'yicha baholayman."
    )
    await db.set_user_state(user_id, "writing", {"task": task, "prompt_id": t["id"]})
    try:
        await cb.message.edit_text(text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        await cb.message.answer(text, parse_mode="HTML")


async def assess_writing(message: Message, state: dict, essay: str) -> None:
    task = state.get("task", 2)
    t = await db.get_writing_task(state.get("prompt_id", 0))
    prompt_text = t["prompt"] if t else ""
    minw = (t["min_words"] if t else (150 if task == 1 else 250))
    prompt = (
        f"Task {task} topshirig'i: {prompt_text}\n"
        f"Talab: kamida {minw} so'z.\n\n"
        f"Foydalanuvchi inshosi:\n{essay}\n\n"
        "Yuqoridagi inshoni IELTS Writing mezonlari bo'yicha baholang."
    )
    answer = await _ask_gemini_custom(message, prompt, WRITING_EXAMINER_PROMPT)
    if answer:
        await _safe_send(message, answer)
    await db.clear_user_state(message.from_user.id)


# --------------------------------------------------------------------------- #
# Handlers — Matematika / Fizika
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("sub:"))
async def on_subject_action(cb: CallbackQuery) -> None:
    _, subject, action = cb.data.split(":")
    user_id = cb.from_user.id
    await cb.answer()

    if action == "solve":
        name = "Matematika" if subject == "math" else "Fizika"
        await db.set_user_state(user_id, "problem", {"subject": subject})
        await cb.message.edit_text(
            f"📝 *{name} — misol yechilishi*\n\n"
            "Misol yoki masalani yozib yuboring — qadam-baqadam yechib beraman.",
            reply_markup=subject_kb(subject),
        )
        return

    if action == "list":
        tests = await db.list_tests(subject)
        name = "Matematika" if subject == "math" else "Fizika"
        if not tests:
            await cb.message.edit_text(
                f"🎯 *{name} testlari*\n\nHozircha test yo'q. "
                "«➕ Test qo'shish» orqali qo'shishingiz mumkin.",
                reply_markup=subject_kb(subject),
            )
            return
        lines = [f"🎯 *{name} testlari* ({len(tests)} ta)\n"]
        for t in tests:
            lines.append(f"• `{t['code']}` — {esc(t['title'])}")
        lines.append(
            "\n📌 Test kodini yuboring (masalan `" + tests[0]["code"] + "`), "
            "so'ng javoblarni `abcdfdddd` ko'rinishida yuboring."
        )
        await cb.message.edit_text("\n".join(lines), reply_markup=subject_kb(subject))
        return

    if action == "add":
        name = "Matematika" if subject == "math" else "Fizika"
        await db.set_user_state(user_id, "test_add", {
            "subject": subject, "step": "title", "title": "", "questions": [], "answers": ""
        })
        await cb.message.edit_text(
            f"➕ *{name} — test qo'shish*\n\n"
            "1️⃣ Test sarlavhasini yuboring (masalan: *Algebra asoslari*).\n\n"
            "ℹ️ Test admin tasdiqlagach bazaga qo'shiladi va unikal kod oladi.",
            reply_markup=subject_kb(subject),
        )
        return


async def handle_test_add(message: Message, state: dict, text: str) -> None:
    """Ko'p qadamli test qo'shish oqimi."""
    user_id = message.from_user.id
    subject = state["subject"]
    step = state["step"]
    data = state

    if step == "title":
        data["title"] = text.strip()[:120]
        data["step"] = "questions"
        await db.set_user_state(user_id, "test_add", data)
        await message.answer(
            "2️⃣ Endi savollarni yuboring. Har bir savol alohida qatorda, "
            "quyidagi formatda:\n\n"
            "`Savol matni | variant1 | variant2 | variant3 | variant4`\n\n"
            "Misol:\n"
            "`2+2 nechaga teng? | 3 | 4 | 5 | 6`\n"
            "`5×5 nechaga teng? | 20 | 25 | 30 | 35`"
        )
        return

    if step == "questions":
        questions = []
        for line in text.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            q = parts[0]
            opts = parts[1:5]
            if len(opts) < 2:
                continue
            questions.append({"q": q, "options": opts})
        if not questions:
            await message.answer(
                "⚠️ Savollar formati noto'g'ri. Har bir qatorda "
                "`Savol | v1 | v2 | v3 | v4` ko'rinishida yuboring."
            )
            return
        data["questions"] = questions
        data["step"] = "answers"
        await db.set_user_state(user_id, "test_add", data)
        await message.answer(
            f"✅ {len(questions)} ta savol qabul qilindi.\n\n"
            "3️⃣ Endi to'g'ri javoblarni variant harflari ketma-ketligi sifatida yuboring.\n"
            f"Misol: `{('a' * len(questions))}` (a, b, c, d harflari)."
        )
        return

    if step == "answers":
        answers = re.sub(r"[^a-f]", "", text.lower())
        n = len(data["questions"])
        if len(answers) != n:
            await message.answer(
                f"⚠️ Javoblar soni savollar soniga teng bo'lishi kerak: "
                f"{n} ta harf kerak, siz {len(answers)} ta yubordingiz."
            )
            return

        payload = {
            "title": data["title"],
            "questions": data["questions"],
            "answers": answers,
        }
        u = message.from_user
        is_admin = config.is_admin(u.id, u.username)

        if is_admin:
            code = await db.next_test_code(subject)
            await db.add_test(subject, code, data["title"], data["questions"],
                              answers, created_by=u.id)
            await db.clear_user_state(user_id)
            await message.answer(
                f"✅ Test bazaga qo'shildi!\n\n"
                f"🔑 Kod: `{code}`\n📄 {esc(data['title'])}\n"
                f"❓ Savollar: {n} ta\n\n"
                f"Endi `{code}` kodini yuborib testni boshlash mumkin."
            )
            return

        # Admin emas — tasdiqlash so'rovi
        aid = await db.create_pending_approval(u.id, subject, payload)
        await db.clear_user_state(user_id)
        await message.answer(
            "⏳ So'rovingiz adminga yuborildi. Tasdiqlangach test bazaga qo'shiladi "
            "va sizga kod yuboriladi."
        )
        await notify_admins_approval(aid, u, subject, payload)


async def notify_admins_approval(aid: int, user, subject: str, payload: dict) -> None:
    """Adminga tasdiqlash so'rovini yuboradi."""
    admin_ids = await get_admin_ids()
    if not admin_ids:
        log.warning("Admin ID topilmadi — tasdiqlash so'rovi yuborilmadi (id=%s).", aid)
        return

    name = "Matematika" if subject == "math" else "Fizika"
    uname = f"@{user.username}" if user.username else user.first_name
    qs = payload["questions"]
    preview = "\n".join(f"{i+1}. {q['q']}" for i, q in enumerate(qs[:5]))
    if len(qs) > 5:
        preview += f"\n… (+{len(qs) - 5} ta)"

    text = (
        f"🔔 *Yangi test tasdiqlash so'rovi* (#{aid})\n\n"
        f"👤 Foydalanuvchi: {esc(uname)} (`{user.id}`)\n"
        f"📚 Fan: *{name}*\n"
        f"📄 Sarlavha: {esc(payload['title'])}\n"
        f"❓ Savollar: {len(qs)} ta\n"
        f"🔑 Javoblar: `{payload['answers']}`\n\n"
        f"{esc(preview)}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"appr:ok:{aid}")
    kb.button(text="❌ Rad etish", callback_data=f"appr:no:{aid}")
    kb.adjust(2)

    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb.as_markup(),
                                   parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            log.warning("Adminga (%s) xabar yuborilmadi: %s", admin_id, exc)


@dp.callback_query(F.data.startswith("appr:"))
async def on_approval(cb: CallbackQuery) -> None:
    _, decision, aid_s = cb.data.split(":")
    aid = int(aid_s)
    u = cb.from_user
    if not config.is_admin(u.id, u.username):
        await cb.answer("Faqat admin tasdiqlashi mumkin.", show_alert=True)
        return

    appr = await db.get_pending_approval(aid)
    if not appr or appr["status"] != "pending":
        await cb.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    subject = appr["subject"]
    payload = appr["payload"]
    requester = appr["user_id"]

    # "addq" — savol qo'shishga ruxsat so'rovi (test emas)
    if subject == "addq":
        if decision == "ok":
            await db.set_approval_status(aid, "approved", u.id)
            await db.register_admin(requester, payload.get("username") or None)
            await cb.answer("Ruxsat berildi ✅")
            try:
                await cb.message.edit_text(f"✅ Ruxsat berildi (#{aid})")
            except Exception:  # noqa: BLE001
                pass
            try:
                await bot.send_message(
                    requester,
                    "🎉 Sizga *savol qo'shish* huquqi berildi!\n\n"
                    "Endi «🧰 Vositalar → ➕ Savol qo'shish» orqali savol qo'shishingiz mumkin.",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Foydalanuvchiga (%s) xabar yuborilmadi: %s", requester, exc)
        else:
            await db.set_approval_status(aid, "rejected", u.id)
            await cb.answer("Rad etildi ❌")
            try:
                await cb.message.edit_text(f"❌ Rad etildi (#{aid})")
            except Exception:  # noqa: BLE001
                pass
            try:
                await bot.send_message(
                    requester,
                    f"😔 Afsuski, savol qo'shish so'rovingiz (#{aid}) rad etildi.",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Foydalanuvchiga (%s) xabar yuborilmadi: %s", requester, exc)
        return

    if decision == "ok":
        code = await db.next_test_code(subject)
        await db.add_test(subject, code, payload["title"], payload["questions"],
                          payload["answers"], created_by=requester)
        await db.set_approval_status(aid, "approved", u.id)
        await cb.answer("Tasdiqlandi ✅")
        try:
            await cb.message.edit_text(
                f"✅ Tasdiqlandi (#{aid})\n🔑 Kod: `{code}`\n📄 {esc(payload['title'])}"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            await bot.send_message(
                requester,
                f"🎉 Sizning testingiz tasdiqlandi!\n\n"
                f"🔑 Kod: `{code}`\n📄 {esc(payload['title'])}\n\n"
                f"Endi `{code}` kodini yuborib testni boshlash mumkin."
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Foydalanuvchiga (%s) xabar yuborilmadi: %s", requester, exc)
    else:
        await db.set_approval_status(aid, "rejected", u.id)
        await cb.answer("Rad etildi ❌")
        try:
            await cb.message.edit_text(f"❌ Rad etildi (#{aid})")
        except Exception:  # noqa: BLE001
            pass
        try:
            await bot.send_message(
                requester,
                f"😔 Afsuski, sizning test so'rovingiz (#{aid}) rad etildi."
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Foydalanuvchiga (%s) xabar yuborilmadi: %s", requester, exc)


async def handle_test_code(message: Message, code: str) -> None:
    """Test kodini qabul qilib, savollarni ko'rsatadi."""
    user_id = message.from_user.id
    test = await db.get_test_by_code(code)
    if not test:
        await message.answer(f"⚠️ `{code}` kodi topilmadi.")
        return

    qs = test["questions"]
    lines = [f"🎯 *{esc(test['code'])}* — {esc(test['title'])}\n"]
    for i, q in enumerate(qs):
        lines.append(f"*{i+1}.* {esc(q['q'])}")
        for j, opt in enumerate(q["options"]):
            lines.append(f"   {chr(65 + j)}) {esc(opt)}")
        lines.append("")
    lines.append(
        f"📝 Javoblarni *{len(qs)}* ta harf sifatida ketma-ket yuboring.\n"
        f"Misol: `{('a' * len(qs))}`"
    )
    await db.set_user_state(user_id, "test_answers", {"code": test["code"]})
    await message.answer("\n".join(lines), parse_mode="HTML")


async def handle_test_answers(message: Message, state: dict, text: str) -> None:
    """Foydalanuvchi javoblarini tekshiradi."""
    user_id = message.from_user.id
    code = state["code"]
    test = await db.get_test_by_code(code)
    if not test:
        await db.clear_user_state(user_id)
        await message.answer("⚠️ Test topilmadi.")
        return

    ua = re.sub(r"[^a-f]", "", text.lower())
    n = len(test["questions"])
    if len(ua) != n:
        await message.answer(
            f"⚠️ {n} ta harf kerak, siz {len(ua)} ta yubordingiz. "
            f"Qaytadan yuboring (masalan `{('a' * n)}`)."
        )
        return

    correct, detail = check_answers(ua, test["answers"])
    await db.record_submission(user_id, code, test["subject"], ua, correct, n, detail)
    await db.bump("quizzes_taken")
    await db.clear_user_state(user_id)

    result = format_test_result(code, test["title"], correct, n, detail, test["questions"])
    await message.answer(result, parse_mode="HTML")


# --------------------------------------------------------------------------- #
# Handlers — PDF testlar (qo'shish + tekshirish)
# --------------------------------------------------------------------------- #
async def handle_pdf_add(message: Message, state: dict, text: str) -> None:
    """PDF dan test qo'shishning ko'p qadamli oqimi.

    Qadamlar: file -> code -> title -> answers
    """
    user_id = message.from_user.id
    step = state.get("step", "file")

    if step == "code":
        code = text.strip()
        if not code or len(code) > 32 or " " in code:
            await message.answer(
                "⚠️ Kod bo'sh joysiz, 32 belgidan qisqa bo'lsin. Qaytadan kiriting:"
            )
            return
        if await db.pdf_test_code_exists(code):
            await message.answer(
                f"⚠️ `{code}` kodi allaqachon band. Boshqa kod kiriting:"
            )
            return
        state["code"] = code
        state["step"] = "title"
        await db.set_user_state(user_id, "pdf_add", state)
        await message.answer(
            "3️⃣ Test sarlavhasini kiriting (masalan: *Matematika 1-chorak testi*)."
        )
        return

    if step == "title":
        state["title"] = text.strip()[:120] or state.get("code", "PDF test")
        state["step"] = "answers"
        await db.set_user_state(user_id, "pdf_add", state)
        qs = state.get("questions", [])
        mc = [q for q in qs if q.get("type") == "mc"]
        op = [q for q in qs if q.get("type") == "open"]
        await message.answer(
            "4️⃣ Endi *to'g'ri javoblarni* kiriting.\n\n"
            f"📊 Savollar: *{len(qs)}* ta (test: {len(mc)}, ochiq: {len(op)})\n\n"
            "Formatlar:\n"
            "• Test savollari — harflar ketma-ketligi: `abcdba`\n"
            "• Ochiq savollar — `36a)2.3` yoki `36)2.3`\n\n"
            "Ikkalasini birga yuborish mumkin:\n"
            "`abcdba 36a)2.3 36b)4.5`"
        )
        return

    if step == "answers":
        questions = state.get("questions", [])
        answers = parse_answer_input(text, questions)
        if not answers:
            await message.answer(
                "⚠️ Javoblarni tushunmadim. Test uchun `abcdba`, ochiq uchun "
                "`36a)2.3` ko'rinishida yuboring."
            )
            return
        code = state.get("code", "")
        title = state.get("title", code)
        await db.add_pdf_test(
            code, title, questions, answers,
            subject=state.get("subject", "umumiy"),
            source_file=state.get("source_file", ""),
            created_by=user_id,
        )
        await db.clear_user_state(user_id)
        await message.answer(
            f"✅ *PDF test bazaga qo'shildi!*\n\n"
            f"🔑 Kod: `{code}`\n📄 {esc(title)}\n"
            f"❓ Savollar: {len(questions)} ta\n"
            f"🔖 Javoblar: {len(answers)} ta\n\n"
            "Endi asosiy menyudagi «📄 PDF testlarni tekshirish» orqali "
            f"`{code}` kodini kiritib testni boshlash mumkin.",
            reply_markup=qadd_type_kb(),
        )
        return


async def handle_pdf_answers_code(message: Message, text: str) -> None:
    """Foydalanuvchi kiritgan test kodini tekshiradi va javob oynasini chiqaradi."""
    user_id = message.from_user.id
    code = text.strip()
    test = await db.get_pdf_test_by_code(code)
    if not test:
        await message.answer(
            f"⚠️ `{code}` kodi topilmadi. Kodni to'g'ri kiriting yoki "
            "«⬅️ Orqaga» orqali menyuga qayting."
        )
        return

    qs = test["questions"]
    lines = [f"📄 *{esc(test['code'])}* — {esc(test['title'])}\n"]
    for q in qs:
        if q.get("type") == "mc":
            lines.append(f"*{q['n']}.* {esc(q['q'])}")
            for j, opt in enumerate(q.get("options", [])):
                lines.append(f"   {chr(65 + j)}) {esc(opt)}")
        else:
            lines.append(f"*{q['key']}.* {esc(q['q'])}")
        lines.append("")
    mc = [q for q in qs if q.get("type") == "mc"]
    op = [q for q in qs if q.get("type") == "open"]
    lines.append("📝 *Javoblaringizni yuboring:*")
    if mc:
        lines.append(f"• Test savollari ({len(mc)} ta) — `{('a' * len(mc))}` ko'rinishida")
    if op:
        lines.append("• Ochiq savollar — `36a)2.3` ko'rinishida")
    lines.append("\nMisol: `abcdba 36a)2.3`")

    await db.set_user_state(user_id, "pdf_answers_input", {"code": test["code"]})
    await message.answer("\n".join(lines), parse_mode="HTML")


async def handle_pdf_answers_input(message: Message, state: dict, text: str) -> None:
    """Foydalanuvchi javoblarini tekshiradi va xatolarni ko'rsatadi."""
    user_id = message.from_user.id
    code = state["code"]
    test = await db.get_pdf_test_by_code(code)
    if not test:
        await db.clear_user_state(user_id)
        await message.answer("⚠️ Test topilmadi.")
        return

    correct, total, detail = check_pdf_answers(text, test)
    await db.record_submission(
        user_id, code, test.get("subject", "umumiy"),
        text.strip(), correct, total, detail,
    )
    await db.bump("quizzes_taken")
    await db.clear_user_state(user_id)

    result = format_pdf_result(code, test["title"], correct, total, detail)
    await message.answer(result, parse_mode="HTML")


# --------------------------------------------------------------------------- #
# Handlers — Vositalar (v4: faqat 2 ta — Savol qo'shish, Kanalga ulash)
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "tools:addq")
async def on_tools_addq(cb: CallbackQuery) -> None:
    u = cb.from_user
    await cb.answer()
    if config.is_admin(u.id, u.username):
        await cb.message.edit_text(
            "➕ *Savol qo'shish*\n\nQaysi bo'limga savol qo'shmoqchisiz?",
            reply_markup=qadd_type_kb(),
        )
        return
    # Admin emas — admindan ruxsat so'raymiz
    aid = await db.create_pending_approval(
        u.id, "addq",
        {"username": u.username or "", "first_name": u.first_name or "", "user_id": u.id},
    )
    await cb.message.edit_text(
        "⏳ *Ruxsat so'raldi*\n\n"
        "Savol qo'shish uchun admin tasdiqlashi kerak. So'rovingiz adminga "
        "yuborildi — tasdiqlangach sizga xabar beraman."
    )
    await notify_admins_addq(aid, u)


async def notify_admins_addq(aid: int, user) -> None:
    """Adminga 'savol qo'shish' ruxsat so'rovini yuboradi."""
    admin_ids = await get_admin_ids()
    if not admin_ids:
        log.warning("Admin ID topilmadi — addq so'rovi yuborilmadi (id=%s).", aid)
        return
    uname = f"@{user.username}" if user.username else (user.first_name or "noma'lum")
    text = (
        f"🔔 *Savol qo'shish uchun ruxsat so'rovi* (#{aid})\n\n"
        f"👤 Foydalanuvchi: {esc(uname)}\n"
        f"🆔 ID: `{user.id}`\n\n"
        "Bu foydalanuvchiga savol qo'shishga ruxsat berasizmi?"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Tasdiqlash", callback_data=f"appr:ok:{aid}")
    kb.button(text="❌ Rad etish", callback_data=f"appr:no:{aid}")
    kb.adjust(2)
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb.as_markup(),
                                   parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            log.warning("Adminga (%s) xabar yuborilmadi: %s", admin_id, exc)


@dp.callback_query(F.data.startswith("qadd:type:"))
async def on_qadd_type(cb: CallbackQuery) -> None:
    kind = cb.data.split(":")[2]
    await cb.answer()
    if kind == "speaking":
        await cb.message.edit_text(
            "🎤 *IELTS Speaking* — qaysi partga savol qo'shasiz?",
            reply_markup=qadd_speaking_part_kb(),
        )
    elif kind == "writing":
        await cb.message.edit_text(
            "✍️ *IELTS Writing* — qaysi taskka topshiriq qo'shasiz?",
            reply_markup=qadd_writing_task_kb(),
        )
    elif kind in ("math", "phys"):
        name = "Matematika" if kind == "math" else "Fizika"
        await db.set_user_state(cb.from_user.id, "test_add", {
            "subject": kind, "step": "title", "title": "", "questions": [], "answers": ""
        })
        await cb.message.edit_text(
            f"➕ *{name} — test qo'shish*\n\n"
            "1️⃣ Test sarlavhasini yuboring (masalan: *Algebra asoslari*).\n\n"
            "ℹ️ Test admin tasdiqlagach bazaga qo'shiladi va unikal kod oladi."
        )
    elif kind == "pdf":
        await db.set_user_state(cb.from_user.id, "pdf_add", {"step": "file"})
        await cb.message.edit_text(
            "📄 *PDF dan test qo'shish*\n\n"
            "1️⃣ PDF faylni yuboring (matematika yoki ixtiyoriy sohadan).\n\n"
            "ℹ️ PDF dan savollar avtomatik ajratib olinadi. Keyin test kodini, "
            "sarlavhani va to'g'ri javoblarni kiritasiz.\n\n"
            "📌 Ochiq savollar formati: `36a)2.3` (savol raqami + variant harfi + javob)."
        )


@dp.callback_query(F.data.startswith("qadd:sp:"))
async def on_qadd_speaking_part(cb: CallbackQuery) -> None:
    part = int(cb.data.split(":")[2])
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "qadd_speaking", {"part": part})
    if part == 2:
        await cb.message.edit_text(
            "🎤 *IELTS Speaking — Part 2 (cue card)*\n\n"
            "Cue card mavzusini yuboring. Keyingi qatordan bandlarni yozing.\n\n"
            "Format:\n`Mavzu | band1 | band2 | band3`\n\n"
            "Misol:\n`Describe a book you liked | what it was | why you read it | why you liked it`"
        )
    else:
        await cb.message.edit_text(
            f"🎤 *IELTS Speaking — Part {part}*\n\n"
            "Savol matnini yuboring (ixtiyoriy: `savol | mavzu`)."
        )


@dp.callback_query(F.data.startswith("qadd:wr:"))
async def on_qadd_writing_task(cb: CallbackQuery) -> None:
    task = int(cb.data.split(":")[2])
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "qadd_writing", {"task": task})
    await cb.message.edit_text(
        f"✍️ *IELTS Writing — Task {task}*\n\n"
        "Topshiriq matnini yuboring (ixtiyoriy: `topshiriq | min_so'z`)."
    )


@dp.callback_query(F.data == "tools:channel")
async def on_tools_channel(cb: CallbackQuery) -> None:
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await cb.message.edit_text(
            "🔒 *Kanalga ulash* faqat admin uchun.\n\n"
            f"Admin: @{config.ADMIN_USERNAMES[0] if config.ADMIN_USERNAMES else 'admin'}"
        )
        return
    n = await db.count_channels()
    await cb.message.edit_text(
        f"📢 *Kanal boshqaruvi*\n\nUlangan kanallar: *{n}* ta\n\nBo'limni tanlang:",
        reply_markup=channel_kb(),
    )


@dp.callback_query(F.data == "chan:connect")
async def on_chan_connect(cb: CallbackQuery) -> None:
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "chan_connect", {})
    await cb.message.edit_text(
        "➕ *Kanal ulash*\n\n"
        "Kanalning @username ini yoki ID sini yuboring.\n\n"
        "⚠️ Bot kanalda *admin* bo'lishi shart.\n\n"
        "Misol: `@mening_kanalim` yoki `-1001234567890`"
    )


@dp.callback_query(F.data == "chan:list")
async def on_chan_list(cb: CallbackQuery) -> None:
    await cb.answer()
    rows = await db.list_channels()
    if not rows:
        await cb.message.edit_text(
            "📋 Hozircha kanal ulanmagan.\n\n«➕ Kanal ulash» orqali ulang.",
            reply_markup=channel_kb(),
        )
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Ulangan kanallar:*\n"]
    for r in rows:
        uname = f" (@{r['username']})" if r["username"] else ""
        lines.append(f"• {esc(r['title'] or r['channel_id'])}{uname}\n  `{r['channel_id']}`")
        kb.button(text=f"🗑 {r['title'] or r['channel_id']}", callback_data=f"chan:del:{r['channel_id']}")
    kb.button(text="⬅️ Orqaga", callback_data="tools:channel")
    kb.adjust(1)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("chan:del:"))
async def on_chan_del(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[2])
    await db.delete_channel(cid)
    await cb.answer("O'chirildi 🗑")
    rows = await db.list_channels()
    if not rows:
        await cb.message.edit_text("📋 Kanallar yo'q.", reply_markup=channel_kb())
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Ulangan kanallar:*\n"]
    for r in rows:
        lines.append(f"• {esc(r['title'] or r['channel_id'])} — `{r['channel_id']}`")
        kb.button(text=f"🗑 {r['title'] or r['channel_id']}", callback_data=f"chan:del:{r['channel_id']}")
    kb.button(text="⬅️ Orqaga", callback_data="tools:channel")
    kb.adjust(1)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


async def _pick_channel(cb: CallbackQuery, action: str) -> None:
    rows = await db.list_channels()
    if not rows:
        await cb.message.edit_text(
            "⚠️ Avval kanal ulang («➕ Kanal ulash»).", reply_markup=channel_kb()
        )
        return
    if len(rows) == 1:
        await _start_channel_action(cb, action, rows[0]["channel_id"])
        return
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.button(text=r["title"] or str(r["channel_id"]),
                  callback_data=f"chan:{action}:pick:{r['channel_id']}")
    kb.button(text="⬅️ Orqaga", callback_data="tools:channel")
    kb.adjust(1)
    await cb.message.edit_text("📢 Qaysi kanalga?", reply_markup=kb.as_markup())


async def _start_channel_action(cb: CallbackQuery, action: str, channel_id: int) -> None:
    if action == "post":
        await db.set_user_state(cb.from_user.id, "chan_post", {"channel_id": channel_id})
        await cb.message.edit_text(
            "✍️ *Kanalga post*\n\n"
            "Yubormoqchi bo'lgan matnni (yoki rasmni izohi bilan) yuboring — "
            "kanalga joylayman."
        )
    elif action == "schedule":
        await db.set_user_state(cb.from_user.id, "chan_schedule", {"channel_id": channel_id})
        await cb.message.edit_text(
            "🗓 *Post rejalashtirish*\n\n"
            "Format: `matn | vaqt`\n\n"
            "Vaqt: `+30m`, `+2h`, `+1d`, `09:30`, `2026-10-20 14:00`\n"
            "Takrorlash uchun: `matn | +1d | 1440` (har 1440 daqiqada)\n\n"
            "Misol: `Bugungi test savollari | +2h`"
        )


@dp.callback_query(F.data == "chan:post")
async def on_chan_post(cb: CallbackQuery) -> None:
    await cb.answer()
    await _pick_channel(cb, "post")


@dp.callback_query(F.data == "chan:schedule")
async def on_chan_schedule(cb: CallbackQuery) -> None:
    await cb.answer()
    await _pick_channel(cb, "schedule")


@dp.callback_query(F.data.startswith("chan:post:pick:"))
async def on_chan_post_pick(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[3])
    await cb.answer()
    await _start_channel_action(cb, "post", cid)


@dp.callback_query(F.data.startswith("chan:schedule:pick:"))
async def on_chan_schedule_pick(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[3])
    await cb.answer()
    await _start_channel_action(cb, "schedule", cid)


async def handle_channel_connect(message: Message, text: str) -> None:
    """Kanalni ulash: @username yoki ID ni tekshirib bazaga yozadi."""
    user_id = message.from_user.id
    raw = text.strip()
    try:
        chat = await bot.get_chat(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("Kanal topilmadi (%s): %s", raw, exc)
        await message.answer(
            "⚠️ Kanal topilmadi. @username yoki ID to'g'riligini tekshiring va "
            "bot kanalga qo'shilganiga ishonch hosil qiling."
        )
        return

    # Bot kanalda admin ekanligini tekshiramiz
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat.id, me.id)
        status = getattr(member, "status", "")
        if status not in ("administrator", "creator"):
            await message.answer(
                "⚠️ Bot bu kanalda *admin* emas. Iltimos, botni kanalga admin qilib "
                "qo'shing, so'ng qayta urinib ko'ring."
            )
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("A'zolikni tekshirishda xato: %s", exc)
        await message.answer("⚠️ Kanal a'zoligini tekshirib bo'lmadi.")
        return

    await db.add_channel(user_id, chat.id, chat.title or "", chat.username or "")
    await db.clear_user_state(user_id)
    uname = f" (@{chat.username})" if chat.username else ""
    await message.answer(
        f"✅ *Kanal ulandi!*\n\n"
        f"📢 {esc(chat.title or chat.id)}{uname}\n"
        f"🆔 `{chat.id}`\n\n"
        "Endi «✍️ Kanalga post» yoki «🗓 Post rejalashtirish» orqali post joylashingiz mumkin.",
        reply_markup=channel_kb(),
    )


async def handle_channel_post(message: Message, state: dict, text: str) -> None:
    """Kanalga darhol post joylaydi."""
    user_id = message.from_user.id
    cid = state["channel_id"]
    try:
        await bot.send_message(cid, text, parse_mode=None)
    except Exception as exc:  # noqa: BLE001
        log.warning("Kanalga post yuborilmadi (%s): %s", cid, exc)
        await message.answer("⚠️ Kanalga post yuborilmadi. Bot admin ekanligini tekshiring.")
        return
    await db.clear_user_state(user_id)
    await message.answer("✅ Post kanalga joylandi!", reply_markup=channel_kb())


async def handle_channel_schedule(message: Message, state: dict, text: str) -> None:
    """Kanalga postni rejalashtiradi."""
    user_id = message.from_user.id
    cid = state["channel_id"]
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        await message.answer(
            "⚠️ Format: `matn | vaqt`\nMisol: `Test savollari | +2h`"
        )
        return
    body = parts[0]
    ts = parse_reminder_time(parts[1])
    if not body or ts is None:
        await message.answer(
            "⚠️ Vaqtni tushunmadim. Formatlar: `+30m`, `+2h`, `+1d`, `09:30`, "
            "`2026-10-20 14:00`."
        )
        return
    repeat = 0
    if len(parts) >= 3 and parts[2].isdigit():
        repeat = int(parts[2])
    pid = await db.add_scheduled_post(cid, body, ts, repeat_minutes=repeat, created_by=user_id)
    await db.clear_user_state(user_id)
    dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    rep = f"\n🔁 Har {repeat} daqiqada takrorlanadi" if repeat else ""
    await message.answer(
        f"✅ Post rejalashtirildi! (#{pid})\n\n📌 {esc(body)}\n⏰ {dt}{rep}",
        reply_markup=channel_kb(),
    )


async def handle_qadd_speaking(message: Message, state: dict, text: str) -> None:
    """IELTS Speaking savolini bazaga qo'shadi."""
    user_id = message.from_user.id
    part = state.get("part", 1)
    if part == 2:
        parts = [p.strip() for p in text.split("|")]
        cue = parts[0]
        bullets = [p for p in parts[1:] if p]
        await db.add_speaking_question(
            part, cue, cue_card=cue, bullets=bullets, prep_seconds=60, speak_seconds=120
        )
    else:
        parts = [p.strip() for p in text.split("|")]
        q = parts[0]
        topic = parts[1] if len(parts) > 1 else ""
        await db.add_speaking_question(part, q, topic=topic)
    await db.clear_user_state(user_id)
    await message.answer(
        f"✅ Savol qo'shildi! (IELTS Speaking — Part {part})",
        reply_markup=qadd_type_kb(),
    )


async def handle_qadd_writing(message: Message, state: dict, text: str) -> None:
    """IELTS Writing topshirig'ini bazaga qo'shadi."""
    user_id = message.from_user.id
    task = state.get("task", 2)
    parts = [p.strip() for p in text.split("|")]
    prompt = parts[0]
    minw = 0
    if len(parts) > 1 and parts[1].isdigit():
        minw = int(parts[1])
    await db.add_writing_task(task, prompt, min_words=minw)
    await db.clear_user_state(user_id)
    await message.answer(
        f"✅ Topshiriq qo'shildi! (IELTS Writing — Task {task})",
        reply_markup=qadd_type_kb(),
    )


@dp.callback_query(F.data == "tools:rem")
async def on_tools_rem(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text(
        "⏰ *Eslatmalar*\n\nEslatma o'rnating — belgilangan vaqtda eslatib qo'yaman.",
        reply_markup=reminders_kb(),
    )


@dp.callback_query(F.data == "tools:rem_new")
async def on_rem_new(cb: CallbackQuery) -> None:
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "reminder", {})
    await cb.message.edit_text(
        "⏰ *Yangi eslatma*\n\n"
        "Eslatma matni va vaqtini quyidagi formatda yuboring:\n\n"
        "`matn | vaqt`\n\n"
        "Vaqt formatlari:\n"
        "• `+30m` — 30 daqiqadan so'ng\n"
        "• `+2h` — 2 soatdan so'ng\n"
        "• `+1d` — 1 kundan so'ng\n"
        "• `09:30` — bugun/ertaga 09:30\n"
        "• `2026-10-20 14:00` — aniq sana va vaqt\n\n"
        "Misol: `Darsni takrorlash | +2h`",
        reply_markup=reminders_kb(),
    )


@dp.callback_query(F.data == "tools:rem_list")
async def on_rem_list(cb: CallbackQuery) -> None:
    await cb.answer()
    rows = await db.list_reminders(cb.from_user.id, only_pending=True)
    if not rows:
        await cb.message.edit_text("📋 Hozircha faol eslatmalar yo'q.",
                                   reply_markup=reminders_kb())
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Faol eslatmalar:*\n"]
    for r in rows:
        dt = datetime.fromtimestamp(r["remind_at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• #{r['id']} — {esc(r['text'])} ({dt})")
        kb.button(text=f"🗑 #{r['id']}", callback_data=f"rem:del:{r['id']}")
    kb.button(text="⬅️ Orqaga", callback_data="tools:rem")
    kb.adjust(3)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("rem:del:"))
async def on_rem_del(cb: CallbackQuery) -> None:
    rid = int(cb.data.split(":")[2])
    await db.delete_reminder(rid, cb.from_user.id)
    await cb.answer("O'chirildi 🗑")
    rows = await db.list_reminders(cb.from_user.id, only_pending=True)
    if not rows:
        await cb.message.edit_text("📋 Faol eslatmalar yo'q.", reply_markup=reminders_kb())
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Faol eslatmalar:*\n"]
    for r in rows:
        dt = datetime.fromtimestamp(r["remind_at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• #{r['id']} — {esc(r['text'])} ({dt})")
        kb.button(text=f"🗑 #{r['id']}", callback_data=f"rem:del:{r['id']}")
    kb.button(text="⬅️ Orqaga", callback_data="tools:rem")
    kb.adjust(3)
    await cb.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())


async def handle_reminder(message: Message, text: str) -> None:
    user_id = message.from_user.id
    if "|" not in text:
        await message.answer(
            "⚠️ Format: `matn | vaqt`\nMisol: `Darsni takrorlash | +2h`"
        )
        return
    body, _, when = text.partition("|")
    body = body.strip()
    ts = parse_reminder_time(when.strip())
    if not body or ts is None:
        await message.answer(
            "⚠️ Vaqtni tushunmadim. Formatlar: `+30m`, `+2h`, `+1d`, `09:30`, "
            "`2026-10-20 14:00`."
        )
        return
    await db.add_reminder(user_id, body, ts)
    await db.clear_user_state(user_id)
    dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    await message.answer(f"✅ Eslatma o'rnatildi!\n\n📌 {esc(body)}\n⏰ {dt}")


# --------------------------------------------------------------------------- #
# Handlers — quiz callbacklari
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("topic:"))
async def on_topic_choice(cb: CallbackQuery) -> None:
    topic = cb.data.split(":", 1)[1]
    user_id = cb.from_user.id
    n = config.QUIZ_QUESTIONS_PER_SESSION
    questions = await db.pick_questions(topic, n)
    if not questions:
        await cb.answer("Bu sohada savollar topilmadi.", show_alert=True)
        return

    await db.start_quiz(user_id, topic, [q["id"] for q in questions])
    await db.bump("quizzes_taken")
    await cb.answer()
    try:
        await cb.message.edit_text(f"🎯 *{topic}* — test boshlandi! ({len(questions)} savol)")
    except Exception:  # noqa: BLE001
        pass
    await send_question(cb.message.chat.id, user_id)


@dp.callback_query(F.data.startswith("q:"))
async def on_quiz_answer(cb: CallbackQuery) -> None:
    try:
        _, qid_s, idx_s = cb.data.split(":")
        qid, idx = int(qid_s), int(idx_s)
    except ValueError:
        await cb.answer("Xato ma'lumot.", show_alert=True)
        return

    user_id = cb.from_user.id
    sess = await db.get_quiz_session(user_id)
    if not sess:
        await cb.answer("Test topilmadi. /quiz bilan boshlang.", show_alert=True)
        return

    qids = sess["question_ids"]
    if sess["current"] >= len(qids) or qids[sess["current"]] != qid:
        await cb.answer("Bu savol eskirgan.", show_alert=True)
        return

    q = await db.get_question(qid)
    if not q:
        await cb.answer("Savol topilmadi.", show_alert=True)
        return

    correct = idx == q["answer"]
    await db.record_answer(user_id, qid, idx, correct)

    if correct:
        result = "✅ <b>To'g'ri!</b>"
    else:
        result = (
            f"❌ <b>Xato.</b>\n"
            f"To'g'ri javob: <b>{esc(q['options'][q['answer']])}</b>"
        )
    if q.get("explanation"):
        result += f"\n💡 {esc(q['explanation'])}"

    try:
        await cb.message.edit_text(f"{esc(q['question'])}\n\n{result}", parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass

    await cb.answer("To'g'ri!" if correct else "Xato")
    await send_question(cb.message.chat.id, user_id)


@dp.callback_query(F.data.startswith("lang:"))
async def on_lang_choice(cb: CallbackQuery) -> None:
    lang = cb.data.split(":", 1)[1]
    await db.set_language(cb.from_user.id, lang)
    names = {"uz": "🇺🇿 O'zbek", "en": "🇬🇧 English", "ru": "🇷🇺 Русский"}
    await cb.answer(f"Til: {names.get(lang, lang)}")
    try:
        await cb.message.edit_text(f"✅ Til o'zgartirildi: *{names.get(lang, lang)}*")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Handlers — ovoz, rasm, PDF, erkin matn
# --------------------------------------------------------------------------- #
@dp.message(F.document)
async def on_document(message: Message) -> None:
    """PDF faylni qabul qilib, undan test qo'shadi (admin yoki ruxsat olgan)."""
    u = message.from_user
    if not u:
        return
    await db.upsert_user(u.id, u.username, u.first_name)

    doc = message.document
    fname = (doc.file_name or "").lower()
    if not fname.endswith(".pdf"):
        await message.answer("⚠️ Faqat *PDF* fayl qabul qilinadi.")
        return

    state = await db.get_user_state(u.id)
    if not state or state["state"] != "pdf_add":
        await message.answer(
            "ℹ️ PDF dan test qo'shish uchun: «🧰 Vositalar → ➕ Savol qo'shish → "
            "📄 PDF dan test» ni tanlang."
        )
        return

    if not config.is_admin(u.id, u.username):
        await message.answer("🔒 PDF dan test qo'shish faqat admin uchun.")
        return

    size_mb = (doc.file_size or 0) / (1024 * 1024)
    if size_mb > config.PDF_MAX_MB:
        await message.answer(
            f"⚠️ Fayl juda katta ({size_mb:.1f} MB). Maksimal: {config.PDF_MAX_MB} MB."
        )
        return

    await _typing(message)
    try:
        file = await bot.get_file(doc.file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
    except Exception as exc:  # noqa: BLE001
        log.exception("PDF yuklab olishda xato: %s", exc)
        await message.answer("⚠️ PDF faylni yuklab bo'lmadi.")
        return

    text = extract_pdf_text(data)
    if not text.strip():
        await message.answer(
            "⚠️ PDF dan matn ajratib bo'lmadi (skanerlangan rasm bo'lishi mumkin). "
            "Boshqa PDF yuboring."
        )
        return

    questions = parse_pdf_questions(text)
    if not questions:
        await message.answer(
            "⚠️ PDF da savollar topilmadi. Savollar `1) ...` ko'rinishida "
            "bo'lishi kerak."
        )
        return

    mc = [q for q in questions if q.get("type") == "mc"]
    op = [q for q in questions if q.get("type") == "open"]
    state["questions"] = questions
    state["source_file"] = doc.file_name or ""
    state["step"] = "code"
    await db.set_user_state(u.id, "pdf_add", state)

    await message.answer(
        f"✅ PDF o'qildi: *{len(questions)}* ta savol topildi "
        f"(test: {len(mc)}, ochiq: {len(op)}).\n\n"
        "2️⃣ Endi test uchun *kod* kiriting (masalan: `12345`).\n\n"
        "ℹ️ Bu kodni foydalanuvchilar testni topish uchun ishlatadi."
    )


@dp.message(F.voice)
async def on_voice(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await db.upsert_user(u.id, u.username, u.first_name)
    if config.is_admin(u.id, u.username):
        await db.register_admin(u.id)

    if not config.ENABLE_VOICE:
        await message.answer("🎙 Ovozli rejim o'chirilgan.")
        return

    await _typing(message)
    try:
        file = await bot.get_file(message.voice.file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
    except Exception as exc:  # noqa: BLE001
        log.exception("Ovozni yuklab olishda xato: %s", exc)
        await message.answer("⚠️ Ovozli xabarni yuklab bo'lmadi.")
        return

    state = await db.get_user_state(u.id)

    # IELTS Speaking baholash
    if state and state["state"] == "speaking":
        prompt = (
            "Quyidagi ovozli xabarni tingla, matnga o'gir (transkript) va "
            "IELTS Speaking mezonlari bo'yicha bahola."
        )
        answer = await _ask_gemini_custom(
            message, prompt, SPEAKING_EXAMINER_PROMPT,
            image_bytes=data, image_mime="audio/ogg",
        )
        if answer:
            await _safe_send(message, answer)
        await db.clear_user_state(u.id)
        return

    # Umumiy ovozli rejim: transkript + javob (suhbat konteksti bilan)
    prompt = (
        "Quyidagi ovozli xabarni tingla va matnga o'gir (transkript). "
        "So'ng transkriptdagi savol yoki so'rovga javob ber. "
        "Javobni quyidagi formatda yoz:\n"
        "🎤 Transkript: <matn>\n\n"
        "💬 Javob: <javob>"
    )
    context = await db.get_context_history(u.id, limit=config.HISTORY_CONTEXT_SIZE)
    answer = await _ask_gemini_custom(
        message, prompt, SYSTEM_PROMPT, image_bytes=data, image_mime="audio/ogg",
        history=context,
    )
    if answer:
        await db.add_history(u.id, "user", "[ovozli xabar]", source="voice")
        await db.add_history(u.id, "assistant", answer, source="voice")
        await _safe_send(message, answer)


@dp.message(F.photo)
async def on_photo(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)

    # Kanalga rasm post qilish holati
    if u:
        state = await db.get_user_state(u.id)
        if state and state["state"] == "chan_post":
            cid = state["data"]["channel_id"]
            caption = (message.caption or "").strip()
            try:
                await bot.send_photo(cid, message.photo[-1].file_id,
                                     caption=caption or None)
            except Exception as exc:  # noqa: BLE001
                log.warning("Kanalga rasm yuborilmadi (%s): %s", cid, exc)
                await message.answer("⚠️ Kanalga rasm yuborilmadi. Bot admin ekanligini tekshiring.")
                return
            await db.clear_user_state(u.id)
            await message.answer("✅ Rasm kanalga joylandi!", reply_markup=channel_kb())
            return

    await _typing(message)
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
    except Exception as exc:  # noqa: BLE001
        log.exception("Rasm yuklab olishda xato: %s", exc)
        await message.answer("⚠️ Rasmni yuklab bo'lmadi.")
        return

    caption = (message.caption or "").strip()
    prompt = (
        "Bu rasmni tahlil qil: unda nima tasvirlangan, matn bo'lsa o'qib ber, "
        "uslub, kayfiyat va mazmun haqida gapirib ber."
    )
    if caption:
        prompt += f" Foydalanuvchi so'rovi: {caption}"

    # Suhbat konteksti (oldingi gaplar) — rasm tahlili ham kontekstga bog'lansin
    context = []
    if u:
        context = await db.get_context_history(u.id, limit=config.HISTORY_CONTEXT_SIZE)
        await db.add_history(
            u.id, "user", f"[rasm] {caption}".strip(), source="image"
        )
    answer = await _ask_gemini(
        message, prompt, image_bytes=data, image_mime="image/jpeg", history=context
    )
    if u and answer:
        await db.add_history(u.id, "assistant", answer, source="image")


@dp.message(F.text, ~F.text.startswith("/"))
async def on_text(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    text = (message.text or "").strip()
    if not text:
        return

    await db.upsert_user(u.id, u.username, u.first_name)
    if config.is_admin(u.id, u.username):
        await db.register_admin(u.id)

    # 0) Ko'p qadamli holatlar
    state = await db.get_user_state(u.id)
    if state:
        st = state["state"]
        if st == "writing":
            await assess_writing(message, state["data"], text)
            return
        if st == "speaking":
            await assess_speaking(message, state["data"], text)
            return
        if st == "problem":
            subject = state["data"].get("subject", "math")
            sys_p = MATH_SOLVER_PROMPT if subject == "math" else PHYSICS_SOLVER_PROMPT
            answer = await _ask_gemini_custom(message, text, sys_p)
            if answer:
                await _safe_send(message, answer)
            await db.clear_user_state(u.id)
            return
        if st == "test_add":
            await handle_test_add(message, state["data"], text)
            return
        if st == "test_answers":
            await handle_test_answers(message, state["data"], text)
            return
        if st == "reminder":
            await handle_reminder(message, text)
            return
        if st == "chan_connect":
            await handle_channel_connect(message, text)
            return
        if st == "chan_post":
            await handle_channel_post(message, state["data"], text)
            return
        if st == "chan_schedule":
            await handle_channel_schedule(message, state["data"], text)
            return
        if st == "qadd_speaking":
            await handle_qadd_speaking(message, state["data"], text)
            return
        if st == "qadd_writing":
            await handle_qadd_writing(message, state["data"], text)
            return
        if st == "pdf_add":
            await handle_pdf_add(message, state["data"], text)
            return
        if st == "pdf_answers_code":
            await handle_pdf_answers_code(message, text)
            return
        if st == "pdf_answers_input":
            await handle_pdf_answers_input(message, state["data"], text)
            return

    # 1) Test kodi (MATH-0001 / PHY-0001)
    if _TEST_CODE_RE.match(text.strip()):
        await handle_test_code(message, text.strip().upper())
        return

    # 1b) PDF test kodi (masalan '12345') — mavjud bo'lsa javob oynasini chiqaramiz
    if re.fullmatch(r"[A-Za-z0-9_-]{2,32}", text.strip()):
        pdf_test = await db.get_pdf_test_by_code(text.strip())
        if pdf_test:
            await handle_pdf_answers_code(message, text.strip())
            return

    # 2) Faol test bo'lsa — tugmalardan foydalanishni eslatamiz
    sess = await db.get_quiz_session(u.id)
    if sess:
        await message.answer(
            "🎯 Test davom etmoqda — javobni *tugmalardan* tanlang.\n"
            "Qaytadan boshlash uchun: /quiz"
        )
        return

    # 3) Tezkor javob (AI'siz, darhol)
    instant = await find_instant_reply(text)
    if instant:
        await db.add_history(u.id, "user", text, source="instant")
        await db.add_history(u.id, "assistant", instant["reply"], source="instant")
        await db.bump("instant_hits")
        await _safe_send(message, instant["reply"])
        return

    # 4) AI javob (hamma soha) — suhbat konteksti bilan
    topic = detect_topic(text)
    # Kontekst: joriy xabardan OLDINGI qatlamlar (xronologik tartibda)
    context = await db.get_context_history(u.id, limit=config.HISTORY_CONTEXT_SIZE)
    await db.add_history(u.id, "user", text, topic=topic, source="ai")
    await db.bump("ai_requests")
    if topic:
        await db.bump(f"topic:{topic}")

    await _typing(message)
    try:
        answer = await pool.generate(
            text, system_instruction=SYSTEM_PROMPT, history=context
        )
    except AllKeysFailedError as exc:
        log.error("Gemini xatosi: %s", exc)
        await message.answer(
            "⚠️ Hozircha AI xizmatiga ulanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Kutilmagan xato: %s", exc)
        await message.answer("⚠️ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
        return

    await db.add_history(u.id, "assistant", answer, topic=topic, source="ai")
    # Savollar bankiga saqlash
    try:
        await db.add_question_bank(u.id, topic or "umumiy", text, answer)
    except Exception:  # noqa: BLE001
        pass
    await _safe_send(message, answer)


# --------------------------------------------------------------------------- #
# Fon vazifasi — eslatmalar
# --------------------------------------------------------------------------- #
async def reminder_loop() -> None:
    """Har REMINDER_CHECK_INTERVAL sekundda muddati kelgan eslatmalarni yuboradi."""
    log.info("Eslatma fon vazifasi ishga tushdi (har %ss).", config.REMINDER_CHECK_INTERVAL)
    while True:
        try:
            due = await db.get_due_reminders()
            for r in due:
                try:
                    await bot.send_message(
                        r["user_id"],
                        f"⏰ *Eslatma!*\n\n📌 {esc(r['text'])}",
                        parse_mode="HTML",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Eslatma yuborilmadi (%s): %s", r["user_id"], exc)
                await db.mark_reminder_sent(r["id"])
        except Exception as exc:  # noqa: BLE001
            log.exception("Eslatma tsiklida xato: %s", exc)
        await asyncio.sleep(config.REMINDER_CHECK_INTERVAL)


# --------------------------------------------------------------------------- #
# Fon vazifasi — rejalashtirilgan kanal postlari
# --------------------------------------------------------------------------- #
async def post_loop() -> None:
    """Har POST_CHECK_INTERVAL sekundda muddati kelgan kanal postlarini yuboradi."""
    log.info("Kanal postlari fon vazifasi ishga tushdi (har %ss).",
             config.POST_CHECK_INTERVAL)
    while True:
        try:
            due = await db.get_due_scheduled_posts()
            for p in due:
                try:
                    if p["media_type"] == "photo" and p["media_file_id"]:
                        await bot.send_photo(
                            p["channel_id"], p["media_file_id"],
                            caption=p["text"] or None,
                        )
                    else:
                        await bot.send_message(
                            p["channel_id"], p["text"] or "📢", parse_mode=None
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Rejalashtirilgan post yuborilmadi (%s): %s",
                                p["channel_id"], exc)
                if p["repeat_minutes"] and p["repeat_minutes"] > 0:
                    nxt = p["run_at"] + p["repeat_minutes"] * 60
                    # O'tib ketgan bo'lsa, hozirdan boshlab hisoblaymiz
                    now = time.time()
                    while nxt <= now:
                        nxt += p["repeat_minutes"] * 60
                    await db.reschedule_post(p["id"], nxt)
                else:
                    await db.mark_post_sent(p["id"])
        except Exception as exc:  # noqa: BLE001
            log.exception("Post tsiklida xato: %s", exc)
        await asyncio.sleep(config.POST_CHECK_INTERVAL)


# --------------------------------------------------------------------------- #
# Ishga tushirish
# --------------------------------------------------------------------------- #
async def load_data() -> None:
    """JSON bazalarini SQLite'ga yuklaydi."""
    # Tezkor javoblar
    p = Path(config.INSTANT_REPLIES_FILE)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data.get("replies", data) if isinstance(data, dict) else data
            await db.load_instant_replies(items)
        except Exception as exc:  # noqa: BLE001
            log.error("instant_replies.json o'qishda xato: %s", exc)
    else:
        log.warning("Tezkor javoblar fayli topilmadi: %s", p)

    # Umumiy test savollari
    p = Path(config.QUIZ_DATA_FILE)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data.get("questions", data) if isinstance(data, dict) else data
            await db.load_quiz_questions(items)
        except Exception as exc:  # noqa: BLE001
            log.error("quiz_data.json o'qishda xato: %s", exc)
    else:
        log.warning("Test savollari fayli topilmadi: %s", p)

    # IELTS Speaking
    p = Path(config.IELTS_SPEAKING_FILE)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data.get("questions", data) if isinstance(data, dict) else data
            await db.load_ielts_speaking(items)
        except Exception as exc:  # noqa: BLE001
            log.error("ielts_speaking.json o'qishda xato: %s", exc)

    # IELTS Writing
    p = Path(config.IELTS_WRITING_FILE)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items = data.get("tasks", data) if isinstance(data, dict) else data
            await db.load_ielts_writing(items)
        except Exception as exc:  # noqa: BLE001
            log.error("ielts_writing.json o'qishda xato: %s", exc)

    # Matematika testlari
    await _load_subject_tests(config.MATH_TESTS_FILE, "math")
    # Fizika testlari
    await _load_subject_tests(config.PHYSICS_TESTS_FILE, "physics")


async def _load_subject_tests(path_str: str, subject: str) -> None:
    p = Path(path_str)
    if not p.exists():
        log.warning("Test fayli topilmadi: %s", p)
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        tests = data.get("tests", data) if isinstance(data, dict) else data
        for t in tests:
            code = (t.get("code") or "").strip().upper()
            if not code:
                continue
            existing = await db.get_test_by_code(code)
            if existing:
                continue
            await db.add_test(
                subject, code, t.get("title", code),
                t.get("questions", []), t.get("answers", ""),
            )
    except Exception as exc:  # noqa: BLE001
        log.error("%s o'qishda xato: %s", path_str, exc)


async def main() -> None:
    config.validate()
    log.info("Bot ishga tushmoqda... Kalitlar: %d, Modellar: %d",
             len(config.GEMINI_API_KEYS), len(config.GEMINI_MODELS))

    # --- 1) Health server (Render Web Service + keep-alive uchun) ---
    health_runner = None
    if config.ENABLE_HEALTH_SERVER and config.PORT > 0:
        health_runner = await health_server.start_health_server(
            port=config.PORT, host=config.HEALTH_HOST
        )

    # --- 2) Bazani zaxiradan tiklash (agar disk bo'sh bo'lsa) ---
    if backup_mgr.enabled and config.RESTORE_ON_START:
        try:
            await backup_mgr.restore_if_needed()
        except Exception as exc:  # noqa: BLE001
            log.error("Tiklashda xato (davom etamiz): %s", exc)

    # --- 3) Baza va ma'lumotlar ---
    await db.connect()
    await load_data()
    await pool.start()

    # --- 4) Bot ma'lumotini health server'ga uzatish ---
    try:
        me = await bot.get_me()
        health_server.state.bot_username = f"@{me.username}"
    except Exception as exc:  # noqa: BLE001
        log.warning("getMe xato: %s", exc)
    # Watchdog — uzoq muddatli barqarorlik (xotira oqishi + event loop)
    watchdog_mgr = watchdog.Watchdog(
        interval=config.WATCHDOG_INTERVAL,
        memory_limit_mb=config.WATCHDOG_MEMORY_LIMIT_MB,
        gc_every=config.WATCHDOG_GC_EVERY,
    )

    health_server.state.detail = {
        "keys": len(config.GEMINI_API_KEYS),
        "models": len(config.GEMINI_MODELS),
        "db": config.DB_PATH,
        **backup_mgr.stats(),
        **watchdog_mgr.stats(),
    }
    health_server.state.ready = True
    log.info("Bot tayyor: %s", health_server.state.bot_username or "(noma'lum)")

    # --- 5) Fon vazifalari ---
    tasks = [asyncio.create_task(reminder_loop(), name="reminders")]
    tasks.append(asyncio.create_task(post_loop(), name="channel_posts"))

    if backup_mgr.enabled:
        tasks.append(asyncio.create_task(backup_mgr.loop(), name="backup"))

    if config.SELF_PING_URL:
        tasks.append(
            asyncio.create_task(
                health_server.keepalive_loop(
                    config.SELF_PING_URL, config.SELF_PING_INTERVAL
                ),
                name="self_ping",
            )
        )

    if config.WATCHDOG_ENABLED:
        tasks.append(asyncio.create_task(watchdog_mgr.loop(), name="watchdog"))

    try:
        # 409 Conflict: auto-deploy paytida qisqa vaqt ikkita instance
        # ishlashi mumkin. Bu holda bot o'lmaydi — kutib qayta urinadi.
        while True:
            try:
                await dp.start_polling(
                    bot, allowed_updates=dp.resolve_used_update_types()
                )
                break
            except TelegramConflictError:
                log.warning(
                    "409 Conflict — boshqa instance polling qilmoqda. "
                    "15s kutib qayta urinamiz..."
                )
                await asyncio.sleep(15)
    finally:
        for t in tasks:
            t.cancel()
        await pool.close()
        await db.close()
        await bot.session.close()
        if health_runner is not None:
            await health_runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to'xtatildi.")
