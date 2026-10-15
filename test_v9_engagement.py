"""v9 sinovlari: kanal statistikasiga reaksiyalar va ko'rishlar qo'shilishi.

Ishga tushirish:  python3 test_v9_engagement.py

Tekshiriladi:
  1. _parse_short_count — '1.2K', '177', '1 020', '2.5M'
  2. parse_channel_preview — t.me/s HTML'idan ko'rish + emoji reaksiyalar
  3. DB: upsert_post_engagement / list_post_engagement / count
  4. _engagement_totals — jami, o'rtacha, emoji taqsimoti, eng ko'p reaksiya
  5. engagement_score / score_label — rivojlanish darajasi
  6. _fmt_emoji / _trend_str
  7. _build_channels_stats — reaksiyalar bo'limi matnda chiqadi
  8. on_message_reaction_count — Bot API hodisasi bazaga yoziladi
  9. Gate message_reaction_count hodisasini o'tkazadi
 10. engagement_loop mavjud va main() da ro'yxatdan o'tgan
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from types import SimpleNamespace

os.environ["DB_PATH"] = "v9_engagement_test.db"
os.environ["LOG_DIR"] = "logs"
os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["GEMINI_API_KEYS"] = "test-key-1,test-key-2"
os.environ["ADMIN_USERNAME"] = "Husan_Dilmurodov"
os.environ["ADMIN_ID"] = "9001"

from aiogram import Bot  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery, Chat, Message, MessageReactionCountUpdated, ReactionCount,
    ReactionTypeEmoji, Update, User,
)

import bot as B  # noqa: E402

# --------------------------------------------------------------------------- #
# Bot API'ga so'rov yubormaslik uchun monkey-patch
# --------------------------------------------------------------------------- #
SENT: list[str] = []
CALLS: list[tuple] = []


async def fake_send_message(chat_id, text, **kw):
    SENT.append(text)
    CALLS.append((text, kw))
    return SimpleNamespace(message_id=1)


async def fake_edit_message_text(*a, **kw):
    text = kw.get("text")
    if text is None and len(a) >= 3:
        text = a[2]
    if text is not None:
        SENT.append(text)
        CALLS.append((text, kw))
    return SimpleNamespace(message_id=1)


async def fake_noop(*a, **k):
    return None


async def fake_get_chat_member_count(chat_id):
    return 203


async def fake_get_chat(chat_id):
    return SimpleNamespace(id=chat_id, title="Test Kanal", username="matmilliysertifikat")


B.bot.send_message = fake_send_message
B.bot.send_chat_action = fake_noop
B.bot.send_photo = fake_noop
B.bot.edit_message_text = fake_edit_message_text
B.bot.get_chat_member_count = fake_get_chat_member_count
B.bot.get_chat = fake_get_chat


async def fake_bot_call(self, method, request_timeout=None):
    text = getattr(method, "text", None)
    if text is not None:
        SENT.append(text)
        CALLS.append((text, {"reply_markup": getattr(method, "reply_markup", None)}))
    return SimpleNamespace(message_id=1)


Bot.__call__ = fake_bot_call


async def fake_collect_engagement(channel_id):
    """Sinovda tarmoqqa chiqmaslik uchun faollik yig'ishni o'chiradi."""
    return {"ok": True, "posts": [], "error": None}


B.collect_channel_engagement = fake_collect_engagement

PASS = 0
FAIL = 0
ADMIN_UID = 9001
ADMIN_UNAME = "Husan_Dilmurodov"
CHAN = -1009999001


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {extra}" if extra else ""))


# Haqiqiy t.me/s tuzilishiga mos namuna (matmilliysertifikat'dan olingan)
SAMPLE_HTML = """
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message" data-post="matmilliysertifikat/124">
  <div class="tgme_widget_message_text">Post matni</div>
  <div class="tgme_widget_message_reactions js-message_reactions">
   <span class="tgme_reaction"><i class="emoji" style="background-image:url('//telegram.org/img/emoji/40/F09F918D.png')"><b>👍</b></i>5</span>
   <span class="tgme_reaction"><i class="emoji" style="background-image:url('//telegram.org/img/emoji/40/E29DA4.png')"><b>❤</b></i>4</span>
   <span class="tgme_reaction"><i class="emoji" style="background-image:url('//telegram.org/img/emoji/40/F09F918F.png')"><b>👏</b></i>4</span>
   <span class="tgme_reaction"><i class="emoji" style="background-image:url('//telegram.org/img/emoji/40/F09FA494.png')"><b>🤔</b></i>1</span>
  </div>
  <div class="tgme_widget_message_footer">
   <span class="tgme_widget_message_views">1.2K</span>
   <span class="tgme_widget_message_meta"><a class="tgme_widget_message_date" href="https://t.me/matmilliysertifikat/124"><time datetime="2026-04-01T11:53:35+00:00" class="time">11:53</time></a></span>
  </div>
 </div>
