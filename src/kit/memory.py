"""Kit's memory, kept in one SQLite file in the data folder.

- **Conversation:** every message, in order. Each exchange is also indexed so
  Kit can find something said weeks ago.
- **Facts:** things Kit has learned about Dan, his projects, where things are
  kept, people and plans. Each has a kind, a date, an importance and its
  history; outdated facts are superseded, not deleted, and important ones can
  be pinned so they're always in mind. "Now" facts (how Dan's been lately) fade
  after two weeks, and a plan knows its date, so a past one isn't upcoming.
- **Days:** a summary of each finished day, so "what were we doing last
  Tuesday?" has an answer.
- **Spend:** what each Claude call cost.
- **Kit himself:** his own notebook (thoughts, opinions, wants, moments and a
  journal, ``kit.notebook``), his self-sheet, and small things such as the
  quirks he picked (``kit_self``).

Facts, days, exchanges and Kit's notebook all live in the knowledge index
(``kit.knowledge``), which later stages extend with notes, documents and projects.
"""

from __future__ import annotations

import functools
import json
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from kit import knowledge
from kit.knowledge import Index, Item
from kit.when import date_in

Clock = Callable[[], datetime]

RECALL_STEP = "recall-step"  # a message source for Kit's "Let me think..." turns
CHAT_FROM = "chat_from"  # kit_self key: the last message before the current chat
# "Keep it local": that message, and Kit's answer to it, never go to a cloud model. Nor
# does what Kit kept from it: facts, notes and summaries are marked private in their
# meta, and his own lines from it (a reminder Dan asked for that way) are listed here.
KEEP_LOCAL = re.compile(
    r"\b(keep (it|this) local|answer (it )?locally|don'?t ask (claude|the cloud|anyone))\b",
    re.IGNORECASE,
)
PRIVATE_SAID = "private_said"  # kit_self key: ids of Kit's lines from what Dan kept local
PRIVATE_KEPT = 200  # the newest this many are listed; older ones are long out of the history

FACTS = "memory"
DAYS = "days"
CONVERSATION = "conversation"
SELF = "self"  # Kit's own notebook: what he thinks, wants and keeps (kit.notebook)
SHEET = "self-sheet"  # who Kit thinks he is, and reviews of it: always in mind, never recalled
FACT_KINDS = {
    "about": "who the owner is: work, background, health, habits",
    "preference": "likes, dislikes and how they want things done",
    "project": "something they're working on, its state and decisions",
    "place": "where something is kept: folders, files, apps, sites",
    "person": "someone in their life and how they relate",
    "plan": "something coming up or intended, with dates",
    "now": "how they've been or what's going on lately (flat out, crook, a visitor "
    "staying): fades after two weeks",
    "other": "anything else worth keeping",
}
# How much each kind of fact matters to Dan's life, 0 to 1, unless the nightly summary
# says (kit.learning). It weighs recall a little (kit.recall).
IMPORTANCE = {
    "person": 0.8,
    "about": 0.7,
    "preference": 0.6,
    "plan": 0.6,
    "now": 0.5,
    "project": 0.5,
    "place": 0.5,
    "other": 0.4,
}
NOW_DAYS = 14  # how long a "now" fact lasts (memory.now_days)

