"""Turning text into meaning vectors, so Kit can find things by what they mean.

"Where do I keep my tax stuff?" should find "Dan's tax returns are in
Documents/Finance/Tax" even though the words barely overlap. The embedding
model runs in Ollama next to the chat model and is small (about 300 MB).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

import httpx

from kit.settings import Settings

Purpose = Literal["query", "document"]


class EmbedError(Exception):
    """The embedding model couldn't be reached or failed."""


class Embedder(Protocol):
    @property
    def model(self) -> str:
        """Name of the model; vectors from different models never mix."""
        ...

    async def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(self, settings: Callable[[], Settings], client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    @property
    def model(self) -> str:
        return self.settings().memory.embed_model

    async def embed(self, texts: list[str], purpose: Purpose) -> list[list[float]]:
        s = self.settings()
        prefix = s.memory.query_prefix if purpose == "query" else s.memory.document_prefix
        body = {"model": s.memory.embed_model, "input": [prefix + t for t in texts]}
        try:
            response = await self.client.post(f"{s.ollama.url}/api/embed", json=body, timeout=60)
        except httpx.HTTPError as e:
            raise EmbedError(f"can't reach Ollama for embeddings: {e}") from e
        if response.status_code != 200:
            raise EmbedError(f"embedding failed ({response.status_code}): {response.text[:200]}")
        vectors = response.json().get("embeddings") or []
        if len(vectors) != len(texts):
            raise EmbedError("embedding model returned the wrong number of vectors")
        return vectors
