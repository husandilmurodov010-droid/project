"""AI Manager Bot - Gemini powered all-purpose Telegram bot.

Runs as a Render web service (Telegram webhook) or locally with polling.
Includes: instant replies, all-domain AI answers, quizzes, question bank,
IELTS / math / physics test tooling, channel management with scheduled posts,
admin approval flow, health server, watchdog and Gist backup.
"""
import asyncio
import contextlib
import datetime as dt
import logging
import os
import sys

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramConflictError
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from aiohttp import web

import config as C
from backup import BackupManager
from database import Database
from gemini_pool import AllKeysFailed, pool
from health_server import HealthServer
from watchdog import Watchdog

# --------------------------------------------------------------------- logging
logging.basicConfig(
    level=getattr(logging, C.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)-9s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bot")

if C.GITHUB_TOKEN:
    log.info("Kalitlar: %d ta Gemini kalit yuklandi, %d model", pool.n_keys, len(pool.models))

router = Router()
db = Database()
backup = BackupManager()
watchdog = Watchdog()
bot: Bot = None
APP_STARTED = False

SUBJECT_KEYWORDS = {
    "matematika": ["hisob", "tenglama", "integral", "hosila", "algebra", "geometriya", "son", "foiz"],
    "tarix": ["tarix", "urush", "sulola", "amir temur", "yil", "imperiya", "mustaqillik"],
    "ingliz tili": ["grammar", "tense", "english", "translation", "tarjima", "ielts"],
    "dasturlash": ["python", "kod", "funksiya", "api", "dastur", "javascript", "sql", "git"],
    "tibbiyot": ["dori", "kasallik", "tibbiyot", "simptom", "davolash", "shifokor"],
    "biznes": ["biznes", "marketing", "startup", "foyda", "investitsiya", "sotuv"],
    "fan": ["fizika", "kimyo", "biologiya", "atom", "energiya", "formula"],
    "geografiya": ["davlat", "poytaxt", "okean", "iqlim", "xarita", "mintaqa"],
}

SYSTEM_PROMPT = (
    "Siz AI Manager Bot - har qanday sohada bilimli, aniq va foydali yordamchisiz. "
    "Foydalanuvchi tilida (o'zbek, rus yoki ingliz) javob bering. Javob qisqa, "
    "tuzilgan va amaliy bo'lsin. Kerak bo'lsa ro'yxat va misollar keltiring."
)


# --------------------------------------------------------------------- helpers
def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
    ])


def main_menu_kb(lang="uz"):
    return _kb([
        [("🎯 Test", "menu:quiz"), ("📊 Statistika", "menu:stats")],
        [("📜 Tarix", "menu:history"), ("🌐 Til", "menu:lang")],
        [("🧰 Vositalar", "menu:tools"), ("ℹ️ Yordam", "menu:help")],
    ])


def tools_kb():
    return _kb([
        [("➕ Savol qo'shish", "tools:addq")],
        [("📢 Kanalga ulash", "tools:channel")],
        [("⬅️ Orqaga", "menu:home")],
    ])


def channel_kb():
    return _kb([
        [("➕ Kanal ulash", "chan:add")],
        [("📋 Kanallarim", "chan:list")],
        [("✍️ Kanalga post", "chan:post")],
        [("🗓 Post rejalashtirish", "chan:schedule")],
        [("⬅️ Orqaga", "menu:tools")],
    ])


def detect_subject(text):
    low = (text or "").lower()
    best, score = None, 0
    for subj, words in SUBJECT_KEYWORDS.items():
        hits = sum(1 for w in words if w in low)
        if hits > score:
            best, score = subj, hits
    return best or "umumiy"


def parse_schedule(raw):
    """'matn | +2h' | 'matn | 09:30' | 'matn | 2026-10-16 09:30' -> (text, iso, repeat_min)"""
    parts = [p.strip() for p in raw.split("|")]
    text = parts[0]
    when, repeat = "", 0
    if len(parts) >= 2:
        when = parts[1]
    if len(parts) >= 3 and parts[2].isdigit():
        repeat = int(parts[2])
    now = dt.datetime.utcnow()
    target = None
    if when.startswith("+"):
        body = when[1:]
        unit = body[-1:].lower()
        amount = body[:-1]
        if amount.isdigit():
            n = int(amount)
            if unit == "m":
                target = now + dt.timedelta(minutes=n)
            elif unit == "h":
                target = now + dt.timedelta(hours=n)
            elif unit == "d":
                target = now + dt.timedelta(days=n)
    elif len(when) == 5 and when[2] == ":":
        h, m = when.split(":")
        target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        if target < now:
            target += dt.timedelta(days=1)
    elif when:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
            try:
                target = dt.datetime.strptime(when, fmt)
                break
            except ValueError:
                continue
    if target is None:
        target = now + dt.timedelta(minutes=5)
    return text, target.strftime("%Y-%m-%dT%H:%M:%SZ"), repeat


