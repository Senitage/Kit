import sqlite3
from datetime import timedelta

import pytest

from fakes import Clock
from kit.memory import Memory


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def test_messages_survive_a_restart(paths, memory, clock):
    memory.add_message("user", "My dog is called Rex.")
    memory.add_message("kit", "Nice name.", '{"x": 1}', "local")
    memory.close()
    again = Memory(paths.state_dir / "memory.db", clock)
    assert [m.text for m in again.recent(10)] == ["My dog is called Rex.", "Nice name."]
    assert again.recent(1)[0].source == "local"
    again.close()


def test_a_reply_keeps_who_answered_it(memory):
    memory.add_message("kit", "Done.", None, "cloud", meta_json='{"role": "work"}')
    assert memory.recent(1)[0].meta_json == '{"role": "work"}'
    assert memory.recent(1)[0].channel is None


def test_recent_is_oldest_first_and_limited(memory):
    for i in range(5):
        memory.add_message("user", f"m{i}")
    assert [m.text for m in memory.recent(2)] == ["m3", "m4"]


def test_days_to_summarise(memory, clock):
    memory.add_message("user", "yesterday")
    clock.now += timedelta(days=1)
    memory.add_message("user", "today")
    assert memory.days_to_summarise() == ["2026-10-05"]
    memory.save_day("2026-10-05", "Talked about the dog.")
    assert memory.days_to_summarise() == []
    day = memory.index.items("days")[0]
    assert day.ref == "2026-10-05" and day.day == "2026-10-05"


def test_facts_replace_keeps_history(memory):
    old = memory.add_fact("Dan drives a Hilux.", "other")
    new = memory.replace_fact(old, "Dan drives a Ranger.")
    assert [f.text for f in memory.facts()] == ["Dan drives a Ranger."]
    history = [i.text for i in memory.index.history(new)]
    assert history == ["Dan drives a Ranger.", "Dan drives a Hilux."]
    assert memory.index.get(new).kind == "other"


def test_pinned_and_forget(memory):
    a = memory.add_fact("Dan likes metric.", "preference", pinned=True)
    memory.add_fact("Something else.")
    assert [f.id for f in memory.pinned_facts()] == [a]
    assert memory.forget(a) and not memory.forget(a)


def test_unknown_kind_becomes_other(memory):
    memory.add_fact("x", "nonsense")
    assert memory.facts()[0].kind == "other"


def test_backup_keeps_newest(memory, paths, clock):
    folder = paths.backups_dir
    memory.add_fact("keep me")
    for _ in range(3):
        memory.backup(folder, keep=2)
        clock.now += timedelta(days=1)
    copies = sorted(folder.glob("memory-*.db"))
    assert len(copies) == 2
    import sqlite3

    db = sqlite3.connect(copies[-1])
    assert db.execute("SELECT text FROM items").fetchone()[0] == "keep me"
    db.close()
    clock.now -= timedelta(days=1)
    assert memory.backed_up_today(folder)


def test_schema_version_is_recorded(memory):
    from kit.memory import MIGRATIONS

    assert memory.db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_old_database_is_migrated_forward(tmp_path, clock):
    """A database made by the first schema gains the knowledge index on open."""
    from kit.memory import MIGRATIONS, Memory

    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(MIGRATIONS[0])
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()
    memory = Memory(path, clock)
    assert memory.db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    memory.add_fact("Dan drives a Hilux.", "about")
    assert [f.text for f in memory.facts()] == ["Dan drives a Hilux."]


def test_spend_by_month(memory, clock):
    memory.record_spend("claude-opus-5-5", 10, 20, 0.5, "q")
    memory.record_spend("claude-opus-5-5", 10, 20, 0.25, "q")
    assert memory.month_spend() == pytest.approx(0.75)
    clock.now += timedelta(days=31)
    assert memory.month_spend() == 0
    assert len(memory.spend_log()) == 2


def test_replace_keeps_where_the_fact_came_from(memory):
    old = memory.add_fact("Dan drives a Hilux.", source_ref="2026-10-01")
    new = memory.replace_fact(old, "Dan drives a Ranger.")
    assert memory.index.get(new).ref == "2026-10-01"
    newer = memory.replace_fact(new, "Dan drives a blue Ranger.", source_ref="2026-10-04")
    assert memory.index.get(newer).ref == "2026-10-04"


def test_forget_removes_earlier_versions_too(memory):
    old = memory.add_fact("Dan drives a Hilux.")
    new = memory.replace_fact(old, "Dan drives a Ranger.")
    assert memory.forget(new)
    assert memory.facts() == [] and memory.index.get(old) is None


def test_a_recalled_conversation_can_be_forgotten(memory):
    memory.add_message("user", "Hey")
    memory.index_exchange(1, "Dan", "Hey", "Kit", "You're the one with the API key.")
    item = memory.index.items("conversation")[0]
    assert not memory.forget(item.id)  # not by the facts API
    assert memory.forget(item.id, conversation=True)
    assert memory.index.items("conversation") == []
    assert [m.text for m in memory.recent(5)] == ["Hey"]  # the chat log stays


def test_new_chat_hides_earlier_turns_but_keeps_the_log(memory):
    memory.add_message("user", "Hey")
    memory.add_message("kit", "You're the one with the API key.")
    memory.new_chat()
    assert memory.recent(10) == []
    memory.add_message("user", "Morning")
    assert [m.text for m in memory.recent(10)] == ["Morning"]
    assert len(memory.messages_on(memory.today())) == 3


def test_spend_summary_by_day_and_model(memory, clock):
    memory.record_spend("claude-sonnet-5-5", 1000, 200, 0.02, "q")
    memory.record_spend("claude-haiku-5-5", 500, 100, 0.001, "q")
    clock.now += timedelta(days=2)
    memory.record_spend("claude-sonnet-5-5", 3000, 400, 0.05, "q")
    s = memory.spend_summary(7)
    assert len(s["days"]) == 7 and s["days"][-1]["date"] == clock.now.date().isoformat()
    assert s["days"][-1]["by_model"] == {"claude-sonnet-5-5": 0.05}
    assert s["days"][-3]["cost_usd"] == pytest.approx(0.021)
    assert [m["model"] for m in s["models"]] == ["claude-sonnet-5-5", "claude-haiku-5-5"]
    assert s["models"][0]["calls"] == 2 and s["models"][0]["input_tokens"] == 4000
    assert s["total_usd"] == pytest.approx(0.071)
    assert memory.spend_summary(1)["total_usd"] == pytest.approx(0.05)
