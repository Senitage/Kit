import asyncio
import json
from datetime import timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, reply
from kit.brain import Brain
from kit.expert import Expert
from kit.memory import Memory
from kit.recall import Recall
from kit.settings import Settings


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def make(memory, *outputs, settings=None, claude=None, error=None, embedder=None):
    model = FakeModel(*outputs, error=error)
    claude = claude or FakeAnthropic()
    s = settings or Settings.model_validate({"memory": {"min_similarity": 0.3}})
    recall = Recall(memory, embedder or FakeEmbedder(), lambda: s)
    expert = Expert(memory, lambda: "k", claude.factory)
    return Brain(lambda: s, memory, model, expert, recall), model, claude


def decision(what, which=0, fact=""):
    return json.dumps({"decision": what, "which": which, "fact": fact})


def test_reply_streams_words_then_whole_reply(memory):
    brain, model, _ = make(memory, reply("Morning.", "Coffee?", emotion="playful"))
    events = collect(brain.chat("Morning Kit"))
    said = "".join(e["text"] for e in events if e["type"] == "say")
    assert said == "Morning. Coffee?"
    assert len([e for e in events if e["type"] == "say"]) > 1  # streamed, not all at once
    final = events[-1]
    assert final["type"] == "reply" and final["reply"]["emotion"] == "playful"
    assert [m.role for m in memory.recent(5)] == ["user", "kit"]


def test_exchange_is_indexed_for_later(memory):
    brain, _, _ = make(memory, reply("Poor Rex."))
    collect(brain.chat("Rex chewed my boots"))
    item = memory.index.items("conversation")[0]
    assert item.text == "Dan: Rex chewed my boots\nKit: Poor Rex."
    assert memory.index.missing_vectors("fake-embed") == []


def test_relevant_memories_are_in_the_prompt(memory):
    memory.add_fact("Dan's dog is called Rex.", "person")
    memory.add_fact("The thickener is on line 2.", "project")
    memory.add_fact("Dan likes metric units.", "preference", pinned=True)
    s = Settings.model_validate({"persona": {"name": "Kip"}, "memory": {"min_similarity": 0.3}})
    brain, model, _ = make(memory, settings=s)
    collect(brain.chat("How's my dog going?"))
    system = model.calls[0][0]["content"]
    assert "You are Kip" in system and "tilt_head" in system
    assert "Dan's dog is called Rex." in system and "(2026-10-05, person)" in system
    assert "Always keep in mind" in system and "metric" in system
    assert "thickener" not in system
    # What changes each turn (clock, memories) comes after the fixed persona text.
    assert system.index("Rex") > system.index("tilt_head") > system.index("You are Kip")


