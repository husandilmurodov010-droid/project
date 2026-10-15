"""Ma'lumotlar bazasi qatlami (SQLite + aiosqlite).

Asosiy jadvallar:
  users            — foydalanuvchilar (user_id, ism, til, ro'yxatdan o'tgan vaqt, oxirgi faollik)
  chat_history     — suhbat tarixi (har bir savol-javob)
  instant_replies  — tezkor javoblar bazasi (kalit so'z -> javob)
  quiz_questions   — testlar bazasi (savol, variantlar, to'g'ri javob, mavzu/soha)
  quiz_sessions    — foydalanuvchining joriy test sessiyasi
  quiz_results     — test natijalari tarixi
  stats            — statistika (so'rovlar, sohalar bo'yicha hisob)

Yangi jadvallar (v3):
  ielts_speaking_questions — IELTS Speaking savollari (Part 1/2/3)
  ielts_writing_tasks      — IELTS Writing topshiriqlari (Task 1/2)
  math_tests               — matematika testlari (kod tizimi)
  physics_tests            — fizika testlari (kod tizimi)
  test_codes               — test kodlari reyestri (kod -> fan/test)
  test_submissions         — foydalanuvchi test javoblari tarixi
  pending_approvals        — admin tasdiqlashini kutayotgan testlar
  reminders                — foydalanuvchi eslatmalari
  question_bank            — savollar banki (foydalanuvchi savol-javoblari)
  user_states              — ko'p qadamli suhbat holati (masalan, test qo'shish)

Barcha metodlar async va xavfsiz (WAL rejimi, parametrlangan so'rovlar).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite

log = logging.getLogger("db")

# Fan -> jadval nomi
_TEST_TABLES = {"math": "math_tests", "physics": "physics_tests"}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    language      TEXT    DEFAULT 'uz',
    created_at    REAL    NOT NULL,
    last_seen     REAL    NOT NULL,
    msg_count     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    role       TEXT    NOT NULL,          -- 'user' | 'assistant'
    text       TEXT    NOT NULL,
    topic      TEXT,                      -- aniqlangan soha
    source     TEXT,                      -- 'instant' | 'ai' | 'quiz'
    created_at REAL    NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_history_user ON chat_history(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS instant_replies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword    TEXT    NOT NULL UNIQUE,   -- normallashtirilgan kalit so'z
    reply      TEXT    NOT NULL,
    category   TEXT    DEFAULT 'general',
    priority   INTEGER DEFAULT 0,
    hits       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    topic      TEXT    NOT NULL,          -- soha: matematika, tarix, ...
    question   TEXT    NOT NULL,
    options    TEXT    NOT NULL,          -- JSON massiv
    answer     INTEGER NOT NULL,          -- to'g'ri variant indeksi (0-based)
    explanation TEXT
);
CREATE INDEX IF NOT EXISTS idx_quiz_topic ON quiz_questions(topic);

CREATE TABLE IF NOT EXISTS quiz_sessions (
    user_id    INTEGER PRIMARY KEY,
    topic      TEXT    NOT NULL,
    question_ids TEXT  NOT NULL,          -- JSON massiv
    current    INTEGER DEFAULT 0,
    score      INTEGER DEFAULT 0,
    answers    TEXT    DEFAULT '[]',      -- JSON: [{"q":id,"chosen":i,"correct":bool}]
    started_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    topic      TEXT    NOT NULL,
    score      INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS stats (
    key        TEXT PRIMARY KEY,
    value      INTEGER DEFAULT 0
);

-- ===================== v3: yangi jadvallar =====================

CREATE TABLE IF NOT EXISTS ielts_speaking_questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    part          INTEGER NOT NULL,       -- 1 | 2 | 3
    topic         TEXT    DEFAULT '',
    question      TEXT    NOT NULL,
    cue_card      TEXT    DEFAULT '',     -- Part 2 uchun
    bullets       TEXT    DEFAULT '[]',   -- Part 2 cue card bandlari (JSON)
    prep_seconds  INTEGER DEFAULT 0,      -- Part 2: 60
    speak_seconds INTEGER DEFAULT 0       -- Part 2: 120
);
CREATE INDEX IF NOT EXISTS idx_speaking_part ON ielts_speaking_questions(part);

CREATE TABLE IF NOT EXISTS ielts_writing_tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task       INTEGER NOT NULL,          -- 1 | 2
    prompt     TEXT    NOT NULL,
    kind       TEXT    DEFAULT '',        -- 'graph' | 'letter' | 'opinion' | ...
    min_words  INTEGER DEFAULT 150
);
CREATE INDEX IF NOT EXISTS idx_writing_task ON ielts_writing_tasks(task);

CREATE TABLE IF NOT EXISTS math_tests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    NOT NULL UNIQUE,   -- MATH-0001
    title      TEXT    NOT NULL,
    questions  TEXT    NOT NULL,          -- JSON: [{"q":..,"options":[..]}]
    answers    TEXT    NOT NULL,          -- 'abcdfdddd' ko'rinishida
    created_by INTEGER,
    created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS physics_tests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    NOT NULL UNIQUE,   -- PHY-0001
    title      TEXT    NOT NULL,
    questions  TEXT    NOT NULL,
    answers    TEXT    NOT NULL,
    created_by INTEGER,
    created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS test_codes (
    code       TEXT    PRIMARY KEY,
    subject    TEXT    NOT NULL,          -- 'math' | 'physics'
    test_id    INTEGER NOT NULL,
    created_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS test_submissions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    code       TEXT    NOT NULL,
    subject    TEXT    NOT NULL,
    answers    TEXT    NOT NULL,          -- foydalanuvchi yuborgan 'abcdfdddd'
    correct    INTEGER NOT NULL,
    total      INTEGER NOT NULL,
    detail     TEXT    DEFAULT '[]',      -- JSON: har savol bo'yicha tahlil
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON test_submissions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS pending_approvals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    subject    TEXT    NOT NULL,
    payload    TEXT    NOT NULL,          -- JSON: test ma'lumotlari
    status     TEXT    DEFAULT 'pending', -- 'pending' | 'approved' | 'rejected'
    created_at REAL    NOT NULL,
    decided_by INTEGER,
    decided_at REAL
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    text       TEXT    NOT NULL,
    remind_at  REAL    NOT NULL,          -- unix timestamp
    sent       INTEGER DEFAULT 0,
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rem_due ON reminders(sent, remind_at);

CREATE TABLE IF NOT EXISTS question_bank (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    subject    TEXT    DEFAULT 'umumiy',
    question   TEXT    NOT NULL,
    answer     TEXT    NOT NULL,
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qbank_subject ON question_bank(subject);

CREATE TABLE IF NOT EXISTS user_states (
    user_id    INTEGER PRIMARY KEY,
    state      TEXT    NOT NULL,
    data       TEXT    DEFAULT '{}',
    updated_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    added_at   REAL    NOT NULL
);

-- ===================== v4: kanal boshqaruvi =====================

CREATE TABLE IF NOT EXISTS channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL UNIQUE,   -- -100...
    title        TEXT    DEFAULT '',
    username     TEXT    DEFAULT '',
    connected_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels(owner_id);

CREATE TABLE IF NOT EXISTS scheduled_posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id     INTEGER NOT NULL,
    text           TEXT    DEFAULT '',
    media_type     TEXT    DEFAULT '',      -- '' | 'photo' | 'document'
    media_file_id  TEXT    DEFAULT '',
    run_at         REAL    NOT NULL,
    repeat_minutes INTEGER DEFAULT 0,       -- 0 = bir marta
    sent           INTEGER DEFAULT 0,
    created_by     INTEGER,
    created_at     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spost_due ON scheduled_posts(sent, run_at);

-- ===================== v6: kanal tasdiqlash (bot kanalga admin qilinganda) =====================

CREATE TABLE IF NOT EXISTS pending_channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL UNIQUE,
    title        TEXT    DEFAULT '',
    username     TEXT    DEFAULT '',
    requested_by INTEGER,
    status       TEXT    DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected'
    created_at   REAL    NOT NULL,
    decided_by   INTEGER,
    decided_at   REAL
);

-- ===================== v5: PDF testlar =====================

CREATE TABLE IF NOT EXISTS pdf_tests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,   -- admin kiritgan kod (masalan '12345')
    title       TEXT    NOT NULL,
    subject     TEXT    DEFAULT 'umumiy',
    questions   TEXT    NOT NULL,          -- JSON: [{"n":1,"key":"1","q":"..","options":[..],"type":"mc"|"open"}]
    answers     TEXT    NOT NULL,          -- JSON: {"1":"a","36a":"2.3"}
    source_file TEXT    DEFAULT '',
    created_by  INTEGER,
    created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pdf_tests_code ON pdf_tests(code);

-- ============== v8: kanal o'sish dinamikasi va foydalanuvchi kontaktlari ==============

CREATE TABLE IF NOT EXISTS channel_member_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    members    INTEGER NOT NULL,
    taken_at   REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chsnap ON channel_member_snapshots(channel_id, taken_at);

CREATE TABLE IF NOT EXISTS user_contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    phone      TEXT    DEFAULT '',
    contact_id INTEGER,
    first_name TEXT    DEFAULT '',
    last_name  TEXT    DEFAULT '',
    username   TEXT    DEFAULT '',
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ucontact ON user_contacts(user_id);

-- ===== v9: kanal postlari faolligi (reaksiyalar + ko'rishlar) =====

CREATE TABLE IF NOT EXISTS post_engagement (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id       INTEGER NOT NULL,
    message_id       INTEGER NOT NULL,
    views            INTEGER,                 -- ko'rishlar (bo'lmasa NULL)
    reactions        TEXT    DEFAULT '',      -- JSON: {"👍":12,"❤":5}
    reactions_total  INTEGER,                 -- jami reaksiyalar
    reactions_emojis INTEGER,                 -- nechta xil emoji
    posted_at        REAL,                    -- post sanasi (unix)
    source           TEXT    DEFAULT '',      -- 'preview' | 'update' | 'post'
    updated_at       REAL    NOT NULL,
    UNIQUE(channel_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_posteng ON post_engagement(channel_id, reactions_total);

CREATE TABLE IF NOT EXISTS channel_engagement_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL,
    score           REAL    NOT NULL,          -- rivojlanish darajasi (0-100)
    reactions_total INTEGER DEFAULT 0,
    reactions_avg   REAL    DEFAULT 0,         -- o'rtacha reaksiya / post
    views_avg       REAL    DEFAULT 0,         -- o'rtacha ko'rish / post
    views_total     INTEGER DEFAULT 0,
    posts           INTEGER DEFAULT 0,
    emoji_top       TEXT    DEFAULT '',        -- eng ko'p ishlatilgan emoji
    taken_at        REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cheeng ON channel_engagement_snapshots(channel_id, taken_at);
"""


