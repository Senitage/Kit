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


def test_the_topic_check_and_recall_share_one_embed_call(memory):
    memory.add_fact("Rex is Dan's dog.", "person")
    embedder = FakeEmbedder()
    recall = make(memory, embedder)
    asyncio.run(recall.index_pending())
    before = embedder.calls
    asyncio.run(recall.closeness("How is Rex?", ["What's the time?", "Any mail?"]))
    recalled = asyncio.run(recall.for_turn("How is Rex?", set()))
    assert embedder.calls == before + 1  # closeness embedded the message already
    assert [h.item.text for h in recalled.memories] == ["Rex is Dan's dog."]


def test_recall_takes_a_vector_it_is_handed(memory):
    memory.add_fact("Rex is Dan's dog.", "person")
    embedder = FakeEmbedder()
    recall = make(memory, embedder)
    asyncio.run(recall.index_pending())
    vector = asyncio.run(embedder.embed(["How is Rex?"], "query"))[0]
    before = embedder.calls
    recalled = asyncio.run(recall.for_turn("How is Rex?", set(), vector))
    assert embedder.calls == before
    assert [h.item.text for h in recalled.memories] == ["Rex is Dan's dog."]


# One search a turn, split by source, ranked as before


def _fixture(memory):
    pinned = memory.add_fact("Dan prefers metric units.", "preference", pinned=True)
    for n in range(6):
        memory.add_fact(f"Rex fact {n}: Rex the dog likes the beach.", "person")
    memory.add_fact("The thickener is on line 2.", "project")
    memory.save_day("2026-10-01", "Dan took Rex to the beach and fixed the thickener.")
    for n in range(30):
        memory.index_exchange(n, "Dan", f"Rex at the beach {n}", "Kit", "Good boy.")
    memory.index.add("self", "thought", "I like hearing about Rex at the beach.")
    memory.index.add("self", "thought", "Thickeners are oddly satisfying.")
    recall = make(memory, relevant_memories=3, conversation_snippets=2, own_memories=2)
    recall.register.add("Rex", "pet", aliases=["the dog"], about="Dan's kelpie")
    recall.register.add("Hilux", "vehicle", about="the ute")
    asyncio.run(recall.index_pending())
    return recall, pinned


def test_one_search_a_turn_gives_each_source_what_its_own_search_gave(memory):
    """The old way: four searches, one per source. The new way: one call, split by
    source. Every part must come out the same, in the same order."""
    from kit.memory import CONVERSATION, DAYS, FACTS, SELF
    from kit.things import THINGS

    recall, pinned = _fixture(memory)
    text = "How is Rex doing at the beach?"
    recent = {"3", "4"}

    async def old_way():
        memories = await recall.search(text, [FACTS, DAYS], 6, exclude={pinned})
        memories = recall.weighed(memories)[:3]
        hits = await recall.search(text, [CONVERSATION], 12)
        conversation = [h for h in hits if h.item.ref not in recent][:2]
        own = await recall.search(text, [SELF], 2)
        named = recall.register.mentioned_in(text)
        things = await recall.search(text, [THINGS], 5, exclude={t.id for t in named})
        return memories, conversation, own, named + [recall.register.get(h.item.id) for h in things]

    memories, conversation, own, things = asyncio.run(old_way())
    got = asyncio.run(recall.for_turn(text, recent))
    ids = lambda hits: [(h.item.id, round(h.score, 6)) for h in hits]  # noqa: E731
    assert ids(got.memories) == ids(memories) and len(memories) == 3
    assert ids(got.conversation) == ids(conversation) and len(conversation) == 2
    assert ids(got.own) == ids(own) and len(own) == 1
    assert [t.id for t in got.things] == [t.id for t in things[:5]] and things[0].name == "Rex"


def test_a_turn_searches_the_index_once_in_a_thread(memory, monkeypatch):
    import kit.recall as module

    recall, _ = _fixture(memory)
    hops = []
    real = module.asyncio.to_thread

    async def counted(fn, *args, **kwargs):
        hops.append(fn.__name__)
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", counted)
    got = asyncio.run(recall.for_turn("How is Rex doing at the beach?", set()))
    assert hops == ["search_many"]  # one search, off the event loop
    assert got.memories and got.conversation and got.own and got.things


def test_switched_off_parts_are_not_searched(memory):
    for n in range(3):
        memory.add_fact(f"Rex fact {n}.")
    recall = make(memory, conversation_snippets=0, own_memories=0, relevant_things=0)
    got = asyncio.run(recall.for_turn("Rex", set()))
    assert got.memories and got.conversation == [] and got.own == [] and got.things == []


# Recency: from when Dan told or confirmed it, never from being recalled


def test_being_recalled_does_not_make_a_fact_fresher(memory):
    from datetime import timedelta

    from kit.recall import weight

    memory.clock.now -= timedelta(days=60)
    old = memory.add_fact("Rex is Dan's dog.", "person")
    memory.clock.now += timedelta(days=60)
    recall = make(memory)
    asyncio.run(recall.index_pending())
    before = weight(memory.index.get(old), memory.clock(), 0.3)
    asyncio.run(recall.for_turn("How is Rex?", set()))
    item = memory.index.get(old)
    assert item.meta["last_recalled"] == "2026-10-05T09:00:00"  # still recorded
    assert weight(item, memory.clock(), 0.3) == before  # but no fresher for it
    memory.index.update_meta([old], {"confirmed": memory.clock().isoformat()})
    assert weight(memory.index.get(old), memory.clock(), 0.3) > before  # Dan said it again
