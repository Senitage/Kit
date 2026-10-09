"""Stand-ins for the local model and cloud models, so tests need no GPU, network or key."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

from kit.local_model import LocalModelError


def reply(*says, emotion="happy", gesture="nod", action="none", text="", detail=""):
    return json.dumps(
        {
            "emotion": emotion,
            "segments": [{"say": s, "gesture": gesture} for s in says],
            "action": {"kind": action, "text": text},
            **({"detail": detail} if detail else {}),
        }
    )


def plan(emotion="happy", gesture="nod", action="none", text=""):
    """The first pass of a two-pass reply (kit.reply.Plan)."""
    return json.dumps(
        {"emotion": emotion, "gesture": gesture, "action": {"kind": action, "text": text}}
    )


class FakeModel:
    """Answers each call with the next canned output, streamed a few characters at a time.

    Two-pass replies (``ollama.speak_pass``) work with the same canned replies: asked
    for a plan, it plans the next ``reply(...)`` and says that reply's words when the
    plain-text call comes. ``calls`` records every call except those plain-text ones,
    which go in ``speak_calls``, so a test sees one call per answer either way. A
    canned output that isn't a reply (``plan(...)`` or plain words) is used as it is."""

    def __init__(self, *outputs, error=None):
        self.outputs = list(outputs)
        self.error = error
        self.calls: list[list[dict]] = []
        self.models: list[str | None] = []
        self.options: list[dict | None] = []
        self.speak_calls: list[list[dict]] = []
        self.speak_options: list[dict | None] = []
        self._words: list[str] = []  # what the planned replies will say

    def _next(self) -> str:
        return self.outputs.pop(0) if self.outputs else reply("Okay.")

    async def stream(self, messages, schema, model=None, options=None):
        if schema is None:
            self.speak_calls.append(messages)
            self.speak_options.append(options)
        else:
            self.calls.append(messages)
            self.models.append(model)
            self.options.append(options)
        if self.error:
            raise LocalModelError(self.error)
        if schema is None:
            out = self._words.pop(0) if self._words else self._next()
        else:
            out = self._next()
            if "gist" not in schema.get("properties", {}) and "gesture" in schema.get(
                "properties", {}
            ):
                out = self._as_plan(out)
        for i in range(0, len(out), 4):
            yield out[i : i + 4]

    def _as_plan(self, out: str) -> str:
        try:
            data = json.loads(out)
        except ValueError:
            return out
        if not isinstance(data, dict) or "segments" not in data:
            return out
        segments = data["segments"] or [{}]
        self._words.append(" ".join(seg.get("say", "") for seg in segments))
        if data.get("detail"):
            self._words[-1] += "\n\n" + data["detail"]
        return json.dumps(
            {
                "emotion": data.get("emotion", "neutral"),
                "gesture": segments[0].get("gesture", "none"),
                "action": data.get("action", {"kind": "none"}),
            }
        )

    async def complete(self, messages, schema, model=None, options=None):
        return "".join([p async for p in self.stream(messages, schema, model, options)])

    async def unload(self):
        self.unloads = getattr(self, "unloads", 0) + 1
        if self.error:
            raise LocalModelError(self.error)


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    async def create(self, **kwargs):
        owner = self.owner
        owner.calls.append(kwargs)
        if owner.gate is not None:  # a slow answer: waits until the test opens the gate
            await owner.gate.wait()
        if owner.error:
            raise owner.error
        n = len(owner.calls) - 1
        stop = owner.stop_reason[min(n, len(owner.stop_reason) - 1)]
        answer = owner.answers[min(n, len(owner.answers) - 1)]
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason=stop,
            content=[
                SimpleNamespace(type="thinking", thinking="hmm"),
                *(
                    SimpleNamespace(type="server_tool_use", name="web_search", input={"query": q})
                    for q in owner.queries
                ),
                SimpleNamespace(type="text", text=answer),
            ],
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=2000,
                cache_creation_input_tokens=None,
                cache_read_input_tokens=owner.cache_read_input_tokens,
                server_tool_use=SimpleNamespace(web_search_requests=owner.searches),
            ),
        )


class FakeAnthropic:
    """Claude. ``answer`` may be one answer or a list, one per call; so may ``stop_reason``."""

    def __init__(
        self,
        answer="The answer is 42.",
        error=None,
        stop_reason="end_turn",
        cache_read_input_tokens=0,
        searches=0,
        queries=(),
    ):
        self.queries = list(queries)
        self.gate = None  # set to an asyncio.Event to hold answers back
        self.answers = answer if isinstance(answer, list) else [answer]
        self.error = error
        self.stop_reason = stop_reason if isinstance(stop_reason, list) else [stop_reason]
        self.cache_read_input_tokens = cache_read_input_tokens
        self.searches = searches
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=FakeMessages(self))
        self.keys: list[str] = []

    def factory(self, key):
        self.keys.append(key)
        return self

    async def close(self):
        pass


def make_cloud(memory, claude=None, key="sk-test", **providers):
    """A Cloud with a fake Claude (and any other providers given)."""
    from kit.cloud import AnthropicProvider, Cloud

    claude = claude or FakeAnthropic()
    all_providers = {"anthropic": AnthropicProvider(claude.factory), **providers}
    return Cloud(memory, lambda provider: key, all_providers)


class Clock:
    """A clock tests can move."""

    def __init__(self, when="2026-10-05T09:00:00"):
        self.now = datetime.fromisoformat(when)

    def __call__(self):
        return self.now


def collect(agen):
    async def run():
        return [e async for e in agen]

    return asyncio.run(run())


class FakeEmbedder:
    """Bag-of-words vectors: texts sharing meaningful words are 'close in meaning'.

    ``same`` maps a word to another so tests can show meaning matches that
    share no words (e.g. "stuff" -> "returns")."""

    model = "fake-embed"

    def __init__(self, same=None, fail=False):
        self.same = same or {}
        self.fail = fail
        self.calls = 0

    async def embed(self, texts, purpose):
        import re
        import zlib

        from kit.embed import EmbedError
        from kit.knowledge import STOPWORDS

        self.calls += 1
        if self.fail:
            raise EmbedError("embedding model not found")
        out = []
        for text in texts:
            vec = [0.0] * 256
            for word in re.findall(r"\w+", text.lower()):
                word = self.same.get(word, word)
                if word in STOPWORDS:
                    continue
                vec[zlib.crc32(word.encode()) % 256] += 1.0
            out.append(vec)
        return out


class FakeWeather:
    """A forecast service that remembers what it was asked."""

    def __init__(self, fail=False):
        self.fail = fail
        self.asked = []

    async def forecast(self, place, country=""):
        from kit.weather import WeatherError

        self.asked.append((place, country))
        if self.fail:
            raise WeatherError("The forecast service returned an error (500).")
        return f"Forecast for {place} from Open-Meteo: clear, 14°C tonight."
