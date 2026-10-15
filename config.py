"""Konfiguratsiya: .env faylidan o'qiladi."""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# --- Gemini ---
# Kalitlarni .env da GEMINI_API_KEYS=key1,key2,key3,... ko'rinishida bering.
# Ikki xil usul qo'llanadi (ikkisi ham ishlaydi, birlashtiriladi):
#   1) GEMINI_API_KEYS=key1,key2,key3,key4,key5   (vergul bilan)
#   2) GEMINI_KEY_1=... GEMINI_KEY_2=... ... GEMINI_KEY_5=...
#      (Render'da har birini alohida env sifatida kiritish uchun qulay)
_raw_keys = os.getenv("GEMINI_API_KEYS", "")
_numbered_keys = [os.getenv(f"GEMINI_KEY_{i}", "") for i in range(1, 11)]
_keys = [k.strip() for k in _raw_keys.split(",") if k.strip()]
_keys += [k.strip() for k in _numbered_keys if k.strip()]
# Takrorlanmasin, kiritilgan tartib saqlansin
GEMINI_API_KEYS = list(dict.fromkeys(_keys))

# Model zaxira zanjiri (fallback): birinchi model kvota/xato bersa, keyingisi sinaladi.
# MUHIM: "gemini-1.5-flash" Google tomonidan olib tashlangan (404) — ishlatilmaydi.
_raw_models = os.getenv(
    "GEMINI_MODELS",
    "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.8-flash,gemini-3.5-flash",
)
GEMINI_MODELS = [m.strip() for m in _raw_models.split(",") if m.strip()]

# Orqaga moslik uchun: bitta model nomi.
GEMINI_MODEL = GEMINI_MODELS[0] if GEMINI_MODELS else "gemini-3.5-flash-lite"

GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta",
).rstrip("/")

# Imagen (ixtiyoriy — rasm generatsiyasi uchun)
IMAGEN_MODEL = os.getenv("IMAGEN_MODEL", "imagen-3.0-generate-002").strip()
ENABLE_IMAGE_GEN = os.getenv("ENABLE_IMAGE_GEN", "true").lower() in ("1", "true", "yes")

# --- Ma'lumotlar bazasi ---
DB_PATH = os.getenv("DB_PATH", "bot.db").strip()
INSTANT_REPLIES_FILE = os.getenv("INSTANT_REPLIES_FILE", "instant_replies.json").strip()
QUIZ_DATA_FILE = os.getenv("QUIZ_DATA_FILE", "quiz_data.json").strip()
IELTS_SPEAKING_FILE = os.getenv("IELTS_SPEAKING_FILE", "ielts_speaking.json").strip()
IELTS_WRITING_FILE = os.getenv("IELTS_WRITING_FILE", "ielts_writing.json").strip()
MATH_TESTS_FILE = os.getenv("MATH_TESTS_FILE", "math_tests.json").strip()
PHYSICS_TESTS_FILE = os.getenv("PHYSICS_TESTS_FILE", "physics_tests.json").strip()

# Tezkor javob tizimi
ENABLE_INSTANT_REPLIES = os.getenv("ENABLE_INSTANT_REPLIES", "true").lower() in ("1", "true", "yes")
# Tezkor javob faqat shu uzunlikdan qisqa xabarlarga qo'llanadi (belgi soni).
INSTANT_MAX_LEN = int(os.getenv("INSTANT_MAX_LEN", "60"))

# --- Test (quiz) ---
QUIZ_QUESTIONS_PER_SESSION = int(os.getenv("QUIZ_QUESTIONS_PER_SESSION", "5"))

# --- Suhbat tarixi / xotira ---
# AI javobida hisobga olinadigan oldingi qatlamlar soni (xotira).
HISTORY_CONTEXT_SIZE = int(os.getenv("HISTORY_CONTEXT_SIZE", "6"))

# --- Umumiy ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.getenv("LOG_DIR", "logs")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "90"))
MAX_RETRIES_PER_KEY = int(os.getenv("MAX_RETRIES_PER_KEY", "2"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "60"))

# --- Admin ---
# ADMIN_IDS — Telegram user_id lar (vergul bilan). ADMIN_USERNAMES — @ belgisisiz.
# ADMIN_IDS — vergul bilan bir nechta id; ADMIN_ID — bitta id (Render uchun qulay)
# ADMIN_USERNAMES — vergul bilan; ADMIN_USERNAME — bitta username
_admin = os.getenv("ADMIN_IDS", "")
_admin_single = os.getenv("ADMIN_ID", "")
_admin_all = ",".join(x for x in (_admin, _admin_single) if x)
ADMIN_IDS = [int(x) for x in _admin_all.split(",") if x.strip().lstrip("-").isdigit()]
ADMIN_IDS = list(dict.fromkeys(ADMIN_IDS))

_admin_unames = os.getenv("ADMIN_USERNAMES", "")
_admin_uname_single = os.getenv("ADMIN_USERNAME", "Husan_Dilmurodov")
_unames_all = ",".join(x for x in (_admin_unames, _admin_uname_single) if x)
ADMIN_USERNAMES = list(
    dict.fromkeys(u.strip().lstrip("@").lower() for u in _unames_all.split(",") if u.strip())
)
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+998 883800311").strip()

# --- Eslatmalar (reminders) ---
# Fon vazifasi har necha sekundda tekshiradi.
REMINDER_CHECK_INTERVAL = int(os.getenv("REMINDER_CHECK_INTERVAL", "30"))

