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


def test_each_source_counts_its_own_changes(memory):
    """A cached view of one source (the notes' names) goes stale only when that
    source changes, not every time a chat exchange is indexed."""
    index = memory.index
    before = index.changes("notes")
    a = index.add("notes", "chunk", "a", ref="file1")
    assert index.changes("notes") == before + 1
    index.add(CONVERSATION, "exchange", "Dan: hi")
    memory.add_fact("Rex is Dan's dog.", "person")
    assert index.changes("notes") == before + 1  # other sources don't count
    index.set_pinned(a, True)
    index.delete_source("notes", ref="file1")
    assert index.changes("notes") == before + 3


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


def test_meta_changes_keep_the_vector_and_items_filter_by_kind(memory):
    e = FakeEmbedder()
    want = memory.index.add("self", "want", "Ask Dan about lunch.", meta={"strength": 0.7})
    memory.index.add("self", "thought", "Pumps again.")
    embed_all(memory, e)
    assert memory.index.set_meta(want, {"strength": 0.7, "said": "2026-10-05T09:00:00"})
    assert memory.index.get(want).meta["said"] == "2026-10-05T09:00:00"
    assert memory.index.missing_vectors(e.model) == []  # same text, same vector
    assert not memory.index.set_meta(9999, {})
    assert [i.text for i in memory.index.items("self", kind="want")] == ["Ask Dan about lunch."]
    assert len(memory.index.items("self")) == 2


# The vector cache: kept in step with every write, never rebuilt for one change


def _vector_ids(memory, embedder):
    return set(memory.index.similarities(query(embedder, "x"), embedder.model))


def test_saved_vectors_join_the_cache_without_a_rebuild(memory):
    e = FakeEmbedder()
    first = memory.add_fact("Rex is the dog.")
    embed_all(memory, e)
    before = memory.index.similarities(query(e, "Rex"), e.model)
    matrix = memory.index._cache.matrix
    second = memory.add_fact("Tax returns are in Documents/Finance/Tax.")
    embed_all(memory, e)
    assert _vector_ids(memory, e) == {first, second}
    assert memory.index._cache.matrix is matrix  # the same matrix, one more row
    assert not memory.index._cache.dirty
    assert memory.index.similarities(query(e, "Rex"), e.model)[first] == before[first]


def test_superseded_edited_and_deleted_items_leave_the_cache(memory):
    e = FakeEmbedder()
    old = memory.add_fact("Dan drives a Hilux.")
    edited = memory.add_fact("The dog is called Rex.")
    gone = memory.add_fact("Dan once had a red bike.")
    memory.index.add("notes", "chunk", "a", ref="file1")
    kept = memory.index.add("notes", "chunk", "b", ref="file2")
    embed_all(memory, e)
    assert len(_vector_ids(memory, e)) == 5
    new = memory.replace_fact(old, "Dan drives a Ford Ranger.")  # supersedes old
    memory.index.update(edited, text="The dog is called Max.")  # its vector went
    memory.forget(gone)
    memory.index.delete_source("notes", ref="file1")
    assert _vector_ids(memory, e) == {kept}  # new and edited have no vector yet
    embed_all(memory, e)
    assert _vector_ids(memory, e) == {new, edited, kept}
    memory.index.delete_source("notes")
    assert _vector_ids(memory, e) == {new, edited}
    assert not memory.index._cache.dirty  # none of it needed a rebuild


def test_the_kept_cache_matches_a_rebuild_from_sqlite(memory):
    e = FakeEmbedder()
    ids = [memory.add_fact(f"fact number {n} about {'Rex' if n % 3 else 'tax'}") for n in range(12)]
    embed_all(memory, e)
    memory.index.supersede(ids[0], ids[1])
    memory.index.delete(ids[5])
    memory.index.update(ids[7], text="rewritten")
    memory.add_fact("Rex ate a sock.")
    embed_all(memory, e)
    q = query(e, "Rex")
    kept = memory.index.similarities(q, e.model)
    memory.index.mark_dirty()
    rebuilt = memory.index.similarities(q, e.model)
    assert kept == rebuilt and len(kept) == 11


def test_the_cache_grows_past_its_spare_rows(memory):
    from kit.knowledge import _SPARE_ROWS

    e = FakeEmbedder()
    memory.add_fact("the first")
    embed_all(memory, e)  # a small matrix, with spare rows
    ids = [memory.add_fact(f"fact {n}") for n in range(_SPARE_ROWS + 20)]
    embed_all(memory, e)
    found = _vector_ids(memory, e)
    assert len(found) == _SPARE_ROWS + 21 and set(ids) <= found
    memory.index.delete(ids[3])
    assert len(_vector_ids(memory, e)) == _SPARE_ROWS + 20


def test_a_vector_for_a_superseded_item_is_not_searched(memory):
    e = FakeEmbedder()
    old = memory.add_fact("Dan drives a Hilux.")
    embed_all(memory, e)
    new = memory.replace_fact(old, "Dan drives a Ranger.")
    memory.index.save_vectors(e.model, [(old, query(e, "Hilux")), (new, query(e, "Ranger"))])
    assert _vector_ids(memory, e) == {new}


def test_search_many_ranks_each_group_like_its_own_search(memory):
    from kit.knowledge import Query

    e = FakeEmbedder()
    for n in range(6):
        memory.add_fact(f"Rex fact {n}: the dog Rex and the beach.", "person")
    for n in range(40):
        memory.index.add(CONVERSATION, "exchange", f"Dan: Rex at the beach again {n}")
    memory.index.add("self", "thought", "I like hearing about Rex.")
    embed_all(memory, e)
    q = "Rex at the beach"
    vec = query(e, q)
    groups = [Query([FACTS], 4), Query([CONVERSATION], 5, frozenset({7})), Query(["self"], 3)]
    together = memory.index.search_many(q, vec, e.model, groups, min_similarity=0.3)
    apart = [
        memory.index.search(q, vec, e.model, g.sources, g.k, 0.3, set(g.exclude)) for g in groups
    ]
    assert [[(h.item.id, h.score) for h in hits] for hits in together] == [
        [(h.item.id, h.score) for h in hits] for hits in apart
    ]
    assert [len(hits) for hits in together] == [4, 5, 1]
