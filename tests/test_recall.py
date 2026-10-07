import asyncio

import pytest

from fakes import Clock, FakeEmbedder
from kit.memory import Memory
from kit.recall import Recall
from kit.settings import Settings


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def make(memory, embedder=None, **memory_settings):
    s = Settings.model_validate({"memory": {"min_similarity": 0.3, **memory_settings}})
    return Recall(memory, embedder if embedder is not None else FakeEmbedder(), lambda: s)


def test_for_turn_brings_pinned_relevant_and_conversation(memory):
    pinned = memory.add_fact("Dan prefers metric units.", "preference", pinned=True)
    memory.add_fact("Rex is Dan's dog.", "person")
    memory.add_fact("The thickener is on line 2.", "project")
    memory.index_exchange(1, "Dan", "Rex ate my sock", "Kit", "Classic Rex.")
    memory.index_exchange(5, "Dan", "Rex again", "Kit", "Oh no.")
    recall = make(memory)
    asyncio.run(recall.index_pending())
    got = asyncio.run(recall.for_turn("How is Rex doing?", recent_refs={"5"}))
    assert [i.id for i in got.pinned] == [pinned]
    assert [h.item.text for h in got.memories] == ["Rex is Dan's dog."]
    assert [h.item.ref for h in got.conversation] == ["1"]


def test_limits_come_from_settings(memory):
    for n in range(5):
        memory.add_fact(f"Rex fact number {n}.")
    recall = make(memory, relevant_memories=2, conversation_snippets=0)
    got = asyncio.run(recall.for_turn("Rex", set()))
    assert len(got.memories) == 2 and got.conversation == []


def test_falls_back_to_words_and_reports(memory):
    memory.add_fact("Rex is the dog.")
    recall = make(memory, embedder=FakeEmbedder(fail=True))
    assert asyncio.run(recall.index_pending()) == 0
    hits = asyncio.run(recall.search("Rex", ["memory"], 5))
    assert len(hits) == 1 and "not found" in recall.embed_problem


def test_index_pending_batches(memory):
    for n in range(70):
        memory.add_fact(f"fact {n}")
    e = FakeEmbedder()
    recall = make(memory, embedder=e)
    assert asyncio.run(recall.index_pending()) == 70
    assert e.calls == 3  # batches of 32
    assert asyncio.run(recall.index_pending()) == 0


def test_one_turn_embeds_the_message_once(memory):
    memory.add_fact("Rex is Dan's dog.", "person")
    embedder = FakeEmbedder()
    recall = make(memory, embedder)
    asyncio.run(recall.index_pending())
    before = embedder.calls
    asyncio.run(recall.for_turn("How is Rex?", set()))
    assert embedder.calls == before + 1
