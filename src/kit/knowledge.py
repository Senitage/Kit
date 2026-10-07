"""One searchable index for everything Kit knows.

Facts Kit has learned, summaries of past days and past conversations all live
here as items, and later stages add more sources the same way: Obsidian notes,
NAS documents, photo captions, projects. Every item can be found two ways at
once, and the results are merged:

- by words, with SQLite full-text search (exact names, numbers, file names);
- by meaning, with vectors from the embedding model ("tax stuff" finds
  "Documents/Finance/Tax").

Items are never silently overwritten. When a fact changes, the new item
supersedes the old one, so Kit can tell what's current and you can see history.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    ref TEXT,
    meta TEXT NOT NULL DEFAULT '{}',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    superseded_by INTEGER REFERENCES items(id)
);
CREATE INDEX IF NOT EXISTS items_source ON items(source, superseded_by);
CREATE INDEX IF NOT EXISTS items_ref ON items(source, ref);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, text, content='items', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, text)
        VALUES ('delete', old.id, old.title, old.text);
    DELETE FROM vectors WHERE item_id = old.id;
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE OF title, text ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, text)
        VALUES ('delete', old.id, old.title, old.text);
    INSERT INTO items_fts(rowid, title, text) VALUES (new.id, new.title, new.text);
    DELETE FROM vectors WHERE item_id = old.id;
END;
CREATE TABLE IF NOT EXISTS vectors (
    item_id INTEGER PRIMARY KEY REFERENCES items(id),
    model TEXT NOT NULL,
    vec BLOB NOT NULL
);
"""

STOPWORDS = frozenset(
    """a an and are as at be but by can could did do does for from had has have he her
    his how i if in into is it its just me my of on or our she so than that the their
    them then there these they this to up was we were what when where which who why will
    with would you your about any been get got im ive kit""".split()
)
RRF_K = 60


@dataclass
class Item:
    id: int
    source: str
    kind: str
    title: str
    text: str
    ref: str | None
    meta: dict
    created: str
    updated: str
    pinned: bool
    superseded_by: int | None

    @property
    def day(self) -> str:
        return self.created[:10]


@dataclass
class Hit:
    item: Item
    score: float
    similarity: float | None = None
    word_match: bool = False


@dataclass
class _VectorCache:
    version: int = -1
    model: str = ""
    ids: list[int] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    matrix: np.ndarray | None = None


def fts_query(text: str) -> str:
    """A forgiving full-text query: any meaningful word may match."""
    words = [w for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS and len(w) > 1]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def _to_blob(vec: Iterable[float]) -> bytes:
    return array("f", vec).tobytes()