async def ask_ai(user_id, text, lang="uz"):
    history = await db.recent_history(user_id, C.HISTORY_TURNS)
    contents = []
    for h in history:
        role = "model" if h["role"] == "assistant" else "user"
        if h["text"]:
            contents.append({"role": role, "parts": [{"text": h["text"]}]})
    contents.append({"role": "user", "parts": [{"text": text}]})
    return await pool.generate(contents, system_instruction=SYSTEM_PROMPT)


def _fail_text(exc, lang="uz"):
    if isinstance(exc, AllKeysFailed):
        return C.t(lang, "busy")
    return C.t(lang, "error")


# --------------------------------------------------------------------- /start
@router.message(F.text.startswith("/start"))
async def cmd_start(m: Message):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    lang = await db.get_lang(m.from_user.id)
    name = m.from_user.first_name or m.from_user.username or "do'st"
    await m.answer(C.t(lang, "welcome", name=name), reply_markup=main_menu_kb(lang))
    await m.answer(C.t(lang, "main_menu"), reply_markup=main_menu_kb(lang))


@router.message(F.text.startswith("/menu"))
async def cmd_menu(m: Message):
    lang = await db.get_lang(m.from_user.id)
    await m.answer(C.t(lang, "main_menu"), reply_markup=main_menu_kb(lang))


@router.message(F.text.startswith("/help"))
async def cmd_help(m: Message):
    lang = await db.get_lang(m.from_user.id)
    text = (
        "📘 <b>Buyruqlar</b>\n\n"
        "/start — Boshlash\n/menu — Asosiy menyu\n/help — Yordam\n"
        "/quiz — Soha bo'yicha test\n/stats — Statistika\n/history — Suhbat tarixi\n"
        "/clearhistory — Tarixni tozalash\n/lang — Til tanlash (uz/en/ru)\n"
        "/bank [so'z] — Savollar banki\n/manga &lt;nom&gt; — Manga ma'lumoti\n"
        "/recommend &lt;janr&gt; — Janr bo'yicha tavsiya\n/image &lt;tavsif&gt; — Rasm yaratish\n"
        "/admin — Admin bilan bog'lanish\n\n"
        "Erkin matn yozsangiz — har qanday sohada javob beraman. 🤖"
    )
    if C.ADMIN_USERNAME:
        text = text.replace("/admin — Admin bilan bog'lanish",
                            f"/admin — Admin: @{C.ADMIN_USERNAME}")
    await m.answer(text, reply_markup=main_menu_kb(lang))


@router.message(F.text.startswith("/lang"))
async def cmd_lang(m: Message):
    await m.answer("🌐 Tilni tanlang / Choose language / Выберите язык:", reply_markup=_kb([
        [("🇺🇿 O'zbek", "lang:uz"), ("🇬🇧 English", "lang:en"), ("🇷🇺 Русский", "lang:ru")],
    ]))


@router.message(F.text.startswith("/stats"))
async def cmd_stats(m: Message):
    await _send_stats(m)


@router.message(F.text.startswith("/history"))
async def cmd_history(m: Message):
    rows = await db.history(m.from_user.id, 15)
    if not rows:
        await m.answer(C.t(await db.get_lang(m.from_user.id), "no_history"))
        return
    lines = ["📜 <b>Oxirgi suhbatlar</b>\n"]
    for r in rows:
        who = "🤖" if r["role"] == "assistant" else "👤"
        snippet = (r["text"] or "")[:90].replace("\n", " ")
        lines.append(f"{who} {snippet}")
    await m.answer("\n".join(lines))


@router.message(F.text.startswith("/clearhistory"))
async def cmd_clear(m: Message):
    await db.clear_history(m.from_user.id)
    await m.answer(C.t(await db.get_lang(m.from_user.id), "cleared"))


@router.message(F.text.startswith("/admin"))
async def cmd_admin(m: Message):
    uname = f"@{C.ADMIN_USERNAME}" if C.ADMIN_USERNAME else "admin"
    phone = f"\n☎️ {C.ADMIN_PHONE}" if C.ADMIN_PHONE else ""
    await m.answer(f"👤 Admin: {uname}{phone}")


