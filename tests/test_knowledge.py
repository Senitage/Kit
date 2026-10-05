import asyncio

import pytest

from fakes import Clock, FakeEmbedder
from kit.knowledge import fts_query
from kit.memory import CONVERSATION, FACTS, Memory


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def embed_all(memory, embedder):
    async def go():
        items = memory.index.missing_vectors(embedder.model, 1000)
        vecs = await embedder.embed([i.text for i in items], "document")
        memory.index.save_vectors(
            embedder.model, [(i.id, v) for i, v in zip(items, vecs, strict=True)]
        )

    asyncio.run(go())


def query(embedder, text):
    return asyncio.run(embedder.embed([text], "query"))[0]


def test_fts_query_drops_stopwords_and_quotes():
    assert fts_query("Where is my tax-return?") == '"tax" OR "return"'
    assert fts_query("the and of") == ""


def test_word_search_finds_names_and_stems(memory):
    memory.add_fact("home_app runs on Django.")
    memory.add_fact("The dog is called Rex.")
    hits = memory.index.search("django apps")
    assert [h.item.text for h in hits] == ["home_app runs on Django."]
    assert hits[0].word_match


def test_meaning_search_finds_without_shared_words(memory):
    e = FakeEmbedder(same={"stuff": "returns"})
    memory.add_fact("Tax returns are in Documents/Finance/Tax.")
    memory.add_fact("The dog is called Rex.")
    embed_all(memory, e)
    hits = memory.index.search("my stuff", query(e, "my stuff"), e.model, min_similarity=0.3)
    assert [h.item.text for h in hits] == ["Tax returns are in Documents/Finance/Tax."]
    assert hits[0].similarity > 0.3 and not hits[0].word_match


def test_shared_common_word_alone_is_not_enough(memory):
    e = FakeEmbedder()
    memory.add_fact("Dan's dog is called Rex and loves the beach and long walks.")
    embed_all(memory, e)
    q = "What is my cat called?"
    hits = memory.index.search(q, query(e, q), e.model, min_similarity=0.5)
    assert hits == []


def test_word_match_counts_without_vectors(memory):
    memory.add_fact("The dog is called Rex.")
    e = FakeEmbedder()
    hits = memory.index.search("Rex", query(e, "Rex"), e.model)
    assert len(hits) == 1  # no vector yet, so words alone decide


def test_superseded_items_are_not_found(memory):
    e = FakeEmbedder()
    old = memory.add_fact("Dan drives a Hilux.")
    memory.replace_fact(old, "Dan drives a Ford Ranger.")
    embed_all(memory, e)
    hits = memory.index.search("Hilux", query(e, "Hilux"), e.model, min_similarity=0.1)
    assert all("Hilux" not in h.item.text for h in hits)


def test_sources_filter_and_exclude(memory):
    fact = memory.add_fact("Rex is the dog.")
    memory.index.add(CONVERSATION, "exchange", "Dan: Rex chewed a shoe")
    assert {h.item.source for h in memory.index.search("Rex", sources=[FACTS])} == {FACTS}
    assert len(memory.index.search("Rex")) == 2
    assert len(memory.index.search("Rex", exclude={fact})) == 1


def test_editing_text_drops_its_vector(memory):
    e = FakeEmbedder()
    item = memory.add_fact("one")
    embed_all(memory, e)
    assert memory.index.missing_vectors(e.model) == []
    memory.index.update(item, text="two")
    assert [i.id for i in memory.index.missing_vectors(e.model)] == [item]
    assert memory.index.search("two")[0].item.id == item


def test_vectors_from_another_model_are_ignored(memory):
    memory.add_fact("Rex is the dog.")
    embed_all(memory, FakeEmbedder())
    assert memory.index.similarities([1.0] * 256, "other-model") == {}
    assert len(memory.index.missing_vectors("other-model")) == 1


def test_delete_source_and_count(memory):
    memory.index.add("notes", "chunk", "a", ref="file1")
    memory.index.add("notes", "chunk", "b", ref="file2")
    assert memory.index.delete_source("notes", ref="file1") == 1
    assert memory.index.count("notes") == 1


def test_meaning_search_in_one_source_is_not_starved_by_another(memory):
    """Thousands of close chat snippets must not hide the one fact of the same meaning."""
    embedder = FakeEmbedder()
    fact = memory.add_fact("Shutdown planning notes are kept in the Shutdown folder.", "place")
    for n in range(80):
        memory.index.add(CONVERSATION, "exchange", f"Dan: shutdown planning notes {n}")
    embed_all(memory, embedder)
    q = "shutdown planning notes"
    hits = memory.index.search(q, query(embedder, q), embedder.model, sources=[FACTS], k=3)
    assert [h.item.id for h in hits] == [fact] and hits[0].similarity is not None


def test_new_vectors_are_seen_by_the_next_search(memory):
    embedder = FakeEmbedder()
    q = "flotation reagent"
    before = memory.index.search(q, query(embedder, q), embedder.model)
    assert before == []
    memory.add_fact("Flotation reagent dosing is 20 g/t.", "project")
    embed_all(memory, embedder)
    after = memory.index.search(q, query(embedder, q), embedder.model)
    assert len(after) == 1


def test_history_follows_every_earlier_version(memory):
    a = memory.add_fact("Dan has a Hilux.")
    b = memory.add_fact("Dan has a ute.")
    c = memory.add_fact("Dan drives a Ranger.")
    memory.index.supersede(a, c)
    memory.index.supersede(b, c)
    assert {i.id for i in memory.index.history(c)} == {a, b, c}
    assert memory.forget(c) and memory.facts() == []