# --- Majburiy kanal (subscription gate) ---
# Foydalanuvchi bo'limlardan foydalanishdan oldin shu kanalga ulanishi kerak.
REQUIRED_CHANNEL_URL = os.getenv(
    "REQUIRED_CHANNEL_URL", "https://t.me/matmilliysertifikat"
).strip()
# getChatMember uchun: @username yoki -100... ID.
REQUIRED_CHANNEL_ID = os.getenv(
    "REQUIRED_CHANNEL_ID", "@matmilliysertifikat"
).strip()
# Gate umuman yoqilgan/o'chirilgani.
ENABLE_SUB_GATE = os.getenv("ENABLE_SUB_GATE", "true").lower() in ("1", "true", "yes")

# --- Kanal boshqaruvi ---
# Standart kanal ID (ixtiyoriy). Bo'sh bo'lsa, kanal bot orqali ulanadi.
DEFAULT_CHANNEL_ID = os.getenv("DEFAULT_CHANNEL_ID", "").strip()
# Rejalashtirilgan postlarni tekshirish oralig'i (sekund).
POST_CHECK_INTERVAL = int(os.getenv("POST_CHECK_INTERVAL", "30"))

# --- Kanal faolligi (reaksiyalar + ko'rishlar) ---
# Fon vazifasi kanal postlarining ko'rish va reaksiya ko'rsatkichlarini
# qanchalik tez-tez yig'ib borishini belgilaydi (sekund).
ENGAGEMENT_CHECK_INTERVAL = int(os.getenv("ENGAGEMENT_CHECK_INTERVAL", "900"))

# --- PDF testlar ---
# PDF dan matn ajratib olish uchun maksimal fayl hajmi (MB).
PDF_MAX_MB = int(os.getenv("PDF_MAX_MB", "20"))
# PDF dan ajratib olinadigan maksimal savol soni.
PDF_MAX_QUESTIONS = int(os.getenv("PDF_MAX_QUESTIONS", "200"))

# --- Ovozli rejim (faqat IELTS Speaking ichida ishlatiladi) ---
# Ovozli xabarlarni matnga o'girish uchun model (Gemini audio input).
VOICE_MODEL = os.getenv("VOICE_MODEL", "gemini-3.5-flash-lite").strip()
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "true").lower() in ("1", "true", "yes")


# --- Render / bulut deploy ---
# Render `PORT` ni avtomatik beradi; 0 bo'lsa health server o'chadi.
PORT = int(os.getenv("PORT", "0"))
ENABLE_HEALTH_SERVER = os.getenv("ENABLE_HEALTH_SERVER", "true").lower() in ("1", "true", "yes")
HEALTH_HOST = os.getenv("HEALTH_HOST", "0.0.0.0").strip()

# Self-ping: Render uxlab qolmasligi uchun servis o'zini ping qiladi.
# Render'da RENDER_EXTERNAL_URL avtomatik mavjud bo'ladi.
SELF_PING_URL = (
    os.getenv("SELF_PING_URL", "").strip()
    or os.getenv("RENDER_EXTERNAL_URL", "").strip()
)
SELF_PING_INTERVAL = int(os.getenv("SELF_PING_INTERVAL", "600"))

# --- Watchdog (uzoq muddatli barqarorlik) ---
# Xotira oqib ketishini (memory leak) va event loop bloklanishini kuzatadi.
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
WATCHDOG_INTERVAL = int(os.getenv("WATCHDOG_INTERVAL", "300"))
# Xotira chegarasi (MB). 0 = o'chirilgan. Oshsa — jarayon toza qayta ishga tushadi.
# Render bepul tarifida ~512 MB RAM; 400 MB xavfsiz chegara.
WATCHDOG_MEMORY_LIMIT_MB = int(os.getenv("WATCHDOG_MEMORY_LIMIT_MB", "0"))
WATCHDOG_GC_EVERY = int(os.getenv("WATCHDOG_GC_EVERY", "6"))

# --- Zaxiralash (GitHub Gist) ---
# Render bepul tarifida disk vaqtinchalik — baza shu yo'l bilan saqlanadi.
BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "false").lower() in ("1", "true", "yes")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GIST_ID = os.getenv("GIST_ID", "").strip()
BACKUP_INTERVAL_SECONDS = int(os.getenv("BACKUP_INTERVAL_SECONDS", "3600"))
RESTORE_ON_START = os.getenv("RESTORE_ON_START", "true").lower() in ("1", "true", "yes")


def is_admin(user_id: int, username: str | None = None) -> bool:
    """Foydalanuvchi admin ekanligini tekshiradi (ID yoki username bo'yicha)."""
    if user_id in ADMIN_IDS:
        return True
    if username and username.lstrip("@").lower() in ADMIN_USERNAMES:
        return True
    return False


def validate() -> None:
    """Ishga tushishdan oldin majburiy sozlamalarni tekshiradi."""
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN bo'sh — .env faylini to'ldiring.")
    if not GEMINI_API_KEYS:
        errors.append("GEMINI_API_KEYS bo'sh — kamida bitta kalit kerak.")
    if not GEMINI_MODELS:
        errors.append("GEMINI_MODELS bo'sh — kamida bitta model kerak.")
    if errors:
        raise SystemExit("\n".join(errors))