@router.message(F.text.startswith("/bank"))
async def cmd_bank(m: Message):
    word = m.text.replace("/bank", "", 1).strip()
    rows = await db.search_bank(word or None, 15)
    total = await db.bank_count()
    if not rows:
        await m.answer(f"📚 Savollar banki bo'sh (jami: {total}).")
        return
    lines = [f"📚 <b>Savollar banki</b> (jami: {total})\n"]
    for r in rows:
        code = f" · <code>{r['code']}</code>" if r["code"] else ""
        lines.append(f"• [{r['kind']}] {r['title']}{code}")
    await m.answer("\n".join(lines))


# --------------------------------------------------------------------- manga / image
@router.message(F.text.startswith("/manga"))
async def cmd_manga(m: Message):
    name = m.text.replace("/manga", "", 1).strip()
    if not name:
        await m.answer("📖 Foydalanish: <code>/manga naruto</code>")
        return
    await m.answer("📖 Qidiryapman...")
    try:
        ans = await ask_ai(m.from_user.id,
                           f"'{name}' mangasi haqida qisqa ma'lumot ber: muallif, janr, "
                           f"asosiy syujet va nega o'qishga arziydi. O'zbek tilida.")
        await db.add_history(m.from_user.id, "assistant", ans, "manga", "ai")
        await m.answer(ans)
    except Exception as e:
        await m.answer(_fail_text(e))


@router.message(F.text.startswith("/recommend"))
async def cmd_recommend(m: Message):
    genre = m.text.replace("/recommend", "", 1).strip() or "sarguzasht"
    await m.answer("🔎 Tavsiya tayyorlayapman...")
    try:
        ans = await ask_ai(m.from_user.id,
                           f"'{genre}' janridagi 5 ta mashhur manga tavsiya qil. Har biri uchun "
                           f"1-2 gaplik izoh yoz. O'zbek tilida.")
        await db.add_history(m.from_user.id, "assistant", ans, "manga", "ai")
        await m.answer(ans)
    except Exception as e:
        await m.answer(_fail_text(e))


@router.message(F.text.startswith("/image"))
async def cmd_image(m: Message):
    if not C.ENABLE_IMAGE_GEN:
        await m.answer("🎨 Rasm generatsiyasi o'chirilgan.")
        return
    prompt = m.text.replace("/image", "", 1).strip()
    if not prompt:
        await m.answer("🎨 Foydalanish: <code>/image quyosh botishi dengizda</code>")
        return
    status = await m.answer("🎨 Rasm yaratilyapti, biroz kuting...")
    try:
        data = await pool.generate_image(prompt)
        from aiogram.types import BufferedInputFile
        await m.answer_photo(BufferedInputFile(data, filename="image.png"),
                             caption=f"🎨 {prompt[:200]}")
        await db.bump("images_generated")
        with contextlib.suppress(Exception):
            await status.delete()
    except Exception as e:
        log.warning("image failed: %s", e)
        await status.edit_text("⚠️ Rasm yaratilmadi. Model hisobingizda yoqilmagan bo'lishi yoki kvota tugagan.")


# --------------------------------------------------------------------- quiz
@router.message(F.text.startswith("/quiz"))
async def cmd_quiz(m: Message):
    await _quiz_subjects(m)


async def _quiz_subjects(m):
    subjects = await db.quiz_subjects()
    if not subjects:
        await m.answer("🎯 Hozircha savollar yo'q.")
        return
    rows = [[(f"{s} ({c})", f"quiz:{s}")] for s, c in subjects[:10]]
    await m.answer("🎯 Sohani tanlang:", reply_markup=_kb(rows))


async def _quiz_send_question(chat_id, user_id):
    session = await db.quiz_session(user_id)
    if not session:
        await bot.send_message(chat_id, "🎯 Test tugadi. Yangi test: /quiz")
        return
    ids = session["question_ids"]
    pos = session["pos"]
    if pos >= len(ids):
        await db.finish_quiz(user_id, session["subject"], session["score"], len(ids))
        await bot.send_message(chat_id,
                               f"🏁 <b>Test tugadi!</b>\n\nNatija: <b>{session['score']}/{len(ids)}</b>\n"
                               f"Soha: {session['subject']}")
        return
    q = await db.quiz_question(ids[pos])
    if not q:
        await bot.send_message(chat_id, "⚠️ Savol topilmadi.")
        return
    opts = q["options"]
    letters = "ABCD"
    buttons = [[(f"{letters[i]}. {o}", f"ans:{session['pos']}:{i}")] for i, o in enumerate(opts)]
    await bot.send_message(
        chat_id,
        f"❓ <b>{pos + 1}/{len(ids)}</b> · {session['subject']}\n\n{q['question']}",
        reply_markup=_kb(buttons),
    )


