"""Kanal qo'shish / admin ruxsat so'rash oqimi uchun tuzatish testi.

Tekshiriladi:
  1. Global obuna gate'i `my_chat_member` hodisasini YUTIB YUBORMAYDI
     (bu — asosiy muammoning ildizi edi).
  2. Gate oddiy foydalanuvchi xabarini esa BLOKLAYDI (himoya saqlanadi).
  3. get_admin_ids() — ADMIN_ID env orqali ishlaydi.
  4. get_admin_ids() — ADMIN_ID BO'SH bo'lsa ham, ADMIN_USERNAME orqali
     bazadan raqamli ID ni topadi (asosiy tuzatish).
  5. notify_admins_channel() — adminga ✅/❌ tugmalari bilan xabar yuboradi.
  6. Hech kimga yetib bormasa — kanal egasiga aniq yo'riqnoma yuboriladi.
  7. admin:chan:ok / :no — kanal ulanadi/rad etiladi VA egasiga xabar boradi.

Ishga tushirish:  timeout 90 python test_channel_approval_fix.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace

# --- Sinov uchun soxta env (bot.py import qilinishidan OLDIN) --------------- #
os.environ["BOT_TOKEN"] = "123456:TESTTOKEN"
os.environ["GEMINI_API_KEYS"] = "test-key-1,test-key-2"
os.environ["PORT"] = "0"
os.environ["ENABLE_SUB_GATE"] = "true"
os.environ["REQUIRED_CHANNEL_URL"] = "https://t.me/matmilliysertifikat"
os.environ["REQUIRED_CHANNEL_ID"] = "@matmilliysertifikat"
os.environ["ADMIN_ID"] = "9001"
os.environ["ADMIN_IDS"] = ""
os.environ["ADMIN_USERNAME"] = "Husan_Dilmurodov"
os.environ["ADMIN_USERNAMES"] = ""
os.environ["SELF_PING_URL"] = ""
os.environ["WATCHDOG_ENABLED"] = "false"
os.environ["BACKUP_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import (  # noqa: E402
    AnswerCallbackQuery,
    EditMessageText,
    GetChatMember,
    SendMessage,
)
from aiogram.types import Chat, Message, Update, User  # noqa: E402

import bot as B  # noqa: E402
import config as C  # noqa: E402

PASS, FAIL = 0, 0

# --------------------------------------------------------------------------- #
# Sessiya darajasidagi interceptor — tarmoqqa chiqmaslik uchun.
# aiogram'da `message.answer()` va `cb.answer()` `bot.send_message` ni EMAS,
# balki `bot.session.make_request` ni chaqiradi.
# --------------------------------------------------------------------------- #
SENT: list[dict] = []
EDITED: list[dict] = []
ANSWERS: list[str] = []
SUB_STATUS = {"status": "left"}


class RecordingSession(BaseSession):
    async def close(self) -> None:
        return None

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            SENT.append({
                "chat_id": method.chat_id,
                "text": method.text or "",
                "kw": {"reply_markup": getattr(method, "reply_markup", None)},
            })
            return _mk_message(method.chat_id, method.text or "", len(SENT))
        if isinstance(method, EditMessageText):
            EDITED.append({
                "chat_id": getattr(method, "chat_id", None),
                "text": method.text or "",
                "kw": {"reply_markup": getattr(method, "reply_markup", None)},
            })
            return _mk_message(getattr(method, "chat_id", 1), method.text or "", len(EDITED))
        if isinstance(method, AnswerCallbackQuery):
            ANSWERS.append(method.text or "")
            return True
        if isinstance(method, GetChatMember):
            return SimpleNamespace(status=SUB_STATUS["status"])
        return True


def _mk_message(chat_id, text, mid):
    return Message(
        message_id=mid, date=1700000000,
        chat=Chat(id=chat_id or 1, type="private"), text=text,
    )


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def buttons_of(kw) -> list[str]:
    rm = kw.get("reply_markup")
    if not rm:
        return []
    kb = getattr(rm, "inline_keyboard", None)
    if kb is None and isinstance(rm, dict):
        kb = rm.get("inline_keyboard")
    out: list[str] = []
    for row in kb or []:
        for b in row:
            txt = getattr(b, "text", None)
            if txt is None and isinstance(b, dict):
                txt = b.get("text")
            if txt:
                out.append(txt)
    return out


def make_my_chat_member_update() -> Update:
    bot_user = {"id": 777, "is_bot": True, "first_name": "Bot",
                "username": "AIManagerProBot"}
    admin = {
        "status": "administrator", "user": bot_user,
        "can_be_edited": False, "is_anonymous": False,
        "can_manage_chat": True, "can_delete_messages": True,
        "can_manage_video_chats": True, "can_restrict_members": True,
        "can_promote_members": False, "can_change_info": True,
        "can_invite_users": True, "can_post_messages": True,
        "can_edit_messages": True, "can_pin_messages": True,
        "can_manage_topics": True, "can_post_stories": True,
        "can_edit_stories": True, "can_delete_stories": True,
    }
    return Update.model_validate(
        {
            "update_id": 1,
            "my_chat_member": {
                "chat": {"id": -1009988776655, "type": "channel",
                         "title": "Yangi Kanal", "username": "yangi_kanal"},
                "from": {"id": 4242, "is_bot": False, "first_name": "Ali",
                         "username": "ali_uz"},
                "date": 1700000000,
                "old_chat_member": {"status": "left", "user": bot_user},
                "new_chat_member": admin,
            },
        },
        context={"bot": B.bot},
    )


def make_message_update() -> Update:
    return Update.model_validate(
        {
            "update_id": 2,
            "message": {
                "message_id": 10, "date": 1700000001,
                "chat": {"id": 4242, "type": "private"},
                "from": {"id": 4242, "is_bot": False, "first_name": "Ali",
                         "username": "ali_uz"},
                "text": "salom",
            },
        },
        context={"bot": B.bot},
    )


async def run() -> None:
    global SUB_STATUS
    db_path = os.path.join(tempfile.gettempdir(), "chan_fix_test.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(db_path + suffix)
        except OSError:
            pass

    B.bot.session = RecordingSession()
    B.db = B.Database(db_path)
    await B.db.connect()

    adder = SimpleNamespace(id=4242, username="ali_uz", first_name="Ali")
    chat = SimpleNamespace(id=-1009988776655, type="channel",
                           title="Yangi Kanal", username="yangi_kanal")

    called = {"hit": 0}

    async def handler(event, data):
        called["hit"] += 1
        return "handled"

    # ------------------------------------------------------------------ #
    print("\n[1] Gate my_chat_member hodisasini O'TKAZIB YUBORADI (asosiy tuzatish)")
    check("_GATE_INNER_EVENTS da my_chat_member YO'Q",
          "my_chat_member" not in B._GATE_INNER_EVENTS)
    SUB_STATUS = {"status": "left"}  # qo'shgan foydalanuvchi kanalga a'zo emas
    upd = make_my_chat_member_update()
    check("Update yaratildi (my_chat_member)", upd.my_chat_member is not None)
    res = await B.sub_gate_outer_middleware(handler, upd, {})
    check("my_chat_member handler'ga YETIB BORDI", called["hit"] == 1, f"hit={called['hit']}")
    check("natija handler'dan qaytdi", res == "handled", str(res))

    # ------------------------------------------------------------------ #
    print("\n[2] Gate oddiy xabarni BLOKLAYDI (himoya saqlangan)")
    called["hit"] = 0
    SENT.clear()
    res2 = await B.sub_gate_outer_middleware(handler, make_message_update(), {})
    check("obuna bo'lmagan oddiy xabar BLOKLANDI", called["hit"] == 0, f"hit={called['hit']}")
    check("bloklangan update None qaytardi", res2 is None, str(res2))
    check("foydalanuvchiga obuna xabari yuborildi", len(SENT) == 1, str(len(SENT)))

    # ------------------------------------------------------------------ #
    print("\n[3] get_admin_ids() — ADMIN_ID env orqali")
    check("ADMIN_ID env o'qildi", 9001 in await B.get_admin_ids())

    # ------------------------------------------------------------------ #
    print("\n[4] get_admin_ids() — ADMIN_ID bo'sh, username orqali bazadan topadi")
    C.ADMIN_IDS = []
    await B.db.upsert_user(7792675322, "Husan_Dilmurodov", "Xusan")
    ids2 = await B.get_admin_ids()
    check("username orqali admin ID topildi (7792675322)",
          7792675322 in ids2, str(ids2))
    await B.db.register_admin(555000, "boshqa_admin")
    ids3 = await B.get_admin_ids()
    check("bazadagi admin ham ro'yxatda (555000)", 555000 in ids3, str(ids3))

    # ------------------------------------------------------------------ #
    print("\n[5] notify_admins_channel — adminga xabar + tugmalar")
    SENT.clear()
    cid = await B.db.create_pending_channel(chat.id, chat.title, chat.username, adder.id)
    await B.notify_admins_channel(cid, adder, chat, chat.id)
    admin_msgs = [m for m in SENT if m["chat_id"] in (7792675322, 9001, 555000)]
    check("adminga xabar yuborildi", len(admin_msgs) >= 1, str(len(admin_msgs)))
    if admin_msgs:
        txt = admin_msgs[0]["text"]
        check("xabarda qo'shgan username'i bor", "@ali_uz" in txt)
        check("xabarda kanal nomi bor", "Yangi Kanal" in txt)
        check("xabarda kanal ID bor", str(chat.id) in txt)
        btns = buttons_of(admin_msgs[0]["kw"])
        check("'Ruxsat berish' tugmasi bor", any("Ruxsat berish" in b for b in btns), str(btns))
        check("'Rad etish' tugmasi bor", any("Rad etish" in b for b in btns), str(btns))
        check("tugma so'rovga bog'langan",
              f"admin:chan:ok:{cid}" in str(admin_msgs[0]["kw"]))

    # ------------------------------------------------------------------ #
    print("\n[6] Admin topilmasa — kanal egasiga yo'riqnoma boradi")
    SENT.clear()
    C.ADMIN_IDS = []
    C.ADMIN_USERNAMES = []
    saved_reg = B.db.get_registered_admins
    saved_un = B.db.get_user_ids_by_usernames

    async def _empty_reg():
        return []

    async def _empty_un(names):
        return []

    B.db.get_registered_admins = _empty_reg
    B.db.get_user_ids_by_usernames = _empty_un
    cid2 = await B.db.create_pending_channel(-1009999001, "Boshqa Kanal", None, adder.id)
    await B.notify_admins_channel(
        cid2, adder,
        SimpleNamespace(id=-1009999001, type="channel", title="Boshqa Kanal",
                        username=None),
        -1009999001,
    )
    owner_msgs = [m for m in SENT if m["chat_id"] == adder.id]
    check("kanal egasiga yo'riqnoma yuborildi", len(owner_msgs) == 1, str(len(owner_msgs)))
    if owner_msgs:
        check("yo'riqnomada /start haqida yozilgan", "/start" in owner_msgs[0]["text"])
    B.db.get_registered_admins = saved_reg
    B.db.get_user_ids_by_usernames = saved_un

    # ------------------------------------------------------------------ #
    print("\n[7] admin:chan:ok / :no — kanal holati VA egasiga xabar")
    C.ADMIN_IDS = [7792675322]
    C.ADMIN_USERNAMES = ["husan_dilmurodov"]
    for verdict, expect_status, word in (("ok", "approved", "ulandi"),
                                         ("no", "rejected", "rad")):
        cur = await B.db.get_pending_channel(cid)
        if cur["status"] != "pending":
            cid = await B.db.create_pending_channel(
                chat.id, chat.title, chat.username, adder.id)
        cb_upd = Update.model_validate(
            {
                "update_id": 500 + len(ANSWERS),
                "callback_query": {
                    "id": f"cb{verdict}",
                    "from": {"id": 7792675322, "is_bot": False,
                             "first_name": "Xusan", "username": "Husan_Dilmurodov"},
                    "chat_instance": "1234567890",
                    "data": f"admin:chan:{verdict}:{cid}",
                    "message": {
                        "message_id": 99, "date": 1700000000,
                        "chat": {"id": 7792675322, "type": "private"},
                        "text": "x",
                    },
                },
            },
            context={"bot": B.bot},
        )
        cb = cb_upd.callback_query
        SENT.clear()
        ANSWERS.clear()
        await B.on_admin_channel_decision(cb)
        again = await B.db.get_pending_channel(cid)
        check(f"status = {expect_status} ({verdict})", again["status"] == expect_status,
              str(again["status"]))
        check(f"callback javobi qaytarildi ({verdict})", len(ANSWERS) >= 1)
        om = [m for m in SENT if m["chat_id"] == adder.id]
        check(f"so'rov egasiga natija xabari yuborildi ({verdict})",
              len(om) == 1, str(len(om)))
        if om:
            check(f"xabarda '{word}' so'zi bor ({verdict})",
                  word in om[0]["text"].lower(), om[0]["text"][:60])

    # ------------------------------------------------------------------ #
    print("\n[8] Handlerlar dispatcher'ga ro'yxatdan o'tgan")
    check("dp.my_chat_member mavjud", getattr(B.dp, "my_chat_member", None) is not None)
    check("on_admin_channel_decision mavjud", hasattr(B, "on_admin_channel_decision"))
    check("get_admin_ids mavjud", hasattr(B, "get_admin_ids"))
    check("get_user_ids_by_usernames mavjud",
          hasattr(B.db, "get_user_ids_by_usernames"))

    await B.db.close()
    print(f"\n{'=' * 58}\nNATIJA: {PASS} ta o'tdi, {FAIL} ta xato\n{'=' * 58}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
