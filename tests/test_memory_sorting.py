"""Sorting what Kit remembers: the day pass by the work model, what counts as a fact,
and `kit memory tidy` for the facts he already has."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, make_cloud
from kit.learning import Learner, apply_tidy, asking, plan_tidy, tidy_messages
from kit.memory import Memory
from kit.prompt import system_prompt
from kit.recall import Recall
from kit.settings import Settings

DAY = json.dumps(
    {
        "summary": "Dan told Kit about Lyla the cat and asked about pump cavitation.",
        "facts": [
            {"kind": "person", "text": "Lyla is Dan's one-year-old ragdoll cat.", "importance": 4},
            {"kind": "about", "text": "Dan likes reading and tinkering.", "importance": 3},
        ],
    }
)


@pytest.fixture
def clock():
    return Clock("2026-10-08T21:00:00")


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def decision(what="new", which=0, fact=""):
    return json.dumps({"decision": what, "which": which, "fact": fact})


def make(memory, *outputs, answer="{}", day_pass="work", key="k"):
    s = Settings.model_validate(
        {"memory": {"min_similarity": 0.3, "day_pass": day_pass}, "routing": {"mode": "cloud-only"}}
    )
    claude = FakeAnthropic(answer=answer)
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    model = FakeModel(*outputs)
    ask = asking(make_cloud(memory, claude, key=key), lambda: s)
    return Learner(memory, recall, model, ask), model, claude


def a_day(memory, clock, private=False):
    said = memory.add_message("user", "My cat Lyla is a one-year-old ragdoll.")
    if private:
        memory.said_privately(said)
    memory.add_message("user", "What causes pump cavitation?")
    clock.now += timedelta(days=1)


def test_the_work_model_reads_the_day_and_sorts_its_facts(memory, clock):
    learner, model, claude = make(memory, answer=[f"Here you go:\n{DAY}", decision()])
    a_day(memory, clock)
    assert asyncio.run(learner.summarise_day("2026-10-08", "Dan", "Kit", cloud=True))
    kinds = {f.kind: f.text for f in memory.facts()}
    assert kinds["person"].startswith("Lyla") and kinds["about"].startswith("Dan likes")
    # The work model read the day and compared the second fact with the first.
    assert model.calls == [] and [c["model"] for c in claude.calls] == ["claude-sonnet-5-5"] * 2
    asked = json.dumps(claude.calls[0])
    assert "Never a log of the conversation" in asked and "or a pet" in asked
    assert memory.month_spend() > 0


def test_a_day_with_something_kept_local_never_leaves_home(memory, clock):
    learner, model, claude = make(memory, DAY, decision(), answer=DAY)
    a_day(memory, clock, private=True)
    assert asyncio.run(learner.summarise_day("2026-10-08", "Dan", "Kit", cloud=True))
    assert claude.calls == [] and model.calls[0][0]["content"].startswith("You are Kit's memory")
    assert all(f.meta.get("private") for f in memory.facts())


def test_the_local_model_steps_in_when_the_cloud_cant(memory, clock):
    learner, model, claude = make(memory, DAY, decision(), answer="Sorry, no.")
    a_day(memory, clock)
    assert asyncio.run(learner.summarise_day("2026-10-08", "Dan", "Kit", cloud=True))
    assert len(claude.calls) == 2 and len(model.calls) == 2 and len(memory.facts()) == 2
    no_key, model, claude = make(memory, DAY, decision("same", 1), key=None)
    memory.add_message("user", "Another day.")
    clock.now += timedelta(days=1)
    assert asyncio.run(no_key.summarise_day("2026-10-09", "Dan", "Kit", cloud=True))
    assert model.calls[0][0]["content"].startswith("You are Kit's memory")


def test_day_pass_local_keeps_it_home(memory, clock):
    learner, model, claude = make(memory, DAY, decision(), answer=DAY, day_pass="local")
    a_day(memory, clock)
    assert asyncio.run(learner.summarise_day("2026-10-08", "Dan", "Kit"))
    assert claude.calls == [] and len(model.calls) == 2
    assert "Never a log of the conversation" in model.calls[0][0]["content"]


def test_the_brain_follows_the_day_pass_setting(paths, clock):
    from kit.brain import Brain

    for day_pass, cloud_calls in (("local", 0), ("work", 1)):
        memory = Memory(paths.state_dir / f"{day_pass}.db", Clock("2026-10-08T21:00:00"))
        s = Settings.model_validate({"memory": {"day_pass": day_pass}})
        claude = FakeAnthropic(answer=json.dumps({"summary": "A quiet one.", "facts": []}))
        recall = Recall(memory, FakeEmbedder(), lambda s=s: s)
        model = FakeModel(json.dumps({"summary": "A quiet one.", "facts": []}))
        brain = Brain(lambda s=s: s, memory, model, make_cloud(memory, claude, key="k"), recall)
        memory.add_message("user", "Quiet one.")
        memory.clock.now += timedelta(days=1)
        assert asyncio.run(brain.summarise_past_days()) == ["2026-10-08"]
        assert len(claude.calls) == cloud_calls
        memory.close()


# kit memory tidy


def seed(memory):
    memory.add_fact("Dan asked about the fundamentals of pump cavitation on 2026-10-06.", "about")
    memory.add_fact("Dan's cat Lyla is a one-year-old ragdoll.", "other")
    memory.add_fact("Dan asked about the cost of a used RTX 3090 in Australia.", "about")
    pinned = memory.add_fact("Dan answered that Brisbane is the capital of Queensland.", "other")
    memory.index.set_pinned(pinned, True)
    memory.add_fact("Dan's doctor wants more tests.", "about", private=True)
    return memory.facts()


def plan(*entries):
    return json.dumps(
        {"facts": [dict(zip(("n", "keep", "kind", "text"), e, strict=True)) for e in entries]}
    )


def test_tidy_drops_logs_moves_pets_and_keeps_what_a_question_showed(memory):
    facts = seed(memory)
    shared = plan(
        (1, False, "about", ""),
        (2, True, "person", ""),
        (3, True, "project", "Dan is thinking about a used RTX 3090 for Kit's server."),
        (4, False, "other", ""),  # pinned: kept whatever the model says
    )
    learner, model, claude = make(memory, plan((1, True, "now", "")), answer=shared)
    plans = asyncio.run(plan_tidy(facts, "Dan", "Kit", model, learner.ask))

    def by(start):
        return next(p for p in plans if p.item.text.startswith(start))

    assert not by("Dan asked about the fundamentals").keep
    assert by("Dan's cat Lyla").kind == "person"
    assert by("Dan answered that Brisbane").keep  # pinned
    # The private fact went to the local model only.
    assert "doctor" not in json.dumps(claude.calls) and "doctor" in model.calls[0][1]["content"]
    assert by("Dan's doctor").kind == "now"
    changed, dropped = apply_tidy(memory, [p for p in plans if p.changes])
    assert (changed, dropped) == (3, 1)
    now = {f.text: f for f in memory.facts()}
    assert "Dan is thinking about a used RTX 3090 for Kit's server." in now
    assert now["Dan's cat Lyla is a one-year-old ragdoll."].kind == "person"
    assert now["Dan answered that Brisbane is the capital of Queensland."].pinned
    assert not any("cavitation" in t for t in now)
    rtx = now["Dan is thinking about a used RTX 3090 for Kit's server."]
    assert [h.text for h in memory.index.history(rtx.id)][-1].startswith("Dan asked about the cost")


def test_a_fact_the_model_skips_is_left_alone(memory):
    facts = seed(memory)[:2]
    learner, model, _ = make(memory, answer=plan((2, True, "person", "")))
    plans = asyncio.run(plan_tidy(facts, "Dan", "Kit", model, learner.ask))
    assert not plans[0].changes and plans[1].kind == "person"


def test_the_tidy_prompt_says_what_a_fact_is():
    content = tidy_messages([], "Dan", "Kit")[0]["content"]
    assert "Never a log of the conversation" in content and "quiz" in content


def test_the_chat_model_knows_what_each_kind_is_for():
    from kit.recall import Recalled

    prompt = system_prompt(Settings().persona, Recalled([], [], []), datetime(2026, 10, 9, 9))
    assert "person: someone in their life, or a pet" in prompt