# --------------------------------------------------------------------- statistics
async def _send_stats(m):
    blocks = await db.overview()
    counters = await db.counters()
    topics = await db.top_topics(6)
    lines = [
        "📊 <b>Statistika</b>\n",
        f"👥 Foydalanuvchilar: <b>{blocks['users']}</b>",
        f"💬 Xabarlar: <b>{blocks['messages']}</b>",
        f"📚 Savollar banki: <b>{blocks['questions']}</b>",
        f"🎯 Test savollari: <b>{blocks['quiz_questions']}</b>",
        f"📢 Kanallar: <b>{blocks['channels']}</b>",
        f"🗓 Rejalashtirilgan postlar: <b>{blocks['scheduled']}</b>",
    ]
    if counters:
        lines.append("\n⚙️ <b>Hisoblagichlar</b>")
        for k, v in list(counters.items())[:8]:
            lines.append(f"• {k}: {v}")
    if topics:
        lines.append("\n🔥 <b>Mashhur sohalar</b>")
        for t, c in topics:
            lines.append(f"• {t}: {c}")
    await m.answer("\n".join(lines))


# --------------------------------------------------------------------- AI fallback
@router.message(F.text)
async def on_text(m: Message):
    if not m.text:
        return
    text = m.text.strip()
    if text.startswith("/"):
        return

    user_id = m.from_user.id
    await db.upsert_user(user_id, m.from_user.username, m.from_user.first_name)
    lang = await db.get_lang(user_id)

    state, payload = await db.get_state(user_id)
    if state:
        handled = await _handle_state(m, state, payload)
        if handled:
            return

    if C.ENABLE_INSTANT_REPLIES and len(text) <= C.INSTANT_MAX_LEN:
        reply = await db.instant_reply(text.lower())
        if reply:
            await db.add_history(user_id, "user", text, "instant", "instant")
            await db.add_history(user_id, "assistant", reply, "instant", "instant")
            await db.bump("instant_hits")
            await m.answer(reply)
            return

    subject = detect_subject(text)
    await db.add_history(user_id, "user", text, subject, "ai")
    await db.bump("ai_requests")
    try:
        await bot.send_chat_action(m.chat.id, "typing")
    except Exception:
        pass
    try:
        ans = await ask_ai(user_id, text, lang)
        await db.add_history(user_id, "assistant", ans, subject, "ai")
        for chunk in _split(ans, 3800):
            await m.answer(chunk)
    except Exception as e:
        log.warning("ai failed: %s", e)
        await m.answer(_fail_text(e, lang))


def _split(text, size):
    return [text[i:i + size] for i in range(0, max(len(text), 1), size)] or [text]


# --------------------------------------------------------------------- callbacks
@router.callback_query(F.data.startswith("menu:"))
async def on_menu(cq: CallbackQuery):
    action = cq.data.split(":", 1)[1]
    lang = await db.get_lang(cq.from_user.id)
    if action == "home":
        await cq.message.edit_text(C.t(lang, "main_menu"), reply_markup=main_menu_kb(lang))
    elif action == "quiz":
        subjects = await db.quiz_subjects()
        rows = [[(f"{s} ({c})", f"quiz:{s}")] for s, c in subjects[:10]] or [[("-", "noop")]]
        await cq.message.edit_text("🎯 Sohani tanlang:", reply_markup=_kb(rows))
    elif action == "stats":
        await cq.answer("Yuborilyapti...")
        await _send_stats(cq.message)
    elif action == "history":
        rows_ = await db.history(cq.from_user.id, 12)
        if not rows_:
            await cq.message.edit_text(C.t(lang, "no_history"), reply_markup=main_menu_kb(lang))
        else:
            body = "\n".join(
                f"{'🤖' if r['role'] == 'assistant' else '👤'} {(r['text'] or '')[:80]}"
                for r in rows_)
            await cq.message.edit_text(f"📜 <b>Tarix</b>\n\n{body}", reply_markup=main_menu_kb(lang))
    elif action == "lang":
        await cq.message.edit_text("🌐 Tilni tanlang:", reply_markup=_kb([
            [("🇺🇿 O'zbek", "lang:uz"), ("🇬🇧 English", "lang:en"), ("🇷🇺 Русский", "lang:ru")]]))
    elif action == "tools":
        await cq.message.edit_text("🧰 <b>Vositalar</b>", reply_markup=tools_kb())
    elif action == "help":
        await cq.answer()
        await _send_help(cq.message)
    await cq.answer()


