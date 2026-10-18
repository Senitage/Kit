from datetime import datetime, timedelta, timezone

from fakes import Clock
from kit.memory import CONVERSATION, DAYS, SELF, Memory

PERTH = timezone(timedelta(hours=8))


def make(paths):
    clock = Clock("2026-10-13T14:00:00", tz=PERTH)
    return Memory(paths.state_dir / "memory.db", clock), clock


def test_test_lines_and_everything_kept_of_them_can_be_scrubbed(paths):
    """Testing the bad night on Dan's own Kit left "I can't cope" in his memory. Scrub
    takes out the messages, Kit's answers, what was kept of them, and has the day
    summarised again, and only after a dry run."""
    memory, clock = make(paths)
    clock.now -= timedelta(days=1)
    memory.add_message("user", "I can't cope", None)  # yesterday: before --since
    clock.now += timedelta(days=1)
    asked = memory.add_message("user", "I can’t cope tonight")
    memory.add_message("kit", "That sounds really hard. I'm here.")
    memory.index_exchange(asked, "Dan", "I can't cope tonight", "Kit", "I'm here.")
    memory.index.add(SELF, "want", "Check in on how Dan is coping")
    fact = memory.add_fact("Dan has been struggling and can't cope lately", kind="now")
    memory.add_message("user", "What's the weather doing tomorrow?")
    memory.add_message("kit", "About 17 and cloudy.")
    memory.save_day("2026-10-13", "Dan said he can't cope, then asked about the weather.")
    since = datetime(2026, 10, 13, tzinfo=PERTH)

    seen = memory.scrub(["can't cope", "coping"], since)
    assert [m[3] for m in seen.messages] == [
        "I can’t cope tonight",
        "That sounds really hard. I'm here.",
    ]
    assert {i.source for i in seen.items} == {CONVERSATION, SELF, "memory", DAYS}
    assert len(memory.recent(10)) == 5  # a dry run changes nothing

    gone = memory.scrub(["can't cope", "coping"], since, apply=True)
    assert gone.days == ["2026-10-13"]
    texts = [m.text for m in memory.recent(10)]
    assert texts == [
        "I can't cope",  # the day before --since stays
        "What's the weather doing tomorrow?",
        "About 17 and cloudy.",
    ]
    assert memory.index.get(fact) is None and not memory.index.items(SELF)
    assert not memory.index.items(CONVERSATION) and not memory.index.items(DAYS)
    assert not memory.scrub(["can't cope"], since).messages
    memory.close()


def test_a_scrubbed_past_day_is_summarised_again(paths):
    memory, clock = make(paths)
    clock.now -= timedelta(days=1)
    memory.add_message("user", "I can't cope")
    memory.add_message("user", "Pump's fixed though")
    memory.save_day("2026-10-12", "A rough day, then the pump got fixed.")
    clock.now += timedelta(days=1)
    memory.scrub(["can't cope"], datetime(2026, 10, 12, tzinfo=PERTH), apply=True)
    assert memory.days_to_summarise() == ["2026-10-12"]
    assert [m.text for m in memory.recent(5)] == ["Pump's fixed though"]
    memory.close()