class Index:
    def __init__(
        self, db: sqlite3.Connection, lock: threading.RLock, clock: Callable[[], datetime]
    ) -> None:
        self.db = db
        self.lock = lock
        self.clock = clock
        self._version = 0
        self._cache = _VectorCache()

    def _now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    def _changed(self) -> None:
        with self.lock:
            self._version += 1

    def _row(self, row) -> Item:
        return Item(
            id=row[0],
            source=row[1],
            kind=row[2],
            title=row[3],
            text=row[4],
            ref=row[5],
            meta=json.loads(row[6] or "{}"),
            created=row[7],
            updated=row[8],
            pinned=bool(row[9]),
            superseded_by=row[10],
        )

    _COLS = "id, source, kind, title, text, ref, meta, created, updated, pinned, superseded_by"

    # Writing

    def add(
        self,
        source: str,
        kind: str,
        text: str,
        title: str = "",
        ref: str | None = None,
        meta: dict | None = None,
        pinned: bool = False,
        created: str | None = None,
    ) -> int:
        now = self._now()
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO items (source, kind, title, text, ref, meta, created, updated, pinned)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source,
                    kind,
                    title,
                    text,
                    ref,
                    json.dumps(meta or {}),
                    created or now,
                    now,
                    int(pinned),
                ),
            )
        self._changed()
        return int(cur.lastrowid)

    def supersede(self, old_id: int, new_id: int) -> None:
        """Mark ``old_id`` as replaced by ``new_id``; it stays for history but isn't recalled."""
        with self.lock, self.db:
            self.db.execute(
                "UPDATE items SET superseded_by = ?, updated = ? WHERE id = ?",
                (new_id, self._now(), old_id),
            )
            # Keep a pin on the newer version.
            self.db.execute(
                "UPDATE items SET pinned = 1 WHERE id = ? AND"
                " (SELECT pinned FROM items WHERE id = ?) = 1",
                (new_id, old_id),
            )
        self._changed()

    def update(self, item_id: int, text: str | None = None, kind: str | None = None) -> None:
        with self.lock, self.db:
            if text is not None:
                self.db.execute(
                    "UPDATE items SET text = ?, updated = ? WHERE id = ?",
                    (text, self._now(), item_id),
                )
            if kind is not None:
                self.db.execute("UPDATE items SET kind = ? WHERE id = ?", (kind, item_id))
        self._changed()

    def set_meta(self, item_id: int, meta: dict) -> bool:
        """Replace an item's meta, e.g. to mark one of Kit's wants as said. Its text and
        vectors stay as they are."""
        with self.lock, self.db:
            cur = self.db.execute(
                "UPDATE items SET meta = ?, updated = ? WHERE id = ?",
                (json.dumps(meta), self._now(), item_id),
            )
        return cur.rowcount > 0

    def set_pinned(self, item_id: int, pinned: bool) -> bool:
        with self.lock, self.db:
            cur = self.db.execute(
                "UPDATE items SET pinned = ? WHERE id = ?", (int(pinned), item_id)
            )
        self._changed()
        return cur.rowcount > 0

    def delete(self, item_id: int) -> bool:
        """Delete an item and every earlier version of it, so nothing of it is recalled."""
        ids = [i.id for i in self.history(item_id)]
        if not ids:
            return False
        marks = ",".join("?" * len(ids))
        with self.lock, self.db:
            self.db.execute(f"UPDATE items SET superseded_by = NULL WHERE id IN ({marks})", ids)
            self.db.execute(f"DELETE FROM items WHERE id IN ({marks})", ids)
        self._changed()
        return True

    def delete_source(self, source: str, ref: str | None = None) -> int:
        """Remove a whole source, or one document of it, e.g. before re-indexing a file."""
        with self.lock, self.db:
            if ref is None:
                cur = self.db.execute("DELETE FROM items WHERE source = ?", (source,))
            else:
                cur = self.db.execute(
                    "DELETE FROM items WHERE source = ? AND ref = ?", (source, ref)
                )
        self._changed()
        return cur.rowcount

    # Reading

    def get(self, item_id: int) -> Item | None:
        with self.lock:
            row = self.db.execute(
                f"SELECT {self._COLS} FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._row(row) if row else None

    def items(
        self,
        source: str,
        include_superseded: bool = False,
        pinned_only: bool = False,
        limit: int = 10_000,
        kind: str | None = None,
    ) -> list[Item]:
        """Items from one source (of one kind, if given), oldest first."""
        where, params = "source = ?", [source]
        if kind is not None:
            where += " AND kind = ?"
            params.append(kind)
        if not include_superseded:
            where += " AND superseded_by IS NULL"
        if pinned_only:
            where += " AND pinned = 1"
        with self.lock:
            rows = self.db.execute(
                f"SELECT {self._COLS} FROM items WHERE {where} ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._row(r) for r in reversed(rows)]

    def history(self, item_id: int) -> list[Item]:
        """The item and every earlier version it replaced, newest first."""
        chain, queue = [], [self.get(item_id)]
        while queue:
            current = queue.pop(0)
            if current is None:
                continue
            chain.append(current)
            with self.lock:
                rows = self.db.execute(
                    f"SELECT {self._COLS} FROM items WHERE superseded_by = ? ORDER BY id DESC",
                    (current.id,),
                ).fetchall()
            queue += [self._row(r) for r in rows]
        return chain

    def count(self, source: str | None = None) -> int:
        with self.lock:
            if source is None:
                return self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            return self.db.execute(
                "SELECT COUNT(*) FROM items WHERE source = ?", (source,)
            ).fetchone()[0]

    # Vectors

    def missing_vectors(self, model: str, limit: int = 64) -> list[Item]:
        """Current items with no vector from ``model`` yet."""
        with self.lock:
            rows = self.db.execute(
                f"SELECT {', '.join('i.' + c.strip() for c in self._COLS.split(','))}"
                " FROM items i LEFT JOIN vectors v ON v.item_id = i.id AND v.model = ?"
                " WHERE v.item_id IS NULL AND i.superseded_by IS NULL ORDER BY i.id LIMIT ?",
                (model, limit),
            ).fetchall()
        return [self._row(r) for r in rows]

    def save_vectors(self, model: str, vectors: list[tuple[int, list[float]]]) -> None:
        with self.lock, self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO vectors (item_id, model, vec) VALUES (?, ?, ?)",
                [(item_id, model, _to_blob(vec)) for item_id, vec in vectors],
            )
        self._changed()

    def _matrix(self, model: str) -> _VectorCache:
        cache = self._cache
        if cache.version != self._version or cache.model != model:
            with self.lock:
                # The version is taken before the read, so a write that lands
                # while this builds makes the result stale at once, not never.
                version = self._version
                rows = self.db.execute(
                    "SELECT v.item_id, i.source, v.vec FROM vectors v"
                    " JOIN items i ON i.id = v.item_id"
                    " WHERE v.model = ? AND i.superseded_by IS NULL",
                    (model,),
                ).fetchall()
            matrix = None
            if rows:
                matrix = np.vstack([np.frombuffer(r[2], dtype=np.float32) for r in rows])
                norms = np.linalg.norm(matrix, axis=1, keepdims=True)
                matrix = matrix / np.where(norms == 0, 1, norms)
            cache = _VectorCache(version, model, [r[0] for r in rows], [r[1] for r in rows], matrix)
            self._cache = cache
        return cache

    # Searching

    def word_search(
        self, query: str, sources: list[str] | None = None, limit: int = 30
    ) -> list[int]:
        match = fts_query(query)
        if not match:
            return []
        sql = (
            "SELECT i.id FROM items_fts f JOIN items i ON i.id = f.rowid"
            " WHERE items_fts MATCH ? AND i.superseded_by IS NULL"
        )
        params: list = [match]
        if sources:
            sql += f" AND i.source IN ({','.join('?' * len(sources))})"
            params += sources
        sql += " ORDER BY bm25(items_fts, 2.0, 1.0) LIMIT ?"
        params.append(limit)
        with self.lock:
            try:
                return [r[0] for r in self.db.execute(sql, params).fetchall()]
            except sqlite3.OperationalError:
                return []

    def similarities(
        self, query_vec: list[float], model: str, sources: list[str] | None = None
    ) -> dict[int, float]:
        """Cosine similarity of the query to every current item (in ``sources``) with a
        vector."""
        cache = self._matrix(model)
        if cache.matrix is None:
            return {}
        q = np.asarray(query_vec, dtype=np.float32)
        if q.shape[0] != cache.matrix.shape[1]:
            return {}
        q = q / (np.linalg.norm(q) or 1)
        scores = (cache.matrix @ q).tolist()
        if not sources:
            return dict(zip(cache.ids, scores, strict=True))
        wanted = set(sources)
        return {
            i: v
            for i, src, v in zip(cache.ids, cache.sources, scores, strict=True)
            if src in wanted
        }

    def search(
        self,
        query: str,
        query_vec: list[float] | None = None,
        model: str = "",
        sources: list[str] | None = None,
        k: int = 8,
        min_similarity: float = 0.5,
        exclude: set[int] | None = None,
        word_slack: float = 0.15,
    ) -> list[Hit]:
        """Words and meaning together, merged by reciprocal rank fusion.

        An item counts as relevant if it's close in meaning (``min_similarity``),
        or if it shares words with the query and is nearly that close. So a
        shared word like "called" doesn't drag in an unrelated memory, and a
        question about something Kit never heard of recalls nothing. Items with
        no vector yet (or when the embedding model is down) go on words alone.
        """
        exclude = exclude or set()
        sims = {}
        if query_vec is not None and model:
            sims = self.similarities(query_vec, model, sources)
        hits: dict[int, Hit] = {}

        for rank, item_id in enumerate(self.word_search(query, sources)):
            sim = sims.get(item_id)
            if item_id in exclude or (sim is not None and sim < min_similarity - word_slack):
                continue
            hit = hits.setdefault(item_id, Hit(None, 0.0, sim))  # type: ignore[arg-type]
            hit.score += 1 / (RRF_K + rank)
            hit.word_match = True

        close = sorted(
            ((i, v) for i, v in sims.items() if v >= min_similarity and i not in exclude),
            key=lambda iv: iv[1],
            reverse=True,
        )[:60]
        for rank, (item_id, sim) in enumerate(close):
            hit = hits.setdefault(item_id, Hit(None, 0.0, sim))  # type: ignore[arg-type]
            hit.score += 1 / (RRF_K + rank)
            hit.similarity = sim

        ranked = sorted(hits.items(), key=lambda kv: kv[1].score, reverse=True)[:k]
        out = []
        for item_id, hit in ranked:
            item = self.get(item_id)
            if item:
                hit.item = item
                out.append(hit)
        return out
