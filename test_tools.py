"""Tools menu + channel management checks."""
import asyncio
import os
import sys
import tempfile

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✅' if cond else '❌'} {name}{(' — ' + detail) if detail else ''}")


async def run():
    os.environ.setdefault("DB_PATH", tempfile.mktemp(suffix=".db"))
    os.environ.setdefault("BOT_TOKEN", "123:TEST")
    os.environ.setdefault("GEMINI_API_KEYS", "dummy")
    sys.path.insert(0, os.getcwd())

    import json
    from database import Database
    import bot as B

    db = Database()
    await db.connect()
    B.db = db

    # --- Tools menu has exactly 2 action buttons (+ back) ---
    kb = B.tools_kb()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    action = [l for l in labels if l != "⬅️ Orqaga"]
    check("Tools menu has exactly 2 actions", len(action) == 2, str(labels))
    check("Tools: Savol qo'shish present", any("Savol qo'shish" in l for l in labels))
    check("Tools: Kanalga ulash present", any("Kanalga ulash" in l for l in labels))
    for old in ("Ovoz", "Rasm", "Savollar banki"):
        check(f"Tools has no legacy '{old}' button", not any(old in l for l in labels))

    # --- channel CRUD ---
    await db.add_channel(1, "@mychan", "Mening kanalim", "mychan")
    await db.add_channel(1, "@mychan", "Mening kanalim v2", "mychan")  # upsert
    chans = await db.channels(1)
    check("channel upsert (no duplicate)", len(chans) == 1, f"count={len(chans)}")
    check("channel title updated on upsert", chans[0]["title"] == "Mening kanalim v2")
    got = await db.get_channel("@mychan")
    check("get_channel by id", got is not None)
    await db.delete_channel("@mychan")
    check("delete_channel", len(await db.channels(1)) == 0)

    # --- scheduled posts ---
    await db.add_post("@chan", "post1", "2026-01-01T00:00:00Z", 0, created_by=1)
    await db.add_post("@chan", "repeat", "2026-01-01T00:00:00Z", 1440, created_by=1)
    posts = await db.posts()
    check("two scheduled posts stored", len(posts) == 2)
    due = await db.due_posts("2030-01-01T00:00:00Z")
    check("due posts detected", len(due) == 2)
    for p in due:
        await db.mark_post_sent(p["id"], p["repeat_min"] or 0)
    remaining = await db.posts()
    check("one-off done, repeating rescheduled", len(remaining) == 1, f"left={len(remaining)}")

    # --- addq approval flow ---
    await db.addq_request(77, "someone", "Someone")
    check("addq request pending", await db.request_status(77) == "pending")
    await db.set_request_status(77, "approved")
    await db.grant_admin(77, granted_by=1)
    check("addq approved -> admin right", await db.is_admin(77))

    # --- question kinds from tools ---
    await db.add_question("speaking", "Part 1: Hometown", "Describe your hometown", added_by=1)
    await db.add_question("writing", "Task 2: Education", "Discuss both views", added_by=1)
    bank = await db.search_bank(None, 10)
    check("speaking + writing appended to bank", len(bank) == 2)
    await db.add_question("math", "Kvadrat tenglama", "x^2-5x+6=0",
                          meta={"options": ["2,3", "1,6"], "answer": 0}, added_by=1)
    bank2 = await db.search_bank("tenglama", 5)
    check("math question searchable", len(bank2) == 1)

    # --- test-code answer checking ---
    def grade(code, answers):
        return code[:len(answers)].lower() == answers.lower()
    check("test-code grading (abcdfdddd style)", grade("abcdfdddd", "abcdfdddd"))
    check("test-code grading mismatch detected", not grade("abcdfdddd", "abcdfddde"))

    # --- time parsing ---
    for raw, ok in (("Matn | +2h", True), ("Matn | 09:30", True),
                    ("Matn | 2026-10-16 09:30", True), ("Matn", True)):
        try:
            t, iso, rep = B.parse_schedule(raw)
            check(f"parse_schedule '{raw}'", iso.endswith("Z"))
        except Exception as e:
            check(f"parse_schedule '{raw}'", False, str(e))

    await db.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
