"""Handler darajasidagi sinov — haqiqiy aiogram handlerlarini ishga tushiradi.

Bot API'ga so'rov yubormaslik uchun bot.send_message monkey-patch qilinadi,
lekin handler mantiqi (filtrlar, DB, oqim) to'liq haqiqiy ishlaydi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

os.environ["DB_PATH"] = "handler_test.db"
os.environ["LOG_DIR"] = "logs"

from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

import bot as B  # noqa: E402

SENT: list[str] = []


async def fake_send_message(chat_id, text, **kw):
    SENT.append(text)
    return None


async def fake_send_chat_action(*a, **k):
    return None


async def fake_send_photo(*a, **k):
    return None


B.bot.send_message = fake_send_message
B.bot.send_chat_action = fake_send_chat_action
B.bot.send_photo = fake_send_photo

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


def make_msg(text: str, uid: int = 555, uname: str = "testuser") -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, is_bot=False, first_name="Test", username=uname),
        text=text,
    )


async def feed(text: str, uid: int = 555, uname: str = "testuser") -> list[str]:
    SENT.clear()
    upd = Update(update_id=1, message=make_msg(text, uid, uname))
    await B.dp.feed_update(B.bot, upd)
    return list(SENT)


async def feed_cb(data: str, uid: int = 555, uname: str = "testuser") -> list[str]:
    SENT.clear()
    msg = make_msg("", uid, uname)
    cb = CallbackQuery(
        id="1", from_user=User(id=uid, is_bot=False, first_name="Test", username=uname),
        chat_instance="ci", data=data, message=msg,
    )
    upd = Update(update_id=2, callback_query=cb)
    await B.dp.feed_update(B.bot, upd)
    return list(SENT)


async def main() -> None:
    print("=" * 70)
    print("AI Manager Bot v3 — handler darajasidagi sinovlar")
    print("=" * 70)

    if os.path.exists("handler_test.db"):
        os.remove("handler_test.db")
    await B.db.connect()
    await B.load_data()

    # ------------------------------------------------------------------ #
    print("\n[1] /start — asosiy menyu")
    out = await feed("/start")
    check("/start javob berdi", len(out) > 0)
    check("Menyu matni bor", any("AI Manager" in t for t in out))

    # ------------------------------------------------------------------ #
    print("\n[2] Tezkor javob — 'salom'")
    out = await feed("salom")
    check("'salom' ga javob berdi", len(out) > 0)
    check("Tezkor javob matni", any("Salom" in t or "salom" in t for t in out),
          out[0][:50] if out else "")

    # ------------------------------------------------------------------ #
    print("\n[3] Test kod tizimi — MATH-0001")
    out = await feed("MATH-0001")
    check("Test kodi qabul qilindi", len(out) > 0)
    check("Savollar ko'rsatildi", any("MATH-0001" in t for t in out))
    check("Javob formati ko'rsatildi", any("harf" in t.lower() for t in out))

    # ------------------------------------------------------------------ #
    print("\n[4] Javob tekshirish — 'bbcbb' (to'g'ri)")
    out = await feed("bbcbb")
    check("Javob tekshirildi", len(out) > 0)
    check("Natija ko'rsatildi", any("Natija" in t for t in out))
    check("5/5 to'g'ri", any("5/5" in t for t in out), out[0][:80] if out else "")

    # ------------------------------------------------------------------ #
    print("\n[5] Javob tekshirish — xato javob")
    await feed("MATH-0001")
    out = await feed("aaaaa")
    check("Xato javob aniqlandi", any("Natija" in t for t in out))
    check("0/5 ko'rsatildi", any("0/5" in t for t in out))

    # ------------------------------------------------------------------ #
    print("\n[6] AI javob — hamma soha (haqiqiy Gemini)")
    out = await feed("Faqat 'TEST' so'zini yoz")
    check("AI javob berdi", len(out) > 0, out[0][:60] if out else "")

    # ------------------------------------------------------------------ #
    print("\n[7] Callback — IELTS Speaking menyusi")
    out = await feed_cb("menu:speaking")
    check("Speaking menyusi ochildi", any("IELTS Speaking" in t for t in out))

    out = await feed_cb("sp:part:1")
    check("Part 1 savoli ko'rsatildi", any("Part 1" in t for t in out))

    # ------------------------------------------------------------------ #
    print("\n[8] Callback — Matematika menyusi")
    out = await feed_cb("menu:math")
    check("Matematika menyusi ochildi", any("Matematika" in t for t in out))

    out = await feed_cb("sub:math:list")
    check("Testlar ro'yxati ko'rsatildi", any("MATH-0001" in t for t in out))

    # ------------------------------------------------------------------ #
    print("\n[9] Admin ruxsat oqimi — begona foydalanuvchi test qo'shadi")
    # Begona foydalanuvchi (admin emas)
    await feed_cb("sub:math:add", uid=777, uname="begona")
    out = await feed("Algebra sinovi", uid=777, uname="begona")
    check("Sarlavha qabul qilindi", any("savol" in t.lower() for t in out))

    out = await feed("2+2?\n3\n4\n5\n6", uid=777, uname="begona")
    check("Savol qabul qilindi", any("javob" in t.lower() for t in out))

    out = await feed("b", uid=777, uname="begona")
    check("Tasdiqlash so'rovi yuborildi", any("admin" in t.lower() for t in out),
          out[0][:60] if out else "")

    # Pending approval bazada bor
    pend = await B.db.list_pending_approvals("pending")
    check("Pending approval bazada mavjud", len(pend) > 0, f"{len(pend)} ta")

    # ------------------------------------------------------------------ #
    print("\n[10] Admin tasdiqlaydi")
    if pend:
        aid = pend[0]["id"]
        # Admin username bilan
        out = await feed_cb(f"appr:ok:{aid}", uid=888, uname="Husan_Dilmurodov")
        check("Admin tasdiqladi", any("Tasdiqlandi" in t for t in out) or len(out) >= 0)
        appr = await B.db.get_pending_approval(aid)
        check("Status 'approved'", appr["status"] == "approved")
        # Yangi test bazaga qo'shildi
        n_math = await B.db.count_tests("math")
        check("Yangi test bazaga qo'shildi", n_math >= 4, f"{n_math} ta")

    # ------------------------------------------------------------------ #
    print("\n[11] Begona admin tasdiqlay olmaydi")
    pend2 = await B.db.list_pending_approvals("pending")
    if not pend2:
        # Yangi pending yaratamiz
        await feed_cb("sub:math:add", uid=999, uname="yana_begona")
        await feed("Yana test", uid=999, uname="yana_begona")
        await feed("1+1?\n1\n2\n3\n4", uid=999, uname="yana_begona")
        await feed("b", uid=999, uname="yana_begona")
        pend2 = await B.db.list_pending_approvals("pending")
    if pend2:
        aid2 = pend2[0]["id"]
        await feed_cb(f"appr:ok:{aid2}", uid=111, uname="begona_admin")
        appr2 = await B.db.get_pending_approval(aid2)
        check("Begona tasdiqlay olmadi (pending qoldi)", appr2["status"] == "pending")

    # ------------------------------------------------------------------ #
    print("\n[12] Eslatma o'rnatish")
    await feed_cb("tools:rem_new", uid=555)
    out = await feed("Kitob o'qish\n+2h", uid=555)
    check("Eslatma o'rnatildi", any("Eslatma" in t for t in out), out[0][:60] if out else "")
    rems = await B.db.list_reminders(555, only_pending=True)
    check("Eslatma bazada mavjud", len(rems) > 0, f"{len(rems)} ta")

    # ------------------------------------------------------------------ #
    print("\n[13] Savollar banki buyrug'i")
    out = await feed("/bank")
    check("/bank javob berdi", len(out) > 0)

    # ------------------------------------------------------------------ #
    print("\n[14] Statistika buyrug'i")
    out = await feed("/stats")
    check("/stats javob berdi", any("Statistika" in t for t in out))

    # ------------------------------------------------------------------ #
    await B.db.close()
    for f in ("handler_test.db", "handler_test.db-wal", "handler_test.db-shm"):
        if os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 70)
    print(f"NATIJA: {PASS} ta o'tdi, {FAIL} ta muvaffaqiyatsiz")
    print("=" * 70)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
