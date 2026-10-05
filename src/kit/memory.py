"""Kit's memory, kept in one SQLite file in the data folder.

- **Conversation:** every message, in order. Each exchange is also indexed so
  Kit can find something said weeks ago.
- **Facts:** things Kit has learned about Dan, his projects, where things are
  kept, people and plans. Each has a kind, a date and its history; outdated
  facts are superseded, not deleted, and important ones can be pinned so
  they're always in mind.
- **Days:** a summary of each finished day, so "what were we doing last
  Tuesday?" has an answer.
- **Spend:** what each Claude call cost.

Facts, days and exchanges all live in the knowledge index (``kit.knowledge``),
which later stages extend with notes, documents and projects.
"""

from __future__ import annotations

import functools
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kit.knowledge import Index, Item

Clock = Callable[[], datetime]

FACTS = "memory"
DAYS = "days"
CONVERSATION = "conversation"
FACT_KINDS = {
    "about": "who the owner is: work, background, health, habits",
    "preference": "likes, dislikes and how they want things done",
    "project": "something they're working on, its state and decisions",
    "place": "where something is kept: folders, files, apps, sites",
    "person": "someone in their life and how they relate",
    "plan": "something coming up or intended, with dates",
    "other": "anything else worth keeping",
}

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
]


@dataclass(frozen=True)
class Message:
    id: int
    at: str
    role: str
    text: str
    reply_json: str | None = None
    source: str | None = None


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

    # Conversation

    @_locked
    def add_message(
        self, role: str, text: str, reply_json: str | None = None, source: str | None = None
    ) -> int:
        now = self.clock()
        with self.db:
            cur = self.db.execute(
                "INSERT INTO messages (at, day, role, text, reply_json, source)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    now.isoformat(timespec="seconds"),
                    now.date().isoformat(),
                    role,
                    text,
                    reply_json,
                    source,
                ),
            )
        return int(cur.lastrowid)

    @_locked
    def recent(self, limit: int) -> list[Message]:
        rows = self.db.execute(
            "SELECT id, at, role, text, reply_json, source FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Message(*row) for row in reversed(rows)]

    @_locked
    def messages_on(self, day: str) -> list[Message]:
        rows = self.db.execute(
            "SELECT id, at, role, text, reply_json, source FROM messages WHERE day = ? ORDER BY id",
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
        self, text: str, kind: str = "other", pinned: bool = False, source_ref: str | None = None
    ) -> int:
        kind = kind if kind in FACT_KINDS else "other"
        return self.index.add(FACTS, kind, text.strip(), ref=source_ref, pinned=pinned)

    def replace_fact(self, old_id: int, text: str, kind: str | None = None) -> int:
        old = self.index.get(old_id)
        new_id = self.add_fact(text, kind or (old.kind if old else "other"))
        self.index.supersede(old_id, new_id)
        return new_id

    def facts(self, limit: int = 10_000) -> list[Item]:
        """Current facts, oldest first."""
        return self.index.items(FACTS, limit=limit)

    def pinned_facts(self) -> list[Item]:
        return self.index.items(FACTS, pinned_only=True)

    def forget(self, fact_id: int) -> bool:
        item = self.index.get(fact_id)
        if item is None or item.source != FACTS:
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

    def save_day(self, day: str, summary: str) -> None:
        if summary.strip():
            self.index.add(
                DAYS,
                "day",
                summary.strip(),
                title=f"Summary of {day}",
                ref=day,
                created=f"{day}T23:59:59",
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
