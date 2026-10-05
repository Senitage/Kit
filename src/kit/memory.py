"""Kit's memory: the conversation, facts it has learned, and Claude spend.

One SQLite file in the data folder's state directory. Messages are kept as
they happened; at the end of each day the local model turns them into a few
facts, and the newest facts go into every prompt so Kit remembers you across
restarts.
"""

from __future__ import annotations

import functools
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

Clock = Callable[[], datetime]

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    day TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'kit')),
    text TEXT NOT NULL,
    reply_json TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    text TEXT NOT NULL
);
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
"""


@dataclass(frozen=True)
class Message:
    id: int
    at: str
    role: str
    text: str
    reply_json: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Fact:
    id: int
    day: str
    text: str


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
        self.clock = clock
        self._lock = threading.RLock()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    @_locked
    def close(self) -> None:
        self.db.close()

    def today(self) -> str:
        return self.clock().date().isoformat()

    def add_message(
        self, role: str, text: str, reply_json: str | None = None, source: str | None = None
    ) -> None:
        now = self.clock()
        with self.db:
            self.db.execute(
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

    @_locked
    def days_to_summarise(self) -> list[str]:
        """Past days with messages that haven't been turned into facts yet."""
        rows = self.db.execute(
            "SELECT DISTINCT day FROM messages WHERE day < ?"
            " AND day NOT IN (SELECT day FROM summarised_days) ORDER BY day",
            (self.today(),),
        ).fetchall()
        return [r[0] for r in rows]

    @_locked
    def save_facts(self, day: str, facts: list[str]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT INTO facts (day, text) VALUES (?, ?)",
                [(day, f.strip()) for f in facts if f.strip()],
            )
            self.db.execute("INSERT OR IGNORE INTO summarised_days (day) VALUES (?)", (day,))

    @_locked
    def facts(self, limit: int = 1000) -> list[Fact]:
        """Facts, oldest first, keeping only the newest ``limit``."""
        rows = self.db.execute(
            "SELECT id, day, text FROM facts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Fact(*row) for row in reversed(rows)]

    @_locked
    def add_fact(self, text: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO facts (day, text) VALUES (?, ?)", (self.today(), text))

    @_locked
    def forget(self, fact_id: int) -> bool:
        with self.db:
            cur = self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        return cur.rowcount > 0

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
