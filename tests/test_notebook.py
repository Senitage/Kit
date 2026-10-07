"""Kit's notebook: his thoughts, wants, journal, self-sheet and quirks."""

import random
from datetime import datetime, timedelta

import pytest

from fakes import Clock
from kit.life import QUIRK_POOL, WORK_QUIRKS
from kit.memory import SELF, SHEET, Memory
from kit.notebook import (
    ASK_LATER,
    EVERYDAY_KEY,
    FOR_LATER,
    Notebook,
    as_aim,
    later_want,
    same_entry,
    tomorrow_morning,
)


@pytest.fixture
def clock():
    return Clock("2026-10-07T10:00:00")


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


@pytest.fixture
def book(memory):
    return Notebook(memory)


def test_entries_are_kept_newest_first_without_near_repeats(book, clock):
    first = book.write("thought", "Dan has had pumps.py open all morning.")
    clock.now += timedelta(minutes=5)
    assert book.write("thought", "Dan has had pumps.py open all morning!") is None
    assert book.write("thought", "   ") is None
    opinion = book.write("opinion", "Tidy flowsheets are underrated.")
    odd = book.write("musing", "An unknown kind is kept as a thought.")
    assert [e.id for e in book.entries()] == [odd, opinion, first]
    assert [e.id for e in book.entries("thought")] == [odd, first]
    assert all(e.source == SELF for e in book.entries())


def test_different_wants_about_similar_things_both_stay():
    assert not same_entry(
        "Ask Dan whether the new cyclone feed pump passed its test.",
        "Ask Dan whether the thickener test passed.",
    )
    assert same_entry(
        "Tell Dan I counted forty-one open tabs yesterday.",
        "Tell Dan I counted 41 open tabs yesterday.",
    )


def test_wants_press_harder_the_longer_they_wait(book, clock):
    old = book.write("want", "Ask Dan whether the cyclone pump passed its test.")
    clock.now += timedelta(hours=2)
    new = book.write("want", "Tell Dan the printer is plotting something.")
    assert book.pressure(book.index.get(old)) == pytest.approx(0.9)
    assert book.pressure(book.index.get(new)) == pytest.approx(0.7)
    assert [w.id for w in book.open_wants()] == [old, new]
    assert book.pressing() == pytest.approx(0.9)
    clock.now += timedelta(hours=10)
    assert book.pressure(book.index.get(old)) == 1.0  # capped


def test_he_shares_his_most_pressing_want_then_a_fresh_thought(book, clock):
    thought = book.write("thought", "The shutdown plan has 214 rows.")
    want = book.write("want", "Ask Dan about the shutdown plan.")
    assert book.to_share().id == want
    book.mark_said(want)
    assert book.index.get(want).meta["said"] == "2026-10-07T10:00:00"
    assert book.open_wants() == [] and book.pressing() == 0.0
    assert book.to_share().id == thought
    book.mark_said(thought)
    assert book.to_share() is None
    fresh = book.write("thought", "Pump curves are oddly beautiful.")
    clock.now += timedelta(hours=4)  # old news by now
    assert book.index.get(fresh) is not None and book.to_share() is None


def test_whats_on_his_mind_lists_wants_then_recent_thoughts(book, clock):
    book.write("thought", "Something from yesterday.")
    clock.now += timedelta(hours=13)
    book.write("opinion", "Hydrocyclones are elegant.")
    clock.now += timedelta(minutes=20)
    book.write("want", "Ask Dan about lunch.")
    mind = book.mind("Dan")
    assert mind == [
        "(you want to ask Dan) about lunch.",
        "(20 minutes ago) Hydrocyclones are elegant.",
    ]
    assert book.latest_thought().text == "Hydrocyclones are elegant."


