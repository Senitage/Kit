"""The local model, reached through Ollama's chat API.

Replies are forced into a JSON schema with Ollama's ``format`` option and
streamed, so the first words can be shown while the rest is generated. Kit's
spoken words in the speaking pass are plain text (no schema), sampled livelier.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Protocol

import httpx

from kit.settings import OllamaSettings

log = logging.getLogger(__name__)


class LocalModelError(Exception):
    """Ollama couldn't be reached or returned an error."""


class LocalModel(Protocol):
    def stream(
        self,
        messages: list[dict],
        schema: dict | None,
        model: str | None = None,
        options: dict | None = None,
    ) -> AsyncIterator[str]:
        """Yield the model's output in pieces as it is generated: JSON matching
        ``schema``, or plain text with None. ``model`` picks another local model than
        the usual one; ``options`` change the sampling (e.g. a higher temperature)."""
        ...

    async def complete(
        self,
        messages: list[dict],
        schema: dict | None,
        model: str | None = None,
        options: dict | None = None,
    ) -> str:
        """The model's whole output at once."""
        ...

    async def warm(self, messages: list[dict]) -> None:
        """Read ``messages`` in without answering, so a later call that starts with
        them only has the rest to read."""
        ...


def lively(s: OllamaSettings, plain: bool = True) -> dict:
    """Sampling for Kit's own words and thoughts: livelier than his JSON decisions,
    with top_k and top_p as Gemma's makers suggest. The repeat penalty is for plain
    text only; in JSON it would fight the format."""
    options = {
        "temperature": s.speak_temperature,
        "min_p": s.min_p,
        "top_k": s.top_k,
        "top_p": s.top_p,
    }
    if plain:
        options["repeat_penalty"] = s.repeat_penalty
        options["repeat_last_n"] = s.repeat_last_n
    return options


class OllamaModel:
    """Talks to Ollama. Settings are read on every call, so changes apply at once."""

    def __init__(self, settings: Callable[[], OllamaSettings], client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    def _body(
        self,
        s: OllamaSettings,
        messages: list[dict],
        schema: dict | None,
        model: str | None,
        options: dict | None = None,
    ) -> dict:
        body = {
            "model": model or s.model,
            "messages": messages,
            "stream": True,
            "think": s.think,
            "keep_alive": "30m",
            "options": {"temperature": s.temperature, "num_ctx": s.num_ctx, **(options or {})},
        }
        if schema is not None:
            body["format"] = schema
        return body

    async def stream(
        self,
        messages: list[dict],
        schema: dict | None,
        model: str | None = None,
        options: dict | None = None,
    ) -> AsyncIterator[str]:
        s = self.settings()
        url = f"{s.url}/api/chat"
        body = self._body(s, messages, schema, model, options)
        try:
            async with self.client.stream("POST", url, json=body, timeout=120) as response:
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
                        _log_timing(data)
                        return
        except httpx.HTTPError as e:
            raise LocalModelError(f"can't reach Ollama at {s.url}: {e}") from e

    async def complete(
        self,
        messages: list[dict],
        schema: dict | None,
        model: str | None = None,
        options: dict | None = None,
    ) -> str:
        return "".join([piece async for piece in self.stream(messages, schema, model, options)])

    async def warm(self, messages: list[dict]) -> None:
        """Ollama keeps what it last read (its prompt cache) and only reads on from
        there when the next prompt starts the same way; one token is the least it
        will do. Same model and options as the real calls, or Ollama would reload it."""
        s = self.settings()
        body = {**self._body(s, messages, None, None, {"num_predict": 1}), "stream": False}
        try:
            r = await self.client.post(f"{s.url}/api/chat", json=body, timeout=120)
        except httpx.HTTPError as e:
            raise LocalModelError(f"can't reach Ollama at {s.url}: {e}") from e
        if r.status_code != 200:
            raise LocalModelError(f"Ollama said {r.status_code}: {r.text[:200]}")
        try:
            _log_timing(r.json())
        except ValueError:
            pass


def _log_timing(done: dict) -> None:
    """How long Ollama took, for the server log. What it had read before (its prompt
    cache) isn't read again, so a prompt that reused it shows few tokens read."""
    if "prompt_eval_count" not in done:
        return
    log.info(
        "local model: read %s tokens in %.2f s, wrote %s in %.2f s",
        done["prompt_eval_count"],
        done.get("prompt_eval_duration", 0) / 1e9,
        done.get("eval_count", 0),
        done.get("eval_duration", 0) / 1e9,
    )
