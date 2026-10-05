"""Stand-ins for the local model and Claude, so tests need no GPU, network or key."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

from kit.local_model import LocalModelError


def reply(*says, emotion="happy", gesture="nod", action="none", text=""):
    return json.dumps(
        {
            "emotion": emotion,
            "segments": [{"say": s, "gesture": gesture} for s in says],
            "action": {"kind": action, "text": text},
        }
    )


class FakeModel:
    """Answers each call with the next canned output, streamed a few characters at a time."""

    def __init__(self, *outputs, error=None):
        self.outputs = list(outputs)
        self.error = error
        self.calls: list[list[dict]] = []

    async def stream(self, messages, schema):
        self.calls.append(messages)
        if self.error:
            raise LocalModelError(self.error)
        out = self.outputs.pop(0) if self.outputs else reply("Okay.")
        for i in range(0, len(out), 4):
            yield out[i : i + 4]

    async def complete(self, messages, schema):
        return "".join([p async for p in self.stream(messages, schema)])


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    async def create(self, **kwargs):
        self.owner.calls.append(kwargs)
        if self.owner.error:
            raise self.owner.error
        return SimpleNamespace(
            model=kwargs["model"],
            stop_reason=self.owner.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking="hmm"),
                SimpleNamespace(type="text", text=self.owner.answer),
            ],
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=2000,
                cache_creation_input_tokens=None,
                cache_read_input_tokens=0,
            ),
        )


class FakeAnthropic:
    def __init__(self, answer="The answer is 42.", error=None, stop_reason="end_turn"):
        self.answer = answer
        self.error = error
        self.stop_reason = stop_reason
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=FakeMessages(self))
        self.keys: list[str] = []

    def factory(self, key):
        self.keys.append(key)
        return self

    async def close(self):
        pass


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