def test_history_is_in_the_prompt(memory):
    brain, model, _ = make(memory, reply("One."), reply("Two."))
    collect(brain.chat("first"))
    collect(brain.chat("second"))
    roles = [m["role"] for m in model.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert model.calls[1][-1]["content"] == "second"


def test_old_conversation_is_recalled_but_not_recent(memory):
    brain, model, _ = make(memory, reply("Noted."))
    collect(brain.chat("The Rex vet appointment is Friday"))
    memory.add_message("user", "filler")  # pushes nothing out; still recent
    brain2, model2, _ = make(memory, reply("Friday."))
    collect(brain2.chat("When is the Rex vet appointment?"))
    # Still in the recent history window, so not repeated as a snippet.
    assert "Earlier conversations" not in model2.calls[0][0]["content"]
    s = Settings.model_validate(
        {"brain": {"history_messages": 2}, "memory": {"min_similarity": 0.3}}
    )
    brain3, model3, _ = make(memory, reply("Friday."), settings=s)
    collect(brain3.chat("Rex vet appointment day?"))
    assert "The Rex vet appointment is Friday" in model3.calls[0][0]["content"]


def test_persona_change_applies_next_message(memory):
    settings = Settings()
    model = FakeModel()
    recall = Recall(memory, None, lambda: settings)
    brain = Brain(lambda: settings, memory, model, Expert(memory, lambda: None), recall)
    collect(brain.chat("hi"))
    settings = Settings.model_validate({"persona": {"name": "Changed"}})
    collect(brain.chat("hi"))
    assert "You are Changed" in model.calls[1][0]["content"]


def test_recall_action_searches_then_answers(memory):
    memory.add_fact("Dan's tax returns are in Documents/Finance/Tax.", "place")
    brain, model, _ = make(
        memory,
        reply("Let me think.", action="recall", text="tax returns folder"),
        reply("They're in Documents/Finance/Tax."),
    )
    events = collect(brain.chat("Where did I say my returns were?"))
    kinds = [e["type"] for e in events]
    assert kinds.count("reply") == 2 and "recalled" in kinds
    assert next(e for e in events if e["type"] == "recalled")["found"] == 1
    second = model.calls[1]
    assert second[-2]["role"] == "assistant" and "recall" in second[-2]["content"]
    assert "Documents/Finance/Tax" in second[-1]["content"]
    assert "Dan: Where did I say" in memory.index.items("conversation")[0].text
    assert "Let me think. They're in" in memory.index.items("conversation")[0].text
    # Next turn's history shows the answer, not the "Let me think" working step.
    history = memory.recent(10)
    assert [m.text for m in history] == [
        "Where did I say my returns were?",
        "They're in Documents/Finance/Tax.",
    ]


def test_recall_with_nothing_found_says_so(memory):
    brain, model, _ = make(
        memory, reply("Hmm.", action="recall", text="cat name"), reply("I don't know.")
    )
    collect(brain.chat("What's my cat called?"))
    assert "found nothing" in model.calls[1][-1]["content"]


def test_remember_action_learns(memory):
    brain, _, _ = make(
        memory, reply("Got it.", action="remember", text="Emma's birthday is 14 March.")
    )
    events = collect(brain.chat("Remember Emma's birthday is 14 March"))
    got = next(e for e in events if e["type"] == "remembered")
    assert got["decision"] == "new" and got["fact"] == "Emma's birthday is 14 March."
    assert memory.facts()[0].text == "Emma's birthday is 14 March."


def test_remember_action_updates(memory):
    memory.add_fact("Dan drives a Hilux.")
    brain, _, _ = make(
        memory,
        reply("Nice.", action="remember", text="Dan now drives a Ranger."),
        decision("update", 1, "Dan drives a Ford Ranger."),
    )
    events = collect(brain.chat("I traded the Hilux for a Ranger"))
    got = next(e for e in events if e["type"] == "remembered")
    assert got["decision"] == "update" and got["replaced"] == "Dan drives a Hilux."
    assert [f.text for f in memory.facts()] == ["Dan drives a Ford Ranger."]


def test_model_asks_for_claude_with_memories(memory):
    memory.add_fact("Dan is studying Kalman filters for the flotation model.", "project")
    brain, _, claude = make(
        memory, reply("Let me check with Claude.", action="ask_claude", text="Kalman maths?")
    )
    events = collect(brain.chat("Explain Kalman filters properly"))
    assert "asking_claude" in [e["type"] for e in events]
    last = events[-1]
    assert last["source"] == "claude" and last["cost_usd"] > 0
    call = claude.calls[0]
    assert call["messages"][-1]["content"] == "Kalman maths?"
    assert "flotation model" in call["system"][0]["text"]
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


def test_broken_json_keeps_the_words(memory):
    brain, _, _ = make(memory, '{"emotion": "happy", "segments": [{"say": "Half a thou')
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "reply"
    assert events[-1]["reply"]["segments"][0]["say"] == "Half a thou"


def test_bad_escape_in_the_stream_keeps_the_words(memory):
    brain, _, _ = make(memory, '{"segments": [{"say": "Hi\\uZZZZ there')  # bad escape, cut off
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "reply" and events[-1]["reply"]["segments"][0]["say"] == "Hi there"


def test_garbage_is_an_error_and_not_indexed(memory):
    brain, _, _ = make(memory, "nonsense")
    assert collect(brain.chat("hi"))[-1]["type"] == "error"
    assert memory.index.items("conversation") == []


def test_ollama_down_is_an_error(memory):
    brain, _, _ = make(memory, error="connection refused")
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "error" and "local brain" in events[-1]["message"]


def test_embeddings_down_still_chats(memory):
    memory.add_fact("Rex is the dog.")
    brain, model, _ = make(memory, reply("Rex!"), embedder=FakeEmbedder(fail=True))
    assert collect(brain.chat("How is Rex?"))[-1]["type"] == "reply"
    assert "Rex is the dog." in model.calls[0][0]["content"]


def test_blank_message_does_nothing(memory):
    brain, model, _ = make(memory)
    assert collect(brain.chat("   ")) == [] and model.calls == []


def test_yesterday_is_remembered_after_restart(paths, memory, clock):
    day = json.dumps(
        {
            "summary": "Dan talked about his dog Rex.",
            "facts": [{"kind": "person", "text": "Dan has a dog called Rex."}],
        }
    )
    brain, _, _ = make(memory, reply("Nice."), day)
    collect(brain.chat("My dog is called Rex"))
    clock.now += timedelta(days=1)
    assert asyncio.run(brain.summarise_past_days()) == ["2026-10-05"]
    assert asyncio.run(brain.summarise_past_days()) == []
    memory.close()

    fresh = Memory(paths.state_dir / "memory.db", clock)  # as if Kit restarted
    brain2, model2, _ = make(fresh, reply("Rex, right?"))
    collect(brain2.chat("What's my dog's name?"))
    system = model2.calls[0][0]["content"]
    assert "Dan has a dog called Rex." in system
    fresh.close()