class Database:
    """SQLite bilan ishlash uchun yupqa async qatlam."""

    def __init__(self, path: str = "bot.db") -> None:
        self.path = path
        self._db: Optional[aiosqlite.Connection] = None

    # ------------------------------------------------------------------ #
    # Ulanish
    # ------------------------------------------------------------------ #
    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        log.info("Ma'lumotlar bazasi tayyor: %s", self.path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Baza ulanmagan — avval connect() chaqiring.")
        return self._db

    # ------------------------------------------------------------------ #
    # Foydalanuvchilar
    # ------------------------------------------------------------------ #
    async def upsert_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> None:
        now = time.time()
        await self.db.execute(
            """
            INSERT INTO users (user_id, username, first_name, created_at, last_seen, msg_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username   = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_seen  = excluded.last_seen,
                msg_count  = users.msg_count + 1
            """,
            (user_id, username, first_name, now, now),
        )
        await self.db.commit()

    async def get_user(self, user_id: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_language(self, user_id: int, lang: str) -> None:
        await self.db.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        await self.db.commit()

    async def get_language(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        return (user or {}).get("language") or "uz"

    async def count_users(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM users")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ================================================================== #
    # v10: foydalanuvchi o'sish dinamikasi (kunlik / oylik)
    # ================================================================== #
    # `users.created_at` — foydalanuvchi ro'yxatdan o'tgan vaqt (unix ts).
    # Quyidagi so'rovlar shu ustun bo'yicha guruhlab, yangi qo'shilgan
    # foydalanuvchilar sonini qaytaradi. `localtime` modifikatori orqali
    # vaqt serverning mahalliy zonasiga o'giriladi — kun/oy chegaralari
    # shu tufayli to'g'ri chiqadi.
    async def count_users_since(self, since_ts: float) -> int:
        """Berilgan vaqtdan keyin ro'yxatdan o'tgan foydalanuvchilar soni."""
        cur = await self.db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE created_at >= ?",
            (float(since_ts),),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def count_users_between(self, start_ts: float, end_ts: float) -> int:
        """[start_ts, end_ts) oralig'ida qo'shilganlar soni."""
        cur = await self.db.execute(
            "SELECT COUNT(*) AS c FROM users "
            "WHERE created_at >= ? AND created_at < ?",
            (float(start_ts), float(end_ts)),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def user_growth_daily(self, days: int = 30) -> list[tuple[str, int]]:
        """Oxirgi `days` kun uchun KUNLIK yangi foydalanuvchilar soni.

        Qaytaradi: ``[('2026-10-01', 5), ...]`` — sana bo'yicha o'sish
        tartibida (eng eskisi birinchi).
        """
        cur = await self.db.execute(
            "SELECT strftime('%Y-%m-%d', created_at, 'unixepoch', 'localtime') AS d, "
            "COUNT(*) AS c FROM users GROUP BY d ORDER BY d DESC LIMIT ?",
            (int(days),),
        )
        rows = await cur.fetchall()
        return [(str(r["d"]), int(r["c"])) for r in reversed(rows) if r["d"]]

    async def user_growth_monthly(self, months: int = 12) -> list[tuple[str, int]]:
        """Oxirgi `months` oy uchun OYLIK yangi foydalanuvchilar soni.

        Qaytaradi: ``[('2026-01', 12), ...]`` — oy bo'yicha o'sish tartibida.
        """
        cur = await self.db.execute(
            "SELECT strftime('%Y-%m', created_at, 'unixepoch', 'localtime') AS m, "
            "COUNT(*) AS c FROM users GROUP BY m ORDER BY m DESC LIMIT ?",
            (int(months),),
        )
        rows = await cur.fetchall()
        return [(str(r["m"]), int(r["c"])) for r in reversed(rows) if r["m"]]

    async def user_growth_summary(self) -> dict[str, Any]:
        """O'sish grafigi uchun qisqa xulosa ko'rsatkichlari.

        jami, bugun, 7 kun, shu oy (30 kun), o'rtacha kunlik va
        eng faol kun/oy.
        """
        now = time.time()
        total = await self.count_users()
        today = await self.count_users_since(now - 86400)
        week = await self.count_users_since(now - 7 * 86400)
        month = await self.count_users_since(now - 30 * 86400)
        daily = await self.user_growth_daily(30)
        monthly = await self.user_growth_monthly(12)
        avg_daily = round(month / 30, 1) if month else 0.0
        best_day = max(daily, key=lambda x: x[1]) if daily else ("", 0)
        best_month = max(monthly, key=lambda x: x[1]) if monthly else ("", 0)
        return {
            "total": total,
            "today": today,
            "week": week,
            "month": month,
            "avg_daily": avg_daily,
            "best_day": best_day,
            "best_month": best_month,
            "active_days": len(daily),
            "active_months": len(monthly),
        }

    # ------------------------------------------------------------------ #
    # Suhbat tarixi
    # ------------------------------------------------------------------ #
    async def add_history(
        self,
        user_id: int,
        role: str,
        text: str,
        topic: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO chat_history (user_id, role, text, topic, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, role, text[:4000], topic, source, time.time()),
        )
        await self.db.commit()

    async def get_history(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT role, text, topic, source, created_at
            FROM chat_history WHERE user_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def clear_history(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await self.db.commit()

    async def clear_conversation(self, user_id: int) -> int:
        """FAQAT shu foydalanuvchining suhbat kontekstini to'liq o'chiradi.

        `chat_history` (AI xotirasi) va `user_states` (joriy holat) shu
        foydalanuvchi uchun tozalanadi. Boshqa foydalanuvchilarga tegmaydi
        (barcha DELETE'lar `WHERE user_id = ?` bilan cheklangan).
        O'chirilgan suhbat qatlamlari sonini qaytaradi.
        """
        cur = await self.db.execute(
            "SELECT COUNT(*) AS c FROM chat_history WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        n = int(row["c"]) if row and row["c"] is not None else 0
        await self.db.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await self.db.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
        await self.db.commit()
        return n

    async def get_context_history(
        self, user_id: int, limit: int = 6
    ) -> list[dict[str, Any]]:
        """AI konteksti uchun oxirgi `limit` ta qatlamni XRONOLOGIK tartibda
        (eng eskisi birinchi) qaytaradi. Faqat 'user' va 'assistant' rollari.
        """
        cur = await self.db.execute(
            """
            SELECT role, text FROM chat_history
            WHERE user_id = ? AND role IN ('user', 'assistant')
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, max(0, int(limit))),
        )
        rows = await cur.fetchall()
        # DESC bilan olingan -> teskari aylantirib xronologik tartibga keltiramiz
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------ #
    # Tezkor javoblar
    # ------------------------------------------------------------------ #
    async def load_instant_replies(self, items: list[dict[str, Any]]) -> int:
        """JSON bazasidan tezkor javoblarni yuklaydi (mavjudlarini yangilaydi)."""
        count = 0
        for it in items:
            kw = (it.get("keyword") or "").strip().lower()
            reply = it.get("reply")
            if not kw or not reply:
                continue
            await self.db.execute(
                """
                INSERT INTO instant_replies (keyword, reply, category, priority)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(keyword) DO UPDATE SET
                    reply    = excluded.reply,
                    category = excluded.category,
                    priority = excluded.priority
                """,
                (kw, reply, it.get("category", "general"), int(it.get("priority", 0))),
            )
            count += 1
        await self.db.commit()
        log.info("Tezkor javoblar yuklandi: %d ta", count)
        return count

    async def get_instant_reply(self, keyword: str) -> Optional[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM instant_replies WHERE keyword = ?", (keyword.strip().lower(),)
        )
        row = await cur.fetchone()
        if not row:
            return None
        await self.db.execute(
            "UPDATE instant_replies SET hits = hits + 1 WHERE id = ?", (row["id"],)
        )
        await self.db.commit()
        d = dict(row)
        d["hits"] = int(d.get("hits", 0)) + 1  # yangilangan qiymatni qaytaramiz
        return d

    async def count_instant_replies(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM instant_replies")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------ #
    # Testlar (quiz)
    # ------------------------------------------------------------------ #
    async def load_quiz_questions(self, items: list[dict[str, Any]]) -> int:
        """JSON bazasidan test savollarini yuklaydi (dublikatlarni o'tkazib yuboradi)."""
        count = 0
        for it in items:
            q = (it.get("question") or "").strip()
            opts = it.get("options") or []
            if not q or len(opts) < 2:
                continue
            cur = await self.db.execute(
                "SELECT id FROM quiz_questions WHERE question = ?", (q,)
            )
            if await cur.fetchone():
                continue
            await self.db.execute(
                """
                INSERT INTO quiz_questions (topic, question, options, answer, explanation)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    it.get("topic", "umumiy"),
                    q,
                    json.dumps(opts, ensure_ascii=False),
                    int(it.get("answer", 0)),
                    it.get("explanation", ""),
                ),
            )
            count += 1
        await self.db.commit()
        log.info("Test savollari yuklandi: %d ta yangi", count)
        return count

    async def get_topics(self) -> list[str]:
        cur = await self.db.execute(
            "SELECT DISTINCT topic FROM quiz_questions ORDER BY topic"
        )
        rows = await cur.fetchall()
        return [r["topic"] for r in rows]

    async def count_questions(self, topic: Optional[str] = None) -> int:
        if topic:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS c FROM quiz_questions WHERE topic = ?", (topic,)
            )
        else:
            cur = await self.db.execute("SELECT COUNT(*) AS c FROM quiz_questions")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def pick_questions(self, topic: str, n: int = 5) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM quiz_questions WHERE topic = ? ORDER BY RANDOM() LIMIT ?",
            (topic, n),
        )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"])
            out.append(d)
        return out

    # --- Sessiya ---
    async def start_quiz(self, user_id: int, topic: str, question_ids: list[int]) -> None:
        await self.db.execute(
            """
            INSERT INTO quiz_sessions (user_id, topic, question_ids, current, score, answers, started_at)
            VALUES (?, ?, ?, 0, 0, '[]', ?)
            ON CONFLICT(user_id) DO UPDATE SET
                topic = excluded.topic,
                question_ids = excluded.question_ids,
                current = 0,
                score = 0,
                answers = '[]',
                started_at = excluded.started_at
            """,
            (user_id, topic, json.dumps(question_ids), time.time()),
        )
        await self.db.commit()

    async def get_quiz_session(self, user_id: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM quiz_sessions WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["question_ids"] = json.loads(d["question_ids"])
        d["answers"] = json.loads(d["answers"])
        return d

    async def get_question(self, qid: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM quiz_questions WHERE id = ?", (qid,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["options"] = json.loads(d["options"])
        return d

    async def record_answer(self, user_id: int, qid: int, chosen: int, correct: bool) -> None:
        sess = await self.get_quiz_session(user_id)
        if not sess:
            return
        answers = sess["answers"]
        answers.append({"q": qid, "chosen": chosen, "correct": correct})
        await self.db.execute(
            """
            UPDATE quiz_sessions
            SET current = current + 1,
                score = score + ?,
                answers = ?
            WHERE user_id = ?
            """,
            (1 if correct else 0, json.dumps(answers), user_id),
        )
        await self.db.commit()

    async def finish_quiz(self, user_id: int) -> Optional[dict[str, Any]]:
        sess = await self.get_quiz_session(user_id)
        if not sess:
            return None
        total = len(sess["question_ids"])
        await self.db.execute(
            """
            INSERT INTO quiz_results (user_id, topic, score, total, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, sess["topic"], sess["score"], total, time.time()),
        )
        await self.db.execute("DELETE FROM quiz_sessions WHERE user_id = ?", (user_id,))
        await self.db.commit()
        return {"topic": sess["topic"], "score": sess["score"], "total": total,
                "answers": sess["answers"]}

    async def get_quiz_results(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT topic, score, total, created_at FROM quiz_results
            WHERE user_id = ? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Statistika
    # ------------------------------------------------------------------ #
    async def bump(self, key: str, amount: int = 1) -> None:
        await self.db.execute(
            """
            INSERT INTO stats (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = value + ?
            """,
            (key, amount, amount),
        )
        await self.db.commit()

    async def get_stat(self, key: str) -> int:
        cur = await self.db.execute("SELECT value FROM stats WHERE key = ?", (key,))
        row = await cur.fetchone()
        return int(row["value"]) if row else 0

    async def get_all_stats(self) -> dict[str, int]:
        cur = await self.db.execute("SELECT key, value FROM stats")
        rows = await cur.fetchall()
        return {r["key"]: int(r["value"]) for r in rows}

    async def top_topics(self, limit: int = 5) -> list[tuple[str, int]]:
        cur = await self.db.execute(
            """
            SELECT topic, COUNT(*) AS c FROM chat_history
            WHERE topic IS NOT NULL AND topic != ''
            GROUP BY topic ORDER BY c DESC LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [(r["topic"], int(r["c"])) for r in rows]

    async def count_messages(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM chat_history")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ================================================================== #
    # v3: IELTS Speaking
    # ================================================================== #
    async def load_ielts_speaking(self, items: list[dict[str, Any]]) -> int:
        count = 0
        for it in items:
            q = (it.get("question") or "").strip()
            if not q:
                continue
            part = int(it.get("part", 1))
            cur = await self.db.execute(
                "SELECT id FROM ielts_speaking_questions WHERE part = ? AND question = ?",
                (part, q),
            )
            if await cur.fetchone():
                continue
            await self.db.execute(
                """
                INSERT INTO ielts_speaking_questions
                    (part, topic, question, cue_card, bullets, prep_seconds, speak_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    part,
                    it.get("topic", ""),
                    q,
                    it.get("cue_card", ""),
                    json.dumps(it.get("bullets", []), ensure_ascii=False),
                    int(it.get("prep_seconds", 0)),
                    int(it.get("speak_seconds", 0)),
                ),
            )
            count += 1
        await self.db.commit()
        log.info("IELTS Speaking savollari yuklandi: %d ta yangi", count)
        return count

    async def get_speaking_questions(self, part: int, limit: int = 1) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM ielts_speaking_questions WHERE part = ? ORDER BY RANDOM() LIMIT ?",
            (part, limit),
        )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["bullets"] = json.loads(d["bullets"] or "[]")
            out.append(d)
        return out

    async def count_speaking(self, part: Optional[int] = None) -> int:
        if part:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS c FROM ielts_speaking_questions WHERE part = ?", (part,)
            )
        else:
            cur = await self.db.execute("SELECT COUNT(*) AS c FROM ielts_speaking_questions")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ================================================================== #
    # v3: IELTS Writing
    # ================================================================== #
    async def load_ielts_writing(self, items: list[dict[str, Any]]) -> int:
        count = 0
        for it in items:
            p = (it.get("prompt") or "").strip()
            if not p:
                continue
            task = int(it.get("task", 1))
            cur = await self.db.execute(
                "SELECT id FROM ielts_writing_tasks WHERE task = ? AND prompt = ?", (task, p)
            )
            if await cur.fetchone():
                continue
            await self.db.execute(
                """
                INSERT INTO ielts_writing_tasks (task, prompt, kind, min_words)
                VALUES (?, ?, ?, ?)
                """,
                (task, p, it.get("kind", ""), int(it.get("min_words", 150))),
            )
            count += 1
        await self.db.commit()
        log.info("IELTS Writing topshiriqlari yuklandi: %d ta yangi", count)
        return count

    async def get_writing_tasks(self, task: int, limit: int = 1) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM ielts_writing_tasks WHERE task = ? ORDER BY RANDOM() LIMIT ?",
            (task, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_writing_task(self, tid: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM ielts_writing_tasks WHERE id = ?", (tid,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def count_writing(self, task: Optional[int] = None) -> int:
        if task:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS c FROM ielts_writing_tasks WHERE task = ?", (task,)
            )
        else:
            cur = await self.db.execute("SELECT COUNT(*) AS c FROM ielts_writing_tasks")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ================================================================== #
    # v3: Testlar (kod tizimi) — matematika / fizika
    # ================================================================== #
    async def next_test_code(self, subject: str) -> str:
        """Keyingi bo'sh test kodini yaratadi (MATH-0001 / PHY-0001)."""
        prefix = "MATH" if subject == "math" else "PHY"
        table = _TEST_TABLES.get(subject)
        if not table:
            raise ValueError(f"Noma'lum fan: {subject}")
        cur = await self.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
        row = await cur.fetchone()
        n = (int(row["c"]) if row else 0) + 1
        while True:
            code = f"{prefix}-{n:04d}"
            cur = await self.db.execute("SELECT 1 FROM test_codes WHERE code = ?", (code,))
            if not await cur.fetchone():
                return code
            n += 1

    async def add_test(
        self,
        subject: str,
        code: str,
        title: str,
        questions: list[dict[str, Any]],
        answers: str,
        created_by: Optional[int] = None,
    ) -> int:
        """Testni bazaga qo'shadi va kod reyestriga yozadi."""
        table = _TEST_TABLES.get(subject)
        if not table:
            raise ValueError(f"Noma'lum fan: {subject}")
        code = code.strip().upper()
        cur = await self.db.execute(
            f"""
            INSERT INTO {table} (code, title, questions, answers, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                title,
                json.dumps(questions, ensure_ascii=False),
                answers.strip().lower(),
                created_by,
                time.time(),
            ),
        )
        test_id = cur.lastrowid
        await self.db.execute(
            """
            INSERT OR REPLACE INTO test_codes (code, subject, test_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (code, subject, test_id, time.time()),
        )
        await self.db.commit()
        log.info("Test qo'shildi: %s (%s)", code, subject)
        return int(test_id)

    async def get_test_by_code(self, code: str) -> Optional[dict[str, Any]]:
        code = (code or "").strip().upper()
        cur = await self.db.execute("SELECT * FROM test_codes WHERE code = ?", (code,))
        row = await cur.fetchone()
        if not row:
            return None
        subject, test_id = row["subject"], row["test_id"]
        table = _TEST_TABLES.get(subject)
        if not table:
            return None
        cur = await self.db.execute(f"SELECT * FROM {table} WHERE id = ?", (test_id,))
        t = await cur.fetchone()
        if not t:
            return None
        d = dict(t)
        d["subject"] = subject
        d["questions"] = json.loads(d["questions"])
        return d

    async def list_tests(self, subject: str) -> list[dict[str, Any]]:
        table = _TEST_TABLES.get(subject)
        if not table:
            return []
        cur = await self.db.execute(
            f"SELECT id, code, title, created_at FROM {table} ORDER BY id"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_tests(self, subject: str) -> int:
        table = _TEST_TABLES.get(subject)
        if not table:
            return 0
        cur = await self.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def record_submission(
        self,
        user_id: int,
        code: str,
        subject: str,
        answers: str,
        correct: int,
        total: int,
        detail: list[dict[str, Any]],
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO test_submissions
                (user_id, code, subject, answers, correct, total, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, code, subject, answers, correct, total,
                json.dumps(detail, ensure_ascii=False), time.time(),
            ),
        )
        await self.db.commit()

    async def get_submissions(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT code, subject, correct, total, created_at FROM test_submissions
            WHERE user_id = ? ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ================================================================== #
    # v7: test ishlaganlar statistikasi (leaderboard)
    # ================================================================== #
    async def test_code_exists(self, code: str) -> bool:
        """Test kodi band yoki yo'qligini tekshiradi (math/physics reyestri)."""
        cur = await self.db.execute(
            "SELECT 1 FROM test_codes WHERE code = ?", ((code or "").strip().upper(),)
        )
        return await cur.fetchone() is not None

    async def count_test_takers(self) -> int:
        """Test ishlagan (kamida bitta topshirgan) foydalanuvchilar soni."""
        cur = await self.db.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM test_submissions"
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def user_test_count(self, user_id: int) -> int:
        """Bitta foydalanuvchi nechta test ishlaganini qaytaradi."""
        cur = await self.db.execute(
            "SELECT COUNT(*) AS c FROM test_submissions WHERE user_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def test_leaderboard(self, limit: int = 50) -> list[dict[str, Any]]:
        """Test ishlagan foydalanuvchilar ro'yxati: har biri nechta test ishlagan.

        Qaytaradi: user_id, username, first_name, tests_taken, total_correct,
        total_questions, last_at (oxirgi topshirilgan vaqt).
        """
        cur = await self.db.execute(
            """
            SELECT s.user_id                                   AS user_id,
                   COALESCE(u.username, '')                    AS username,
                   COALESCE(u.first_name, '')                  AS first_name,
                   COUNT(*)                                    AS tests_taken,
                   COALESCE(SUM(s.correct), 0)                 AS total_correct,
                   COALESCE(SUM(s.total), 0)                   AS total_questions,
                   MAX(s.created_at)                           AS last_at
            FROM test_submissions s
            LEFT JOIN users u ON u.user_id = s.user_id
            GROUP BY s.user_id
            ORDER BY tests_taken DESC, last_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ================================================================== #
    # v3: Admin tasdiqlash oqimi
    # ================================================================== #
    async def create_pending_approval(
        self, user_id: int, subject: str, payload: dict[str, Any]
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO pending_approvals (user_id, subject, payload, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (user_id, subject, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_pending_approval(self, aid: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM pending_approvals WHERE id = ?", (aid,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        return d

    async def set_approval_status(
        self, aid: int, status: str, decided_by: Optional[int] = None
    ) -> None:
        await self.db.execute(
            "UPDATE pending_approvals SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (status, decided_by, time.time(), aid),
        )
        await self.db.commit()

    async def list_pending_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM pending_approvals WHERE status = ? ORDER BY id", (status,)
        )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            out.append(d)
        return out

    # ================================================================== #
    # v3: Eslatmalar (reminders)
    # ================================================================== #
    async def add_reminder(self, user_id: int, text: str, remind_at: float) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO reminders (user_id, text, remind_at, sent, created_at)
            VALUES (?, ?, ?, 0, ?)
            """,
            (user_id, text, remind_at, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_due_reminders(self, now: Optional[float] = None) -> list[dict[str, Any]]:
        now = now if now is not None else time.time()
        cur = await self.db.execute(
            "SELECT * FROM reminders WHERE sent = 0 AND remind_at <= ? ORDER BY remind_at",
            (now,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def mark_reminder_sent(self, rid: int) -> None:
        await self.db.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (rid,))
        await self.db.commit()

    async def list_reminders(self, user_id: int, only_pending: bool = True) -> list[dict[str, Any]]:
        if only_pending:
            cur = await self.db.execute(
                "SELECT * FROM reminders WHERE user_id = ? AND sent = 0 ORDER BY remind_at",
                (user_id,),
            )
        else:
            cur = await self.db.execute(
                "SELECT * FROM reminders WHERE user_id = ? ORDER BY remind_at DESC LIMIT 20",
                (user_id,),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete_reminder(self, rid: int, user_id: int) -> None:
        await self.db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?", (rid, user_id)
        )
        await self.db.commit()

    # ================================================================== #
    # v3: Savollar banki
    # ================================================================== #
    async def add_question_bank(
        self, user_id: Optional[int], subject: str, question: str, answer: str
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO question_bank (user_id, subject, question, answer, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, subject, question, answer, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def search_question_bank(
        self, query: Optional[str] = None, subject: Optional[str] = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM question_bank WHERE 1=1"
        params: list[Any] = []
        if subject:
            sql += " AND subject = ?"
            params.append(subject)
        if query:
            sql += " AND (question LIKE ? OR answer LIKE ?)"
            params += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cur = await self.db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_question_bank(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM question_bank")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ================================================================== #
    # v3: Ko'p qadamli suhbat holati
    # ================================================================== #
    async def set_user_state(
        self, user_id: int, state: str, data: Optional[dict[str, Any]] = None
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO user_states (user_id, state, data, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state,
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (user_id, state, json.dumps(data or {}, ensure_ascii=False), time.time()),
        )
        await self.db.commit()

    async def get_user_state(self, user_id: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM user_states WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data"] or "{}")
        return d

    async def clear_user_state(self, user_id: int) -> None:
        await self.db.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
        await self.db.commit()

    # ================================================================== #
    # v3: Adminlar reyestri
    # ================================================================== #
    async def register_admin(self, user_id: int, username: Optional[str] = None) -> None:
        """Adminni bazaga yozadi (username bo'yicha topilgan adminlar uchun)."""
        await self.db.execute(
            """
            INSERT INTO admins (user_id, username, added_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username = COALESCE(excluded.username, admins.username)
            """,
            (user_id, username, time.time()),
        )
        await self.db.commit()

    async def get_registered_admins(self) -> list[int]:
        cur = await self.db.execute("SELECT user_id FROM admins")
        rows = await cur.fetchall()
        return [int(r["user_id"]) for r in rows]

    async def get_user_ids_by_usernames(self, usernames: list[str]) -> list[int]:
        """Berilgan username(lar)ga mos foydalanuvchi ID larini topadi.

        Adminni RAQAMLI ID bo'yicha aniqlash uchun ishlatiladi: ADMIN_ID
        o'rnatilmagan bo'lsa ham, ADMIN_USERNAME orqali uning ID si topiladi
        (foydalanuvchi botga kamida bir marta yozgan bo'lishi kerak).
        """
        if not usernames:
            return []
        found: set[int] = set()
        for un in usernames:
            un = (un or "").strip().lstrip("@")
            if not un:
                continue
            for table in ("users", "admins"):
                try:
                    cur = await self.db.execute(
                        f"SELECT user_id FROM {table} "
                        "WHERE lower(username) = lower(?)",
                        (un,),
                    )
                    for r in await cur.fetchall():
                        found.add(int(r["user_id"]))
                except Exception as exc:  # noqa: BLE001
                    log.debug("username qidiruv xato (%s): %s", table, exc)
        found.discard(0)
        return sorted(found)

    # ================================================================== #
    # v4: Savol qo'shish (IELTS Speaking / Writing)
    # ================================================================== #
    async def add_speaking_question(
        self, part: int, question: str, topic: str = "", cue_card: str = "",
        bullets: Optional[list[str]] = None, prep_seconds: int = 0, speak_seconds: int = 0,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO ielts_speaking_questions
                (part, topic, question, cue_card, bullets, prep_seconds, speak_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (part, topic, question, cue_card,
             json.dumps(bullets or [], ensure_ascii=False), prep_seconds, speak_seconds),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def add_writing_task(
        self, task: int, prompt: str, kind: str = "", min_words: int = 0
    ) -> int:
        if not min_words:
            min_words = 150 if task == 1 else 250
        cur = await self.db.execute(
            """
            INSERT INTO ielts_writing_tasks (task, prompt, kind, min_words)
            VALUES (?, ?, ?, ?)
            """,
            (task, prompt, kind, min_words),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    # ================================================================== #
    # v4: Kanallar
    # ================================================================== #
    async def add_channel(
        self, owner_id: int, channel_id: int, title: str = "", username: str = ""
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO channels (owner_id, channel_id, title, username, connected_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                owner_id = excluded.owner_id,
                title    = excluded.title,
                username = excluded.username
            """,
            (owner_id, channel_id, title, username, time.time()),
        )
        await self.db.commit()

    async def get_channel(self, channel_id: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_channels(self, owner_id: Optional[int] = None) -> list[dict[str, Any]]:
        if owner_id is None:
            cur = await self.db.execute("SELECT * FROM channels ORDER BY id DESC")
        else:
            cur = await self.db.execute(
                "SELECT * FROM channels WHERE owner_id = ? ORDER BY id DESC", (owner_id,)
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete_channel(self, channel_id: int, owner_id: Optional[int] = None) -> None:
        if owner_id is None:
            await self.db.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        else:
            await self.db.execute(
                "DELETE FROM channels WHERE channel_id = ? AND owner_id = ?",
                (channel_id, owner_id),
            )
        await self.db.commit()

    async def count_channels(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM channels")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def count_channel_posts(self, channel_id: int, sent_only: bool = False) -> int:
        """Kanal uchun rejalashtirilgan (yoki yuborilgan) postlar soni."""
        if sent_only:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS c FROM scheduled_posts WHERE channel_id = ? AND sent = 1",
                (channel_id,),
            )
        else:
            cur = await self.db.execute(
                "SELECT COUNT(*) AS c FROM scheduled_posts WHERE channel_id = ?",
                (channel_id,),
            )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    # ================================================================== #
    # v8: kanal statistikasi (o'sish dinamikasi) va kontaktlar
    # ================================================================== #
    async def record_channel_snapshot(self, channel_id: int, members: int) -> None:
        """Kanal a'zolari sonini vaqt bo'yicha yozib boradi (o'sishni hisoblash uchun)."""
        await self.db.execute(
            "INSERT INTO channel_member_snapshots (channel_id, members, taken_at) "
            "VALUES (?, ?, ?)",
            (int(channel_id), int(members), time.time()),
        )
        await self.db.commit()

    async def get_channel_growth(self, channel_id: int) -> dict[str, Any]:
        """Kanal rivojlanish darajasi: hozirgi son, 24 soat va 7 kunlik o'sish."""
        now = time.time()
        cur = await self.db.execute(
            "SELECT members, taken_at FROM channel_member_snapshots "
            "WHERE channel_id = ? ORDER BY taken_at ASC",
            (int(channel_id),),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            return {}
        first, last = rows[0], rows[-1]

        def _at_or_before(ts: float) -> dict[str, Any]:
            best = first
            for r in rows:
                if float(r["taken_at"]) <= ts:
                    best = r
                else:
                    break
            return best

        base_24 = _at_or_before(now - 86400)
        base_7 = _at_or_before(now - 7 * 86400)
        cur_m = int(last["members"])
        return {
            "current": cur_m,
            "first": int(first["members"]),
            "first_at": float(first["taken_at"]),
            "growth_total": cur_m - int(first["members"]),
            "growth_24h": cur_m - int(base_24["members"]),
            "growth_7d": cur_m - int(base_7["members"]),
            "samples": len(rows),
        }

    async def get_channel_post_metrics(self, channel_id: int) -> dict[str, int]:
        """Kanal postlari ko'rsatkichlari: jami / yuborilgan / kutilayotgan."""
        cur = await self.db.execute(
            "SELECT COUNT(*) AS c, "
            "SUM(CASE WHEN sent = 1 THEN 1 ELSE 0 END) AS s "
            "FROM scheduled_posts WHERE channel_id = ?",
            (int(channel_id),),
        )
        row = await cur.fetchone()
        total = int(row["c"] or 0) if row else 0
        sent = int(row["s"] or 0) if row else 0
        return {"total": total, "sent": sent, "pending": total - sent}

    async def add_user_contact(
        self,
        user_id: int,
        phone: str = "",
        contact_id: Optional[int] = None,
        first_name: str = "",
        last_name: str = "",
        username: str = "",
    ) -> None:
        """Foydalanuvchi ulashgan kontaktni saqlaydi (admin bog'lanishi uchun)."""
        await self.db.execute(
            "INSERT INTO user_contacts "
            "(user_id, phone, contact_id, first_name, last_name, username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(user_id), phone or "", contact_id,
                first_name or "", last_name or "", username or "", time.time(),
            ),
        )
        await self.db.commit()

    # ================================================================== #
    # v9: kanal postlari faolligi — reaksiyalar va ko'rishlar
    # ================================================================== #
    async def upsert_post_engagement(
        self,
        channel_id: int,
        message_id: int,
        views: Optional[int] = None,
        reactions_json: str = "",
        reactions_total: Optional[int] = None,
        reactions_emojis: Optional[int] = None,
        posted_at: Optional[float] = None,
        source: str = "",
    ) -> None:
        """Bitta kanal postining ko'rish va reaksiya ko'rsatkichlarini yozadi.

        Faqat berilgan maydonlar yangilanadi (COALESCE) — masalan faqat
        reaksiyalar kelganda ko'rishlar soni saqlanib qoladi.
        """
        await self.db.execute(
            """
            INSERT INTO post_engagement
                (channel_id, message_id, views, reactions, reactions_total,
                 reactions_emojis, posted_at, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id, message_id) DO UPDATE SET
                views            = COALESCE(excluded.views, post_engagement.views),
                reactions        = CASE WHEN excluded.reactions != ''
                                        THEN excluded.reactions
                                        ELSE post_engagement.reactions END,
                reactions_total  = COALESCE(excluded.reactions_total, post_engagement.reactions_total),
                reactions_emojis = COALESCE(excluded.reactions_emojis, post_engagement.reactions_emojis),
                posted_at        = COALESCE(excluded.posted_at, post_engagement.posted_at),
                source           = CASE WHEN excluded.source != ''
                                        THEN excluded.source
                                        ELSE post_engagement.source END,
                updated_at       = excluded.updated_at
            """,
            (
                int(channel_id), int(message_id), views, reactions_json or "",
                reactions_total, reactions_emojis, posted_at, source or "",
                time.time(),
            ),
        )
        await self.db.commit()

    async def list_post_engagement(
        self, channel_id: int, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Kanal postlarining faollik ko'rsatkichlari (reaksiya bo'yicha kamayish)."""
        cur = await self.db.execute(
            "SELECT * FROM post_engagement WHERE channel_id = ? "
            "ORDER BY COALESCE(reactions_total, 0) DESC, COALESCE(views, 0) DESC "
            "LIMIT ?",
            (int(channel_id), int(limit)),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_post_engagement(self, channel_id: int) -> int:
        cur = await self.db.execute(
            "SELECT COUNT(*) AS c FROM post_engagement WHERE channel_id = ?",
            (int(channel_id),),
        )
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def add_channel_engagement_snapshot(
        self,
        channel_id: int,
        score: float,
        reactions_total: int = 0,
        reactions_avg: float = 0,
        views_avg: float = 0,
        views_total: int = 0,
        posts: int = 0,
        emoji_top: str = "",
    ) -> None:
        """Kanal faolligi (rivojlanish darajasi) ko'rsatkichlarini vaqt bo'yicha yozadi."""
        await self.db.execute(
            "INSERT INTO channel_engagement_snapshots "
            "(channel_id, score, reactions_total, reactions_avg, views_avg, "
            " views_total, posts, emoji_top, taken_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(channel_id), float(score), int(reactions_total),
                float(reactions_avg), float(views_avg), int(views_total),
                int(posts), emoji_top or "", time.time(),
            ),
        )
        await self.db.commit()

    async def get_channel_engagement(self, channel_id: int) -> dict[str, Any]:
        """Oxirgi va oldingi faollik suratini qaytaradi (dinamika uchun)."""
        cur = await self.db.execute(
            "SELECT * FROM channel_engagement_snapshots WHERE channel_id = ? "
            "ORDER BY taken_at DESC LIMIT 2",
            (int(channel_id),),
        )
        rows = [dict(r) for r in await cur.fetchall()]
        if not rows:
            return {"latest": None, "previous": None, "samples": 0}
        cur2 = await self.db.execute(
            "SELECT COUNT(*) AS c FROM channel_engagement_snapshots WHERE channel_id = ?",
            (int(channel_id),),
        )
        crow = await cur2.fetchone()
        return {
            "latest": rows[0],
            "previous": rows[1] if len(rows) > 1 else None,
            "samples": int(crow["c"]) if crow else len(rows),
        }

    # ================================================================== #
    # v6: kanal tasdiqlash oqimi (bot kanalga admin qilinganda)
    # ================================================================== #
    async def create_pending_channel(
        self, channel_id: int, title: str = "", username: str = "",
        requested_by: Optional[int] = None,
    ) -> int:
        """Kanal uchun tasdiqlash so'rovini yaratadi (yoki yangilaydi) va id qaytaradi."""
        await self.db.execute(
            """
            INSERT INTO pending_channels
                (channel_id, title, username, requested_by, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                title        = excluded.title,
                username     = excluded.username,
                requested_by = excluded.requested_by,
                status       = 'pending'
            """,
            (channel_id, title, username, requested_by, time.time()),
        )
        await self.db.commit()
        cur = await self.db.execute(
            "SELECT id FROM pending_channels WHERE channel_id = ?", (channel_id,)
        )
        row = await cur.fetchone()
        return int(row["id"]) if row else 0

    async def get_pending_channel(self, cid: int) -> Optional[dict[str, Any]]:
        cur = await self.db.execute("SELECT * FROM pending_channels WHERE id = ?", (cid,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def set_pending_channel_status(
        self, cid: int, status: str, decided_by: Optional[int] = None
    ) -> None:
        await self.db.execute(
            "UPDATE pending_channels SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
            (status, decided_by, time.time(), cid),
        )
        await self.db.commit()

    async def list_pending_channels(self, status: str = "pending") -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT * FROM pending_channels WHERE status = ? ORDER BY id", (status,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ================================================================== #
    # v4: Rejalashtirilgan postlar
    # ================================================================== #
    async def add_scheduled_post(
        self, channel_id: int, text: str, run_at: float, media_type: str = "",
        media_file_id: str = "", repeat_minutes: int = 0, created_by: Optional[int] = None,
    ) -> int:
        cur = await self.db.execute(
            """
            INSERT INTO scheduled_posts
                (channel_id, text, media_type, media_file_id, run_at,
                 repeat_minutes, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (channel_id, text, media_type, media_file_id, run_at,
             repeat_minutes, created_by, time.time()),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_due_scheduled_posts(self, now: Optional[float] = None) -> list[dict[str, Any]]:
        now = now or time.time()
        cur = await self.db.execute(
            "SELECT * FROM scheduled_posts WHERE sent = 0 AND run_at <= ? ORDER BY run_at",
            (now,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def mark_post_sent(self, pid: int) -> None:
        await self.db.execute("UPDATE scheduled_posts SET sent = 1 WHERE id = ?", (pid,))
        await self.db.commit()

    async def reschedule_post(self, pid: int, next_run_at: float) -> None:
        await self.db.execute(
            "UPDATE scheduled_posts SET run_at = ?, sent = 0 WHERE id = ?",
            (next_run_at, pid),
        )
        await self.db.commit()

    async def list_scheduled_posts(
        self, channel_id: Optional[int] = None, only_pending: bool = True
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM scheduled_posts WHERE 1=1"
        params: list[Any] = []
        if channel_id is not None:
            sql += " AND channel_id = ?"
            params.append(channel_id)
        if only_pending:
            sql += " AND sent = 0"
        sql += " ORDER BY run_at"
        cur = await self.db.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def delete_scheduled_post(self, pid: int) -> None:
        await self.db.execute("DELETE FROM scheduled_posts WHERE id = ?", (pid,))
        await self.db.commit()

    # ================================================================== #
    # v5: PDF testlar (kod bilan kodlangan, ochiq savollarni qo'llab-quvvatlaydi)
    # ================================================================== #
    async def add_pdf_test(
        self,
        code: str,
        title: str,
        questions: list[dict[str, Any]],
        answers: dict[str, str],
        subject: str = "umumiy",
        source_file: str = "",
        created_by: Optional[int] = None,
    ) -> int:
        """PDF dan olingan testni bazaga qo'shadi (kod unikal bo'lishi shart)."""
        code = (code or "").strip()
        cur = await self.db.execute(
            """
            INSERT INTO pdf_tests
                (code, title, subject, questions, answers, source_file, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                title,
                subject,
                json.dumps(questions, ensure_ascii=False),
                json.dumps(answers, ensure_ascii=False),
                source_file,
                created_by,
                time.time(),
            ),
        )
        await self.db.commit()
        log.info("PDF test qo'shildi: %s (%s savol)", code, len(questions))
        return int(cur.lastrowid)

    async def get_pdf_test_by_code(self, code: str) -> Optional[dict[str, Any]]:
        code = (code or "").strip()
        cur = await self.db.execute("SELECT * FROM pdf_tests WHERE code = ?", (code,))
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["questions"] = json.loads(d["questions"] or "[]")
        d["answers"] = json.loads(d["answers"] or "{}")
        return d

    async def pdf_test_code_exists(self, code: str) -> bool:
        cur = await self.db.execute(
            "SELECT 1 FROM pdf_tests WHERE code = ?", ((code or "").strip(),)
        )
        return await cur.fetchone() is not None

    async def list_pdf_tests(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            "SELECT id, code, title, subject, created_at FROM pdf_tests "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def count_pdf_tests(self) -> int:
        cur = await self.db.execute("SELECT COUNT(*) AS c FROM pdf_tests")
        row = await cur.fetchone()
        return int(row["c"]) if row else 0

    async def delete_pdf_test(self, code: str) -> None:
        await self.db.execute("DELETE FROM pdf_tests WHERE code = ?", ((code or "").strip(),))
        await self.db.commit()