MIGRATIONS = [
    # 1: the first schema.
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        day TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'kit')),
        text TEXT NOT NULL,
        reply_json TEXT,
        source TEXT
    );
    CREATE INDEX IF NOT EXISTS messages_day ON messages(day);
    CREATE TABLE IF NOT EXISTS summarised_days (day TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS spend (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        month TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        cost_usd REAL NOT NULL,
        question TEXT NOT NULL
    );
    """,
    # 2: the knowledge index (facts, day summaries, conversation and later sources).
    knowledge.SCHEMA,
    # 3: which way each message came in (kit.channels): desk, voice, phone, web, terminal.
    "ALTER TABLE messages ADD COLUMN channel TEXT;",
    # 4: things about Kit himself, such as the quirks he picked (kit.life).
    "CREATE TABLE IF NOT EXISTS kit_self (key TEXT PRIMARY KEY, value TEXT NOT NULL);",
]


@dataclass(frozen=True)
class Message:
    id: int
    at: str
    role: str
    text: str
    reply_json: str | None = None
    source: str | None = None
    channel: str | None = None


@dataclass(frozen=True)
class Spend:
    at: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    question: str


def local_now() -> datetime:
    return datetime.now().astimezone()


def _locked(method):
    """The API serves requests on several threads; one connection, one at a time."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class Memory:
    def __init__(self, db_path: Path, clock: Clock = local_now) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self.clock = clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.index = Index(self.db, self._lock, clock)

    def _migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.db:
                self.db.executescript(script)
                self.db.execute(f"PRAGMA user_version = {number}")

    @_locked
    def close(self) -> None:
        self.db.close()

    def today(self) -> str:
        return self.clock().date().isoformat()

    # Kit himself

    @_locked
    def self_value(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM kit_self WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    @_locked
    def set_self_value(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO kit_self (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # Conversation

    @_locked
    def add_message(
        self,
        role: str,
        text: str,
        reply_json: str | None = None,
        source: str | None = None,
        channel: str | None = None,
    ) -> int:
        now = self.clock()
        with self.db:
            cur = self.db.execute(
                "INSERT INTO messages (at, day, role, text, reply_json, source, channel)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(timespec="seconds"),
                    now.date().isoformat(),
                    role,
                    text,
                    reply_json,
                    source,
                    channel,
                ),
            )
        return int(cur.lastrowid)

    @_locked
    def recent(self, limit: int) -> list[Message]:
        """The latest turns as the model should see them: a recall step ("Let me
        think...") is a working note, not a turn, so it's left out, and nothing
        from before the last new chat is."""
        rows = self.db.execute(
            "SELECT id, at, role, text, reply_json, source, channel FROM messages"
            " WHERE id > ? AND (source IS NULL OR source != ?) ORDER BY id DESC LIMIT ?",
            (int(self.self_value(CHAT_FROM) or 0), RECALL_STEP, limit),
        ).fetchall()
        return [Message(*row) for row in reversed(rows)]

    @_locked
    def new_chat(self) -> None:
        """Start a fresh conversation: earlier turns leave the chat history (and stop
        being copied by the model) but stay in the log, day summaries and recall."""
        row = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()
        self.set_self_value(CHAT_FROM, str(row[0]))

    @_locked
    def previous_chat(self, limit: int = 12) -> list[Message]:
        """The end of the conversation before the current one (``new_chat``), oldest
        first, recall steps left out: what a new chat picks one thing up from."""
        rows = self.db.execute(
            "SELECT id, at, role, text, reply_json, source, channel FROM messages"
            " WHERE id <= ? AND (source IS NULL OR source != ?) ORDER BY id DESC LIMIT ?",
            (int(self.self_value(CHAT_FROM) or 0), RECALL_STEP, limit),
        ).fetchall()
        return [Message(*row) for row in reversed(rows)]

    def said_privately(self, message_id: int) -> None:
        """Kit's line ``message_id`` came from something Dan kept local."""
        said = self.private_said()
        said.add(message_id)
        self.set_self_value(PRIVATE_SAID, json.dumps(sorted(said)[-PRIVATE_KEPT:]))

    def private_said(self) -> set[int]:
        try:
            said = json.loads(self.self_value(PRIVATE_SAID) or "[]")
        except ValueError:
            return set()
        return {i for i in said if isinstance(i, int)} if isinstance(said, list) else set()

    def shared(self, messages: list[Message]) -> list[Message]:
        """The messages fit for a cloud model: whatever Dan said to keep local and
        Kit's answer to it left out, and Kit's lines from it."""
        out, held, private = [], False, self.private_said()
        for m in messages:
            if m.role == "user":
                held = bool(KEEP_LOCAL.search(m.text))
            if not held and m.id not in private:
                out.append(m)
        return out

    @_locked
    def set_message_source(self, message_id: int, source: str) -> None:
        with self.db:
            self.db.execute("UPDATE messages SET source = ? WHERE id = ?", (source, message_id))

    @_locked
    def messages_on(self, day: str) -> list[Message]:
        rows = self.db.execute(
            "SELECT id, at, role, text, reply_json, source, channel FROM messages"
            " WHERE day = ? ORDER BY id",
            (day,),
        ).fetchall()
        return [Message(*row) for row in rows]

    def index_exchange(
        self, user_msg_id: int, owner: str, user_text: str, name: str, reply_text: str
    ) -> int:
        """Make one exchange findable later."""
        return self.index.add(
            CONVERSATION,
            "exchange",
            f"{owner}: {user_text}\n{name}: {reply_text}",
            ref=str(user_msg_id),
        )

    # Facts

    def add_fact(
        self,
        text: str,
        kind: str = "other",
        pinned: bool = False,
        source_ref: str | None = None,
        importance: float | None = None,
        private: bool = False,
    ) -> int:
        """A new fact. A plan keeps the date it's for, so once it's gone Kit knows it's
        past; a "now" fact is never pinned, since it fades. A ``private`` one came from
        what Dan kept local, and never goes to a cloud model."""
        kind = kind if kind in FACT_KINDS else "other"
        weight = IMPORTANCE[kind] if importance is None else max(0.0, min(1.0, importance))
        meta: dict = {"importance": round(weight, 2)}
        if private:
            meta["private"] = True
        if kind == "plan" and (day := date_in(text, self.clock())) is not None:
            meta["when"] = day.isoformat()
        pinned = pinned and kind != "now"
        return self.index.add(FACTS, kind, text.strip(), ref=source_ref, pinned=pinned, meta=meta)

    def replace_fact(
        self,
        old_id: int,
        text: str,
        kind: str | None = None,
        source_ref: str | None = None,
        private: bool = False,
    ) -> int:
        """``text`` in place of fact ``old_id``. It stays private if either was."""
        old = self.index.get(old_id)
        kind = kind or (old.kind if old else "other")
        importance = old.meta.get("importance") if old and old.kind == kind else None
        new_id = self.add_fact(
            text,
            kind,
            source_ref=source_ref or (old.ref if old else None),
            importance=float(importance) if isinstance(importance, int | float) else None,
            private=private or bool(old and old.meta.get("private")),
        )
        self.index.supersede(old_id, new_id)
        if kind == "now":
            self.index.set_pinned(new_id, False)
        return new_id

    def tidy_now(self, days: int = NOW_DAYS) -> int:
        """ "Now" facts older than ``days`` go (how Dan's been lately is soon old news;
        the day summaries keep the gist). Returns how many went."""
        cutoff = (self.clock() - timedelta(days=days)).isoformat(timespec="seconds")
        old = [f.id for f in self.index.items(FACTS, kind="now") if f.created < cutoff]
        return sum(self.index.delete(i) for i in old)

    def facts(self, limit: int = 10_000) -> list[Item]:
        """Current facts, oldest first."""
        return self.index.items(FACTS, limit=limit)

    def pinned_facts(self) -> list[Item]:
        return self.index.items(FACTS, pinned_only=True)

    def forget(self, fact_id: int, conversation: bool = False) -> bool:
        """Delete a fact. With ``conversation``, a past exchange Kit shouldn't recall
        (e.g. a reply it keeps parroting) can go too; the chat log itself is kept."""
        item = self.index.get(fact_id)
        allowed = (FACTS, CONVERSATION) if conversation else (FACTS,)
        if item is None or item.source not in allowed:
            return False
        return self.index.delete(fact_id)

    # Days

    @_locked
    def days_to_summarise(self) -> list[str]:
        """Past days with messages that haven't been summarised yet."""
        rows = self.db.execute(
            "SELECT DISTINCT day FROM messages WHERE day < ?"
            " AND day NOT IN (SELECT day FROM summarised_days) ORDER BY day",
            (self.today(),),
        ).fetchall()
        return [r[0] for r in rows]

    def save_day(self, day: str, summary: str, private: bool = False) -> None:
        """The summary of ``day``; ``private`` if Dan kept something local that day,
        since the summary may tell it."""
        if summary.strip():
            self.index.add(
                DAYS,
                "day",
                summary.strip(),
                title=f"Summary of {day}",
                ref=day,
                created=f"{day}T23:59:59",
                meta={"private": True} if private else None,
            )
        with self._lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO summarised_days (day) VALUES (?)", (day,))

    # Spend

    @_locked
    def record_spend(
        self, model: str, input_tokens: int, output_tokens: int, cost_usd: float, question: str
    ) -> None:
        now = self.clock()
        with self.db:
            self.db.execute(
                "INSERT INTO spend (at, month, model, input_tokens, output_tokens, cost_usd,"
                " question) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(timespec="seconds"),
                    now.strftime("%Y-%m"),
                    model,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    question[:500],
                ),
            )

    @_locked
    def month_spend(self, month: str | None = None) -> float:
        month = month or self.clock().strftime("%Y-%m")
        row = self.db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM spend WHERE month = ?", (month,)
        ).fetchone()
        return float(row[0])

    @_locked
    def spend_log(self, limit: int = 50) -> list[Spend]:
        rows = self.db.execute(
            "SELECT at, model, input_tokens, output_tokens, cost_usd, question FROM spend"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Spend(*row) for row in rows]

    @_locked
    def spend_summary(self, days: int = 30) -> dict:
        """Cloud spend over the last ``days`` days (today included): a row per day
        with each model's cost, and each model's totals, for charts and tables."""
        today = self.clock().date()
        first = today - timedelta(days=days - 1)
        rows = self.db.execute(
            "SELECT substr(at, 1, 10), model, COUNT(*), SUM(input_tokens), SUM(output_tokens),"
            " SUM(cost_usd) FROM spend WHERE at >= ? GROUP BY 1, 2 ORDER BY 1",
            (first.isoformat(),),
        ).fetchall()
        by_day = {(first + timedelta(days=i)).isoformat(): {} for i in range(days)}
        models: dict[str, dict] = {}
        for day, model, calls, tokens_in, tokens_out, cost in rows:
            if day not in by_day:
                continue
            by_day[day][model] = round(cost, 6)
            m = models.setdefault(
                model,
                {
                    "model": model,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            m["calls"] += calls
            m["input_tokens"] += tokens_in
            m["output_tokens"] += tokens_out
            m["cost_usd"] += cost
        for m in models.values():
            m["cost_usd"] = round(m["cost_usd"], 6)
        return {
            "days": [
                {"date": day, "cost_usd": round(sum(costs.values()), 6), "by_model": costs}
                for day, costs in by_day.items()
            ],
            "models": sorted(models.values(), key=lambda m: -m["cost_usd"]),
            "total_usd": round(sum(m["cost_usd"] for m in models.values()), 6),
        }

    # Backups

    def backup(self, folder: Path, keep: int) -> Path:
        """Copy the whole memory to ``folder``, keeping the newest ``keep`` copies."""
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"memory-{self.clock():%Y%m%d-%H%M%S}.db"
        with self._lock:
            dest = sqlite3.connect(target)
            try:
                self.db.backup(dest)
            finally:
                dest.close()
        for old in sorted(folder.glob("memory-*.db"))[:-keep]:
            old.unlink()
        return target

    def backed_up_today(self, folder: Path) -> bool:
        return any(folder.glob(f"memory-{self.clock():%Y%m%d}-*.db"))