async def _send_help(message):
    text = (
        "ℹ️ <b>Yordam</b>\n\n"
        "Erkin matn yozing — har qanday sohada javob beraman.\n\n"
        "🎯 <b>Test</b> — /quiz\n📊 <b>Statistika</b> — /stats\n"
        "📜 <b>Tarix</b> — /history\n🧰 <b>Vositalar</b> — menyudan\n"
    )
    await message.edit_text(text, reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cq: CallbackQuery):
    lang = cq.data.split(":", 1)[1]
    await db.set_lang(cq.from_user.id, lang)
    await cq.message.edit_text(C.t(lang, "main_menu"), reply_markup=main_menu_kb(lang))
    await cq.answer("✅")


@router.callback_query(F.data.startswith("quiz:"))
async def on_quiz_subject(cq: CallbackQuery):
    subject = cq.data.split(":", 1)[1]
    ids = await db.start_quiz(cq.from_user.id, subject)
    if not ids:
        await cq.answer("Savollar yo'q", show_alert=True)
        return
    await cq.message.edit_text(f"🎯 <b>{subject}</b> — {len(ids)} savol. Boshlaymiz!")
    await cq.answer()
    await _quiz_send_question(cq.message.chat.id, cq.from_user.id)


@router.callback_query(F.data.startswith("ans:"))
async def on_quiz_answer(cq: CallbackQuery):
    parts = cq.data.split(":")
    if len(parts) != 3:
        await cq.answer()
        return
    chosen = int(parts[2])
    session = await db.quiz_session(cq.from_user.id)
    if not session or session["pos"] != int(parts[1]):
        await cq.answer("Eskirgan savol", show_alert=True)
        return
    q = await db.quiz_question(session["question_ids"][session["pos"]])
    letters = "ABCD"
    correct = chosen == q["answer"]
    if correct:
        await cq.answer("✅ To'g'ri!")
    else:
        await cq.answer(f"❌ Xato. To'g'ri javob: {letters[q['answer']]}", show_alert=True)
    res = await db.advance_quiz(cq.from_user.id, correct)
    note = "✅" if correct else f"❌ To'g'ri: <b>{letters[q['answer']]}</b>"
    if q.get("explanation"):
        note += f"\n💡 {q['explanation']}"
    with contextlib.suppress(Exception):
        await cq.message.edit_reply_markup(reply_markup=_kb(
            [[(f"{'🟢' if i == q['answer'] else '⚪️'} {letters[i]}. {o}", "noop")]
             for i, o in enumerate(q["options"])]))
    await bot.send_message(cq.message.chat.id, note)
    if res and res["pos"] >= res["total"]:
        await db.finish_quiz(cq.from_user.id, res["subject"], res["score"], res["total"])
        await bot.send_message(cq.message.chat.id,
                               f"🏁 <b>Test tugadi!</b>\n\nNatija: <b>{res['score']}/{res['total']}</b>\n"
                               f"Soha: {res['subject']}")
    else:
        await _quiz_send_question(cq.message.chat.id, cq.from_user.id)


# --------------------------------------------------------------------- tools
@router.callback_query(F.data.startswith("tools:"))
async def on_tools(cq: CallbackQuery):
    action = cq.data.split(":", 1)[1]
    if action == "addq":
        is_admin = await db.is_admin(cq.from_user.id)
        status = await db.request_status(cq.from_user.id)
        if is_admin:
            await _ask_question_kind(cq)
        elif status == "approved":
            await _ask_question_kind(cq)
        elif status == "pending":
            await cq.answer("⏳ So'rovingiz adminda ko'rilmoqda.", show_alert=True)
        else:
            await db.addq_request(cq.from_user.id, cq.from_user.username or "-",
                                  cq.from_user.first_name or "-")
            await _notify_admin_request(cq)
            await cq.answer("📨 So'rov adminga yuborildi.", show_alert=True)
    elif action == "channel":
        await cq.message.edit_text("📢 <b>Kanal boshqaruvi</b>", reply_markup=channel_kb())
        await cq.answer()
        return
    await cq.answer()


async def _notify_admin_request(cq):
    text = (f"🔔 <b>Yangi ruxsat so'rovi</b>\n\n"
            f"👤 {cq.from_user.first_name or '-'} (@{cq.from_user.username or '-'})\n"
            f"🆔 <code>{cq.from_user.id}</code>")
    kb = _kb([[("✅ Tasdiqlash", f"addq:ok:{cq.from_user.id}"),
               ("❌ Rad etish", f"addq:no:{cq.from_user.id}")]])
    for aid in C.admin_ids():
        with contextlib.suppress(Exception):
            await bot.send_message(aid, text, reply_markup=kb)


