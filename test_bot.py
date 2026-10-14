"""Bot-side checks: database, instant replies, subject detection, quiz, Gemini pool, getMe."""
import asyncio
import json
import os
import sys
import tempfile
import urllib.request

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}{(' — ' + detail) if detail else ''}")


async def run():
    os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
    from database import Database
    db = Database()
    await db.connect()

    n = await db.instant_reply("salom")
    check("instant reply (salom) is instant", bool(n))
    n2 = await db.instant_reply("assalomu alaykum")
    check("instant reply (assalomu alaykum)", bool(n2))
    none = await db.instant_reply("bu qandaydir uzoq noaniq savol matni")
    check("no false instant match", none is None)

    subjects = await db.quiz_subjects()
    check("quiz seeded (10 subjects)", len(subjects) >= 10, f"got {len(subjects)}")

    ids = await db.start_quiz(1, subjects[0][0])
    check("quiz session starts", len(ids) > 0)
    q = await db.quiz_question(ids[0])
    check("quiz question loads with options", bool(q) and len(q["options"]) >= 2)
    adv = await db.advance_quiz(1, True)
    check("quiz advances + scores", adv and adv["score"] == 1)

    await db.upsert_user(1, "tester", "Test")
    await db.add_history(1, "user", "salom", "instant", "instant")
    hist = await db.recent_history(1, 8)
    check("history roundtrip", len(hist) == 1 and hist[0]["text"] == "salom")

    await db.add_question("writing", "Task 2 test", "Some prompt", added_by=1)
    bank = await db.search_bank("Task", 10)
    check("question bank insert+search", len(bank) == 1)

    await db.add_channel(1, "-100123", "Test Channel", "testchan")
    chans = await db.channels(1)
    check("channel connect+list", len(chans) == 1)
    await db.add_post("-100123", "hello", "2020-01-01T00:00:00Z")
    due = await db.due_posts("2030-01-01T00:00:00Z")
    check("scheduled post is due", len(due) == 1)
    await db.mark_post_sent(due[0]["id"], 0)
    due2 = await db.due_posts("2030-01-01T00:00:00Z")
    check("scheduled post marked done", len(due2) == 0)

    check("is_admin False for stranger", not await db.is_admin(999))
    await db.grant_admin(2, granted_by=1)
    check("grant_admin works", await db.is_admin(2))

    stats = await db.overview()
    check("stats overview keys", "users" in stats and "messages" in stats)

    await db.close()

    # subject detection (pure function, import bot lazily)
    os.environ["BOT_TOKEN"] = os.environ.get("BOT_TOKEN", "123:TEST")
    os.environ["GEMINI_API_KEYS"] = os.environ.get("GEMINI_API_KEYS", "dummy")
    try:
        sys.path.insert(0, os.getcwd())
        import importlib
        botmod = importlib.import_module("bot")
        check("detect_subject -> matematika", botmod.detect_subject("tenglamani yechib ber") == "matematika")
        check("detect_subject -> dasturlash", botmod.detect_subject("python kod yoz") == "dasturlash")
        t, iso, rep = botmod.parse_schedule("Salom | +2h | 60")
        check("parse_schedule relative", t == "Salom" and rep == 60 and iso.endswith("Z"))
    except Exception as e:
        check("bot module import", False, str(e))

    # Gemini pool real call (only if a real key is present)
    key = os.environ.get("GEMINI_API_KEYS", "")
    if key and not key.startswith("dummy"):
        from gemini_pool import GeminiPool, AllKeysFailed
        p = GeminiPool(keys=[k for k in key.split(",") if k])
        try:
            ans = await p.generate([{"role": "user", "parts": [{"text": "Faqat 'OK' deb javob ber."}]}],
                                   max_output_tokens=20)
            check("Gemini real API call", len(ans) > 0, ans[:40])
        except AllKeysFailed as e:
            check("Gemini real API call", False, f"all keys failed: {str(e)[:80]}")
    else:
        print("⏭  Gemini real call skipped (no real key in env)")

    # Telegram getMe
    token = os.environ.get("BOT_TOKEN", "")
    if token and ":" in token and not token.endswith("TEST"):
        try:
            with urllib.request.urlopen(
                    f"https://api.telegram.org/bot{token}/getMe", timeout=20) as r:
                d = json.load(r)
            check("Telegram getMe", d.get("ok") is True, d.get("result", {}).get("username"))
        except Exception as e:
            check("Telegram getMe", False, str(e)[:80])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
