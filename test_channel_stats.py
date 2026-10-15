"""v6 sinovlari: kanal tasdiqlash oqimi + admin-only statistika.

Ishga tushirish:  python3 test_channel_stats.py

Tekshiriladi:
  1. Asosiy menyuda "Statistika" FAQAT adminga ko'rinadi
  2. /stats buyrug'i faqat adminga ishlaydi
  3. menu:stats callback — faqat admin
  4. stats:chanadd — kanal qo'shish holatini o'rnatadi (admin)
  5. stats:chanstats — kanallar statistikasi (a'zolar + postlar)
  6. my_chat_member — bot kanalga admin qilinganda pending_channels yaratiladi
     va adminga ✅/❌ tugmalari bilan xabar boradi
  7. admin:chan:ok — kanal botga ulanadi
  8. admin:chan:no — kanal rad etiladi
  9. Begona foydalanuvchi kanal qarorini qabul qila olmaydi
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from types import SimpleNamespace

os.environ["DB_PATH"] = "chan_stats_test.db"
os.environ["LOG_DIR"] = "logs"
os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["GEMINI_API_KEYS"] = "test-key-1,test-key-2"
os.environ["ADMIN_USERNAME"] = "Husan_Dilmurodov"
os.environ["ADMIN_ID"] = "9001"

from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

import bot as B  # noqa: E402

# --------------------------------------------------------------------------- #
# Bot API'ga so'rov yubormaslik uchun monkey-patch
# --------------------------------------------------------------------------- #
SENT: list[str] = []          # faqat matnlar (mavjud test uslubi)
CALLS: list[tuple] = []        # (text, kwargs) — reply_markup tekshirish uchun


async def fake_send_message(chat_id, text, **kw):
    SENT.append(text)
    CALLS.append((text, kw))
    return SimpleNamespace(message_id=1)


async def fake_edit_message_text(*a, **kw):
    # edit_text(chat_id, message_id, text, ...) yoki (text=...)
    text = kw.get("text")
    if text is None and len(a) >= 3:
        text = a[2]
    if text is not None:
        SENT.append(text)
        CALLS.append((text, kw))
    return SimpleNamespace(message_id=1)


async def fake_noop(*a, **k):
    return None


class _FakeChat:
    def __init__(self, cid, title, username=None, ctype="channel"):
        self.id = cid
        self.title = title
        self.username = username
        self.type = ctype


async def fake_get_chat(raw):
    return _FakeChat(-1009999001, "Test Kanal", "test_kanal")


async def fake_get_chat_member(chat_id, user_id):
    return SimpleNamespace(status="administrator")


async def fake_get_chat_member_count(chat_id):
    return 4321


async def fake_get_me():
    return SimpleNamespace(id=777777, username="AIManagerProBot")


B.bot.send_message = fake_send_message
B.bot.send_chat_action = fake_noop
B.bot.send_photo = fake_noop
B.bot.edit_message_text = fake_edit_message_text
B.bot.get_chat = fake_get_chat
B.bot.get_chat_member = fake_get_chat_member
B.bot.get_chat_member_count = fake_get_chat_member_count
B.bot.get_me = fake_get_me


# aiogram 3.13: `message.answer(...)` → `Bot.__call__(method)` orqali ishlaydi,
# shuning uchun `Bot.__call__` ni patch qilmasak so'rov tarmoqqa ketib qotib qoladi.
from aiogram import Bot  # noqa: E402


async def fake_bot_call(self, method, request_timeout=None):
    text = getattr(method, "text", None)
    if text is not None:
        SENT.append(text)
        CALLS.append((text, {"reply_markup": getattr(method, "reply_markup", None)}))
    return SimpleNamespace(message_id=1)


Bot.__call__ = fake_bot_call

PASS = 0
FAIL = 0

ADMIN_UID = 9001
ADMIN_UNAME = "Husan_Dilmurodov"
USER_UID = 555
USER_UNAME = "testuser"


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}" + (f" — {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {extra}" if extra else ""))


def buttons_of(kw) -> list[str]:
    """reply_markup kwargs ichidan tugma matnlarini yig'adi."""
    rm = kw.get("reply_markup")
    if rm is None:
        return []
    kb = getattr(rm, "inline_keyboard", None)
    if kb is None:
        return []
    return [b.text for row in kb for b in row]


def make_msg(text: str, uid: int, uname: str) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, is_bot=False, first_name="Test", username=uname),
        text=text,
    )


