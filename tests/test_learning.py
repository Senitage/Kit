import asyncio
import json
from datetime import timedelta

import pytest

from fakes import Clock, FakeEmbedder, FakeModel
from kit.learning import Learner
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


def make(memory, *outputs, embedder=None):
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}})
    recall = Recall(memory, embedder or FakeEmbedder(), lambda: s)
    model = FakeModel(*outputs)
    return Learner(memory, recall, model), model, recall


def decision(what, which, fact):
    return json.dumps({"decision": what, "which": which, "fact": fact})


def learn(learner, text, kind="other"):
    return asyncio.run(learner.learn(text, kind))


def test_first_fact_is_added_without_asking_the_model(memory):
    learner, model, _ = make(memory)
    got = learn(learner, "Dan  drives a   Hilux.")
    assert got.decision == "new" and got.text == "Dan drives a Hilux."
    assert model.calls == []
    assert memory.index.missing_vectors("fake-embed") == []  # embedded straight away


def test_update_supersedes_the_old_fact(memory):
    learner, model, _ = make(memory, decision("update", 1, "Dan drives a Ford Ranger."))
    learn(learner, "Dan drives a Hilux.")
    got = learn(learner, "Dan sold the Hilux and drives a Ranger now.")
    assert got.decision == "update" and got.replaced == "Dan drives a Hilux."
    assert [f.text for f in memory.facts()] == ["Dan drives a Ford Ranger."]
    assert "Dan drives a Hilux." in model.calls[0][1]["content"]


def test_same_keeps_one_copy(memory):
    learner, _, _ = make(memory, decision("same", 1, ""))
    learn(learner, "Emma's birthday is 14 March.")
    got = learn(learner, "Emma has her birthday on 14 March.")
    assert got.decision == "same" and len(memory.facts()) == 1


def test_unrelated_fact_is_new(memory):
    learner, model, _ = make(memory, decision("new", 0, "x"))
    learn(learner, "Emma's birthday is 14 March.")
    learn(learner, "The thickener is on line 2.")
    assert len(memory.facts()) == 2


def test_bad_model_answer_falls_back_to_adding(memory):
    learner, _, _ = make(memory, "garbage", decision("update", 9, "out of range"))
    learn(learner, "Emma's birthday is 14 March.")
    learn(learner, "Emma's birthday is on 14 March.")
    learn(learner, "Emma birthday 14 March again.")
    assert len(memory.facts()) == 3


def test_works_when_embeddings_are_down(memory):
    learner, _, recall = make(memory, embedder=FakeEmbedder(fail=True))
    learn(learner, "Rex is the dog.")
    assert len(memory.facts()) == 1 and recall.embed_problem


def test_summarise_day_saves_summary_and_learns_facts(memory, clock):
    day = json.dumps(
        {
            "summary": "Worked on the flotation model; Rex was sick.",
            "facts": [
                {"kind": "project", "text": "Dan is fixing the flotation model."},
                {"kind": "person", "text": " "},
            ],
        }
    )
    learner, model, _ = make(memory, day)
    memory.add_message("user", "Rex is sick and the flotation model is broken")
    clock.now += timedelta(days=1)
    assert asyncio.run(learner.summarise_day("2026-10-05", "Dan", "Kit"))
    assert [f.kind for f in memory.facts()] == ["project"]
    assert memory.facts()[0].ref == "2026-10-05"
    assert memory.index.items("days")[0].text.startswith("Worked on")
    assert "[09:00] Dan: Rex is sick" in model.calls[0][1]["content"]
    assert memory.days_to_summarise() == []


def test_failed_summary_leaves_the_day_for_later(memory, clock):
    learner, _, _ = make(memory, "not json")
    memory.add_message("user", "hi")
    clock.now += timedelta(days=1)
    assert not asyncio.run(learner.summarise_day("2026-10-05", "Dan", "Kit"))
    assert memory.days_to_summarise() == ["2026-10-05"]
