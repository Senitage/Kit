"""Kit's background work in the cloud (routing.background chat): his thoughts and
pipe-ups go to the chat model, fact comparisons to the work model, what Dan kept local
stays home, the local model steps in when the cloud can't, and in cloud-only mode the
local model leaves the GPU soon after it's used."""

import asyncio
import json

import httpx
import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.local_model import OllamaModel
from kit.memory import Memory
from kit.pc_context import Snapshot
from kit.recall import Recall
from kit.settings import Settings, local_settings

HAIKU = "claude-haiku-5-5"


def thought(text="Rain's coming, the cat will sulk."):
    return json.dumps({"thought": text, "kind": "thought", "want": "", "feeling": "same"})


def said(text):
    return json.dumps({"emotion": "happy", "segments": [{"say": text, "gesture": "nod"}]})


def snap():
    return Snapshot.model_validate(
        {"focus": {"app": "Chrome", "title": "Footy scores"}, "idle_seconds": 40}
    )


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-07T10:00:00"))
    yield m
    m.close()


def make(memory, *outputs, claude=None, background="chat", **sections):
    routing = {"background": background, **sections.pop("routing", {})}
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}, "routing": routing, **sections})
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude), recall)
    brain.pc.update(snap())
    return brain, model, claude


def test_stays_local_unless_dan_says_so():
    assert Settings().routing.background == "local"


def test_his_thoughts_go_to_the_chat_model(memory):
    brain, model, claude = make(memory, claude=FakeAnthropic(answer=thought()))
    had = asyncio.run(brain.think(("quiet", "A quiet moment.")))
    assert had is not None and had.text == "Rain's coming, the cat will sulk."
    assert [c["model"] for c in claude.calls] == [HAIKU] and model.calls == []
    assert [e.text for e in brain.notebook.entries()] == [had.text]


def test_with_background_local_the_local_model_thinks(memory):
    brain, model, claude = make(memory, thought(), background="local")
    assert asyncio.run(brain.think()) is not None
    assert claude.calls == [] and len(model.calls) == 1


def test_a_thought_from_what_dan_kept_local_stays_home(memory):
    brain, model, claude = make(memory, reply("Righto."), thought())
    collect(brain.chat("Keep it local: I'm thinking of quitting my job."))
    asyncio.run(brain.think())
    assert claude.calls == [] and len(model.calls) == 2


def test_when_the_cloud_cant_the_local_model_thinks(memory):
    brain, model, claude = make(memory, thought(), cloud={"monthly_cap_usd": 0})
    assert asyncio.run(brain.think()) is not None
    assert len(model.calls) == 1


def test_without_the_local_fallback_he_just_doesnt_think(memory):
    brain, model, _ = make(
        memory, thought(), cloud={"monthly_cap_usd": 0}, routing={"fallback_to_local": False}
    )
    assert asyncio.run(brain.think()) is None
    assert model.calls == []


def test_his_pipe_ups_go_to_the_chat_model(memory):
    brain, model, claude = make(memory, claude=FakeAnthropic(answer=said("Footy's on, eh?")))
    events = collect(brain.pipe_up("bored"))
    out = next(e for e in events if e["type"] == "reply")
    assert out["reply"]["segments"][0]["say"] == "Footy's on, eh?" and out["model"] == HAIKU
    assert out["source"] == "pipe_up"
    assert model.calls == [] and model.speak_calls == []


def test_a_pipe_up_he_said_lately_gets_another_go(memory):
    memory.add_message("kit", "Footy's on, eh? Who are we going for?")
    answers = [said("Footy's on, eh? Who are we going for?"), said("Fancy a cuppa?")]
    brain, _, claude = make(memory, claude=FakeAnthropic(answer=answers))
    events = collect(brain.pipe_up("bored"))
    out = next(e for e in events if e["type"] == "reply")
    assert out["reply"]["segments"][0]["say"] == "Fancy a cuppa?" and len(claude.calls) == 2
    assert "you've said that" in str(claude.calls[1]["messages"][-1]["content"])


def test_saying_the_same_thing_every_go_he_keeps_quiet(memory):
    memory.add_message("kit", "Footy's on, eh? Who are we going for?")
    again = said("Footy's on, eh? Who are we going for?")
    brain, _, claude = make(memory, claude=FakeAnthropic(answer=again))
    events = collect(brain.pipe_up("bored"))
    assert any(e["type"] == "kept_quiet" for e in events)
    assert not any(e["type"] == "reply" for e in events) and len(claude.calls) == 3


def test_a_pipe_up_from_what_dan_kept_local_stays_home(memory):
    brain, model, claude = make(memory, reply("So, the job thing?"))
    brain.notebook.write("want", "Ask Dan about the job thing.", private=True)
    collect(brain.pipe_up("want"))
    assert claude.calls == [] and len(model.calls) == 1


def test_when_the_cloud_cant_the_local_model_pipes_up(memory):
    brain, model, _ = make(memory, reply("Quiet in here."), cloud={"monthly_cap_usd": 0})
    events = collect(brain.pipe_up("bored"))
    assert any(e["type"] == "reply" for e in events) and len(model.calls) == 1


def test_a_fact_is_compared_by_the_work_model(memory):
    brain, model, claude = make(
        memory, claude=FakeAnthropic(answer='{"decision": "same", "which": 1, "fact": ""}')
    )
    memory.add_fact("Dan's cat is called Milo.", "person")
    learned = asyncio.run(brain.learner.learn("Dan's cat is Milo.", "person", "Dan", cloud=True))
    assert learned.decision == "same" and model.calls == []


def test_in_cloud_only_the_local_model_leaves_the_gpu_soon_after():
    def keep(**routing):
        return local_settings(Settings.model_validate({"routing": routing})).keep_alive

    assert keep() == "30m"
    assert keep(mode="cloud-only") == "30m"
    assert keep(background="chat") == "30m"  # balanced: it still answers chat
    assert keep(mode="cloud-only", background="chat") == "2m"


def test_ollama_is_told_how_long_to_keep_the_model():
    s = Settings.model_validate({"ollama": {"keep_alive": "5m"}})
    body = OllamaModel(lambda: s.ollama, None)._body(s.ollama, [], None, None)
    assert body["keep_alive"] == "5m"


def test_switching_over_takes_the_local_model_off_the_gpu_once(memory):
    brain, model, _ = make(memory, routing={"mode": "cloud-only"})
    asyncio.run(brain.free_gpu())
    asyncio.run(brain.free_gpu())
    assert model.unloads == 1


def test_the_local_model_stays_while_it_still_answers_chat(memory):
    brain, model, _ = make(memory)  # balanced: it answers small talk
    asyncio.run(brain.free_gpu())
    assert not hasattr(model, "unloads")


def test_ollama_is_asked_to_unload_the_chat_model():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})

    s = Settings.model_validate({"ollama": {"model": "gemma4:e4b"}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(OllamaModel(lambda: s.ollama, client).unload())
    assert seen == [{"model": "gemma4:e4b", "keep_alive": 0}]