def test_a_want_for_tomorrow_waits_till_the_morning(book, clock):
    later = book.write(
        "want", "Tomorrow, ask Dan how the shutdown went.", after="2026-10-08T07:00:00"
    )
    lunch = book.write("want", "Ask Dan about lunch.")
    assert [w.id for w in book.open_wants()] == [lunch]
    assert [w.id for w in book.unsaid_wants()] == [lunch, later]
    assert book.pressure(book.index.get(later)) == 0.0
    assert book.mind("Dan") == [
        "(you want to ask Dan) about lunch.",
        "(you want to ask Dan tomorrow morning, not before) how the shutdown went.",
    ]
    book.mark_said(lunch)
    assert book.pressing() == pytest.approx(0.0) and book.to_share() is None
    clock.now += timedelta(hours=21)  # 07:00 the next day
    assert book.to_share().id == later
    assert book.pressing() == 1.0  # it's waited all night, so it can't wait any more


def test_tomorrow_is_after_he_has_slept():
    assert tomorrow_morning(datetime(2026, 10, 7, 15, 0), "07:00") == "2026-10-08T07:00:00"
    assert tomorrow_morning(datetime(2026, 10, 8, 0, 30), "07:00") == "2026-10-08T07:00:00"
    assert ASK_LATER.search("Ask me tomorrow how the shutdown went.")
    assert ASK_LATER.search("Tomorrow morning, remind me to ring Steve.")
    assert not ASK_LATER.search("Ask me anything. I'll know tomorrow.")
    assert FOR_LATER.search("Tomorrow: ask Dan how the shutdown went.")


def test_being_asked_to_ask_later_becomes_a_want_of_his_own():
    assert later_want("Ask me tomorrow how the shutdown went.", "Dan") == (
        "Ask Dan how the shutdown went."
    )
    assert later_want("Could you remind me in the morning to ring Steve?", "Dan") == (
        "Remind Dan to ring Steve."
    )
    assert later_want("Tomorrow, ask me how the shutdown went", "Dan") == (
        "Ask Dan how the shutdown went."
    )
    # Leaning on what came before, or speaking for Dan: Dan's words, as said.
    assert later_want("Big day. Ask me tomorrow how it went.", "Dan") == (
        'Dan asked you: "Big day. Ask me tomorrow how it went."'
    )
    assert later_want("Remind me tomorrow that I owe Steve a call.", "Dan").startswith(
        'Dan asked you: "Remind me'
    )


def test_a_want_is_what_he_means_to_do_and_what_about():
    # Put to a small model as a note, "Tell Dan I counted..." was read out word for word.
    assert as_aim("Tell Dan I counted 41 tabs.", "Dan") == ("tell Dan", "I counted 41 tabs.")
    assert as_aim("Tomorrow, ask Dan how the shutdown went.", "Dan") == (
        "ask Dan",
        "how the shutdown went.",
    )
    assert as_aim("Ask Dan's opinion on the pump.", "Dan") == (
        "bring this up",
        "Ask Dan's opinion on the pump.",
    )
    assert as_aim("The pump curve looks off.", "Dan") == (
        "bring this up",
        "The pump curve looks off.",
    )


def test_a_want_he_brings_up_himself_is_said(book):
    shutdown = book.write("want", "Ask Dan how the shutdown went.")
    pump = book.write("want", "Ask Dan whether the cyclone pump passed its test.")
    assert book.said_in("Which pump?", "Dan") == []
    assert book.said_in("Morning! How did the shutdown go?", "Dan") == [shutdown]
    assert [w.id for w in book.open_wants()] == [pump]


def test_small_thoughts_and_old_wants_fade_but_opinions_stay(book, clock):
    book.write("thought", "A passing thought.")
    book.write("want", "Ask about the pump.")
    book.write("opinion", "Tidy flowsheets are underrated.")
    book.write("moment", "Dan's tests went green, to a cheer.")
    clock.now += timedelta(days=8)
    assert book.tidy() == 1  # the want
    clock.now += timedelta(days=7)
    assert book.tidy() == 1  # the thought
    assert {e.kind for e in book.entries()} == {"opinion", "moment"}


def test_writing_a_days_journal_again_replaces_it(book):
    first = book.write_journal("2026-10-06", "Quiet day.")
    again = book.write_journal("2026-10-06", "Quiet day, then the build broke.")
    entry = book.journal("2026-10-06")
    assert entry.id == again and entry.created == "2026-10-06T23:59:59"
    assert [i.id for i in book.index.history(again)] == [again, first]
    assert book.on("2026-10-06") == []  # the journal isn't a note of the day