@router.callback_query(F.data.startswith("addq:"))
async def on_addq_decision(cq: CallbackQuery):
    if not await db.is_admin(cq.from_user.id):
        await cq.answer("Faqat admin", show_alert=True)
        return
    _, decision, uid = cq.data.split(":")
    uid = int(uid)
    if decision == "ok":
        await db.grant_admin(uid, granted_by=cq.from_user.id)
        await db.set_request_status(uid, "approved")
        with contextlib.suppress(Exception):
            await bot.send_message(uid, "✅ Sizga savol qo'shish huquqi berildi!")
        await cq.message.edit_text(cq.message.text + "\n\n✅ <b>Tasdiqlandi</b>")
    else:
        await db.set_request_status(uid, "rejected")
        with contextlib.suppress(Exception):
            await bot.send_message(uid, "❌ So'rovingiz rad etildi.")
        await cq.message.edit_text(cq.message.text + "\n\n❌ <b>Rad etildi</b>")
    await cq.answer()


async def _ask_question_kind(cq):
    await db.set_state(cq.from_user.id, "addq_kind")
    await cq.message.edit_text("➕ <b>Savol qo'shish</b>\n\nTurini tanlang:", reply_markup=_kb([
        [("🎤 IELTS Speaking", "addqk:speaking"), ("✍️ IELTS Writing", "addqk:writing")],
        [("➗ Matematika", "addqk:math"), ("⚛️ Fizika", "addqk:physics")],
        [("⬅️ Orqaga", "menu:tools")],
    ]))
    await cq.answer()


@router.callback_query(F.data.startswith("addqk:"))
async def on_addq_kind(cq: CallbackQuery):
    kind = cq.data.split(":", 1)[1]
    await db.set_state(cq.from_user.id, "addq_body", {"kind": kind})
    await cq.message.edit_text(
        "✍️ Savol matnini yuboring.\n\n"
        "Variantli savol uchun format:\n<code>Savol? | variant1 | variant2 | variant3 | variant4 | 1</code>\n"
        "(oxirgi raqam — to'g'ri javob indeksi, 0 dan boshlab)")
    await cq.answer()


@router.callback_query(F.data.startswith("chan:"))
async def on_channel(cq: CallbackQuery):
    action = cq.data.split(":", 1)[1]
    uid = cq.from_user.id
    if action == "add":
        await db.set_state(uid, "chan_add")
        await cq.message.edit_text("📢 Kanalning <code>@username</code> yoki ID sini yuboring.\n"
                                   "Bot kanalda admin bo'lishi kerak.")
    elif action == "list":
        chans = await db.channels(uid)
        if not chans:
            await cq.message.edit_text("📋 Hozircha kanal ulanmagan.", reply_markup=channel_kb())
        else:
            lines = ["📋 <b>Kanallarim</b>\n"]
            for c in chans:
                lines.append(f"• {c['title']} — <code>{c['channel_id']}</code>")
            await cq.message.edit_text("\n".join(lines), reply_markup=channel_kb())
    elif action == "post":
        chans = await db.channels(uid)
        if not chans:
            await cq.answer("Avval kanal ulang", show_alert=True)
            await cq.answer()
            return
        await db.set_state(uid, "chan_post")
        rows = [[(c["title"], f"pickchan:{c['channel_id']}")] for c in chans]
        await cq.message.edit_text("✍️ Qaysi kanalga post joylaymiz?", reply_markup=_kb(rows))
    elif action == "schedule":
        chans = await db.channels(uid)
        if not chans:
            await cq.answer("Avval kanal ulang", show_alert=True)
            await cq.answer()
            return
        await db.set_state(uid, "chan_schedule")
        rows = [[(c["title"], f"schedchan:{c['channel_id']}")] for c in chans]
        await cq.message.edit_text("🗓 Qaysi kanalga rejalashtiramiz?", reply_markup=_kb(rows))
    await cq.answer()


