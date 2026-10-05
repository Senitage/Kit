import asyncio
from datetime import timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeModel, collect, reply
from kit.brain import Brain
from kit.expert import Expert
from kit.memory import Memory
from kit.settings import Settings


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def make(memory, *outputs, settings=None, claude=None, error=None):
    model = FakeModel(*outputs, error=error)
    claude = claude or FakeAnthropic()
    s = settings or Settings()
    brain = Brain(lambda: s, memory, model, Expert(memory, lambda: "k", claude.factory))
    return brain, model, claude


def test_reply_streams_words_then_whole_reply(memory):
    brain, model, _ = make(memory, reply("Morning.", "Coffee?", emotion="playful"))
    events = collect(brain.chat("Morning Kit"))
    said = "".join(e["text"] for e in events if e["type"] == "say")
    assert said == "Morning. Coffee?"
    assert len([e for e in events if e["type"] == "say"]) > 1  # streamed, not all at once
    final = events[-1]
    assert final["type"] == "reply" and final["reply"]["emotion"] == "playful"
    assert [m.role for m in memory.recent(5)] == ["user", "kit"]


def test_prompt_has_persona_history_and_facts(memory):
    memory.add_fact("Dan's dog is called Rex.")
    s = Settings()
    s.persona.name = "Kip"
    brain, model, _ = make(memory, reply("One."), reply("Two."), settings=s)
    collect(brain.chat("first"))
    collect(brain.chat("second"))
    system = model.calls[1][0]["content"]
    assert "You are Kip" in system and "Rex" in system and "tilt_head" in system
    roles = [m["role"] for m in model.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert model.calls[1][-1]["content"] == "second"


def test_persona_change_applies_next_message(memory):
    settings = Settings()
    model = FakeModel()
    brain = Brain(lambda: settings, memory, model, Expert(memory, lambda: None))
    collect(brain.chat("hi"))
    settings = Settings.model_validate({"persona": {"name": "Changed"}})
    collect(brain.chat("hi"))
    assert "You are Changed" in model.calls[1][0]["content"]


def test_model_asks_for_claude(memory):
    brain, _, claude = make(
        memory, reply("Let me check with Claude.", action="ask_claude", text="Kalman maths?")
    )
    events = collect(brain.chat("Explain Kalman filters properly"))
    kinds = [e["type"] for e in events]
    assert "asking_claude" in kinds
    last = events[-1]
    assert last["source"] == "claude" and last["cost_usd"] > 0
    assert claude.calls[0]["messages"][-1]["content"] == "Kalman maths?"
    assert memory.recent(1)[0].source == "claude"


def test_saying_ask_claude_skips_the_local_model(memory):
    brain, model, claude = make(memory)
    events = collect(brain.chat("Ask Claude why the sky is blue"))
    assert model.calls == []
    assert claude.calls[0]["messages"][-1]["content"] == "Ask Claude why the sky is blue"
    assert events[-1]["source"] == "claude"


def test_claude_context_alternates(memory):
    brain, _, claude = make(memory, reply("a"), reply("b"))
    collect(brain.chat("one"))
    collect(brain.chat("two"))
    collect(brain.chat("ask claude three"))
    roles = [m["role"] for m in claude.calls[0]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]


def test_remember_action_saves_a_fact(memory):
    brain, _, _ = make(memory, reply("Got it.", action="remember", text="Birthday is 14 March."))
    events = collect(brain.chat("Remember my birthday is 14 March"))
    assert {"type": "remembered", "fact": "Birthday is 14 March."} in events
    assert memory.facts()[0].text == "Birthday is 14 March."


def test_broken_json_keeps_the_words(memory):
    brain, _, _ = make(memory, '{"emotion": "happy", "segments": [{"say": "Half a thou')
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "reply"
    assert events[-1]["reply"]["segments"][0]["say"] == "Half a thou"


def test_garbage_is_an_error(memory):
    brain, _, _ = make(memory, "nonsense")
    assert collect(brain.chat("hi"))[-1]["type"] == "error"


def test_ollama_down_is_an_error(memory):
    brain, _, _ = make(memory, error="connection refused")
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "error" and "local brain" in events[-1]["message"]


def test_blank_message_does_nothing(memory):
    brain, model, _ = make(memory)
    assert collect(brain.chat("   ")) == [] and model.calls == []


def test_yesterday_becomes_facts(memory, clock):
    brain, model, _ = make(memory, reply("Nice."), '{"facts": ["Dan has a dog called Rex."]}')
    collect(brain.chat("My dog is called Rex"))
    clock.now += timedelta(days=1)
    assert asyncio.run(brain.summarise_past_days()) == ["2026-10-05"]
    assert "Rex" in model.calls[1][1]["content"]
    assert asyncio.run(brain.summarise_past_days()) == []
    brain.model = FakeModel(reply("Rex, right?"))
    collect(brain.chat("What's my dog's name?"))
    assert "Dan has a dog called Rex." in brain.model.calls[0][0]["content"]


def test_failed_summary_is_retried_later(memory, clock):
    brain, _, _ = make(memory, reply("ok"), "not json")
    collect(brain.chat("hi"))
    clock.now += timedelta(days=1)
    assert asyncio.run(brain.summarise_past_days()) == []
    assert memory.days_to_summarise() == ["2026-10-05"]
