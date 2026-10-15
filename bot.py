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

import aiohttp
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

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ChatMemberUpdated,
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
    "va allaqachon berilgan misolni qaytadan so'ramang. Faqat foydalanuvchi aniq "
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

WRITING_TASK1_PROMPT = (
    "Sen tajribali IELTS Writing instruktorsan. Foydalanuvchi Task 1 uchun "
    "grafik, diagramma, jadval yoki jarayon rasmini yuboradi. Vazifang:\n"
    "1) Rasmni diqqat bilan tahlil qil: grafik turi (line/bar/pie/table/process/map), "
    "o'qlar, birliklar, eng yuqori va eng past nuqtalar, umumiy tendentsiya.\n"
    "2) O'zbek tilida qisqa xulosa yoz: asosiy tendentsiyalar va taqqoslashlar.\n"
    "3) Foydalanuvchiga shu grafik asosida IELTS Task 1 inshosini yozish uchun "
    "tuzilma (Introduction / Overview / Body 1 / Body 2) va foydali inglizcha "
    "iboralar (masalan: 'rose sharply', 'accounted for', 'by contrast') taklif qil.\n"
    "4) Oxirida namuna Overview paragrafini ingliz tilida yozib ber.",
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


# --- Navigatsiya tarixi (har bir foydalanuvchi uchun alohida) ---
_nav_stack: dict[int, list[dict]] = {}
_NAV_MAX = 25


def _push_nav(cb: CallbackQuery) -> None:
    """Joriy ekranni navigatsiya tarixiga saqlaydi ('⬅️ Orqaga' uchun)."""
    try:
        msg = cb.message
        if msg is None or not getattr(msg, "text", None):
            return
        stack = _nav_stack.setdefault(cb.from_user.id, [])
        if stack and stack[-1].get("text") == msg.text:
            return
        stack.append({"text": msg.text, "markup": msg.reply_markup})
        if len(stack) > _NAV_MAX:
            stack.pop(0)
    except Exception:  # noqa: BLE001
        pass


def back_kb():
    """Har bir javob tagiga qo'shiladigan '⬅️ Orqaga' + '🏠 Asosiy menyu' tugmalari."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Orqaga", callback_data="nav:back")
    kb.button(text="🏠 Asosiy menyu", callback_data="menu:main")
    kb.adjust(2)
    return kb.as_markup()


def _with_back(markup):
    """Berilgan klaviaturaga '⬅️ Orqaga' va '🏠 Asosiy menyu' tugmalarini qo'shadi."""
    if markup is None:
        return back_kb()
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    flat = [
        getattr(b, "callback_data", None)
        for row in markup.inline_keyboard
        for b in row
    ]
    # Asosiy menyuning o'zida ortiqcha tugma qo'shmaymiz
    if "menu:ai" in flat:
        return markup
    row = []
    if "nav:back" not in flat:
        row.append(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="nav:back"))
    if "menu:main" not in flat:
        row.append(InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="menu:main"))
    if row:
        markup.inline_keyboard.append(row)
    return markup