@router.callback_query(F.data.startswith(("pickchan:", "schedchan:")))
async def on_pick_channel(cq: CallbackQuery):
    kind, channel_id = cq.data.split(":", 1)
    state = "chan_post_text" if kind == "pickchan" else "chan_sched_text"
    await db.set_state(cq.from_user.id, state, {"channel_id": channel_id})
    if kind == "pickchan":
        await cq.message.edit_text("✍️ Post matnini yuboring. Rasm uchun rasm yuboring.")
    else:
        await cq.message.edit_text(
            "🗓 Formatda yuboring:\n<code>Matn | vaqt</code>\n\n"
            "Vaqt misollari: <code>+2h</code>, <code>09:30</code>, <code>2026-10-16 09:30</code>\n"
            "Takrorlash uchun: <code>Matn | +1d | 1440</code> (har 1440 daqiqa)")
    await cq.answer()


# --------------------------------------------------------------------- state flows
async def _handle_state(m: Message, state, payload):
    user_id = m.from_user.id
    if state == "addq_body":
        kind = (payload or {}).get("kind", "speaking")
        raw = m.text or ""
        parts = [p.strip() for p in raw.split("|")]
        title = parts[0][:120] if parts else raw[:120]
        if len(parts) >= 6:
            question, options, answer = parts[0], parts[1:5], int(parts[5]) if parts[5].isdigit() else 0
            await db.add_question(kind, title, question,
                                  meta={"options": options, "answer": answer}, added_by=user_id)
        else:
            await db.add_question(kind, title, raw, added_by=user_id)
        await db.clear_state(user_id)
        await m.answer(f"✅ Savol qo'shildi: <b>{title}</b>\n/bank bilan ko'rishingiz mumkin.")
        return True

    if state == "chan_add":
        target = (m.text or "").strip()
        try:
            chat = await bot.get_chat(target)
            member = await bot.get_chat_member(chat.id, bot.id)
            if member.status not in ("administrator", "creator"):
                await m.answer("⚠️ Bot bu kanalda admin emas. Avval admin qiling.")
                return True
            await db.add_channel(user_id, chat.id, chat.title or target,
                                 chat.username or None)
            await db.clear_state(user_id)
            await m.answer(f"✅ Kanal ulandi: <b>{chat.title}</b>", reply_markup=channel_kb())
        except Exception as e:
            await m.answer(f"⚠️ Kanal topilmadi yoki ruxsat yo'q: <code>{str(e)[:120]}</code>")
        return True

    if state == "chan_post_text":
        channel_id = (payload or {}).get("channel_id")
        try:
            if m.photo:
                cap = m.caption or ""
                await bot.send_photo(channel_id, m.photo[-1].file_id, caption=cap)
            else:
                await bot.send_message(channel_id, m.html_text or m.text)
            await db.clear_state(user_id)
            await db.bump("channel_posts")
            await m.answer("✅ Post joylandi.", reply_markup=channel_kb())
        except Exception as e:
            await m.answer(f"⚠️ Post yuborilmadi: <code>{str(e)[:120]}</code>")
        return True

    if state == "chan_sched_text":
        channel_id = (payload or {}).get("channel_id")
        text, iso, repeat = parse_schedule(m.text or "")
        await db.add_post(channel_id, text, iso, repeat, created_by=user_id)
        await db.clear_state(user_id)
        when = iso.replace("T", " ").replace("Z", " UTC")
        extra = f" (har {repeat} daqiqada)" if repeat else ""
        await m.answer(f"🗓 Rejalashtirildi: <b>{when}</b>{extra}", reply_markup=channel_kb())
        return True

    await db.clear_state(user_id)
    return False


# --------------------------------------------------------------------- background
async def post_loop():
    """Send scheduled channel posts when due."""
    while True:
        try:
            now = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            for p in await db.due_posts(now):
                try:
                    if p.get("media"):
                        await bot.send_photo(p["channel_id"], p["media"], caption=p["text"])
                    else:
                        await bot.send_message(p["channel_id"], p["text"])
                    await db.mark_post_sent(p["id"], p["repeat_min"] or 0)
                    await db.bump("scheduled_sent")
                    log.info("scheduled post %s sent", p["id"])
                except Exception as e:
                    log.warning("post %s failed: %s", p["id"], e)
        except Exception as e:
            log.warning("post_loop error: %s", e)
        await asyncio.sleep(30)


async def self_ping_loop():
    """Keep the free Render instance awake from the inside."""
    base = C.RENDER_EXTERNAL_URL or C.WEBHOOK_BASE_URL
    if not base:
        return
    url = base.rstrip("/") + "/health"
    import aiohttp
    while True:
        await asyncio.sleep(max(60, C.SELF_PING_INTERVAL))
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    log.info("self-ping %s -> %s", url, r.status)
        except Exception as e:
            log.warning("self-ping failed: %s", e)


