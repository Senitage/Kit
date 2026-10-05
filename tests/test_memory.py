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
    memory.save_facts("2026-10-05", ["Dan has a dog called Rex.", " "])
    assert memory.days_to_summarise() == []
    assert [f.text for f in memory.facts()] == ["Dan has a dog called Rex."]


def test_facts_newest_kept_and_forget(memory):
    for i in range(3):
        memory.add_fact(f"f{i}")
    assert [f.text for f in memory.facts(2)] == ["f1", "f2"]
    first = memory.facts()[0]
    assert memory.forget(first.id) and not memory.forget(first.id)


def test_spend_by_month(memory, clock):
    memory.record_spend("claude-opus-5-5", 10, 20, 0.5, "q")
    memory.record_spend("claude-opus-5-5", 10, 20, 0.25, "q")
    assert memory.month_spend() == pytest.approx(0.75)
    clock.now += timedelta(days=31)
    assert memory.month_spend() == 0
    assert len(memory.spend_log()) == 2
