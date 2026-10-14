"""AI Manager Bot - configuration.

Every value is read from the environment (.env locally, Render env in prod).
No secret is ever written into this file.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _env(key, default=""):
    v = os.getenv(key)
    return v if v not in (None, "") else default


def _bool(key, default=False):
    return str(os.getenv(key, str(default))).strip().lower() in ("1", "true", "yes", "on")


def _int(key, default):
    try:
        return int(str(os.getenv(key, default)).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- Telegram
BOT_TOKEN = _env("BOT_TOKEN") or _env("TELEGRAM_BOT_TOKEN")


# ---------------------------------------------------------------- Gemini keys
def _collect_keys():
    """Accept GEMINI_API_KEYS (comma separated) and/or GEMINI_KEY_1..5."""
    raw = []
    csv = _env("GEMINI_API_KEYS")
    if csv:
        raw += [k.strip() for k in csv.split(",")]
    for i in range(1, 6):
        raw.append(_env(f"GEMINI_KEY_{i}"))
    out, seen = [], set()
    for k in raw:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


GEMINI_API_KEYS = _collect_keys()
GEMINI_MODELS = [m.strip() for m in _env(
    "GEMINI_MODELS",
    "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-flash-lite-latest,"
    "gemini-3.8-flash,gemini-flash-latest",
).split(",") if m.strip()]
GEMINI_IMAGE_MODELS = [m.strip() for m in _env(
    "GEMINI_IMAGE_MODELS",
    "gemini-3.1-flash-image,gemini-3-pro-image",
).split(",") if m.strip()]
COOLDOWN_SECONDS = _int("COOLDOWN_SECONDS", 60)
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 60)


# ---------------------------------------------------------------- Database
DB_PATH = _env("DB_PATH", "bot.db")


# ---------------------------------------------------------------- Health server
PORT = _int("PORT", 0)
ENABLE_HEALTH_SERVER = _bool("ENABLE_HEALTH_SERVER", True)
SELF_PING_ENABLED = _bool("SELF_PING_ENABLED", True)
SELF_PING_INTERVAL = _int("SELF_PING_INTERVAL", 600)
RENDER_EXTERNAL_URL = _env("RENDER_EXTERNAL_URL")


# ---------------------------------------------------------------- Watchdog
WATCHDOG_ENABLED = _bool("WATCHDOG_ENABLED", True)
WATCHDOG_INTERVAL = _int("WATCHDOG_INTERVAL", 300)
WATCHDOG_MEMORY_LIMIT_MB = _int("WATCHDOG_MEMORY_LIMIT_MB", 400)
WATCHDOG_GC_EVERY = _int("WATCHDOG_GC_EVERY", 6)


# ---------------------------------------------------------------- Backup (GitHub Gist)
BACKUP_ENABLED = _bool("BACKUP_ENABLED", False)
GITHUB_TOKEN = _env("GITHUB_TOKEN")
GIST_ID = _env("GIST_ID")
BACKUP_INTERVAL_SECONDS = _int("BACKUP_INTERVAL_SECONDS", 3600)
RESTORE_ON_START = _bool("RESTORE_ON_START", True)


# ---------------------------------------------------------------- Admin
ADMIN_ID = _env("ADMIN_ID") or _env("ADMIN_IDS")
ADMIN_USERNAME = _env("ADMIN_USERNAME", "Husan_Dilmurodov").lstrip("@")
ADMIN_PHONE = _env("ADMIN_PHONE", "")


def admin_ids():
    out = []
    for part in ADMIN_ID.replace(";", ",").split(","):
        p = part.strip()
        if p.isdigit():
            out.append(int(p))
    return out


# ---------------------------------------------------------------- Features
ENABLE_INSTANT_REPLIES = _bool("ENABLE_INSTANT_REPLIES", True)
INSTANT_MAX_LEN = _int("INSTANT_MAX_LEN", 60)
QUIZ_QUESTIONS_PER_SESSION = _int("QUIZ_QUESTIONS_PER_SESSION", 5)
ENABLE_IMAGE_GEN = _bool("ENABLE_IMAGE_GEN", True)
HISTORY_TURNS = _int("HISTORY_TURNS", 8)
LOG_LEVEL = _env("LOG_LEVEL", "INFO")
WEBHOOK_BASE_URL = _env("WEBHOOK_BASE_URL")
DEFAULT_LANG = _env("DEFAULT_LANG", "uz")

TEXTS = {
    "uz": {
        "welcome": "Assalomu alaykum, {name}! \U0001f916\n\nMen <b>AI Manager Bot</b> \u2014 har qanday sohada yordam beradigan aqlli yordamchingizman.",
        "choose_lang": "Tilni tanlang:",
        "main_menu": "\U0001f4cb Asosiy menyu",
        "ask_ai": "\u2753 Savolingizni yozing \u2014 men javob beraman.",
        "thinking": "\U0001f914 O'ylayapman...",
        "cleared": "\U0001f9f9 Suhbat tarixi tozalandi.",
        "no_history": "\U0001f4ed Tarix bo'sh.",
        "error": "\u26a0\ufe0f Xatolik yuz berdi. Keyinroq urinib ko'ring.",
        "busy": "\u23f3 Barcha kalitlar band. Iltimos, biroz kutib qayta urinib ko'ring.",
    },
    "en": {
        "welcome": "Hello, {name}! \U0001f916\n\nI am <b>AI Manager Bot</b> \u2014 your all-purpose AI assistant.",
        "choose_lang": "Choose a language:",
        "main_menu": "\U0001f4cb Main menu",
        "ask_ai": "\u2753 Send me a question and I will answer.",
        "thinking": "\U0001f914 Thinking...",
        "cleared": "\U0001f9f9 Chat history cleared.",
        "no_history": "\U0001f4ed No history yet.",
        "error": "\u26a0\ufe0f Something went wrong. Please try again.",
        "busy": "\u23f3 All keys are busy. Please retry shortly.",
    },
    "ru": {
        "welcome": "\u0417\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435, {name}! \U0001f916\n\n\u042f <b>AI Manager Bot</b> \u2014 \u0432\u0430\u0448 \u0443\u043d\u0438\u0432\u0435\u0440\u0441\u0430\u043b\u044c\u043d\u044b\u0439 AI-\u043f\u043e\u043c\u043e\u0449\u043d\u0438\u043a.",
        "choose_lang": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u044f\u0437\u044b\u043a:",
        "main_menu": "\U0001f4cb \u0413\u043b\u0430\u0432\u043d\u043e\u0435 \u043c\u0435\u043d\u044e",
        "ask_ai": "\u2753 \u0417\u0430\u0434\u0430\u0439\u0442\u0435 \u0432\u043e\u043f\u0440\u043e\u0441 \u2014 \u044f \u043e\u0442\u0432\u0435\u0447\u0443.",
        "thinking": "\U0001f914 \u0414\u0443\u043c\u0430\u044e...",
        "cleared": "\U0001f9f9 \u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043e\u0447\u0438\u0449\u0435\u043d\u0430.",
        "no_history": "\U0001f4ed \u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043f\u0443\u0441\u0442\u0430.",
        "error": "\u26a0\ufe0f \u041f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0430 \u043e\u0448\u0438\u0431\u043a\u0430. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.",
        "busy": "\u23f3 \u0412\u0441\u0435 \u043a\u043b\u044e\u0447\u0438 \u0437\u0430\u043d\u044f\u0442\u044b. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.",
    },
}


def t(lang, key, **kw):
    lang = lang if lang in TEXTS else DEFAULT_LANG
    s = TEXTS[lang].get(key) or TEXTS[DEFAULT_LANG].get(key, key)
    return s.format(**kw) if kw else s