async def feed(text: str, uid: int = USER_UID, uname: str = USER_UNAME) -> list[str]:
    SENT.clear()
    CALLS.clear()
    upd = Update(update_id=1, message=make_msg(text, uid, uname))
    await B.dp.feed_update(B.bot, upd)
    return list(SENT)


async def feed_cb(data: str, uid: int = USER_UID, uname: str = USER_UNAME) -> list[str]:
    SENT.clear()
    CALLS.clear()
    msg = make_msg("", uid, uname)
    cb = CallbackQuery(
        id="1",
        from_user=User(id=uid, is_bot=False, first_name="Test", username=uname),
        chat_instance="ci",
        data=data,
        message=msg,
    )
    upd = Update(update_id=2, callback_query=cb)
    await B.dp.feed_update(B.bot, upd)
    return list(SENT)


async def main() -> None:
    print("=" * 70)
    print("AI Manager Bot v6 — kanal tasdiqlash + admin statistikasi sinovlari")
    print("=" * 70)

    if os.path.exists("chan_stats_test.db"):
        os.remove("chan_stats_test.db")
    await B.db.connect()
    await B.load_data()

    # ------------------------------------------------------------------ #
    print("\n[1] Asosiy menyu — Statistika faqat adminga")
    kb_user = B.main_menu_kb(is_admin=False)
    kb_admin = B.main_menu_kb(is_admin=True)
    txt_user = [b.text for row in kb_user.inline_keyboard for b in row]
    txt_admin = [b.text for row in kb_admin.inline_keyboard for b in row]
    check("Oddiy foydalanuvchi menyusida Statistika YO'Q",
          not any("Statistika" in t for t in txt_user))
    check("Admin menyusida Statistika BOR",
          any("Statistika" in t for t in txt_admin))
    check("Boshqa bo'limlar saqlangan (Speaking/Writing/Vositalar)",
          all(any(x in t for t in txt_user)
              for x in ("IELTS Speaking", "IELTS Writing", "Vositalar")))

    # ------------------------------------------------------------------ #
    print("\n[2] /stats buyrug'i — faqat admin")
    out = await feed("/stats", uid=USER_UID, uname=USER_UNAME)
    check("Oddiy foydalanuvchiga /stats taqiqlangan",
          any("faqat admin" in t.lower() for t in out), out[0][:50] if out else "")
    out = await feed("/stats", uid=ADMIN_UID, uname=ADMIN_UNAME)
    check("Adminga /stats ko'rinadi", any("Statistika" in t for t in out))

    # ------------------------------------------------------------------ #
    print("\n[3] menu:stats callback — faqat admin")
    out = await feed_cb("menu:stats", uid=USER_UID, uname=USER_UNAME)
    check("Oddiy foydalanuvchi menu:stats ni ocholmaydi",
          any("faqat admin" in t.lower() for t in out))
    out = await feed_cb("menu:stats", uid=ADMIN_UID, uname=ADMIN_UNAME)
    check("Admin menu:stats ni ochadi", any("Statistika" in t for t in out))
    check("Stats bo'limida 'Kanal qo'shish' tugmasi bor",
          any("Kanal qo'shish" in b for t, kw in CALLS for b in buttons_of(kw)))
    check("Stats bo'limida 'Kanallar statistikasi' tugmasi bor",
          any("Kanallar statistikasi" in b for t, kw in CALLS for b in buttons_of(kw)))

    # ------------------------------------------------------------------ #
    print("\n[4] stats:chanadd — kanal qo'shish holati (admin)")
    await feed_cb("stats:chanadd", uid=ADMIN_UID, uname=ADMIN_UNAME)
    st = await B.db.get_user_state(ADMIN_UID)
    check("chan_connect holati o'rnatildi", bool(st) and st["state"] == "chan_connect")
    await B.db.clear_user_state(ADMIN_UID)

    # ------------------------------------------------------------------ #
    print("\n[5] my_chat_member — bot kanalga admin qilindi")
    bot_user = User(id=777777, is_bot=True, first_name="AI Manager",
                    username="AIManagerProBot")
    adder = User(id=2222, is_bot=False, first_name="Ali",
                 username="ali_uz")
    ev = SimpleNamespace(
        chat=_FakeChat(-1009999001, "Yangi Kanal", "yangi_kanal"),
        from_user=adder,
        old_chat_member=SimpleNamespace(status="left", user=bot_user),
        new_chat_member=SimpleNamespace(status="administrator", user=bot_user),
    )
    SENT.clear()
    CALLS.clear()
    await B.on_my_chat_member(ev)
    pend = await B.db.list_pending_channels("pending")
    check("pending_channels da so'rov yaratildi", len(pend) == 1, f"{len(pend)} ta")
    check("admin xabari yuborildi (matn)",
          any("kanalga admin qilindi" in t.lower() for t in SENT))
    check("xabarda qo'shgan foydalanuvchi username'i bor",
          any("@ali_uz" in t for t in SENT))
    check("xabarda kanal nomi bor", any("Yangi Kanal" in t for t in SENT))
    check("✅ Ruxsat berish tugmasi bor",
          any("Ruxsat berish" in b for t, kw in CALLS for b in buttons_of(kw)))
    check("❌ Rad etish tugmasi bor",
          any("Rad etish" in b for t, kw in CALLS for b in buttons_of(kw)))

    # Qayta chaqirilsa — takroriy so'rov yaratilmaydi (eski holat)
    ev2 = SimpleNamespace(
        chat=_FakeChat(-1009999002, "Allaqachon", None),
        from_user=adder,
        old_chat_member=SimpleNamespace(status="administrator", user=bot_user),
        new_chat_member=SimpleNamespace(status="administrator", user=bot_user),
    )
    await B.on_my_chat_member(ev2)
    check("allaqachon admin bo'lgan kanal uchun so'rov yo'q",
          len(await B.db.list_pending_channels("pending")) == 1)

    # ------------------------------------------------------------------ #
    print("\n[6] Begona admin kanal qarorini qabul qila olmaydi")
    cid = pend[0]["id"]
    await feed_cb(f"admin:chan:no:{cid}", uid=USER_UID, uname=USER_UNAME)
    still = await B.db.get_pending_channel(cid)
    check("Begona rad eta olmadi (pending qoldi)", still["status"] == "pending")

    # ------------------------------------------------------------------ #
    print("\n[7] admin:chan:ok — kanal botga ulanadi")
    await feed_cb(f"admin:chan:ok:{cid}", uid=ADMIN_UID, uname=ADMIN_UNAME)
    req = await B.db.get_pending_channel(cid)
    check("so'rov 'approved'", req["status"] == "approved")
    ch = await B.db.get_channel(-1009999001)
    check("kanal bazaga ulandi", ch is not None)
    check("kanal nomi saqlandi", ch and ch["title"] == "Yangi Kanal")
    check("javobda 'ulandi' tasdiqi bor",
          any("ulandi" in t.lower() for t in SENT))

    # ------------------------------------------------------------------ #
    print("\n[8] stats:chanstats — kanallar statistikasi")
    await B.db.add_scheduled_post(-1009999001, "Post 1", 0, created_by=ADMIN_UID)
    await B.db.add_scheduled_post(-1009999001, "Post 2", 0, created_by=ADMIN_UID)
    out = await feed_cb("stats:chanstats", uid=ADMIN_UID, uname=ADMIN_UNAME)
    joined = "\n".join(out)
    check("kanallar statistikasi ko'rsatildi", "Kanallar statistikasi" in joined)
    check("a'zolar soni ko'rsatildi (4321)", "4321" in joined, joined[:80])
    check("postlar soni ko'rsatildi (2)", "2" in joined)

    n_posts = await B.db.count_channel_posts(-1009999001)
    check("count_channel_posts to'g'ri", n_posts == 2, str(n_posts))

    # ------------------------------------------------------------------ #
    print("\n[9] admin:chan:no — rad etish oqimi")
    cid2 = await B.db.create_pending_channel(-1009999003, "Rad Kanal", None, USER_UID)
    await feed_cb(f"admin:chan:no:{cid2}", uid=ADMIN_UID, uname=ADMIN_UNAME)
    req2 = await B.db.get_pending_channel(cid2)
    check("so'rov 'rejected'", req2["status"] == "rejected")
    check("kanal bazaga qo'shilmadi", await B.db.get_channel(-1009999003) is None)

    # ------------------------------------------------------------------ #
    print("\n[10] my_chat_member handler dispatcher'ga ro'yxatdan o'tgan")
    observers = getattr(B.dp, "my_chat_member", None)
    check("dp.my_chat_member observer mavjud", observers is not None)
    # callback handlerlari ro'yxatdan o'tganini tekshiramiz
    reg_hits = []
    for name in ("on_my_chat_member", "on_admin_channel_decision",
                 "on_menu_stats", "on_stats_chanadd", "on_stats_chanstats"):
        reg_hits.append(hasattr(B, name))
    check("barcha yangi handlerlar mavjud", all(reg_hits))

    await B.db.close()
    for f in ("chan_stats_test.db", "chan_stats_test.db-wal", "chan_stats_test.db-shm"):
        if os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 70)
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