# --- Pastdagi doimiy panel (reply keyboard) ---
BTN_START = "🚀 Start"
BTN_MAIN = "🏠 Asosiy menyu"
BTN_RESET = "🔄 Suhbatni tozalash"
BTN_REMIND = "⏰ Eslatma"
BTN_CHANNEL = "📢 Kanalga ulanish"


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Pastda doimiy turuvchi panel (inline emas — reply keyboard)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_START), KeyboardButton(text=BTN_MAIN)],
            [KeyboardButton(text=BTN_REMIND), KeyboardButton(text=BTN_RESET)],
            [KeyboardButton(text=BTN_CHANNEL)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# --- Test tugagach: kontakt ulashish (2-talab) ---
CONTACT_BTN = "📱 Telefon raqamim"
CONTACT_RE = re.compile(r"kontakt|aloqa|bog['’]lanish", re.IGNORECASE)


def contact_reply_kb() -> ReplyKeyboardMarkup:
    """Test tugagach ko'rsatiladigan vaqtinchalik kontakt ulashish klaviaturasi."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CONTACT_BTN, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def contact_ask_text(title: str) -> str:
    """Test nomi bilan birga kontakt so'raydigan matn."""
    return (
        f"📄 *{esc(title)}*\n\n"
        "📱 *Bog'lanish uchun kontaktingizni ulashishni xohlaysizmi?*\n"
        "Quyidagi «📱 Telefon raqamim» tugmasini bosing yoki telefon "
        "raqamingizni yozib yuboring — mutaxassis siz bilan bog'lanadi."
    )


# --- Majburiy kanal (subscription gate) ---
def sub_gate_kb() -> InlineKeyboardMarkup:
    """Obuna bo'lmagan foydalanuvchiga ko'rsatiladigan klaviatura.

    Faqat ikkita tugma: kanalga obuna bo'lish havolasi va tekshirish tugmasi.
    """
    kb = InlineKeyboardBuilder()
    if config.REQUIRED_CHANNEL_URL:
        kb.button(text="📢 Kanalga obuna bo'lish", url=config.REQUIRED_CHANNEL_URL)
    kb.button(text="✅ Obunani tekshirish", callback_data="sub:check")
    kb.adjust(1)
    return kb.as_markup()


# Obuna natijasini qisqa muddat keshda saqlaymiz: har bir xabar uchun Telegram
# API'ga murojaat qilish rate-limit'ga olib kelmasligi uchun.
_SUB_CACHE: dict[int, tuple[float, bool]] = {}
_SUB_CACHE_POS_TTL = 180.0  # obuna tasdiqlangan bo'lsa — 3 daqiqa
_SUB_CACHE_NEG_TTL = 30.0   # obuna yo'q bo'lsa — 30 sekund


def gate_text() -> str:
    """Majburiy obuna haqidagi asosiy xabar matni."""
    return (
        "🔒 *Botdan foydalanish uchun kanalga obuna bo'ling*\n\n"
        f"📢 *Kanal:* {config.REQUIRED_CHANNEL_URL}\n\n"
        "Obuna bo'lgach, «✅ Obunani tekshirish» tugmasini bosing."
    )


async def is_subscribed(user_id: int, force: bool = False) -> bool:
    """Foydalanuvchi majburiy kanalga obuna bo'lganini getChatMember orqali tekshiradi.

    force=True — keshni chetlab o'tib, Telegram'dan qayta so'raydi
    («✅ Obunani tekshirish» tugmasi shunday chaqiradi).
    """
    if not config.ENABLE_SUB_GATE or not config.REQUIRED_CHANNEL_URL:
        return True
    # Adminlar tekshiruvsiz o'tadi.
    if user_id in config.ADMIN_IDS:
        return True

    now = time.time()
    if not force:
        cached = _SUB_CACHE.get(user_id)
        if cached is not None:
            ts, value = cached
            ttl = _SUB_CACHE_POS_TTL if value else _SUB_CACHE_NEG_TTL
            if now - ts < ttl:
                return value

    cid = config.REQUIRED_CHANNEL_ID or config.REQUIRED_CHANNEL_URL
    try:
        member = await bot.get_chat_member(chat_id=cid, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        # Tekshirib bo'lmasa (kanal noto'g'ri/yopiq yoki bot admin emas) —
        # foydalanuvchini bloklamaymiz (fail-open).
        log.warning("getChatMember xato (%s): %s", cid, exc)
        return True
    status = getattr(member, "status", "")
    s = (status.value if hasattr(status, "value") else str(status)).lower()
    ok = s in ("creator", "administrator", "member", "restricted")
    _SUB_CACHE[user_id] = (now, ok)
    return ok


async def _gate_send_message(message: Message) -> None:
    """Obuna bo'lmagan foydalanuvchiga ogohlantirish + tugmalarni yuboradi."""
    try:
        await message.answer(gate_text(), reply_markup=sub_gate_kb())
    except Exception as exc:  # noqa: BLE001
        log.warning("Obuna xabarini yuborib bo'lmadi: %s", exc)


async def _gate_reject_callback(cb: CallbackQuery) -> None:
    """Obuna bo'lmagan foydalanuvchi tugma bosganda: alert + ogohlantirish."""
    try:
        await cb.answer("❌ Siz hali kanalga obuna bo'lmagansiz.", show_alert=True)
    except Exception:  # noqa: BLE001
        pass
    for sender in (
        lambda: cb.message.edit_text(gate_text(), reply_markup=sub_gate_kb()),
        lambda: cb.message.answer(gate_text(), reply_markup=sub_gate_kb()),
    ):
        try:
            await sender()
            return
        except Exception:  # noqa: BLE001
            continue
    log.warning("Obuna callback xabarini yuborib bo'lmadi.")


async def require_sub(cb: CallbackQuery) -> bool:
    """Bo'limga kirishdan oldin kanal obunasini tekshiradi. False = to'xtatish."""
    if await is_subscribed(cb.from_user.id, force=True):
        return True
    await _gate_reject_callback(cb)
    return False


# --------------------------------------------------------------------------- #
# MAJBURIY KANAL — GLOBAL FILTR (barcha bo'limlarga tegishli)
# --------------------------------------------------------------------------- #
# Obuna bo'lmagan foydalanuvchi uchun ruxsat etilgan yagona tugmalar:
_GATE_ALLOWED_EXACT = {"sub:check", "sub:noaccess"}
# Kanal egasi tasdiqlash tugmalari (kanal ulash oqimi buzilmasligi uchun).
_GATE_ALLOWED_PREFIX = ("admin:chan:",)
# Matnli buyruqlar: /start o'tadi — handler o'zi obuna xabarini beradi va
# foydalanuvchini bazaga yozadi. Qolgan hamma narsa bloklanadi.
_GATE_ALLOWED_COMMANDS = {"/start"}
# DIQQAT: "my_chat_member" va "chat_member" bu ro'yxatda YO'Q — ular botning
# o'z a'zoligi haqidagi hodisalar (masalan bot kanalga admin qilinishi).
# Ularni to'sish kanal qo'shish oqimini butunlay o'ldiradi: admin hech qanday
# bildirishnoma olmaydi. Gate bu hodisalarni har doim o'tkazib yuboradi.
_GATE_INNER_EVENTS = (
    "message",
    "edited_message",
    "callback_query",
    "channel_post",
    "edited_channel_post",
)


def _gate_inner(event):
    """Update ichidan haqiqiy hodisani (message/callback_query/...) ajratadi."""
    if isinstance(event, (Message, CallbackQuery)):
        return event
    for name in _GATE_INNER_EVENTS:
        obj = getattr(event, name, None)
        if obj is not None:
            return obj
    return None


def _gate_allows(event) -> bool:
    """Obuna bo'lmagan foydalanuvchi uchun ruxsat etilgan hodisami?"""
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return data in _GATE_ALLOWED_EXACT or data.startswith(_GATE_ALLOWED_PREFIX)
    if isinstance(event, Message):
        txt = (event.text or "").strip()
        if not txt:
            return False
        # "/start" yoki "/start@AIManagerProBot"
        first = txt.split()[0].split("@")[0].lower()
        return first in _GATE_ALLOWED_COMMANDS
    return False


async def sub_gate_outer_middleware(handler, event, data):
    """Eng tashqi qatlam: obuna bo'lmagan foydalanuvchini BUTUNLAY to'sadi.

    Bu middleware `dp.update` ga ro'yxatdan o'tadi — ya'ni har qanday
    yangilanish (matn, buyruq, tugma, fayl, ovoz, rasm) handler'ga yetib
    borishidan OLDIN ishlaydi. Shu tufayli obuna bo'lmagan foydalanuvchi
    botning hech bir funksiyasidan foydalana olmaydi.
    """
    if not config.ENABLE_SUB_GATE or not config.REQUIRED_CHANNEL_URL:
        return await handler(event, data)

    # Bot a'zoligi hodisalari (my_chat_member / chat_member) hech qachon
    # to'silmaydi: ular "foydalanuvchi funksiyadan foydalanmoqda" hodisasi emas,
    # balki botning kanalga qo'shilishini bildiradi. Aks holda kanal qo'shish
    # oqimi (adminga ruxsat so'rovi) umuman ishlamaydi.
    if (
        getattr(event, "my_chat_member", None) is not None
        or getattr(event, "chat_member", None) is not None
    ):
        return await handler(event, data)

    inner = _gate_inner(event)
    user = getattr(inner, "from_user", None) if inner is not None else None
    if user is None:
        return await handler(event, data)

    # Adminlar cheklovsiz ishlaydi.
    if config.is_admin(user.id, getattr(user, "username", None)):
        return await handler(event, data)

    if await is_subscribed(user.id):
        return await handler(event, data)

    # --- Obuna bo'lmagan foydalanuvchi ---
    if _gate_allows(inner):
        return await handler(event, data)

    if isinstance(inner, CallbackQuery):
        await _gate_reject_callback(inner)
    elif isinstance(inner, Message):
        await _gate_send_message(inner)
    return None


async def _ans(message: Message, text: str, **kwargs) -> None:
    """Javob yuboradi va tagiga '⬅️ Orqaga' + '🏠 Asosiy menyu' tugmalarini qo'shadi."""
    kwargs["reply_markup"] = _with_back(kwargs.get("reply_markup"))
    await message.answer(text, **kwargs)


async def _edit(cb: CallbackQuery, text: str, **kwargs) -> None:
    """Callback xabarini tahrirlaydi va tagiga navigatsiya tugmalarini qo'shadi."""
    _push_nav(cb)
    kwargs["reply_markup"] = _with_back(kwargs.get("reply_markup"))
    await cb.message.edit_text(text, **kwargs)


async def _reset_my_conversation(user_id: int) -> int:
    """FAQAT shu foydalanuvchining suhbat tarixini tozalaydi.

    Boshqa foydalanuvchilarning suhbatiga hech qanday ta'sir qilmaydi:
    `chat_history` faqat `user_id` bo'yicha o'chiriladi. Shu foydalanuvchining
    navigatsiya tarixi ham tozalanadi. O'chirilgan qatlamlar sonini qaytaradi.
    """
    _nav_stack.pop(user_id, None)
    try:
        return await db.clear_conversation(user_id)
    except Exception:  # noqa: BLE001
        log.exception("Suhbatni tozalashda xato (user=%s)", user_id)
        return 0


async def _safe_send(message: Message, text: str) -> None:
    """Markdown buzilsa, oddiy matn sifatida qayta yuboradi."""
    if not text:
        text = "🤔 Javob bo'sh chiqdi. Savolni boshqacha yozib ko'ring."
    for chunk in _split(text, 4000):
        try:
            await _ans(message, chunk)
        except Exception:  # noqa: BLE001
            await _ans(message, chunk, parse_mode=None)


async def _ask_gemini(message: Message, prompt: str, **kwargs) -> str | None:
    """Gemini'ga so'rov yuborib, javobni xavfsiz yuboradi (xotira bilan).
    Javob matnini ham qaytaradi.
    """
    await _typing(message)
    if "history" not in kwargs:
        u = message.from_user
        if u:
            try:
                kwargs["history"] = await db.get_context_history(
                    u.id, limit=config.HISTORY_CONTEXT_SIZE
                )
            except Exception:  # noqa: BLE001
                kwargs["history"] = []
    try:
        answer = await pool.generate(prompt, system_instruction=SYSTEM_PROMPT, **kwargs)
    except AllKeysFailedError as exc:
        log.error("Gemini xatosi: %s", exc)
        await _ans(message, 
            "⚠️ Hozircha AI xizmatiga ulanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
        return None
    except Exception as exc:  # noqa: BLE001
        log.exception("Kutilmagan xato: %s", exc)
        await _ans(message, "⚠️ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
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
        await _ans(message, 
            "⚠️ Hozircha AI xizmatiga ulanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("Kutilmagan xato: %s", exc)
        await _ans(message, "⚠️ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
    return None


async def get_admin_ids() -> list[int]:
    """Adminning RAQAMLI Telegram ID larini ishonchli aniqlaydi.

    Manbalar (birlashtiriladi):
      1) .env / Render: ADMIN_IDS, ADMIN_ID
      2) Bazadagi `admins` jadvali (botga /start yozgan adminlar)
      3) Bazadagi `users`/`admins` jadvalidan ADMIN_USERNAMES bo'yicha qidiruv

    Ilgari faqat (1) va (2) ishlatilardi — shu sababli ADMIN_ID o'rnatilmagan
    va admin botga /start yozmagan holatda ro'yxat BO'SH qaytardi va adminga
    hech qanday bildirishnoma yuborilmasdi. Endi (3) ham qo'shilgan.
    """
    ids: set[int] = set(config.ADMIN_IDS)

    try:
        ids.update(await db.get_registered_admins())
    except Exception as exc:  # noqa: BLE001
        log.warning("get_registered_admins xato: %s", exc)

    try:
        names = [u for u in config.ADMIN_USERNAMES if u]
        if names:
            ids.update(await db.get_user_ids_by_usernames(names))
    except Exception as exc:  # noqa: BLE001
        log.warning("Admin username bo'yicha qidiruv xato: %s", exc)

    ids.discard(0)
    result = sorted(ids)
    if not result:
        log.error(
            "ADMIN TOPILMADI! ADMIN_IDS=%s ADMIN_ID(belgilanmagan bo'lishi mumkin) "
            "ADMIN_USERNAMES=%s. Admin botga /start yozishi YOKI Render'da "
            "ADMIN_ID raqamli qiymati o'rnatilishi kerak.",
            config.ADMIN_IDS,
            config.ADMIN_USERNAMES,
        )
    return result


# --------------------------------------------------------------------------- #
# Klaviaturalar
# --------------------------------------------------------------------------- #
def main_menu_kb(is_admin: bool = False):
    """Asosiy menyu. `📊 Statistika` faqat adminga ko'rinadi."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 AI bilan ishlash", callback_data="menu:ai")
    kb.button(text="🎤 IELTS Speaking", callback_data="menu:speaking")
    kb.button(text="✍️ IELTS Writing", callback_data="menu:writing")
    kb.button(text="➗ Matematika", callback_data="menu:math")
    kb.button(text="⚛️ Fizika", callback_data="menu:physics")
    kb.button(text="🧰 Vositalar", callback_data="menu:tools")
    kb.button(text="📄 PDF testlarni tekshirish", callback_data="menu:pdftest")
    kb.button(text="🎯 Testlar (umumiy)", callback_data="menu:quiz")
    kb.button(text="🔄 Suhbatni tozalash", callback_data="menu:reset")
    if is_admin:
        kb.button(text="➕ Test qo'shish", callback_data="menu:testadd")
        kb.button(text="📊 Statistika", callback_data="menu:stats")
        kb.adjust(1, 2, 2, 1, 1, 1, 1, 1, 1)
    else:
        # 4-talab: oddiy foydalanuvchiga admin statistikasi o'rniga faqat
        # umumiy kanal statistikasi ko'rinadi.
        kb.button(text="📈 Kanal statistikasi", callback_data="menu:chanstats")
        kb.adjust(1, 2, 2, 1, 1, 1, 1, 1)
    return kb.as_markup()


def _menu_kb_for(user) -> object:
    """Foydalanuvchi admin bo'lsa Statistika tugmasi bilan menyu qaytaradi."""
    is_admin = bool(user and config.is_admin(user.id, user.username))
    return main_menu_kb(is_admin)


def speaking_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Part 1 — oddiy savollar", callback_data="sp:part:1")
    kb.button(text="Part 2 — cue card", callback_data="sp:part:2")
    kb.button(text="Part 3 — muhokama", callback_data="sp:part:3")
    kb.adjust(1)
    return kb.as_markup()


def writing_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Task 1 — grafik/xat", callback_data="wr:task:1")
    kb.button(text="Task 2 — insho", callback_data="wr:task:2")
    kb.adjust(1)
    return kb.as_markup()


def subject_kb(subject: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Misol yechilishi", callback_data=f"sub:{subject}:solve")
    kb.button(text="🎯 Testlar", callback_data=f"sub:{subject}:list")
    kb.button(text="➕ Test qo'shish", callback_data=f"sub:{subject}:add")
    kb.adjust(1)
    return kb.as_markup()


def tools_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Savol qo'shish", callback_data="tools:addq")
    kb.button(text="📢 Kanalga ulash", callback_data="tools:channel")
    kb.adjust(1)
    return kb.as_markup()


def qadd_type_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎤 IELTS Speaking", callback_data="qadd:type:speaking")
    kb.button(text="✍️ IELTS Writing", callback_data="qadd:type:writing")
    kb.button(text="➗ Matematika", callback_data="qadd:type:math")
    kb.button(text="⚛️ Fizika", callback_data="qadd:type:phys")
    kb.button(text="📄 PDF dan test", callback_data="qadd:type:pdf")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def qadd_speaking_part_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Part 1", callback_data="qadd:sp:1")
    kb.button(text="Part 2", callback_data="qadd:sp:2")
    kb.button(text="Part 3", callback_data="qadd:sp:3")
    kb.adjust(3, 1)
    return kb.as_markup()


def qadd_writing_task_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Task 1", callback_data="qadd:wr:1")
    kb.button(text="Task 2", callback_data="qadd:wr:2")
    kb.adjust(2, 1)
    return kb.as_markup()


def channel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Kanal ulash", callback_data="chan:connect")
    kb.button(text="📋 Kanallarim", callback_data="chan:list")
    kb.button(text="✍️ Kanalga post", callback_data="chan:post")
    kb.button(text="🗓 Post rejalashtirish", callback_data="chan:schedule")
    kb.adjust(1)
    return kb.as_markup()


def reminders_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Yangi eslatma", callback_data="tools:rem_new")
    kb.button(text="📋 Mening eslatmalarim", callback_data="tools:rem_list")
    kb.adjust(1)
    return kb.as_markup()


def stats_admin_kb():
    """Statistika bo'limi (faqat admin): test ishlaganlar + kanal boshqaruvi."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Test ishlaganlar", callback_data="stats:testtakers")
    kb.button(text="➕ Kanal qo'shish", callback_data="stats:chanadd")
    kb.button(text="📈 Kanallar statistikasi", callback_data="stats:chanstats")
    kb.adjust(1)
    return kb.as_markup()


def testadd_subject_kb():
    """Test qo'shish: fan tanlash."""
    kb = InlineKeyboardBuilder()
    kb.button(text="➗ Matematika", callback_data="tadd:sub:math")
    kb.button(text="⚛️ Fizika", callback_data="tadd:sub:physics")
    kb.adjust(2, 1)
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
    await bot.send_message(
        chat_id, text, reply_markup=_with_back(kb.as_markup()), parse_mode="HTML"
    )


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
    await bot.send_message(
        chat_id, "\n".join(lines), reply_markup=back_kb(), parse_mode="HTML"
    )


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


def _apply_day_part(hh: int, part: str | None) -> int:
    """Kun qismiga qarab 12-soatlik vaqtni 24-soatlikka o'giradi."""
    if part == "pm" and hh < 12:
        return hh + 12
    if part == "am" and hh == 12:
        return 0
    return hh


_NAT_DAY_RE = re.compile(r"\b(ertaga|etaga|bugun|indinga|indin)\b", re.IGNORECASE)
_NAT_PM_RE = re.compile(
    r"\b(kechqurun|kechqurun|kechki|kechasi|kech|tunda|tun)\b", re.IGNORECASE
)
_NAT_AM_RE = re.compile(r"\b(ertalab|tongda|tong|saharda)", re.IGNORECASE)
_NAT_NOON_RE = re.compile(r"\b(tushda|peshin|kunduzi|kunduz)\b", re.IGNORECASE)
_NAT_STRIP_RE = re.compile(
    r"\b(ertaga|etaga|bugun|indinga|indin|ertalab|tongda|tong|saharda|kechqurun|"
    r"kechki|kechasi|kech|tunda|tun|tushda|peshin|kunduzi|kunduz|soat|da|keyin|"
    r"so['’]?ng|o['’]?tib|menga|iltimos)\b",
    re.IGNORECASE,
)


def parse_reminder_natural(text: str) -> tuple[str, float] | None:
    """Tabiiy tildagi eslatmani tahlil qiladi.

    Misollar:
      "ertaga soat 12 da matematika darsini takrorlash"
      "30 daqiqadan keyin suv ichish"
      "bugun kechqurun soat 20 da uchrashuv"
      "2 soatdan so'ng dori ichish"

    Qaytaradi: (eslatma_matni, timestamp) yoki None (tushunilmasa).
    """
    if not text or not text.strip():
        return None
    s = text.strip()
    low = s.lower()
    now = datetime.now()
    target = None
    spans: list[tuple[int, int]] = []

    # Kun siljishi
    day_offset = 0
    dm = _NAT_DAY_RE.search(low)
    if dm:
        w = dm.group(1)
        if w in ("ertaga", "etaga"):
            day_offset = 1
        elif w in ("indinga", "indin"):
            day_offset = 2

    # Kun qismi
    part = None
    if _NAT_PM_RE.search(low):
        part = "pm"
    elif _NAT_AM_RE.search(low):
        part = "am"
    elif _NAT_NOON_RE.search(low):
        part = "pm"

    # 1) Nisbiy: "30 daqiqadan keyin" / "2 soatdan so'ng" / "3 kundan keyin"
    m = re.search(
        r"(\d{1,3})\s*(daqiqa|minut|min\w*)\s*(?:dan\s*)?(?:keyin|so['’]?ng|o['’]?tib)",
        low,
    )
    if m:
        target = now + timedelta(minutes=int(m.group(1)))
        spans.append(m.span())
    if target is None:
        m = re.search(
            r"(\d{1,3})\s*(soat)\s*(?:dan\s*)?(?:keyin|so['’]?ng|o['’]?tib)", low
        )
        if m:
            target = now + timedelta(hours=int(m.group(1)))
            spans.append(m.span())
    if target is None:
        m = re.search(
            r"(\d{1,3})\s*(kun)\s*(?:dan\s*)?(?:keyin|so['’]?ng|o['’]?tib)", low
        )
        if m:
            target = now + timedelta(days=int(m.group(1)))
            spans.append(m.span())

    # 2) Absolyut: "soat 12 da", "soat 18:30 da"
    if target is None:
        m = re.search(r"soat\s*(\d{1,2})(?:[:.](\d{2}))?", low)
        if m:
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            hh = _apply_day_part(hh, part)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                base = now + timedelta(days=day_offset)
                try:
                    target = base.replace(hour=hh, minute=mm, second=0, microsecond=0)
                except ValueError:
                    target = None
                if target is not None and target <= now and day_offset == 0:
                    # Vaqt o'tib ketgan bo'lsa — ertaga
                    target += timedelta(days=1)
                if target is not None:
                    spans.append(m.span())

    if target is None:
        return None

    # Matnni tozalash: vaqt qismini va kun so'zlarini olib tashlaymiz
    body = s
    for a, b in sorted(spans, reverse=True):
        body = body[:a] + " " + body[b:]
    body = _NAT_STRIP_RE.sub(" ", body)
    body = re.sub(r"\s+", " ", body).strip(" ,.-—:;!?")
    if not body:
        body = "Eslatma"
    return body, target.timestamp()


_REMINDER_INTENT_RE = re.compile(
    r"\b(eslat|yodga\s*sol|esda\s*tut|yodda\s*tut|eslatib\s*qo|qilaman|boraman|"
    r"o['’]?qiyman|uchrashaman|tayyorlanaman|ichaman|yozaman|ko['’]?raman|boshlayman|"
    r"tugataman|yuboraman|qo['’]?ngiroq\s*qilaman)\b",
    re.IGNORECASE,
)


def looks_like_reminder(text: str) -> bool:
    """Matn tabiiy tildagi eslatmaga o'xshaydimi (vaqt + harakat)."""
    if not text or len(text) > 250:
        return False
    low = text.lower()
    if not _REMINDER_INTENT_RE.search(low):
        return False
    if re.search(r"soat\s*\d", low):
        return True
    if re.search(
        r"\d{1,3}\s*(daqiqa|minut|soat|kun)\w*\s*(?:dan\s*)?(?:keyin|so['’]?ng)", low
    ):
        return True
    if re.search(r"\b(ertaga|indinga|bugun)\b", low) and re.search(r"\d", low):
        return True
    return False


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
    # Majburiy kanal: /start bosilganda birinchi navbatda obuna so'raladi.
    if not await is_subscribed(u.id if u else 0, force=True):
        await message.answer(gate_text(), reply_markup=sub_gate_kb())
        return
    name = u.first_name if u else "do'stim"
    await _ans(message, 
        f"👋 Salom, *{name}*!\n\n"
        "Men *AI Manager* — HAMMA soha bo'yicha AI yordamchingizman.\n\n"
        "Quyidagi bo'limlardan birini tanlang 👇",
        reply_markup=_menu_kb_for(u),
    )
    await _ans(message,
        "ℹ️ Pastdagi doimiy paneldan ham foydalanishingiz mumkin:\n"
        f"«{BTN_START}», «{BTN_MAIN}», «{BTN_REMIND}», «{BTN_RESET}», "
        f"«{BTN_CHANNEL}».",
        reply_markup=main_reply_kb(),
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
    await _ans(message, "🏠 *Asosiy menyu* — bo'limni tanlang:", reply_markup=_menu_kb_for(u))


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _ans(message, 
        "ℹ️ *AI Manager — yordam*\n\n"
        "🏠 *Bo'limlar (menyu):*\n"
        "🎤 IELTS Speaking — Part 1/2/3, ovozli javobni baholash\n"
        "✍️ IELTS Writing — Task 1/2, inshoni baholash\n"
        "➗ Matematika — misol yechish + testlar\n"
        "⚛️ Fizika — misol yechish + testlar\n"
        "🧰 Vositalar — savol qo'shish, kanal boshqaruvi\n"
        "🤖 AI bilan ishlash — erkin suhbat\n\n"
        "🎯 *Buyruqlar:*\n"
        "`/menu` — asosiy menyu\n"
        "`/quiz` — soha bo'yicha test\n"
        "`/stats` — statistika (faqat admin)\n"
        "`/history` — suhbat tarixi\n"
        "`/lang` — til (uz/en/ru)\n"
        "`/bank [so'z]` — savollar banki\n"
        "`/manga Naruto` — manga haqida\n"
        "`/image <tavsif>` — rasm yaratish\n\n"
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
        await _ans(message, "⚠️ Test savollari bazasi bo'sh.")
        return

    kb = InlineKeyboardBuilder()
    for t in topics:
        n = await db.count_questions(t)
        kb.button(text=f"{t} ({n})", callback_data=f"topic:{t}")
    kb.adjust(2)

    await _ans(message, "🎯 *Test o'tash*\n\nQaysi sohadan boshlaymiz?", reply_markup=kb.as_markup())


async def build_stats_text(u) -> str:
    """Statistika matnini tayyorlaydi (faqat admin ko'radi)."""
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
        f"👥 Test ishlaganlar: *{await db.count_test_takers()}*",
    ]

    if top:
        lines.append("\n🔥 *Eng ko'p so'ralgan sohalar:*")
        for topic, cnt in top:
            lines.append(f"• {topic} — {cnt}")

    if results:
        lines.append("\n🕘 *Sizning oxirgi testlaringiz:*")
        for r in results:
            lines.append(f"• {r['topic']}: {r['score']}/{r['total']}")

    return "\n".join(lines)


@dp.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Statistika — FAQAT admin uchun."""
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
    if not u or not config.is_admin(u.id, u.username):
        await _ans(message, 
            "🔒 *Statistika* faqat admin uchun.\n\n"
            f"Admin: @{config.ADMIN_USERNAMES[0] if config.ADMIN_USERNAMES else 'admin'}"
        )
        return
    await _ans(message, await build_stats_text(u))


@dp.message(Command("history"))
async def cmd_history(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await db.upsert_user(u.id, u.username, u.first_name)
    rows = await db.get_history(u.id, limit=10)
    if not rows:
        await _ans(message, "🕘 Hozircha suhbat tarixi bo'sh. Savol yozing!")
        return

    lines = ["🕘 *Oxirgi suhbatlaringiz:*\n"]
    for r in reversed(rows):
        who = "👤" if r["role"] == "user" else "🤖"
        txt = r["text"].replace("\n", " ")
        if len(txt) > 120:
            txt = txt[:120] + "…"
        lines.append(f"{who} {txt}")

    lines.append("\n🗑 Tozalash uchun: /clearhistory")
    await _ans(message, "\n".join(lines))


@dp.message(Command("clearhistory"))
async def cmd_clear_history(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await _reset_my_conversation(u.id)
    await _ans(message, "🗑 Suhbat tarixi tozalandi.")


@dp.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    """Suhbatni tozalab, yangi suhbat boshlaydi (kontekstni unutadi)."""
    u = message.from_user
    if not u:
        return
    await _reset_my_conversation(u.id)
    await _ans(message, 
        "🔄 *Suhbat tozalandi.* Yangi suhbat boshlandi — endi bot oldingi "
        "gaplarni eslab qolmaydi.",
        reply_markup=_menu_kb_for(u),
    )


# --------------------------------------------------------------------------- #
# Majburiy kanal — tekshirish / yo'naltirish handlerlari
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "sub:check")
async def on_sub_check(cb: CallbackQuery) -> None:
    """«✅ Tekshirish» — kanal obunasini qayta tekshiradi."""
    # force=True — keshni chetlab o'tib, Telegram'dan qayta so'raymiz.
    if await is_subscribed(cb.from_user.id, force=True):
        await cb.answer("✅ Obuna tasdiqlandi!")
        await cb.message.edit_text(
            "✅ *Rahmat!* Kanalga obuna bo'ldingiz.\n\n"
            "🏠 *Asosiy menyu* — bo'limni tanlang:",
            reply_markup=_menu_kb_for(cb.from_user),
        )
        return
    await cb.answer("❌ Siz hali kanalga obuna bo'lmagansiz.", show_alert=True)
    await cb.message.edit_text(
        "❌ *Siz hali kanalga obuna bo'lmagansiz.*\n\n"
        f"📢 *Kanal:* {config.REQUIRED_CHANNEL_URL}\n\n"
        "Obuna bo'lgach, «✅ Obunani tekshirish» tugmasini qayta bosing.",
        reply_markup=sub_gate_kb(),
    )


@dp.callback_query(F.data == "sub:noaccess")
async def on_sub_noaccess(cb: CallbackQuery) -> None:
    """«Kanalga ulanish» (URL tugmasi ishlamagan holat) uchun matnli yo'riqnoma."""
    await cb.answer()
    await cb.message.edit_text(
        "📢 *Kanalga obuna bo'lish*\n\n"
        f"Quyidagi havola orqali kanalga obuna bo'ling:\n{config.REQUIRED_CHANNEL_URL}\n\n"
        "So'ng «✅ Obunani tekshirish» tugmasini bosing.",
        reply_markup=sub_gate_kb(),
    )


@dp.callback_query(F.data == "menu:reset")
async def on_menu_reset(cb: CallbackQuery) -> None:
    """Suhbat tarixini tozalab, yangi suhbat boshlaydi."""
    await cb.answer("Suhbat tozalandi")
    # 3-talab: suhbat HAR IKKI tomondan tozalanadi (chat_history + user_states)
    n = await _reset_my_conversation(cb.from_user.id)
    try:
        await _edit(cb, 
            "🔄 *Suhbat tozalandi.* Eski suhbat ham, bot xotirasi ham tozalandi "
            f"({n} ta qatlam o'chirildi).\n\n"
            "▶️ Yangi suhbatni boshlash uchun /start ni yuboring.\n\n"
            "🏠 *Asosiy menyu* — bo'limni tanlang:",
            reply_markup=_menu_kb_for(cb.from_user),
        )
    except Exception:  # noqa: BLE001
        await _ans(cb.message, 
            "🔄 Suhbat tozalandi. Yangi suhbatni /start bilan boshlang.",
            reply_markup=_menu_kb_for(cb.from_user),
        )
    # Tozalashdan keyin «⬅️ Orqaga» o'chirilgan ekranga qaytmasligi uchun
    # navigatsiya tarixini ham tozalaymiz (faqat shu foydalanuvchi uchun).
    _nav_stack.pop(cb.from_user.id, None)


# --------------------------------------------------------------------------- #
# 2-talab: kontakt (telefon) qabul qilish
# --------------------------------------------------------------------------- #
async def _save_contact_and_ack(message: Message, phone: str, name: str = "") -> None:
    """Kontaktni bazaga yozib, foydalanuvchiga tasdiq yuboradi."""
    u = message.from_user
    try:
        await db.add_user_contact(
            u.id, phone=phone, first_name=name or (u.first_name or ""),
            username=u.username or "",
        )
    except Exception:  # noqa: BLE001
        log.exception("Kontaktni saqlashda xato (user=%s)", u.id)
    await db.clear_user_state(u.id)
    await _ans(message,
        "✅ *Rahmat!* Kontaktingiz qabul qilindi.\n\n"
        "Mutaxassis tez orada siz bilan bog'lanadi.",
        reply_markup=main_reply_kb(),
    )


@dp.message(F.contact)
async def on_contact(message: Message) -> None:
    """📱 «Kontakt ulashish» tugmasi bosilganda ishlaydi (2-talab)."""
    c = message.contact
    if c is None:
        return
    name = " ".join(x for x in [c.first_name, c.last_name] if x)
    await _save_contact_and_ack(message, c.phone_number or "", name=name)


async def handle_contact_text(message: Message, text: str) -> bool:
    """Kontakt kutilayotganda yozilgan matnni qayta ishlaydi.

    ``True`` — raqam saqlandi; ``False`` — kontakt emas, odatdagi oqimga
    qaytish kerak."""
    raw = (text or "").strip()
    phone = re.sub(r"[^0-9+]", "", raw)
    if len(phone) >= 7 and re.fullmatch(r"[+0-9\s()\-]+", raw):
        await _save_contact_and_ack(message, phone)
        return True
    # Kontakt emas — holatni tozalab, odatdagi oqimga qaytaramiz
    await message.answer(
        "📱 Telefon raqamingizni yuboring yoki «📱 Kontakt ulashish» "
        "tugmasini bosing.",
        reply_markup=contact_reply_kb(),
    )
    return False


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
    await _ans(message, "🌐 *Tilni tanlang:*", reply_markup=kb.as_markup())


@dp.message(Command("bank"))
async def cmd_bank(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)
    query = (message.text or "").partition(" ")[2].strip()
    rows = await db.search_question_bank(query or None, limit=10)
    if not rows:
        await _ans(message, 
            "📚 Savollar banki bo'sh yoki natija topilmadi.\n"
            "Savol bersangiz, javoblar avtomatik bankka saqlanadi."
        )
        return
    lines = ["📚 *Savollar banki:*\n"]
    for r in rows:
        q = r["question"].replace("\n", " ")[:100]
        lines.append(f"• [{r['subject']}] {q}")
    lines.append("\n🔎 Qidirish: `/bank so'z`")
    await _ans(message, "\n".join(lines))


@dp.message(Command("manga"))
async def cmd_manga(message: Message) -> None:
    title = (message.text or "").partition(" ")[2].strip()
    if not title:
        await _ans(message, "✍️ Foydalanish: `/manga Naruto`")
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
        await _ans(message, "✍️ Foydalanish: `/image kiberpank manga qahramoni`")
        return
    if not config.ENABLE_IMAGE_GEN:
        await _ans(message, "🖼 Rasm generatsiyasi o'chirilgan.")
        return

    await _typing(message)
    try:
        images = await pool.generate_image(prompt, count=1)
    except AllKeysFailedError as exc:
        log.error("Rasm xatosi: %s", exc)
        await _ans(message, 
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
    await db.clear_user_state(cb.from_user.id)
    try:
        await _edit(cb, "🏠 *Asosiy menyu* — bo'limni tanlang:",
                                   reply_markup=_menu_kb_for(cb.from_user))
    except Exception:  # noqa: BLE001
        await _ans(cb.message, "🏠 *Asosiy menyu*:", reply_markup=_menu_kb_for(cb.from_user))


@dp.callback_query(F.data == "nav:back")
async def on_nav_back(cb: CallbackQuery) -> None:
    """'⬅️ Orqaga' — oldingi ekranga qaytaradi."""
    await cb.answer()
    stack = _nav_stack.get(cb.from_user.id) or []
    if not stack:
        # Tarix bo'sh — asosiy menyuga qaytaramiz
        try:
            await cb.message.edit_text(
                "🏠 *Asosiy menyu* — bo'limni tanlang:",
                reply_markup=_menu_kb_for(cb.from_user),
            )
        except Exception:  # noqa: BLE001
            await _ans(cb.message, "🏠 *Asosiy menyu*:",
                       reply_markup=_menu_kb_for(cb.from_user))
        return
    prev = stack.pop()
    try:
        await cb.message.edit_text(prev["text"], reply_markup=prev["markup"])
    except Exception:  # noqa: BLE001
        try:
            await _ans(cb.message, prev["text"], reply_markup=prev["markup"])
        except Exception:  # noqa: BLE001
            pass


@dp.callback_query(F.data == "menu:ai")
async def on_menu_ai(cb: CallbackQuery) -> None:
    """AI bilan erkin suhbat rejimi."""
    await cb.answer()
    if not await require_sub(cb):
        return
    await db.set_user_state(cb.from_user.id, "ai_chat", {})
    await _edit(
        cb,
        "🤖 *AI bilan ishlash*\n\n"
        "Endi menga istalgan savolni yozing — matematika, fizika, tarix, ingliz tili, "
        "dasturlash, tibbiyot, biznes, fan, geografiya, adabiyot va boshqa har qanday "
        "sohada javob beraman.\n\n"
        "✍️ Savolingizni shu chatga yozing.\n"
        "🚪 Chiqish uchun «🏠 Asosiy menyu» tugmasini bosing.",
    )


@dp.callback_query(F.data == "menu:speaking")
async def on_menu_speaking(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await require_sub(cb):
        return
    await _edit(cb, 
        "🎤 *IELTS Speaking*\n\nQuestion type ni tanlang:",
        reply_markup=speaking_kb(),
    )


@dp.callback_query(F.data == "menu:writing")
async def on_menu_writing(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await require_sub(cb):
        return
    await _edit(cb, 
        "✍️ *IELTS Writing*\n\nTask ni tanlang:",
        reply_markup=writing_kb(),
    )


@dp.callback_query(F.data == "menu:math")
async def on_menu_math(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await require_sub(cb):
        return
    await _edit(cb, 
        "➗ *Matematika*\n\nBo'limni tanlang:",
        reply_markup=subject_kb("math"),
    )


@dp.callback_query(F.data == "menu:physics")
async def on_menu_physics(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await require_sub(cb):
        return
    await _edit(cb, 
        "⚛️ *Fizika*\n\nBo'limni tanlang:",
        reply_markup=subject_kb("phys"),
    )


@dp.callback_query(F.data == "menu:tools")
async def on_menu_tools(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await require_sub(cb):
        return
    await _edit(cb, 
        "🧰 *Vositalar*\n\nBo'limni tanlang:",
        reply_markup=tools_kb(),
    )


@dp.callback_query(F.data == "menu:pdftest")
async def on_menu_pdftest(cb: CallbackQuery) -> None:
    """PDF testlarni tekshirish: test kodini so'raydi."""
    await cb.answer()
    if not await require_sub(cb):
        return
    await db.set_user_state(cb.from_user.id, "pdf_answers_code", {})
    await _edit(cb, 
        "📄 *PDF testlarni tekshirish*\n\n"
        "Test kodini kiriting:\n\n"
        "Misol: `12345`",
    )


@dp.callback_query(F.data == "menu:stats")
async def on_menu_stats(cb: CallbackQuery) -> None:
    """Statistika bo'limi — FAQAT admin uchun."""
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, 
            "🔒 *Statistika* faqat admin uchun.\n\n"
            f"Admin: @{config.ADMIN_USERNAMES[0] if config.ADMIN_USERNAMES else 'admin'}"
        )
        return
    n = await db.count_channels()
    text = await build_stats_text(u) + f"\n\n📢 Ulangan kanallar: *{n}* ta"
    try:
        await _edit(cb, text, reply_markup=stats_admin_kb())
    except Exception:  # noqa: BLE001
        await _ans(cb.message, text, reply_markup=stats_admin_kb())


@dp.callback_query(F.data == "stats:chanadd")
async def on_stats_chanadd(cb: CallbackQuery) -> None:
    """Statistika bo'limidan kanal qo'shish (admin)."""
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, "🔒 Faqat admin uchun.")
        return
    await db.set_user_state(u.id, "chan_connect", {})
    await _edit(cb, 
        "➕ *Kanal qo'shish*\n\n"
        "Kanalning @username ini yoki ID sini yuboring.\n\n"
        "⚠️ Bot kanalda *admin* bo'lishi shart.\n\n"
        "Misol: `@mening_kanalim` yoki `-1001234567890`"
    )


async def _channel_avg_views(channel_id: int) -> int | None:
    """Kanal postlarining o'rtacha ko'rish sonini Telegram Bot API orqali oladi.

    Bot API ba'zi kanallarda ko'rishlar sonini bermaydi — o'shanda ``None``.
    """
    token = getattr(bot, "token", "") or ""
    if not token:
        return None
    url = f"https://api.telegram.org/bot{token}/getChatHistory"
    payload = {"chat_id": channel_id, "limit": 30, "offset": 0}
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
        if not data.get("ok"):
            return None
        views = [
            int(m["views"]) for m in (data.get("result") or [])
            if isinstance(m.get("views"), int)
        ]
        if not views:
            return None
        return round(sum(views) / len(views))
    except Exception as exc:  # noqa: BLE001
        log.debug("Ko'rishlar sonini olib bo'lmadi (%s): %s", channel_id, exc)
        return None


async def _build_channels_stats(rows: list) -> list[str]:
    """Kanal statistikasi matnini tayyorlaydi.

    6-talab: a'zolar sonidan tashqari rivojlanish darajasi (24s / 7 kun / jami
    o'sish), postlar holati va o'rtacha ko'rishlar ham ko'rsatiladi.
    """
    lines = ["📈 *Kanallar statistikasi*\n"]
    for r in rows:
        cid = r["channel_id"]
        posts = await db.count_channel_posts(cid)
        sent = await db.count_channel_posts(cid, sent_only=True)
        members = "—"
        members_n: int | None = None
        try:
            members_n = int(await bot.get_chat_member_count(cid))
            members = str(members_n)
        except Exception as exc:  # noqa: BLE001
            log.debug("A'zolar sonini olib bo'lmadi (%s): %s", cid, exc)
        # Rivojlanish darajasini hisoblash uchun oniy suratga olamiz
        if members_n is not None:
            try:
                await db.record_channel_snapshot(cid, members_n)
            except Exception:  # noqa: BLE001
                log.debug("Kanal surati yozilmadi (%s)", cid)

        uname = f" (@{r['username']})" if r["username"] else ""
        lines.append(
            f"• *{esc(r['title'] or cid)}*{uname}\n"
            f"  🆔 `{cid}`\n"
            f"  👥 A'zolar: *{members}* · 📨 Postlar: *{posts}* "
            f"(yuborilgan: *{sent}*, kutilayotgan: *{max(0, posts - sent)}*)"
        )
        try:
            growth = await db.get_channel_growth(cid)
        except Exception:  # noqa: BLE001
            growth = {}
        if growth:
            def _fmt(d: int) -> str:
                return f"+{d}" if d > 0 else str(d)

            lines.append(
                f"  📊 O'sish: 24 soat *{_fmt(growth['growth_24h'])}* · "
                f"7 kun *{_fmt(growth['growth_7d'])}* · "
                f"jami *{_fmt(growth['growth_total'])}*"
            )
        if sent:
            views = await _channel_avg_views(cid)
            if views is not None:
                lines.append(f"  👁 O'rtacha ko'rishlar (post): *{views}*")
    return lines


@dp.callback_query(F.data == "menu:chanstats")
async def on_menu_chanstats(cb: CallbackQuery) -> None:
    """📈 Umumiy kanal statistikasi — BARCHA foydalanuvchilar uchun (4-talab)."""
    await cb.answer()
    rows = await db.list_channels()
    if not rows:
        await _edit(cb, "📈 *Kanal statistikasi*\n\nHozircha kanal ulanmagan.")
        return
    lines = await _build_channels_stats(rows)
    await _edit(cb, "\n".join(lines))


@dp.callback_query(F.data == "stats:chanstats")
async def on_stats_chanstats(cb: CallbackQuery) -> None:
    """Kanallar statistikasi (admin): a'zolar, o'sish, postlar, ko'rishlar."""
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, "🔒 Faqat admin uchun.")
        return
    rows = await db.list_channels()
    if not rows:
        await _edit(cb, 
            "📈 Hozircha kanal yo'q. «➕ Kanal qo'shish» orqali ulang.",
            reply_markup=stats_admin_kb(),
        )
        return
    lines = await _build_channels_stats(rows)
    # 5-talab: bu yerda `stats_admin_kb()` qayta berilmaydi — aks holda
    # «Kanallar statistikasi» tugmasi ichma-ich qayta chiqib ketardi.
    await _edit(cb, "\n".join(lines))


# --------------------------------------------------------------------------- #
# v7: Test qo'shish bo'limi (admin) va test natijasi tahlili
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "menu:testadd")
async def on_menu_testadd(cb: CallbackQuery) -> None:
    """"Test qo'shish" bo'limi — faqat admin."""
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, 
            "🔒 *Test qo'shish* faqat admin uchun.\n\n"
            f"Admin: @{config.ADMIN_USERNAMES[0] if config.ADMIN_USERNAMES else 'admin'}"
        )
        return
    await _edit(cb, 
        "➕ *Test qo'shish*\n\n"
        "Qaysi fandan test qo'shmoqchisiz?\n\n"
        "ℹ️ Test *kodi*, *sarlavhasi*, *savollari* va *javoblari* ni ketma-ket "
        "kiritasiz. Kod band bo'lmasligi kerak.",
        reply_markup=testadd_subject_kb(),
    )


@dp.callback_query(F.data.startswith("tadd:sub:"))
async def on_tadd_subject(cb: CallbackQuery) -> None:
    """Test qo'shish: fan tanlandi — kod so'raladi."""
    subject = cb.data.split(":")[2]
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, "🔒 Faqat admin uchun.")
        return
    if subject not in ("math", "physics"):
        await _edit(cb, "⚠️ Noma'lum fan.")
        return
    name = "Matematika" if subject == "math" else "Fizika"
    await db.set_user_state(u.id, "test_add2", {
        "subject": subject, "step": "code", "code": "",
        "title": "", "questions": [],
    })
    await _edit(cb, 
        f"➕ *{name} — test qo'shish*\n\n"
        "1️⃣ Test *kodini* yuboring (2–32 belgi: harflar, raqamlar, `-`, `_`).\n\n"
        "Misol: `ALG-1`, `MATH-9`, `12345`",
        reply_markup=testadd_subject_kb(),
    )


@dp.callback_query(F.data == "stats:testtakers")
async def on_stats_testtakers(cb: CallbackQuery) -> None:
    """Test ishlagan foydalanuvchilar ro'yxati va har biri nechta test ishlagani."""
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, "🔒 Faqat admin uchun.")
        return
    rows = await db.test_leaderboard(50)
    if not rows:
        await _edit(cb, 
            "🏆 Hozircha hech kim test ishlamagan.\n\n"
            "Foydalanuvchi test kodini yuborib test ishlagach, shu yerda ko'rinadi.",
            reply_markup=stats_admin_kb(),
        )
        return

    total_takers = await db.count_test_takers()
    lines = [f"🏆 *Test ishlaganlar* ({total_takers} ta foydalanuvchi)\n"]
    for i, r in enumerate(rows, 1):
        uid = r["user_id"]
        uname = f"@{r['username']}" if r.get("username") else (r.get("first_name") or "noma'lum")
        tests = int(r.get("tests_taken") or 0)
        tot_c = int(r.get("total_correct") or 0)
        tot_q = int(r.get("total_questions") or 0)
        pct = round(tot_c / tot_q * 100) if tot_q else 0
        last = ""
        try:
            last = " · 🕒 " + datetime.fromtimestamp(float(r["last_at"])).strftime("%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            pass
        lines.append(
            f"{i}. *{esc(uname)}*\n"
            f"   🆔 `{uid}`\n"
            f"   📝 Testlar: *{tests}* ta · 🎯 O'rtacha: *{pct}%* ({tot_c}/{tot_q}){last}"
        )
    await _edit(cb, "\n".join(lines), reply_markup=stats_admin_kb())


async def analyze_result_with_ai(subject: str, title: str, correct: int, total: int,
                                 detail: list[dict], questions: list[dict]) -> str | None:
    """Test natijasini AI orqali tahlil qiladi: zaif joylar va tavsiyalar.

    Xato bo'lsa yoki barcha javob to'g'ri bo'lsa — ``None`` qaytaradi.
    """
    wrong = [d for d in detail if not d.get("ok")]
    if not wrong:
        return None
    rows = []
    for d in wrong[:12]:
        qt = ""
        try:
            idx = int(d.get("i", 0)) - 1
            if 0 <= idx < len(questions):
                qt = questions[idx].get("q", "")
        except Exception:  # noqa: BLE001
            qt = d.get("q", "")
        rows.append(
            f"- Savol {d.get('i') or d.get('key')}: {qt} "
            f"| o'quvchi: {d.get('user')} | to'g'ri: {d.get('correct')}"
        )
    prompt = (
        f"Test: {title} (fan: {subject})\n"
        f"Natija: {correct}/{total} to'g'ri.\n"
        f"Xato javoblar:\n" + "\n".join(rows) + "\n\n"
        "Yuqoridagi natijani O'QUVCHIGA tahlil qilib ber:\n"
        "1) Qaysi mavzularda zaif ekani (xatolardan kelib chiqib),\n"
        "2) Har bir xato uchun qisqa izoh (nima uchun xato),\n"
        "3) 2-3 ta aniq tavsiya (nima takrorlash kerak).\n"
        "O'zbek tilida, qisqa va foydali qilib yoz."
    )
    try:
        return await pool.generate(
            prompt,
            system_instruction=SYSTEM_PROMPT,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Natija tahlili (AI) ishlamadi: %s", exc)
        return None


@dp.callback_query(F.data == "menu:quiz")
async def on_menu_quiz(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await require_sub(cb):
        return
    topics = await db.get_topics()
    if not topics:
        await _ans(cb.message, "⚠️ Test savollari bazasi bo'sh.")
        return
    kb = InlineKeyboardBuilder()
    for t in topics:
        n = await db.count_questions(t)
        kb.button(text=f"{t} ({n})", callback_data=f"topic:{t}")
    kb.adjust(2)
    await _edit(cb, "🎯 *Test o'tash*\n\nQaysi sohadan boshlaymiz?",
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
        await _edit(cb, text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        await _ans(cb.message, text, parse_mode="HTML")


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
        await _edit(cb, text, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        await _ans(cb.message, text, parse_mode="HTML")


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
        await _edit(cb, 
            f"📝 *{name} — misol yechilishi*\n\n"
            "Misol yoki masalani yozib yuboring — qadam-baqadam yechib beraman.",
            reply_markup=subject_kb(subject),
        )
        return

    if action == "list":
        tests = await db.list_tests(subject)
        name = "Matematika" if subject == "math" else "Fizika"
        if not tests:
            await _edit(cb, 
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
        await _edit(cb, "\n".join(lines), reply_markup=subject_kb(subject))
        return

    if action == "add":
        name = "Matematika" if subject == "math" else "Fizika"
        await db.set_user_state(user_id, "test_add", {
            "subject": subject, "step": "title", "title": "", "questions": [], "answers": ""
        })
        await _edit(cb, 
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
        await _ans(message, 
            "2️⃣ Endi savollarni yuboring. Har bir savolni alohida blok qilib yozing:\n"
            "birinchi qatorda savol, keyingi qatorlarda variantlar.\n"
            "Bloklar orasida bo'sh qator qoldiring.\n\n"
            "Misol:\n"
            "2+2 nechaga teng?\n3\n4\n5\n6\n\n"
            "5×5 nechaga teng?\n20\n25\n30\n35"
        )
        return

    if step == "questions":
        questions = []
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if len(lines) < 3:
                continue
            q = lines[0]
            opts = lines[1:5]
            if len(opts) < 2:
                continue
            questions.append({"q": q, "options": opts})
        if not questions:
            await _ans(message, 
                "⚠️ Savollar formati noto'g'ri. Har bir savolni alohida blok qilib "
                "yuboring: birinchi qatorda savol, keyingi qatorlarda variantlar."
            )
            return
        data["questions"] = questions
        data["step"] = "answers"
        await db.set_user_state(user_id, "test_add", data)
        await _ans(message, 
            f"✅ {len(questions)} ta savol qabul qilindi.\n\n"
            "3️⃣ Endi to'g'ri javoblarni variant harflari ketma-ketligi sifatida yuboring.\n"
            f"Misol: `{('a' * len(questions))}` (a, b, c, d harflari)."
        )
        return

    if step == "answers":
        answers = re.sub(r"[^a-f]", "", text.lower())
        n = len(data["questions"])
        if len(answers) != n:
            await _ans(message, 
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
            uname = f"@{u.username}" if u.username else (u.first_name or "noma'lum")
            await _ans(message, 
                f"✅ Test bazaga qo'shildi!\n\n"
                f"🔑 Kod: `{code}`\n📄 {esc(data['title'])}\n"
                f"👤 Muallif: {esc(uname)} (ID: `{u.id}`)\n"
                f"❓ Savollar: {n} ta\n\n"
                f"Endi `{code}` kodini yuborib testni boshlash mumkin."
            )
            return

        # Admin emas — tasdiqlash so'rovi
        aid = await db.create_pending_approval(u.id, subject, payload)
        await db.clear_user_state(user_id)
        await _ans(message, 
            "⏳ So'rovingiz adminga yuborildi. Tasdiqlangach test bazaga qo'shiladi "
            "va sizga kod yuboriladi."
        )
        await notify_admins_approval(aid, u, subject, payload)


async def handle_test_add2(message: Message, state: dict, text: str) -> None:
    """Admin uchun test qo'shish: kod -> sarlavha -> savollar -> javoblar."""
    user_id = message.from_user.id
    subject = state["subject"]
    step = state["step"]
    data = state

    if step == "code":
        code = text.strip().upper()
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", code):
            await _ans(message, 
                "⚠️ Kod 2–32 belgidan iborat bo'lsin (harflar, raqamlar, `-`, `_`).\n"
                "Misol: `ALG-1` yoki `12345`"
            )
            return
        if await db.test_code_exists(code) or await db.pdf_test_code_exists(code):
            await _ans(message, f"⚠️ `{code}` kodi allaqachon band. Boshqa kod yuboring.")
            return
        data["code"] = code
        data["step"] = "title"
        await db.set_user_state(user_id, "test_add2", data)
        await _ans(message, 
            f"✅ Kod: `{code}`\n\n"
            "2️⃣ Endi test *sarlavhasini* yuboring (masalan: *Algebra asoslari*)."
        )
        return

    if step == "title":
        data["title"] = text.strip()[:120]
        data["step"] = "questions"
        await db.set_user_state(user_id, "test_add2", data)
        await _ans(message, 
            "3️⃣ Endi savollarni yuboring. Har bir savolni alohida blok qilib yozing:\n"
            "birinchi qatorda savol, keyingi qatorlarda variantlar.\n"
            "Bloklar orasida bo'sh qator qoldiring.\n\n"
            "Misol:\n"
            "2+2 nechaga teng?\n3\n4\n5\n6\n\n"
            "5×5 nechaga teng?\n20\n25\n30\n35"
        )
        return

    if step == "questions":
        questions = []
        for block in re.split(r"\n\s*\n", text.strip()):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if len(lines) < 3:
                continue
            q = lines[0]
            opts = lines[1:5]
            if len(opts) < 2:
                continue
            questions.append({"q": q, "options": opts})
        if not questions:
            await _ans(message, 
                "⚠️ Savollar formati noto'g'ri. Har bir savolni alohida blok qilib "
                "yuboring: birinchi qatorda savol, keyingi qatorlarda variantlar."
            )
            return
        data["questions"] = questions
        data["step"] = "answers"
        await db.set_user_state(user_id, "test_add2", data)
        await _ans(message, 
            f"✅ {len(questions)} ta savol qabul qilindi.\n\n"
            "4️⃣ Endi to'g'ri javoblarni variant harflari ketma-ketligi sifatida yuboring.\n"
            f"Misol: `{('a' * len(questions))}` (a, b, c, d harflari)."
        )
        return

    if step == "answers":
        answers = re.sub(r"[^a-f]", "", text.lower())
        n = len(data["questions"])
        if len(answers) != n:
            await _ans(message, 
                f"⚠️ Javoblar soni savollar soniga teng bo'lishi kerak: "
                f"{n} ta harf kerak, siz {len(answers)} ta yubordingiz."
            )
            return
        code = data["code"]
        await db.add_test(subject, code, data["title"], data["questions"],
                          answers, created_by=user_id)
        await db.clear_user_state(user_id)
        await _ans(message, 
            f"✅ Test bazaga qo'shildi!\n\n"
            f"🔑 Kod: `{code}`\n📄 {esc(data['title'])}\n"
            f"❓ Savollar: {n} ta\n\n"
            f"Endi `{code}` kodini yuborib testni boshlash mumkin."
        )
        return


async def notify_admins_approval(aid: int, user, subject: str, payload: dict) -> None:
    """Adminga tasdiqlash so'rovini yuboradi."""
    admin_ids = await get_admin_ids()
    if not admin_ids:
        log.warning("Admin ID topilmadi — tasdiqlash so'rovi yuborilmadi (id=%s).", aid)
        return

    name = "Matematika" if subject == "math" else "Fizika"
    uname = f"@{user.username}" if user.username else (user.first_name or "noma'lum")
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
        f"🔑 Javoblar: `{payload['answers']}`\n"
        f"ℹ️ Username bo'lmasa, {esc(uname)} (ID: `{user.id}`) orqali bog'laning.\n\n"
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
                await _edit(cb, f"✅ Ruxsat berildi (#{aid})")
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
                await _edit(cb, f"❌ Rad etildi (#{aid})")
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
            await _edit(cb, 
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
            await _edit(cb, f"❌ Rad etildi (#{aid})")
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
        await _ans(message, f"⚠️ `{code}` kodi topilmadi.")
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
    await _ans(message, "\n".join(lines), parse_mode="HTML")


async def handle_test_answers(message: Message, state: dict, text: str) -> None:
    """Foydalanuvchi javoblarini tekshiradi."""
    user_id = message.from_user.id
    code = state["code"]
    test = await db.get_test_by_code(code)
    if not test:
        await db.clear_user_state(user_id)
        await _ans(message, "⚠️ Test topilmadi.")
        return

    ua = re.sub(r"[^a-f]", "", text.lower())
    n = len(test["questions"])
    if len(ua) != n:
        await _ans(message, 
            f"⚠️ {n} ta harf kerak, siz {len(ua)} ta yubordingiz. "
            f"Qaytadan yuboring (masalan `{('a' * n)}`)."
        )
        return

    correct, detail = check_answers(ua, test["answers"])
    await db.record_submission(user_id, code, test["subject"], ua, correct, n, detail)
    await db.bump("quizzes_taken")
    await db.clear_user_state(user_id)

    result = format_test_result(code, test["title"], correct, n, detail, test["questions"])
    await _ans(message, result, parse_mode="HTML")

    # Natijani tahlil qilib (taqdim etib) qo'shimcha izoh yuboramiz
    analysis = await analyze_result_with_ai(
        test["subject"], test["title"], correct, n, detail, test["questions"]
    )
    if analysis:
        await _safe_send(message, "🤖 *Tahlil va tavsiyalar*\n\n" + analysis)

    # 2-talab: test TUGAGACH test nomi ko'rsatiladi va kontakt ulashish
    # tugmasi beriladi (javob qabul qilinganidan keyin).
    await _ans(message, contact_ask_text(test["title"]), parse_mode="HTML",
               reply_markup=contact_reply_kb())


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
            await _ans(message, 
                "⚠️ Kod bo'sh joysiz, 32 belgidan qisqa bo'lsin. Qaytadan kiriting:"
            )
            return
        if await db.pdf_test_code_exists(code):
            await _ans(message, 
                f"⚠️ `{code}` kodi allaqachon band. Boshqa kod kiriting:"
            )
            return
        state["code"] = code
        state["step"] = "title"
        await db.set_user_state(user_id, "pdf_add", state)
        await _ans(message, 
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
        await _ans(message, 
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
            await _ans(message, 
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
        await _ans(message, 
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
        await _ans(message, 
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
    await _ans(message, "\n".join(lines), parse_mode="HTML")


async def handle_pdf_answers_input(message: Message, state: dict, text: str) -> None:
    """Foydalanuvchi javoblarini tekshiradi va xatolarni ko'rsatadi."""
    user_id = message.from_user.id
    code = state["code"]
    test = await db.get_pdf_test_by_code(code)
    if not test:
        await db.clear_user_state(user_id)
        await _ans(message, "⚠️ Test topilmadi.")
        return

    correct, total, detail = check_pdf_answers(text, test)
    await db.record_submission(
        user_id, code, test.get("subject", "umumiy"),
        text.strip(), correct, total, detail,
    )
    await db.bump("quizzes_taken")
    await db.clear_user_state(user_id)

    result = format_pdf_result(code, test["title"], correct, total, detail)
    await _ans(message, result, parse_mode="HTML")

    # PDF test uchun ham natija tahlili
    questions = []
    for q in test.get("questions", []):
        opts = q.get("options") or []
        label = q.get("q", "")
        if opts:
            label += " (" + ", ".join(str(o) for o in opts[:6]) + ")"
        questions.append({"q": label})
    analysis = await analyze_result_with_ai(
        test.get("subject", "umumiy"), test["title"], correct, total,
        [{"i": d.get("key"), "user": d.get("user"), "correct": d.get("correct"),
          "ok": d.get("ok")} for d in detail],
        questions,
    )
    if analysis:
        await _safe_send(message, "🤖 *Tahlil va tavsiyalar*\n\n" + analysis)

    # 2-talab: test TUGAGACH test nomi ko'rsatiladi va kontakt ulashish
    # tugmasi beriladi (javob qabul qilinganidan keyin).
    await _ans(message, contact_ask_text(test["title"]), parse_mode="HTML",
               reply_markup=contact_reply_kb())


# --------------------------------------------------------------------------- #
# Handlers — Vositalar (v4: faqat 2 ta — Savol qo'shish, Kanalga ulash)
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "tools:addq")
async def on_tools_addq(cb: CallbackQuery) -> None:
    u = cb.from_user
    await cb.answer()
    if config.is_admin(u.id, u.username):
        await _edit(cb, 
            "➕ *Savol qo'shish*\n\nQaysi bo'limga savol qo'shmoqchisiz?",
            reply_markup=qadd_type_kb(),
        )
        return
    # Admin emas — admindan ruxsat so'raymiz
    aid = await db.create_pending_approval(
        u.id, "addq",
        {"username": u.username or "", "first_name": u.first_name or "", "user_id": u.id},
    )
    await _edit(cb, 
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
        "Bu foydalanuvchiga savol qo'shishga ruxsat berasizmi?\n\n"
        "ℹ️ Username yo'q bo'lsa, ID orqali bog'lanishingiz mumkin."
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
        await _edit(cb, 
            "🎤 *IELTS Speaking* — qaysi partga savol qo'shasiz?",
            reply_markup=qadd_speaking_part_kb(),
        )
    elif kind == "writing":
        await _edit(cb, 
            "✍️ *IELTS Writing* — qaysi taskka topshiriq qo'shasiz?",
            reply_markup=qadd_writing_task_kb(),
        )
    elif kind in ("math", "phys"):
        name = "Matematika" if kind == "math" else "Fizika"
        await db.set_user_state(cb.from_user.id, "test_add", {
            "subject": kind, "step": "title", "title": "", "questions": [], "answers": ""
        })
        await _edit(cb, 
            f"➕ *{name} — test qo'shish*\n\n"
            "1️⃣ Test sarlavhasini yuboring (masalan: *Algebra asoslari*).\n\n"
            "ℹ️ Test admin tasdiqlagach bazaga qo'shiladi va unikal kod oladi."
        )
    elif kind == "pdf":
        await db.set_user_state(cb.from_user.id, "pdf_add", {"step": "file"})
        await _edit(cb, 
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
        await _edit(cb, 
            "🎤 *IELTS Speaking — Part 2 (cue card)*\n\n"
            "Cue card mavzusini birinchi qatorga, bandlarni keyingi qatorlarga yozing.\n\n"
            "Misol:\n"
            "Describe a book you liked\n"
            "what it was\n"
            "why you read it\n"
            "why you liked it"
        )
    else:
        await _edit(cb, 
            f"🎤 *IELTS Speaking — Part {part}*\n\n"
            "Savol matnini yuboring. (Ixtiyoriy: ikkinchi qatorga mavzuni yozing.)"
        )


@dp.callback_query(F.data.startswith("qadd:wr:"))
async def on_qadd_writing_task(cb: CallbackQuery) -> None:
    task = int(cb.data.split(":")[2])
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "qadd_writing", {"task": task})
    await _edit(cb, 
        f"✍️ *IELTS Writing — Task {task}*\n\n"
        "Topshiriq matnini yuboring. (Ixtiyoriy: ikkinchi qatorga minimal so'z sonini yozing.)"
    )


@dp.callback_query(F.data == "tools:channel")
async def on_tools_channel(cb: CallbackQuery) -> None:
    u = cb.from_user
    await cb.answer()
    if not config.is_admin(u.id, u.username):
        await _edit(cb, 
            "🔒 *Kanalga ulash* faqat admin uchun.\n\n"
            f"Admin: @{config.ADMIN_USERNAMES[0] if config.ADMIN_USERNAMES else 'admin'}"
        )
        return
    n = await db.count_channels()
    await _edit(cb, 
        f"📢 *Kanal boshqaruvi*\n\nUlangan kanallar: *{n}* ta\n\nBo'limni tanlang:",
        reply_markup=channel_kb(),
    )


@dp.callback_query(F.data == "chan:connect")
async def on_chan_connect(cb: CallbackQuery) -> None:
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "chan_connect", {})
    await _edit(cb, 
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
        await _edit(cb, 
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
    kb.adjust(1)
    await _edit(cb, "\n".join(lines), reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("chan:del:"))
async def on_chan_del(cb: CallbackQuery) -> None:
    cid = int(cb.data.split(":")[2])
    await db.delete_channel(cid)
    await cb.answer("O'chirildi 🗑")
    rows = await db.list_channels()
    if not rows:
        await _edit(cb, "📋 Kanallar yo'q.", reply_markup=channel_kb())
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Ulangan kanallar:*\n"]
    for r in rows:
        lines.append(f"• {esc(r['title'] or r['channel_id'])} — `{r['channel_id']}`")
        kb.button(text=f"🗑 {r['title'] or r['channel_id']}", callback_data=f"chan:del:{r['channel_id']}")
    kb.adjust(1)
    await _edit(cb, "\n".join(lines), reply_markup=kb.as_markup())


async def _pick_channel(cb: CallbackQuery, action: str) -> None:
    rows = await db.list_channels()
    if not rows:
        await _edit(cb, 
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
    kb.adjust(1)
    await _edit(cb, "📢 Qaysi kanalga?", reply_markup=kb.as_markup())


async def _start_channel_action(cb: CallbackQuery, action: str, channel_id: int) -> None:
    if action == "post":
        await db.set_user_state(cb.from_user.id, "chan_post", {"channel_id": channel_id})
        await _edit(cb, 
            "✍️ *Kanalga post*\n\n"
            "Yubormoqchi bo'lgan matnni (yoki rasmni izohi bilan) yuboring — "
            "kanalga joylayman."
        )
    elif action == "schedule":
        await db.set_user_state(cb.from_user.id, "chan_schedule", {"channel_id": channel_id})
        await _edit(cb, 
            "🗓 *Post rejalashtirish*\n\n"
            "Birinchi qatorda post matni, ikkinchi qatorda vaqt.\n\n"
            "Vaqt: `+30m`, `+2h`, `+1d`, `09:30`, `2026-10-20 14:00`\n"
            "Takrorlash uchun uchinchi qatorga daqiqalarni yozing (masalan 1440).\n\n"
            "Misol:\nBugungi test savollari\n+2h"
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
        await _ans(message, 
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
            await _ans(message, 
                "⚠️ Bot bu kanalda *admin* emas. Iltimos, botni kanalga admin qilib "
                "qo'shing, so'ng qayta urinib ko'ring."
            )
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("A'zolikni tekshirishda xato: %s", exc)
        await _ans(message, "⚠️ Kanal a'zoligini tekshirib bo'lmadi.")
        return

    await db.add_channel(user_id, chat.id, chat.title or "", chat.username or "")
    await db.clear_user_state(user_id)
    uname = f" (@{chat.username})" if chat.username else ""
    await _ans(message, 
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
        await _ans(message, "⚠️ Kanalga post yuborilmadi. Bot admin ekanligini tekshiring.")
        return
    await db.clear_user_state(user_id)
    await _ans(message, "✅ Post kanalga joylandi!", reply_markup=channel_kb())


async def handle_channel_schedule(message: Message, state: dict, text: str) -> None:
    """Kanalga postni rejalashtiradi."""
    user_id = message.from_user.id
    cid = state["channel_id"]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        await _ans(message, 
            "⚠️ Format: birinchi qatorda matn, ikkinchi qatorda vaqt.\n"
            "Misol:\nTest savollari\n+2h"
        )
        return
    body = lines[0]
    ts = parse_reminder_time(lines[1])
    if not body or ts is None:
        await _ans(message, 
            "⚠️ Vaqtni tushunmadim. Formatlar: `+30m`, `+2h`, `+1d`, `09:30`, "
            "`2026-10-20 14:00`."
        )
        return
    repeat = 0
    if len(lines) >= 3 and lines[2].isdigit():
        repeat = int(lines[2])
    pid = await db.add_scheduled_post(cid, body, ts, repeat_minutes=repeat, created_by=user_id)
    await db.clear_user_state(user_id)
    dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    rep = f"\n🔁 Har {repeat} daqiqada takrorlanadi" if repeat else ""
    await _ans(message, 
        f"✅ Post rejalashtirildi! (#{pid})\n\n📌 {esc(body)}\n⏰ {dt}{rep}",
        reply_markup=channel_kb(),
    )


async def handle_qadd_speaking(message: Message, state: dict, text: str) -> None:
    """IELTS Speaking savolini bazaga qo'shadi."""
    user_id = message.from_user.id
    part = state.get("part", 1)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if part == 2:
        cue = lines[0] if lines else text.strip()
        bullets = lines[1:]
        await db.add_speaking_question(
            part, cue, cue_card=cue, bullets=bullets, prep_seconds=60, speak_seconds=120
        )
    else:
        q = lines[0] if lines else text.strip()
        topic = lines[1] if len(lines) > 1 else ""
        await db.add_speaking_question(part, q, topic=topic)
    await db.clear_user_state(user_id)
    await _ans(message, 
        f"✅ Savol qo'shildi! (IELTS Speaking — Part {part})",
        reply_markup=qadd_type_kb(),
    )


async def handle_qadd_writing(message: Message, state: dict, text: str) -> None:
    """IELTS Writing topshirig'ini bazaga qo'shadi."""
    user_id = message.from_user.id
    task = state.get("task", 2)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    prompt = lines[0] if lines else text.strip()
    minw = 0
    if len(lines) > 1 and lines[1].isdigit():
        minw = int(lines[1])
    await db.add_writing_task(task, prompt, min_words=minw)
    await db.clear_user_state(user_id)
    await _ans(message, 
        f"✅ Topshiriq qo'shildi! (IELTS Writing — Task {task})",
        reply_markup=qadd_type_kb(),
    )


@dp.callback_query(F.data == "tools:rem")
async def on_tools_rem(cb: CallbackQuery) -> None:
    await cb.answer()
    await _edit(cb, 
        "⏰ *Eslatmalar*\n\nEslatma o'rnating — belgilangan vaqtda eslatib qo'yaman.",
        reply_markup=reminders_kb(),
    )


@dp.callback_query(F.data == "tools:rem_new")
async def on_rem_new(cb: CallbackQuery) -> None:
    await cb.answer()
    await db.set_user_state(cb.from_user.id, "reminder", {})
    await _edit(cb, 
        "⏰ *Yangi eslatma*\n\n"
        "Oddiy qilib, bir gapda yozing:\n\n"
        "📝 _Ertaga soat 12 da matematika darsini takrorlash_\n"
        "📝 _30 daqiqadan keyin suv ichish_\n"
        "📝 _Bugun kechqurun soat 20 da uchrashuv_\n\n"
        "Yoki ikki qatorda: matn, keyin vaqt (`+2h`, `09:30`, `2026-10-20 14:00`).",
        reply_markup=reminders_kb(),
    )


@dp.callback_query(F.data == "tools:rem_list")
async def on_rem_list(cb: CallbackQuery) -> None:
    await cb.answer()
    rows = await db.list_reminders(cb.from_user.id, only_pending=True)
    if not rows:
        await _edit(cb, "📋 Hozircha faol eslatmalar yo'q.",
                                   reply_markup=reminders_kb())
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Faol eslatmalar:*\n"]
    for r in rows:
        dt = datetime.fromtimestamp(r["remind_at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• #{r['id']} — {esc(r['text'])} ({dt})")
        kb.button(text=f"🗑 #{r['id']}", callback_data=f"rem:del:{r['id']}")
    kb.adjust(3)
    await _edit(cb, "\n".join(lines), reply_markup=kb.as_markup())


@dp.callback_query(F.data.startswith("rem:del:"))
async def on_rem_del(cb: CallbackQuery) -> None:
    rid = int(cb.data.split(":")[2])
    await db.delete_reminder(rid, cb.from_user.id)
    await cb.answer("O'chirildi 🗑")
    rows = await db.list_reminders(cb.from_user.id, only_pending=True)
    if not rows:
        await _edit(cb, "📋 Faol eslatmalar yo'q.", reply_markup=reminders_kb())
        return
    kb = InlineKeyboardBuilder()
    lines = ["📋 *Faol eslatmalar:*\n"]
    for r in rows:
        dt = datetime.fromtimestamp(r["remind_at"]).strftime("%Y-%m-%d %H:%M")
        lines.append(f"• #{r['id']} — {esc(r['text'])} ({dt})")
        kb.button(text=f"🗑 #{r['id']}", callback_data=f"rem:del:{r['id']}")
    kb.adjust(3)
    await _edit(cb, "\n".join(lines), reply_markup=kb.as_markup())


async def handle_reminder(message: Message, text: str) -> None:
    user_id = message.from_user.id

    # 1) Ikki qatorli format: birinchi qatorda matn, ikkinchisida vaqt
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2:
        ts2 = parse_reminder_time(lines[1])
        if ts2 is not None:
            await db.add_reminder(user_id, lines[0], ts2)
            await db.clear_user_state(user_id)
            dt = datetime.fromtimestamp(ts2).strftime("%Y-%m-%d %H:%M")
            await _ans(message, f"✅ Eslatma o'rnatildi!\n\n📌 {esc(lines[0])}\n⏰ {dt}")
            return

    # 2) Tabiiy til (bitta gap): "ertaga soat 12 da matematika"
    natural = parse_reminder_natural(text)
    if natural:
        body, ts = natural
        await db.add_reminder(user_id, body, ts)
        await db.clear_user_state(user_id)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        await _ans(message, f"✅ Eslatma o'rnatildi!\n\n📌 {esc(body)}\n⏰ {dt}")
        return

    # 3) Tushunmadik — oddiy tilda yo'riqnoma
    await _ans(message, 
        "🤔 Vaqtni tushunmadim. Oddiy qilib yozing, masalan:\n\n"
        "• _Ertaga soat 12 da matematika darsini takrorlash_\n"
        "• _30 daqiqadan keyin suv ichish_\n"
        "• _Bugun kechqurun soat 20 da uchrashuv_"
    )


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
        await _edit(cb, f"🎯 *{topic}* — test boshlandi! ({len(questions)} savol)")
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
        await _edit(cb, f"{esc(q['question'])}\n\n{result}", parse_mode="HTML")
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
        await _edit(cb, f"✅ Til o'zgartirildi: *{names.get(lang, lang)}*")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Handlers — ovoz, rasm, PDF, erkin matn
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Handlers — Bot kanalga admin qilinganda (my_chat_member)
# --------------------------------------------------------------------------- #
async def notify_admins_channel(cid: int, added_by, chat, chat_id: int) -> None:
    """Bot kanalga qo'shilganda adminlarga xabar yuboradi va ruxsat so'raydi.

    Ishonchli yetkazish:
      * ADMIN_ID o'rnatilmagan / admin botga /start yozmagan bo'lsa ham,
        username bo'yicha qidiruv orqali admin ID topiladi (get_admin_ids).
      * Har bir adminga yuborish natijasi logga yoziladi (yutib yuborilmaydi).
      * Hech kimga yetib bormasa — so'rov YARATILGAN holicha qoladi va kanal
        egasiga aniq yo'riqnoma yuboriladi.
    """
    admin_ids = await get_admin_ids()

    if added_by:
        uname = f"@{added_by.username}" if added_by.username else (added_by.first_name or "noma'lum")
        uid = added_by.id
    else:
        uname = "noma'lum"
        uid = 0
    uname2 = f" (@{chat.username})" if getattr(chat, "username", None) else ""
    text = (
        "📢 *Bot kanalga admin qilindi*\n\n"
        f"👤 Qo'shgan: {esc(uname)}\n"
        f"🆔 Foydalanuvchi ID: `{uid}`\n"
        f"📣 Kanal: *{esc(chat.title or chat_id)}*{uname2}\n"
        f"🆔 Kanal ID: `{chat_id}`\n"
        f"🔖 So'rov: `#{cid}`\n\n"
        "Bu kanalni botga ulashga ruxsat berasizmi?"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Ruxsat berish", callback_data=f"admin:chan:ok:{cid}")
    kb.button(text="❌ Rad etish", callback_data=f"admin:chan:no:{cid}")
    kb.adjust(2)

    delivered: list[int] = []
    failed: list[tuple[int, str]] = []
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb.as_markup(),
                                   parse_mode="HTML")
            delivered.append(admin_id)
            log.info("Kanal so'rovi (#%s) adminga yuborildi: %s", cid, admin_id)
        except Exception as exc:  # noqa: BLE001
            failed.append((admin_id, str(exc)))
            log.error("Adminga (%s) kanal so'rovi YUBORILMADI: %s", admin_id, exc)

    if not delivered:
        # Hech bir adminga yetib bormadi — bu jimgina yo'qolmasin.
        log.error(
            "Kanal so'rovi (#%s) hech bir adminga yetib BORMADI. admin_ids=%s, "
            "xatolar=%s. Sabab: ADMIN_ID o'rnatilmagan YOKI admin botga /start "
            "yozmagan (Telegram botga birinchi bo'lib yozmagan odamga xabar "
            "yuborishga ruxsat bermaydi).",
            cid, admin_ids, failed,
        )
        # Kanal egasiga (qo'shgan foydalanuvchiga) aniq yo'riqnoma yuboramiz.
        if added_by and added_by.id:
            try:
                await bot.send_message(
                    added_by.id,
                    "⚠️ *Kanal so'rovi adminga yetib bormadi*\n\n"
                    f"📣 Kanal: *{esc(chat.title or chat_id)}*\n\n"
                    "Sabab: bot admin bilan hali bog'lanmagan. Buni tuzatish uchun "
                    "admin (egasi) botga kirib *bir marta* `/start` yozishi kerak — "
                    "shundan keyin bot unga xabar yubora oladi.\n\n"
                    "Shundan so'ng kanalni qayta ulang yoki qo'shishni qaytaring.",
                    parse_mode="HTML",
                )
            except Exception as exc:  # noqa: BLE001
                log.error("Kanal egasiga (%s) yo'riqnoma yuborilmadi: %s", uid, exc)
        return

    # So'rov muvaffaqiyatli yetkazildi — kanal egasiga ham javob beramiz.
    if added_by and added_by.id:
        try:
            await bot.send_message(
                added_by.id,
                "⏳ *So'rov adminga yuborildi*\n\n"
                f"📣 Kanal: *{esc(chat.title or chat_id)}*\n\n"
                "Admin tasdiqlagach, kanal botga ulanadi va sizga xabar beraman.",
                parse_mode="HTML",
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Kanal egasiga tasdiq xabari yuborilmadi (%s): %s", uid, exc)


@dp.my_chat_member()
async def on_my_chat_member(event: ChatMemberUpdated) -> None:
    """Bot kanalga admin qilinganda adminlarga xabar yuboradi va ruxsat so'raydi."""
    chat = event.chat
    if getattr(chat, "type", "") != "channel":
        return
    new_status = getattr(event.new_chat_member, "status", "")
    old_status = getattr(event.old_chat_member, "status", "")
    new_s = new_status.value if hasattr(new_status, "value") else str(new_status)
    old_s = old_status.value if hasattr(old_status, "value") else str(old_status)
    if new_s not in ("administrator", "creator"):
        return
    if old_s in ("administrator", "creator"):
        return  # allaqachon admin edi — qayta so'ramaymiz
    if await db.get_channel(chat.id):
        return  # allaqachon ulangan

    added_by = event.from_user
    cid = await db.create_pending_channel(
        chat.id, chat.title or "", chat.username or "",
        added_by.id if added_by else 0,
    )
    log.info("Kanal tasdiqlash so'rovi yaratildi: %s (#%s)", chat.id, cid)
    await notify_admins_channel(cid, added_by, chat, chat.id)


@dp.callback_query(F.data.startswith("admin:chan:"))
async def on_admin_channel_decision(cb: CallbackQuery) -> None:
    """Admin kanalni botga ulashga ruxsat beradi yoki rad etadi."""
    parts = cb.data.split(":")
    if len(parts) != 4:
        return
    _, _, decision, cid_s = parts
    cid = int(cid_s)
    u = cb.from_user
    if not config.is_admin(u.id, u.username):
        await cb.answer("Faqat admin ruxsat berishi mumkin.", show_alert=True)
        return
    req = await db.get_pending_channel(cid)
    if not req or req["status"] != "pending":
        await cb.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    if decision == "ok":
        await db.add_channel(
            req["requested_by"] or u.id, req["channel_id"],
            req["title"] or "", req["username"] or "",
        )
        await db.set_pending_channel_status(cid, "approved", u.id)
        await cb.answer("Ruxsat berildi ✅")
        # So'rov egasiga natijani xabar qilamiz.
        if req.get("requested_by"):
            try:
                await bot.send_message(
                    req["requested_by"],
                    "✅ *Kanal botga ulandi!*\n\n"
                    f"📣 {esc(req['title'] or req['channel_id'])}\n"
                    f"🆔 `{req['channel_id']}`\n\n"
                    "Admin so'rovingizni tasdiqladi. Endi kanaldan foydalanishingiz "
                    "mumkin.",
                    parse_mode="HTML",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Kanal egasiga (%s) tasdiq xabari yuborilmadi: %s",
                    req["requested_by"], exc,
                )
        try:
            await cb.message.edit_text(
                f"✅ *Kanal botga ulandi!*\n\n"
                f"📣 {esc(req['title'] or req['channel_id'])}\n"
                f"🆔 `{req['channel_id']}`\n\n"
                "Endi kanal statistikada ko'rinadi va kanalga post joylash mumkin."
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            await bot.send_message(
                req["channel_id"],
                "✅ Bu kanal botga ulandi. Endi admin kanalga post joylashi va kanalni boshqarishi mumkin.",
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("Kanalga xabar yuborilmadi (%s): %s", req["channel_id"], exc)
    else:
        await db.set_pending_channel_status(cid, "rejected", u.id)
        await cb.answer("Rad etildi ❌")
        try:
            await cb.message.edit_text(f"❌ Kanal so'rovi rad etildi (`{req['channel_id']}`).")
        except Exception:  # noqa: BLE001
            pass
        # So'rov egasiga rad etilganini xabar qilamiz.
        if req.get("requested_by"):
            try:
                await bot.send_message(
                    req["requested_by"],
                    "❌ *Kanal so'rovingiz rad etildi.*\n\n"
                    f"📣 {esc(req['title'] or req['channel_id'])}\n"
                    f"🆔 `{req['channel_id']}`",
                    parse_mode="HTML",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Kanal egasiga (%s) rad xabari yuborilmadi: %s",
                    req["requested_by"], exc,
                )


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
        await _ans(message, "⚠️ Faqat *PDF* fayl qabul qilinadi.")
        return

    state = await db.get_user_state(u.id)
    if not state or state["state"] != "pdf_add":
        await _ans(message, 
            "ℹ️ PDF dan test qo'shish uchun: «🧰 Vositalar → ➕ Savol qo'shish → "
            "📄 PDF dan test» ni tanlang."
        )
        return

    if not config.is_admin(u.id, u.username):
        await _ans(message, "🔒 PDF dan test qo'shish faqat admin uchun.")
        return

    size_mb = (doc.file_size or 0) / (1024 * 1024)
    if size_mb > config.PDF_MAX_MB:
        await _ans(message, 
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
        await _ans(message, "⚠️ PDF faylni yuklab bo'lmadi.")
        return

    text = extract_pdf_text(data)
    if not text.strip():
        await _ans(message, 
            "⚠️ PDF dan matn ajratib bo'lmadi (skanerlangan rasm bo'lishi mumkin). "
            "Boshqa PDF yuboring."
        )
        return

    questions = parse_pdf_questions(text)
    if not questions:
        await _ans(message, 
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

    await _ans(message, 
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
        await _ans(message, "🎙 Ovozli rejim o'chirilgan.")
        return

    await _typing(message)
    try:
        file = await bot.get_file(message.voice.file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
    except Exception as exc:  # noqa: BLE001
        log.exception("Ovozni yuklab olishda xato: %s", exc)
        await _ans(message, "⚠️ Ovozli xabarni yuklab bo'lmadi.")
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

    # Ovozli rejim FAQAT IELTS Speaking ichida ishlatiladi.
    # Boshqa joyda ovoz yuborilsa — foydalanuvchini Speaking'ga yo'naltiramiz.
    await _ans(message, 
        "🎤 Ovozli javob faqat *IELTS Speaking* bo'limida baholanadi.\n\n"
        "👇 *IELTS Speaking* → Part tanlang, savolga ovozli xabar yuboring "
        "— IELTS mezonlari bo'yicha baholayman.",
        reply_markup=Speaking_redirect_kb(),
    )


def Speaking_redirect_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎤 IELTS Speaking", callback_data="menu:speaking")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(F.photo)
async def on_photo(message: Message) -> None:
    u = message.from_user
    if u:
        await db.upsert_user(u.id, u.username, u.first_name)

    # Kanalga rasm post qilish holati
    state = None
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
                await _ans(message, "⚠️ Kanalga rasm yuborilmadi. Bot admin ekanligini tekshiring.")
                return
            await db.clear_user_state(u.id)
            await _ans(message, "✅ Rasm kanalga joylandi!", reply_markup=channel_kb())
            return

    await _typing(message)
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buf = await bot.download_file(file.file_path)
        data = buf.read()
    except Exception as exc:  # noqa: BLE001
        log.exception("Rasm yuklab olishda xato: %s", exc)
        await _ans(message, "⚠️ Rasmni yuklab bo'lmadi.")
        return

    caption = (message.caption or "").strip()

    # Rasm FAQAT IELTS Writing Task 1 ichida ishlatiladi (grafik/diagramma).
    if state and state["state"] == "writing" and state["data"].get("task") == 1:
        prompt = (
            "Bu grafik/diagramma/rasmni IELTS Writing Task 1 uchun tahlil qil."
            " Asosiy tendentsiyalar, eng katta/kichik qiymatlar, taqqoslashlar va "
            "umumiy xulosani aniqla. So'ng foydalanuvchiga shu grafik asosida Task 1 "
            "inshosini yozish uchun tuzilma va foydali iboralar taklif qil."
        )
        if caption:
            prompt += f" Foydalanuvchi so'rovi: {caption}"
        answer = await _ask_gemini_custom(
            message, prompt, WRITING_TASK1_PROMPT, image_bytes=data,
            image_mime="image/jpeg",
        )
        if answer:
            await _safe_send(message, answer)
        return

    # Boshqa joyda rasm yuborilsa — Writing Task 1'ga yo'naltiramiz.
    await _ans(message, 
        "🖼 Rasm tahlili *IELTS Writing Task 1* bo'limida ishlatiladi "
        "(grafik/diagramma tahlili).\n\n"
        "👇 *IELTS Writing* → Task 1 ni tanlab, rasm yuboring.",
        reply_markup=Writing_redirect_kb(),
    )


def Writing_redirect_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ IELTS Writing", callback_data="menu:writing")
    kb.adjust(1)
    return kb.as_markup()


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

    # 0) Pastdagi doimiy panel tugmalari (oddiy, tabiiy)
    if text == BTN_START:
        # /start — yangi suhbat: AI xotirasi ham, joriy holat ham tozalanadi
        await _reset_my_conversation(u.id)
        name = u.first_name or "do'stim"
        await _ans(message, 
            f"👋 Xush kelibsiz, *{name}*!\n\nBo'limni tanlang 👇",
            reply_markup=_menu_kb_for(u),
        )
        await _ans(message, "ℹ️ Doimiy panel pastda qoladi.",
                   reply_markup=main_reply_kb())
        return
    if text == BTN_MAIN:
        await db.clear_user_state(u.id)
        await _ans(message, "🏠 *Asosiy menyu* — bo'limni tanlang:",
                   reply_markup=_menu_kb_for(u))
        return
    if text == BTN_RESET:
        # 3-talab: suhbat HAR IKKI tomondan tozalanadi va /start bilan
        # qaytadan boshlash taklif qilinadi (eski tugmalar/suhbat qolmaydi).
        await _reset_my_conversation(u.id)
        await _ans(message, 
            "🔄 *Suhbat tozalandi.* Eski suhbat ham, bot xotirasi ham "
            "tozalandi.\n\n▶️ Yangi suhbatni boshlash uchun /start ni yuboring.",
            reply_markup=_menu_kb_for(u),
        )
        return
    if text == BTN_REMIND:
        await db.set_user_state(u.id, "reminder", {})
        await _ans(message, 
            "⏰ *Eslatma*\n\nOddiy qilib yozing — masalan:\n"
            "`Ertaga soat 12 da matematika darsini takrorlash`",
            reply_markup=reminders_kb(),
        )
        return
    if text == BTN_CHANNEL:
        cid = config.DEFAULT_CHANNEL_ID
        if cid:
            try:
                chat = await bot.get_chat(cid)
                await _ans(message, 
                    f"📢 *Kanal:* {esc(getattr(chat, 'title', cid))}\n"
                    f"ID: `{chat.id}`\n\n"
                    "Bot shu kanalga post joylay oladi.",
                )
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("get_chat xato: %s", exc)
        await _ans(message, 
            "📢 *Kanal boshqaruvi*\n\nKanal ulash, post joylash va "
            "rejalashtirish uchun:",
            reply_markup=channel_kb(),
        )
        return

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
        if st == "ai_chat":
            await _ask_gemini(message, text)
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
        if st == "test_add2":
            await handle_test_add2(message, state["data"], text)
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
        if st == "contact":
            if await handle_contact_text(message, text):
                return
            # kontakt emas — pastdagi odatdagi oqimga tushamiz

    # 2-talab: foydalanuvchi kontaktni oddiy xabar sifatida yozsa ham qabul qilamiz
    _phone_like = re.sub(r"[^0-9+]", "", text)
    if (
        len(_phone_like) >= 7
        and re.fullmatch(r"[+0-9][0-9\s()\-]{6,}[0-9]", text.strip())
    ):
        await _save_contact_and_ack(message, _phone_like)
        return

    # 1) Test kodi (MATH-0001 / PHY-0001)
    if _TEST_CODE_RE.match(text.strip()):
        await handle_test_code(message, text.strip().upper())
        return

    # 1b) Boshqa test kodlari (admin kiritgan kod yoki PDF) — mavjud bo'lsa javob oynasi
    if re.fullmatch(r"[A-Za-z0-9_-]{2,32}", text.strip()):
        raw = text.strip()
        if await db.test_code_exists(raw):
            await handle_test_code(message, raw.upper())
            return
        pdf_test = await db.get_pdf_test_by_code(raw)
        if pdf_test:
            await handle_pdf_answers_code(message, raw)
            return

    # 2) Faol test bo'lsa — tugmalardan foydalanishni eslatamiz
    sess = await db.get_quiz_session(u.id)
    if sess:
        await _ans(message, 
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

    # 3b) Tabiiy tildagi eslatma ("ertaga soat 12 da ...")
    if looks_like_reminder(text):
        natural = parse_reminder_natural(text)
        if natural:
            body_n, ts_n = natural
            await db.add_reminder(u.id, body_n, ts_n)
            dt_n = datetime.fromtimestamp(ts_n).strftime("%Y-%m-%d %H:%M")
            await _ans(message, f"✅ Eslatma o'rnatildi!\n\n📌 {esc(body_n)}\n⏰ {dt_n}")
            return

    # 4) AI javob (hamma soha)
    topic = detect_topic(text)
    await db.add_history(u.id, "user", text, topic=topic, source="ai")
    await db.bump("ai_requests")
    if topic:
        await db.bump(f"topic:{topic}")

    await _typing(message)
    try:
        answer = await pool.generate(
            text, system_instruction=SYSTEM_PROMPT,
            history=await db.get_context_history(u.id, limit=config.HISTORY_CONTEXT_SIZE),
        )
    except AllKeysFailedError as exc:
        log.error("Gemini xatosi: %s", exc)
        await _ans(message, 
            "⚠️ Hozircha AI xizmatiga ulanib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."
        )
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("Kutilmagan xato: %s", exc)
        await _ans(message, "⚠️ Kutilmagan xatolik yuz berdi. Qayta urinib ko'ring.")
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
                        reply_markup=back_kb(),
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
        "sub_gate": bool(config.ENABLE_SUB_GATE),
        "req_channel": config.REQUIRED_CHANNEL_ID or None,
    }

    # Majburiy kanal tekshiruvi — barcha yangilanishlar uchun eng tashqi qatlam.
    dp.update.outer_middleware(sub_gate_outer_middleware)
    log.info(
        "Majburiy kanal tekshiruvi: %s (kanal=%s)",
        "yoqilgan" if config.ENABLE_SUB_GATE else "o'chirilgan",
        config.REQUIRED_CHANNEL_ID or "-",
    )

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