def test_only_notebook_entries_can_be_forgotten_here(book, memory):
    note = book.write("thought", "Forget me.")
    fact = memory.add_fact("Dan likes metric units.", "preference")
    assert not book.forget(fact)
    assert book.forget(note) and book.entries() == []


def test_self_sheet_versions_and_going_back(book, memory, clock):
    assert book.sheet() is None and book.sheet_history() == []
    first = book.set_sheet("I'm Kit. I like pumps.", basis="curious; cheeky")
    clock.now += timedelta(days=1)
    book.set_sheet("I'm Kit. I like pumps and teasing Dan.", basis="curious; cheeky")
    assert book.sheet().text.endswith("teasing Dan.")
    assert book.sheet().source == SHEET and book.sheet().meta["basis"] == "curious; cheeky"
    assert [s.text for s in book.sheet_history()][1] == "I'm Kit. I like pumps."
    restored = book.restore_sheet(first, "Dan")
    sheet = book.sheet()
    assert sheet.id == restored and sheet.text == "I'm Kit. I like pumps."
    assert sheet.meta["note"] == "Dan went back to the version from 2026-10-07"
    assert len(book.sheet_history()) == 3  # nothing lost
    assert "undid a change to your self-sheet" in book.vetoes()[0]
    assert book.restore_sheet(9999, "Dan") is None
    note = book.write("thought", "Not a sheet.")
    assert book.restore_sheet(note, "Dan") is None
    # The sheet is never recalled like a memory: it's always in his prompt.
    assert memory.index.items(SELF, kind="sheet") == []


def test_reviews_are_kept_newest_first(book, clock):
    book.add_review("Looks fine.", by="opus")
    clock.now += timedelta(days=7)
    book.add_review("He's got cheekier. Looks fine.", by="opus")
    assert [r.text for r in book.reviews()] == ["He's got cheekier. Looks fine.", "Looks fine."]


def test_quirks_can_be_retired_and_given_back(book, memory):
    book.set_quirks(["you love puns", "you count tabs", "you say righto"])
    book.set_quirks(["you love puns", "you count tabs", "you hum when it works"])
    assert book.retired_quirks() == [{"quirk": "you say righto", "by": "kit", "day": "2026-10-07"}]
    assert book.banned_quirks() == set()
    assert book.retire_quirk("you count tabs", "Dan")
    assert not book.retire_quirk("you count tabs", "Dan")
    assert book.quirks() == ["you love puns", "you hum when it works"]
    assert book.banned_quirks() == {"you count tabs"}
    assert "Don't bring it back" in book.vetoes()[-1]
    assert book.restore_quirk("you count tabs", "Dan")
    assert "you count tabs" in book.quirks() and book.banned_quirks() == set()
    assert not book.restore_quirk("you never had this", "Dan")


def test_vetoes_keep_only_the_latest(book):
    for n in range(15):
        book.add_veto(f"veto {n}")
    assert book.vetoes()[0] == "veto 5" and len(book.vetoes()) == 10


def test_work_quirks_are_swapped_for_everyday_ones_once(memory):
    # Dan asked for less talk about pumps, code and calculations.
    assert not set(QUIRK_POOL) & set(WORK_QUIRKS)
    book = Notebook(memory)
    assert book.swap_work_quirks("Dan") == []  # none picked yet: nothing to swap
    assert memory.self_value(EVERYDAY_KEY) is None
    righto = "you say 'righto' a bit too much"
    pumps, sheets = WORK_QUIRKS[0], "you compliment tidy spreadsheets"
    book.set_quirks([righto, pumps, sheets])
    assert book.swap_work_quirks("Dan", random.Random(1)) == [pumps, sheets]
    quirks = book.quirks()
    assert len(quirks) == 3 and quirks[0] == righto and set(quirks) <= set(QUIRK_POOL)
    assert {pumps, sheets} <= book.banned_quirks()  # his reflection won't bring them back
    assert "less talk about work" in book.vetoes()[-1]
    # Only once: one Dan gives back stays.
    assert book.restore_quirk(pumps, "Dan")
    assert book.swap_work_quirks("Dan") == [] and pumps in book.quirks()
