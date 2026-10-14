"""SQLite layer (aiosqlite) for AI Manager Bot.

All tables from the v5 design: users, chat_history, instant_replies,
quiz_*, stats, ielts_*, math_tests, physics_tests, test_codes, reminders,
question_bank, user_states, admins, channels, scheduled_posts.
"""
import json
import logging
import os
import time

import aiosqlite

from config import (
    ADMIN_ID,
    ADMIN_USERNAME,
    DEFAULT_LANG,
    QUIZ_QUESTIONS_PER_SESSION,
    DB_PATH,
)

log = logging.getLogger("db")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    lang          TEXT DEFAULT 'uz',
    joined_at     TEXT,
    last_seen     TEXT,
    msg_count     INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chat_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    role          TEXT,
    text          TEXT,
    topic         TEXT,
    source        TEXT,
    created_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_hist_user ON chat_history(user_id, id DESC);

CREATE TABLE IF NOT EXISTS instant_replies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword       TEXT UNIQUE,
    reply         TEXT,
    category      TEXT DEFAULT 'general',
    priority      INTEGER DEFAULT 0,
    uses          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT,
    question      TEXT,
    options       TEXT,
    answer        INTEGER,
    explanation   TEXT
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
    user_id       INTEGER PRIMARY KEY,
    subject       TEXT,
    question_ids  TEXT,
    pos           INTEGER DEFAULT 0,
    score         INTEGER DEFAULT 0,
    started_at    TEXT,
    updated_at    TEXT
);
CREATE TABLE IF NOT EXISTS quiz_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    subject       TEXT,
    score         INTEGER,
    total         INTEGER,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS stats (
    key           TEXT PRIMARY KEY,
    value         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS question_bank (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT,
    title         TEXT,
    body          TEXT,
    meta          TEXT,
    code          TEXT,
    added_by      INTEGER,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS test_codes (
    code          TEXT PRIMARY KEY,
    kind          TEXT,
    title         TEXT,
    payload       TEXT,
    created_by    INTEGER,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS math_tests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT,
    question      TEXT,
    options       TEXT,
    answer        INTEGER
);
CREATE TABLE IF NOT EXISTS physics_tests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT,
    question      TEXT,
    options       TEXT,
    answer        INTEGER
);

CREATE TABLE IF NOT EXISTS reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    text          TEXT,
    due_at        TEXT,
    repeat_min    INTEGER DEFAULT 0,
    sent          INTEGER DEFAULT 0,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS user_states (
    user_id       INTEGER PRIMARY KEY,
    state         TEXT,
    payload       TEXT,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    granted_by    INTEGER,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS addq_requests (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    status        TEXT,
    created_at    TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id      INTEGER,
    channel_id    TEXT UNIQUE,
    title         TEXT,
    username      TEXT,
    connected_at  TEXT
);
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id    TEXT,
    text          TEXT,
    media         TEXT,
    run_at        TEXT,
    repeat_min    INTEGER DEFAULT 0,
    sent_count    INTEGER DEFAULT 0,
    done          INTEGER DEFAULT 0,
    created_by    INTEGER,
    created_at    TEXT
);
"""


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Database:
    def __init__(self, path=None):
        self.path = path or DB_PATH
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()
        await self._bootstrap()
        log.info("database ready at %s", self.path)

    async def close(self):
        if self.conn:
            await self.conn.close()

    # ---------------------------------------------------------- bootstrap
    async def _bootstrap(self):
        await self._seed_instant_replies()
        await self._seed_quiz()
        await self._seed_admin()

    async def _seed_admin(self):
        uid = None
        raw = (ADMIN_ID or "").split(",")[0].strip()
        if raw.isdigit():
            uid = int(raw)
        if uid:
            await self.conn.execute(
                "INSERT OR IGNORE INTO admins(user_id, username, granted_by, created_at) VALUES(?,?,?,?)",
                (uid, ADMIN_USERNAME, uid, now_iso()),
            )
            await self.conn.commit()

    async def _seed_instant_replies(self):
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM instant_replies")
        row = await cur.fetchone()
        if row and row["c"]:
            return
        rows = _load_json("instant_replies.json", [])
        for item in rows:
            await self.conn.execute(
                "INSERT OR IGNORE INTO instant_replies(keyword, reply, category, priority) VALUES(?,?,?,?)",
                (item.get("keyword", "").lower().strip(), item.get("reply", ""),
                 item.get("category", "general"), item.get("priority", 0)),
            )
        await self.conn.commit()
        log.info("seeded %d instant replies", len(rows))

    async def _seed_quiz(self):
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM quiz_questions")
        row = await cur.fetchone()
        if row and row["c"]:
            return
        rows = _load_json("quiz_data.json", [])
        for q in rows:
            await self.conn.execute(
                "INSERT INTO quiz_questions(subject, question, options, answer, explanation) VALUES(?,?,?,?,?)",
                (q.get("subject", "umumiy"), q.get("question", ""),
                 json.dumps(q.get("options", []), ensure_ascii=False),
                 int(q.get("answer", 0)), q.get("explanation", "")),
            )
        await self.conn.commit()
        log.info("seeded %d quiz questions", len(rows))

    # ---------------------------------------------------------- users
    async def upsert_user(self, user_id, username=None, first_name=None):
        ts = now_iso()
        await self.conn.execute(
            """INSERT INTO users(user_id, username, first_name, lang, joined_at, last_seen, msg_count)
               VALUES(?,?,?,?,?,?,1)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=COALESCE(excluded.username, users.username),
                 first_name=COALESCE(excluded.first_name, users.first_name),
                 last_seen=excluded.last_seen,
                 msg_count=users.msg_count+1""",
            (user_id, username, first_name, DEFAULT_LANG, ts, ts),
        )
        await self.conn.commit()

    async def get_lang(self, user_id):
        cur = await self.conn.execute("SELECT lang FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row["lang"] if row and row["lang"] else DEFAULT_LANG

    async def set_lang(self, user_id, lang):
        await self.upsert_user(user_id)
        await self.conn.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
        await self.conn.commit()

    # ---------------------------------------------------------- history
    async def add_history(self, user_id, role, text, topic=None, source="ai"):
        await self.conn.execute(
            "INSERT INTO chat_history(user_id, role, text, topic, source, created_at) VALUES(?,?,?,?,?,?)",
            (user_id, role, text, topic, source, now_iso()),
        )
        await self.conn.commit()

    async def recent_history(self, user_id, limit=8):
        cur = await self.conn.execute(
            "SELECT role, text FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [{"role": r["role"], "text": r["text"]} for r in reversed(rows)]

    async def history(self, user_id, limit=20):
        cur = await self.conn.execute(
            "SELECT role, text, created_at FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def clear_history(self, user_id):
        await self.conn.execute("DELETE FROM chat_history WHERE user_id=?", (user_id,))
        await self.conn.commit()

    # ---------------------------------------------------------- instant replies
    async def instant_reply(self, text):
        key = (text or "").strip().lower()
        if not key:
            return None
        cur = await self.conn.execute(
            """SELECT id, reply FROM instant_replies
               WHERE ? = keyword OR ? LIKE keyword || '%'
               ORDER BY priority DESC, LENGTH(keyword) DESC LIMIT 1""",
            (key, key),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await self.conn.execute("UPDATE instant_replies SET uses=uses+1 WHERE id=?", (row["id"],))
        await self.conn.commit()
        return row["reply"]

    # ---------------------------------------------------------- quiz
    async def quiz_subjects(self):
        cur = await self.conn.execute(
            "SELECT subject, COUNT(*) AS c FROM quiz_questions GROUP BY subject ORDER BY c DESC"
        )
        return [(r["subject"], r["c"]) for r in await cur.fetchall()]

    async def start_quiz(self, user_id, subject):
        cur = await self.conn.execute(
            "SELECT id FROM quiz_questions WHERE subject=? ORDER BY RANDOM() LIMIT ?",
            (subject, QUIZ_QUESTIONS_PER_SESSION),
        )
        ids = [r["id"] for r in await cur.fetchall()]
        if not ids:
            return []
        ts = now_iso()
        await self.conn.execute(
            """INSERT INTO quiz_sessions(user_id, subject, question_ids, pos, score, started_at, updated_at)
               VALUES(?,?,?,0,0,?,?)
               ON CONFLICT(user_id) DO UPDATE SET subject=excluded.subject,
                 question_ids=excluded.question_ids, pos=0, score=0, updated_at=excluded.updated_at""",
            (user_id, subject, json.dumps(ids), ts, ts),
        )
        await self.conn.commit()
        return ids

    async def quiz_session(self, user_id):
        cur = await self.conn.execute("SELECT * FROM quiz_sessions WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["question_ids"] = json.loads(d["question_ids"] or "[]")
        return d

    async def quiz_question(self, qid):
        cur = await self.conn.execute("SELECT * FROM quiz_questions WHERE id=?", (qid,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["options"] = json.loads(d["options"] or "[]")
        return d

    async def advance_quiz(self, user_id, correct):
        s = await self.quiz_session(user_id)
        if not s:
            return None
        pos = s["pos"] + 1
        score = s["score"] + (1 if correct else 0)
        await self.conn.execute(
            "UPDATE quiz_sessions SET pos=?, score=?, updated_at=? WHERE user_id=?",
            (pos, score, now_iso(), user_id),
        )
        await self.conn.commit()
        return {"pos": pos, "score": score, "total": len(s["question_ids"]), "subject": s["subject"]}

    async def finish_quiz(self, user_id, subject, score, total):
        await self.conn.execute(
            "INSERT INTO quiz_results(user_id, subject, score, total, created_at) VALUES(?,?,?,?,?)",
            (user_id, subject, score, total, now_iso()),
        )
        await self.conn.execute("DELETE FROM quiz_sessions WHERE user_id=?", (user_id,))
        await self.conn.commit()

    # ---------------------------------------------------------- question bank / addq
    async def add_question(self, kind, title, body, meta=None, code=None, added_by=None):
        await self.conn.execute(
            """INSERT INTO question_bank(kind, title, body, meta, code, added_by, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (kind, title, body, json.dumps(meta or {}, ensure_ascii=False), code, added_by, now_iso()),
        )
        await self.conn.commit()

    async def search_bank(self, word=None, limit=20):
        if word:
            cur = await self.conn.execute(
                "SELECT id, kind, title, code FROM question_bank WHERE title LIKE ? OR body LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{word}%", f"%{word}%", limit),
            )
        else:
            cur = await self.conn.execute(
                "SELECT id, kind, title, code FROM question_bank ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]

    async def bank_count(self):
        cur = await self.conn.execute("SELECT COUNT(*) AS c FROM question_bank")
        row = await cur.fetchone()
        return row["c"] if row else 0

    async def is_admin(self, user_id):
        cur = await self.conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        return (await cur.fetchone()) is not None

    async def grant_admin(self, user_id, username=None, granted_by=None):
        await self.conn.execute(
            "INSERT OR IGNORE INTO admins(user_id, username, granted_by, created_at) VALUES(?,?,?,?)",
            (user_id, username, granted_by, now_iso()),
        )
        await self.conn.commit()

    async def addq_request(self, user_id, username, first_name):
        await self.conn.execute(
            """INSERT INTO addq_requests(user_id, username, first_name, status, created_at)
               VALUES(?,?,?,'pending',?)
               ON CONFLICT(user_id) DO UPDATE SET status='pending', created_at=excluded.created_at""",
            (user_id, username, first_name, now_iso()),
        )
        await self.conn.commit()

    async def request_status(self, user_id):
        cur = await self.conn.execute("SELECT status FROM addq_requests WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row["status"] if row else None

    async def set_request_status(self, user_id, status):
        await self.conn.execute("UPDATE addq_requests SET status=? WHERE user_id=?", (status, user_id))
        await self.conn.commit()

    # ---------------------------------------------------------- channels / posts
    async def add_channel(self, owner_id, channel_id, title, username):
        await self.conn.execute(
            """INSERT INTO channels(owner_id, channel_id, title, username, connected_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(channel_id) DO UPDATE SET owner_id=excluded.owner_id,
                 title=excluded.title, username=excluded.username""",
            (owner_id, str(channel_id), title, username, now_iso()),
        )
        await self.conn.commit()

    async def channels(self, owner_id=None):
        if owner_id:
            cur = await self.conn.execute(
                "SELECT * FROM channels WHERE owner_id=? ORDER BY id DESC", (owner_id,))
        else:
            cur = await self.conn.execute("SELECT * FROM channels ORDER BY id DESC")
        return [dict(r) for r in await cur.fetchall()]

    async def get_channel(self, channel_id):
        cur = await self.conn.execute("SELECT * FROM channels WHERE channel_id=?", (str(channel_id),))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def delete_channel(self, channel_id):
        await self.conn.execute("DELETE FROM channels WHERE channel_id=?", (str(channel_id),))
        await self.conn.commit()

    async def add_post(self, channel_id, text, run_at, repeat_min=0, media=None, created_by=None):
        await self.conn.execute(
            """INSERT INTO scheduled_posts(channel_id, text, media, run_at, repeat_min, created_by, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (str(channel_id), text, media, run_at, repeat_min, created_by, now_iso()),
        )
        await self.conn.commit()

    async def due_posts(self, now_iso_str):
        cur = await self.conn.execute(
            "SELECT * FROM scheduled_posts WHERE done=0 AND run_at<=? ORDER BY run_at LIMIT 20",
            (now_iso_str,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def mark_post_sent(self, post_id, repeat_min):
        if repeat_min and repeat_min > 0:
            cur = await self.conn.execute("SELECT run_at, sent_count FROM scheduled_posts WHERE id=?", (post_id,))
            row = await cur.fetchone()
            import datetime as _dt
            base = _dt.datetime.strptime(row["run_at"], "%Y-%m-%dT%H:%M:%SZ") if row else _dt.datetime.utcnow()
            nxt = (base + _dt.timedelta(minutes=repeat_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
            await self.conn.execute(
                "UPDATE scheduled_posts SET run_at=?, sent_count=sent_count+1 WHERE id=?", (nxt, post_id))
        else:
            await self.conn.execute(
                "UPDATE scheduled_posts SET done=1, sent_count=sent_count+1 WHERE id=?", (post_id,))
        await self.conn.commit()

    async def posts(self, limit=20):
        cur = await self.conn.execute(
            "SELECT * FROM scheduled_posts WHERE done=0 ORDER BY run_at LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]

    async def delete_post(self, post_id):
        await self.conn.execute("DELETE FROM scheduled_posts WHERE id=?", (post_id,))
        await self.conn.commit()

    # ---------------------------------------------------------- states
    async def set_state(self, user_id, state, payload=None):
        await self.conn.execute(
            """INSERT INTO user_states(user_id, state, payload, updated_at) VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET state=excluded.state,
                 payload=excluded.payload, updated_at=excluded.updated_at""",
            (user_id, state, json.dumps(payload or {}, ensure_ascii=False), now_iso()),
        )
        await self.conn.commit()

    async def get_state(self, user_id):
        cur = await self.conn.execute("SELECT state, payload FROM user_states WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return None, {}
        return row["state"], json.loads(row["payload"] or "{}")

    async def clear_state(self, user_id):
        await self.conn.execute("DELETE FROM user_states WHERE user_id=?", (user_id,))
        await self.conn.commit()

    # ---------------------------------------------------------- stats
    async def bump(self, key, amount=1):
        await self.conn.execute(
            """INSERT INTO stats(key, value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET value=stats.value+?""",
            (key, amount, amount),
        )
        await self.conn.commit()

    async def counters(self):
        cur = await self.conn.execute("SELECT key, value FROM stats")
        return {r["key"]: r["value"] for r in await cur.fetchall()}

    async def overview(self):
        out = {}
        for name, sql in (
            ("users", "SELECT COUNT(*) c FROM users"),
            ("messages", "SELECT COUNT(*) c FROM chat_history"),
            ("questions", "SELECT COUNT(*) c FROM question_bank"),
            ("quiz_questions", "SELECT COUNT(*) c FROM quiz_questions"),
            ("channels", "SELECT COUNT(*) c FROM channels"),
            ("scheduled", "SELECT COUNT(*) c FROM scheduled_posts WHERE done=0"),
        ):
            cur = await self.conn.execute(sql)
            out[name] = (await cur.fetchone())["c"]
        cur = await self.conn.execute(
            "SELECT subject, COUNT(*) c FROM chat_history WHERE topic IS NOT NULL GROUP BY subject=subject")
        return out

    async def top_topics(self, limit=8):
        cur = await self.conn.execute(
            "SELECT topic, COUNT(*) c FROM chat_history WHERE topic IS NOT NULL "
            "GROUP BY topic ORDER BY c DESC LIMIT ?", (limit,))
        return [(r["topic"], r["c"]) for r in await cur.fetchall()]


# ---------------------------------------------------------------- seeding
def _load_json(name, default):
    path = os.path.join(BASE_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log.warning("cannot load %s: %s", name, e)
        return default
