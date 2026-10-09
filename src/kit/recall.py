"""Finding what Kit knows that matters right now.

Every turn, the message is used to search memory (facts, past days, old
conversation, the register of things and Kit's own notebook) by words and by
meaning, and the best matches go into the prompt with their dates. If the
embedding model is down, recall falls back to words only rather than failing.

Among facts and days that are relevant, the ones that matter more to Dan's life
and the ones recalled lately come first (``weight``), the way a person's
memory works; a floor keeps an old, small fact from ever dropping out of reach.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from kit.embed import Embedder, EmbedError
from kit.knowledge import Hit, Item
from kit.life import parse_time
from kit.memory import CONVERSATION, DAYS, FACTS, IMPORTANCE, KEEP_LOCAL, SELF, Memory
from kit.settings import Settings
from kit.things import THINGS, Register, Thing

EMBED_BATCH = 32
RECENCY_DAYS = 30  # a memory last recalled this long ago counts half as fresh


def weight(item: Item, now: datetime, floor: float) -> float:
    """How much a relevant memory counts, ``floor`` to 1: half how much it matters to
    Dan's life (its importance; pinned is 1), half how lately it was recalled (or
    learned). ``floor`` 1 weighs them all the same."""
    if floor >= 1:
        return 1.0
    importance = item.meta.get("importance", IMPORTANCE.get(item.kind, 0.5))
    importance = 1.0 if item.pinned else float(importance)
    try:
        last = parse_time(str(item.meta.get("last_recalled") or item.created), now)
        days = max(0.0, (now - last).total_seconds() / 86400)
    except ValueError:
        days = 0.0
    fresh = 0.5 ** (days / RECENCY_DAYS)
    return floor + (1 - floor) * (min(1.0, max(0.0, importance)) + fresh) / 2


@dataclass
class Recalled:
    pinned: list[Item]
    memories: list[Hit]
    conversation: list[Hit]
    things: list[Thing] = field(default_factory=list)
    own: list[Hit] = field(default_factory=list)  # from Kit's own notebook

    def ids(self) -> set[int]:
        return (
            {i.id for i in self.pinned}
            | {h.item.id for h in self.memories + self.conversation + self.own}
            | {t.id for t in self.things}
        )

    def for_cloud(self) -> Recalled:
        """What a cloud model may see: nothing Dan kept local, and nothing Kit kept
        from it (kit.memory.KEEP_LOCAL)."""
        return Recalled(
            [i for i in self.pinned if not private(i)],
            [h for h in self.memories if not private(h.item)],
            [h for h in self.conversation if not private(h.item)],
            self.things,
            [h for h in self.own if not private(h.item)],
        )


def private(item: Item) -> bool:
    """Kept from something Dan kept local, or the exchange itself."""
    return bool(item.meta.get("private")) or bool(KEEP_LOCAL.search(item.text))


class Recall:
    def __init__(
        self, memory: Memory, embedder: Embedder | None, settings: Callable[[], Settings]
    ) -> None:
        self.memory = memory
        self.embedder = embedder
        self.settings = settings
        self.embed_problem: str | None = None
        self.register = Register(memory)
        self._last_query: tuple[str, str, list[float]] | None = None  # (model, text, vector)

    async def query_vector(self, query: str) -> list[float] | None:
        if self.embedder is None:
            return None
        model = self.embedder.model
        if self._last_query and self._last_query[:2] == (model, query):
            return self._last_query[2]  # one turn searches several sources with one query
        try:
            vec = (await self.embedder.embed([query], "query"))[0]
        except EmbedError as e:
            self.embed_problem = str(e)
            return None
        self.embed_problem = None
        self._last_query = (model, query, vec)
        return vec

    async def search(
        self,
        query: str,
        sources: list[str],
        k: int,
        exclude: set[int] | None = None,
    ) -> list[Hit]:
        s = self.settings().memory
        vec = await self.query_vector(query)
        model = self.embedder.model if self.embedder else ""
        return self.memory.index.search(query, vec, model, sources, k, s.min_similarity, exclude)

    async def for_turn(self, text: str, recent_refs: set[str]) -> Recalled:
        """What to put in front of the model for this message."""
        s = self.settings().memory
        pinned = self.memory.pinned_facts()
        memories = await self.search(
            text, [FACTS, DAYS], s.relevant_memories * 2, exclude={i.id for i in pinned}
        )
        memories = self.weighed(memories)[: s.relevant_memories]
        now = self.memory.clock()
        self.memory.index.update_meta(
            [h.item.id for h in memories if h.item.source == FACTS],
            {"last_recalled": now.isoformat(timespec="seconds")},
        )
        conversation = []
        if s.conversation_snippets:
            hits = await self.search(text, [CONVERSATION], s.conversation_snippets + 10)
            # Skip exchanges still in the recent history; they're already in view.
            conversation = [h for h in hits if h.item.ref not in recent_refs][
                : s.conversation_snippets
            ]
        own = await self.search(text, [SELF], s.own_memories) if s.own_memories else []
        return Recalled(pinned, memories, conversation, await self.things_for(text), own)

    def weighed(self, hits: list[Hit]) -> list[Hit]:
        """Relevant memories, the ones that matter more and were recalled lately
        first (``weight``)."""
        now, floor = self.memory.clock(), self.settings().memory.weight_floor
        return sorted(hits, key=lambda h: h.score * weight(h.item, now, floor), reverse=True)

    async def closeness(self, text: str, others: list[str]) -> float | None:
        """How close ``text`` is in meaning to the closest of ``others`` (cosine,
        -1 to 1), or None without an embedder."""
        if self.embedder is None or not others:
            return None
        try:
            vecs = await self.embedder.embed([text, *others], "query")
        except EmbedError as e:
            self.embed_problem = str(e)
            return None
        unit = [_unit(v) for v in vecs]
        return max(sum(a * b for a, b in zip(unit[0], u, strict=True)) for u in unit[1:])

    async def things_for(self, text: str) -> list[Thing]:
        """Register entries that matter for this message: the ones it names, then
        the closest by words and meaning."""
        k = self.settings().memory.relevant_things
        if not k:
            return []
        named = self.register.mentioned_in(text)
        hits = await self.search(text, [THINGS], k, exclude={t.id for t in named})
        found = named + [t for h in hits if (t := self.register.get(h.item.id))]
        return found[:k]

    async def index_pending(self, limit: int = 512) -> int:
        """Embed items that don't have a vector yet. Returns how many were done."""
        if self.embedder is None:
            return 0
        model, done = self.embedder.model, 0
        while done < limit:
            batch = self.memory.index.missing_vectors(model, EMBED_BATCH)
            if not batch:
                break
            try:
                vectors = await self.embedder.embed(
                    [f"{i.title}\n{i.text}".strip() for i in batch], "document"
                )
            except EmbedError as e:
                self.embed_problem = str(e)
                break
            self.memory.index.save_vectors(
                model, list(zip([i.id for i in batch], vectors, strict=True))
            )
            done += len(batch)
        return done


def _unit(vec: list[float]) -> list[float]:
    norm = sum(x * x for x in vec) ** 0.5 or 1.0
    return [x / norm for x in vec]
