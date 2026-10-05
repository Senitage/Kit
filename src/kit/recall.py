"""Finding what Kit knows that matters right now.

Every turn, the message is used to search memory (facts, past days and old
conversation) by words and by meaning, and the best matches go into the
prompt with their dates. If the embedding model is down, recall falls back to
words only rather than failing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from kit.embed import Embedder, EmbedError
from kit.knowledge import Hit, Item
from kit.memory import CONVERSATION, DAYS, FACTS, Memory
from kit.settings import Settings

EMBED_BATCH = 32


@dataclass
class Recalled:
    pinned: list[Item]
    memories: list[Hit]
    conversation: list[Hit]

    def ids(self) -> set[int]:
        return {i.id for i in self.pinned} | {h.item.id for h in self.memories + self.conversation}


class Recall:
    def __init__(
        self, memory: Memory, embedder: Embedder | None, settings: Callable[[], Settings]
    ) -> None:
        self.memory = memory
        self.embedder = embedder
        self.settings = settings
        self.embed_problem: str | None = None

    async def _query_vector(self, query: str) -> list[float] | None:
        if self.embedder is None:
            return None
        try:
            vec = (await self.embedder.embed([query], "query"))[0]
        except EmbedError as e:
            self.embed_problem = str(e)
            return None
        self.embed_problem = None
        return vec

    async def search(
        self,
        query: str,
        sources: list[str],
        k: int,
        exclude: set[int] | None = None,
    ) -> list[Hit]:
        s = self.settings().memory
        vec = await self._query_vector(query)
        model = self.embedder.model if self.embedder else ""
        return self.memory.index.search(query, vec, model, sources, k, s.min_similarity, exclude)

    async def for_turn(self, text: str, recent_refs: set[str]) -> Recalled:
        """What to put in front of the model for this message."""
        s = self.settings().memory
        pinned = self.memory.pinned_facts()
        memories = await self.search(
            text, [FACTS, DAYS], s.relevant_memories, exclude={i.id for i in pinned}
        )
        conversation = []
        if s.conversation_snippets:
            hits = await self.search(text, [CONVERSATION], s.conversation_snippets + 10)
            # Skip exchanges still in the recent history; they're already in view.
            conversation = [h for h in hits if h.item.ref not in recent_refs][
                : s.conversation_snippets
            ]
        return Recalled(pinned, memories, conversation)

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
