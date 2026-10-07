"""The local model, reached through Ollama's chat API.

Replies are forced into a JSON schema with Ollama's ``format`` option and
streamed, so the first words can be shown while the rest is generated.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Protocol

import httpx

from kit.settings import OllamaSettings


class LocalModelError(Exception):
    """Ollama couldn't be reached or returned an error."""


class LocalModel(Protocol):
    def stream(
        self, messages: list[dict], schema: dict, model: str | None = None
    ) -> AsyncIterator[str]:
        """Yield the model's output in pieces as it is generated. ``model`` picks
        another local model than the usual one."""
        ...

    async def complete(self, messages: list[dict], schema: dict) -> str:
        """The model's whole output at once."""
        ...


class OllamaModel:
    """Talks to Ollama. Settings are read on every call, so changes apply at once."""

    def __init__(self, settings: Callable[[], OllamaSettings], client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    def _body(
        self, s: OllamaSettings, messages: list[dict], schema: dict, model: str | None
    ) -> dict:
        return {
            "model": model or s.model,
            "messages": messages,
            "format": schema,
            "stream": True,
            "think": s.think,
            "keep_alive": "30m",
            "options": {"temperature": s.temperature, "num_ctx": s.num_ctx},
        }

    async def stream(
        self, messages: list[dict], schema: dict, model: str | None = None
    ) -> AsyncIterator[str]:
        s = self.settings()
        url = f"{s.url}/api/chat"
        try:
            async with self.client.stream(
                "POST", url, json=self._body(s, messages, schema, model), timeout=120
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    raise LocalModelError(
                        f"Ollama said {response.status_code}: {response.text[:200]}"
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LocalModelError(f"Ollama error: {data['error']}")
                    piece = data.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if data.get("done"):
                        return
        except httpx.HTTPError as e:
            raise LocalModelError(f"can't reach Ollama at {s.url}: {e}") from e

    async def complete(self, messages: list[dict], schema: dict) -> str:
        return "".join([piece async for piece in self.stream(messages, schema)])