# --------------------------------------------------------------------- runtime
def build_state_provider():
    def provider():
        st = {"bot": "@" + (bot.username or "") if bot and bot.username else None}
        st.update(pool.status())
        st.update(watchdog.status())
        st.update(backup.status())
        try:
            st["requests_total"] = pool.requests_total
        except Exception:
            pass
        st.pop("keys_detail", None)
        return st
    return provider


async def on_startup():
    global APP_STARTED, bot
    await db.connect()
    if backup.enabled and C.RESTORE_ON_START and not os.path.exists(C.DB_PATH):
        with contextlib.suppress(Exception):
            await backup.restore_on_start()
    me = await bot.get_me()
    log.info("Bot tayyor: @%s", me.username)
    await bot.set_my_commands([
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="menu", description="Asosiy menyu"),
        BotCommand(command="quiz", description="Test o'tash"),
        BotCommand(command="stats", description="Statistika"),
        BotCommand(command="history", description="Suhbat tarixi"),
        BotCommand(command="lang", description="Tilni almashtirish"),
        BotCommand(command="image", description="Rasm yaratish"),
        BotCommand(command="help", description="Yordam"),
    ])
    watchdog.start()
    backup.start()
    asyncio.create_task(post_loop())
    if C.SELF_PING_ENABLED:
        asyncio.create_task(self_ping_loop())
    APP_STARTED = True


async def run_webhook():
    """Render web-service mode: health endpoints + Telegram webhook on one port."""
    base = (C.WEBHOOK_BASE_URL or C.RENDER_EXTERNAL_URL or "").rstrip("/")
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not base:
        log.warning("WEBHOOK_BASE_URL berilmagan - polling rejimiga o'tamiz")
        return await run_polling()
    if not secret:
        secret = "aimgr" + (C.BOT_TOKEN.split(":")[0][-6:] if C.BOT_TOKEN else "local")
        log.warning("WEBHOOK_SECRET berilmagan - generatsiya qilindi")

    webhook_url = f"{base}/webhook/{secret}"
    port = C.PORT or 10000
    health = HealthServer(port, build_state_provider())
    app = health.build()

    async def webhook_handler(request):
        if request.match_info.get("secret") != secret:
            return web.Response(status=403, text="forbidden")
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="bad json")
        asyncio.create_task(_feed(data))
        return web.Response(text="ok")

    app.router.add_post("/webhook/{secret}", webhook_handler)

    # ONE runner owns the port: it serves /health, /ping, /status AND the webhook.
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("HTTP server listening on 0.0.0.0:%s (/health, /ping, /status, /webhook)", port)

    try:
        await bot.set_webhook(webhook_url, secret_token=secret,
                              allowed_updates=dp.resolve_used_update_types(),
                              drop_pending_updates=True)
        log.info("Webhook registered: %s", f"{base}/webhook/***")
        health.ready = True
        while True:
            await asyncio.sleep(3600)
    except TelegramBadRequest as e:
        # Telegram requires an HTTPS URL. If we cannot register a webhook we still
        # serve the health endpoints and fall back to long polling in-process.
        log.warning("Webhook o'rnatilmadi (%s) - polling'ga o'tamiz", e)
        health.ready = True
        try:
            await dp.start_polling(bot, handle_signals=False)
        finally:
            await runner.cleanup()

async def _feed(data):
    try:
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        log.warning("feed_update failed: %s", e)


async def run_polling():
    await bot.delete_webhook(drop_pending_updates=True)
    if C.PORT:
        health = HealthServer(C.PORT, build_state_provider())
        await health.start()
        health.ready = True
    while True:
        try:
            await dp.start_polling(bot, handle_signals=False)
        except TelegramConflictError:
            log.warning("409 Conflict - boshqa instance ishlayapti, 15s kutamiz")
            await asyncio.sleep(15)
        except Exception as e:
            log.error("polling crashed: %s - 10s kutamiz", e)
            await asyncio.sleep(10)


def main():
    global bot, dp
    if not C.BOT_TOKEN:
        log.error("BOT_TOKEN bo'sh - .env faylini yoki Render env ni to'ldiring")
        sys.exit(2)
    bot = Bot(C.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    async def bootstrap():
        await on_startup()

    async def run():
        await bootstrap()
        if os.getenv("WEBHOOK_MODE", "").lower() == "polling":
            await run_polling()
        else:
            await run_webhook()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("to'xtatildi")
    except Exception:
        log.exception("FATAL: bot ishga tushmadi")
        sys.exit(1)


if __name__ == "__main__":
    main()