</div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message" data-post="matmilliysertifikat/125">
  <div class="tgme_widget_message_text">Boshqa post</div>
  <div class="tgme_widget_message_reactions js-message_reactions">
   <span class="tgme_reaction"><i class="emoji"><b>👍</b></i>2</span>
  </div>
  <div class="tgme_widget_message_footer">
   <span class="tgme_widget_message_views">198</span>
   <span class="tgme_widget_message_meta"><a class="tgme_widget_message_date" href="https://t.me/matmilliysertifikat/125"><time datetime="2026-04-02T09:00:00+00:00" class="time">09:00</time></a></span>
  </div>
 </div>
</div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message" data-post="matmilliysertifikat/126">
  <div class="tgme_widget_message_text">Reaksiyasiz post</div>
  <div class="tgme_widget_message_footer">
   <span class="tgme_widget_message_views">1 020</span>
   <span class="tgme_widget_message_meta"><a class="tgme_widget_message_date" href="https://t.me/matmilliysertifikat/126"><time datetime="2026-04-03T09:00:00+00:00" class="time">09:00</time></a></span>
  </div>
 </div>
</div>
"""


def make_msg(text: str, uid: int, uname: str) -> Message:
    return Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, is_bot=False, first_name="Test", username=uname),
        text=text,
    )


async def feed_cb(data: str, uid: int = ADMIN_UID, uname: str = ADMIN_UNAME) -> list[str]:
    SENT.clear()
    CALLS.clear()
    msg = make_msg("", uid, uname)
    cb = CallbackQuery(id="1", from_user=User(id=uid, is_bot=False, first_name="Test", username=uname),
                       chat_instance="ci", data=data, message=msg)
    await B.dp.feed_update(B.bot, Update(update_id=2, callback_query=cb))
    return list(SENT)


async def main() -> None:
    print("=" * 70)
    print("AI Manager Bot v9 — kanal reaksiyalari va ko'rishlar sinovlari")
    print("=" * 70)

    for f in ("v9_engagement_test.db", "v9_engagement_test.db-wal", "v9_engagement_test.db-shm"):
        if os.path.exists(f):
            os.remove(f)
    await B.db.connect()
    await B.load_data()

    # ------------------------------------------------------------------ #
    print("\n[1] _parse_short_count")
    check("'177' -> 177", B._parse_short_count("177") == 177)
    check("'1.2K' -> 1200", B._parse_short_count("1.2K") == 1200)
    check("'2.5M' -> 2500000", B._parse_short_count("2.5M") == 2500000)
    check("'1 020' -> 1020", B._parse_short_count("1 020") == 1020)
    check("'1\\u202f020' -> 1020", B._parse_short_count("1\u202f020") == 1020)
    check("bo'sh -> None", B._parse_short_count("") is None)
    check("None -> None", B._parse_short_count(None) is None)

    # ------------------------------------------------------------------ #
    print("\n[2] parse_channel_preview (haqiqiy t.me/s tuzilishi)")
    posts = B.parse_channel_preview(SAMPLE_HTML)
    check("3 ta post topildi", len(posts) == 3, str(len(posts)))
    p124 = next((p for p in posts if p["message_id"] == 124), None)
    check("post 124 topildi", p124 is not None)
    check("post 124 ko'rishlar = 1200", p124 and p124["views"] == 1200, str(p124 and p124["views"]))
    check("post 124 jami reaksiya = 14", p124 and p124["total"] == 14, str(p124 and p124["total"]))
    check("post 124 emoji taqsimoti to'g'ri",
          p124 and p124["reactions"] == {"👍": 5, "❤": 4, "👏": 4, "🤔": 1},
          str(p124 and p124["reactions"]))
    check("post 124 sanasi olindi", p124 and p124["date"] == "2026-04-01T11:53:35+00:00")
    p126 = next((p for p in posts if p["message_id"] == 126), None)
    check("reaksiyasiz post: total=0", p126 and p126["total"] == 0)
    check("reaksiyasiz post: views=1020", p126 and p126["views"] == 1020, str(p126 and p126["views"]))

    # ------------------------------------------------------------------ #
    print("\n[3] DB: upsert / list / count")
    for p in posts:
        await B.db.upsert_post_engagement(
            CHAN, p["message_id"], views=p["views"],
            reactions_json=B.json.dumps(p["reactions"], ensure_ascii=False),
            reactions_total=p["total"], reactions_emojis=len(p["reactions"]),
            source="preview",
        )
    n = await B.db.count_post_engagement(CHAN)
    check("3 ta yozuv saqlandi", n == 3, str(n))
    rows = await B.db.list_post_engagement(CHAN)
    check("eng ko'p reaksiya birinchi (post 124)",
          rows and rows[0]["message_id"] == 124, str(rows and rows[0]["message_id"]))
    # upsert yangilash: faqat views berilsa reaksiyalar saqlanadi
    await B.db.upsert_post_engagement(CHAN, 124, views=1500, source="preview")
    r124 = next(r for r in await B.db.list_post_engagement(CHAN) if r["message_id"] == 124)
    check("upsert: views yangilandi (1500)", r124["views"] == 1500, str(r124["views"]))
    check("upsert: reaksiyalar saqlanib qoldi (14)", r124["reactions_total"] == 14, str(r124["reactions_total"]))

    # ------------------------------------------------------------------ #
    print("\n[4] _engagement_totals")
    rows = await B.db.list_post_engagement(CHAN)
    t = B._engagement_totals(rows)
    check("postlar soni = 3", t["posts"] == 3, str(t["posts"]))
    check("jami reaksiya = 16", t["react_total"] == 16, str(t["react_total"]))
    check("o'rtacha reaksiya/post ≈ 5.33", abs(t["react_avg"] - 16 / 3) < 0.01, f"{t['react_avg']:.2f}")
    check("emoji taqsimoti: 👍 = 7", t["emoji"].get("👍") == 7, str(t["emoji"]))
    check("eng ko'p emoji = 👍", t["emoji_top"] == "👍", t["emoji_top"])
    check("o'rtacha ko'rish = (1500+198+1020)/3", abs(t["views_avg"] - (1500 + 198 + 1020) / 3) < 0.5, f"{t['views_avg']:.0f}")
    check("eng ko'p reaksiya olgan post = 124", t["top_post"] and t["top_post"]["message_id"] == 124)

    # ------------------------------------------------------------------ #
    print("\n[5] engagement_score / score_label")
    s = B.engagement_score(t, 203)
    check("ball 0-100 oralig'ida", 0 <= s <= 100, str(s))
    check("ball > 0 (faollik bor)", s > 0, str(s))
    check("score_label ishlaydi", B.score_label(s) in ("past", "o'rtacha", "yuqori", "juda yuqori"))
    check("bo'sh ma'lumot -> past ball", B.engagement_score(B._engagement_totals([]), 0) == 0.0)

    # ------------------------------------------------------------------ #
    print("\n[6] _fmt_emoji / _trend_str")
    check("_fmt_emoji taqsimotni chiqaradi", "👍 7" in B._fmt_emoji(t["emoji"]), B._fmt_emoji(t["emoji"]))
    check("_fmt_emoji bo'sh -> 'yo'q'", B._fmt_emoji({}) == "yo'q")
    check("_trend_str o'sish", "↑" in B._trend_str(10, 5))
    check("_trend_str pasayish", "↓" in B._trend_str(3, 5))
    check("_trend_str o'zgarmagan", "o'zgarmagan" in B._trend_str(5, 5))
    check("_trend_str None -> —", B._trend_str(5, None) == "—")

    # ------------------------------------------------------------------ #
    print("\n[7] _build_channels_stats — reaksiyalar bo'limi")
    await B.db.add_channel(ADMIN_UID, CHAN, "Test Kanal", "matmilliysertifikat")
    lines = await B._build_channels_stats(await B.db.list_channels())
    joined = "\n".join(lines)
    check("'Reaksiyalar' bo'limi bor", "Reaksiyalar" in joined)
    check("jami reaksiya ko'rsatildi (16)", "16" in joined)
    check("emoji taqsimoti ko'rsatildi (👍)", "👍" in joined)
    check("eng ko'p reaksiya olgan post ko'rsatildi", "Eng ko'p reaksiya olgan" in joined)
    check("o'rtacha ko'rish/post ko'rsatildi", "O'rtacha ko'rish/post" in joined)
    check("rivojlanish darajasi ko'rsatildi", "Rivojlanish darajasi" in joined)
    check("a'zolar soni saqlanib qoldi (203)", "203" in joined)
    check("o'sish bo'limi saqlanib qoldi", "O'sish" in joined)

    # ------------------------------------------------------------------ #
    print("\n[8] on_message_reaction_count — Bot API hodisasi")
    ev = MessageReactionCountUpdated(
        chat=Chat(id=CHAN, type="channel", title="Test Kanal"),
        message_id=999,
        date=datetime.now(),
        reactions=[
            ReactionCount(type=ReactionTypeEmoji(type="emoji", emoji="👍"), total_count=12),
            ReactionCount(type=ReactionTypeEmoji(type="emoji", emoji="❤"), total_count=5),
        ],
    )
    await B.on_message_reaction_count(ev)
    r999 = next((r for r in await B.db.list_post_engagement(CHAN) if r["message_id"] == 999), None)
    check("hodisa bazaga yozildi", r999 is not None)
    check("jami reaksiya = 17", r999 and r999["reactions_total"] == 17, str(r999 and r999["reactions_total"]))
    check("emoji taqsimoti saqlandi", r999 and "👍" in (r999["reactions"] or ""), str(r999 and r999["reactions"]))
    check("manba 'update'", r999 and r999["source"] == "update", str(r999 and r999["source"]))

    # ------------------------------------------------------------------ #
    print("\n[9] Gate message_reaction_count hodisasini o'tkazadi")
    gate_ev = SimpleNamespace(
        message_reaction_count=ev, message=None, callback_query=None,
        my_chat_member=None, chat_member=None,
    )
    passed = {"v": False}

    async def _h(e, d):
        passed["v"] = True

    await B.sub_gate_outer_middleware(_h, gate_ev, {})
    check("gate reaksiya hodisasini o'tkazdi", passed["v"] is True)

    # ------------------------------------------------------------------ #
    print("\n[10] engagement_loop va ro'yxatdan o'tish")
    check("engagement_loop mavjud", hasattr(B, "engagement_loop"))
    check("on_message_reaction_count handler mavjud", hasattr(B, "on_message_reaction_count"))
    check("on_message_reaction handler mavjud", hasattr(B, "on_message_reaction"))
    check("config.ENGAGEMENT_CHECK_INTERVAL mavjud", hasattr(B.config, "ENGAGEMENT_CHECK_INTERVAL"))
    src = open("bot.py", encoding="utf-8").read()
    check("engagement_loop main() da ro'yxatdan o'tgan",
          'create_task(engagement_loop()' in src)
    check("getChatHistory ishlatilmaydi (faqat izohda)",
          src.count("getChatHistory") == 1)

    await B.db.close()
    for f in ("v9_engagement_test.db", "v9_engagement_test.db-wal", "v9_engagement_test.db-shm"):
        if os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 70)
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
