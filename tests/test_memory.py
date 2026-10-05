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
    assert memory.db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_spend_by_month(memory, clock):
    memory.record_spend("claude-opus-5-5", 10, 20, 0.5, "q")
    memory.record_spend("claude-opus-5-5", 10, 20, 0.25, "q")
    assert memory.month_spend() == pytest.approx(0.75)
    clock.now += timedelta(days=31)
    assert memory.month_spend() == 0
    assert len(memory.spend_log()) == 2


def test_forget_removes_earlier_versions_too(memory):
    old = memory.add_fact("Dan drives a Hilux.")
    new = memory.replace_fact(old, "Dan drives a Ranger.")
    assert memory.forget(new)
    assert memory.facts() == [] and memory.index.get(old) is None
