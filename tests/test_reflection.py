"""Kit's nightly reflection: journal, self-sheet, quirks, and the weekly review."""

import asyncio
import json
from datetime import timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, make_cloud
from kit.brain import Brain
from kit.memory import Memory
from kit.notebook import Notebook, basis
from kit.recall import Recall
from kit.reflection import REFLECTED_KEY, Reflector, clean_sheet, json_with, next_quirks
from kit.settings import Settings

DAY = "2026-10-07"
REFLECTION = {
    "journal": "Dan fought the build all afternoon. I felt for Dan, then we won.",
    "self_sheet": "I'm Kit. I keep Dan company and I've become the build's biggest critic.",
    "quirks": ["you love puns", "you count tabs", "you hum when a build finally passes"],
    "opinions": ["Flaky tests are worse than failing ones."],
    "moments": ["Dan cheered when the tests went green."],
    "wants": ["Ask Dan whether the build stayed green overnight."],
}


@pytest.fixture
def clock():
    return Clock(f"{DAY}T21:00:00")


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def make(memory, answers=(), outputs=(), key="k", **life):
    s = Settings.model_validate({"life": life})
    claude = FakeAnthropic(answer=list(answers) or "{}")
    model = FakeModel(*outputs)
    book = Notebook(memory)
    book.set_quirks(["you love puns", "you count tabs", "you say righto"])
    reflector = Reflector(memory, book, model, make_cloud(memory, claude, key=key), lambda: s)
    return reflector, book, claude, model


def a_day(memory, book):
    memory.add_message("user", "The build failed again.")
    memory.add_message("kit", "Again? It's not a build any more, it's a hobby.")
    book.write("thought", "Dan has been fighting that build for an hour.")


def test_first_self_sheet_is_written_by_the_work_model_from_the_persona(memory):
    sheet = "I'm Kit. I live on Dan's desk, I like pumps and I tease a little."
    reflector, book, claude, model = make(memory, [f'Here: {{"self_sheet": "{sheet}"}}'])
    assert asyncio.run(reflector.first_sheet())
    written = book.sheet()
    assert written.text == sheet
    assert written.meta["basis"] == basis(Settings().persona)
    assert written.meta["note"].startswith("first written by ")
    call = claude.calls[0]
    assert "tools" not in call  # no web search for writing about himself
    assert "Answer only with JSON in this shape" in call["messages"][-1]["content"]
    assert "you say righto" in call["messages"][-1]["content"]
    assert model.calls == [] and memory.month_spend() > 0  # logged as spend


def test_the_local_model_steps_in_when_the_cloud_cant(memory):
    local = json.dumps({"self_sheet": "I'm Kit, written at home."})
    reflector, book, claude, model = make(memory, outputs=[local], key=None)
    assert asyncio.run(reflector.first_sheet())
    assert book.sheet().text == "I'm Kit, written at home."
    assert book.sheet().meta["note"] == "first written by qwen3:8b"
    assert claude.calls == [] and model.calls[0][0]["content"].startswith("You are Kit")


def test_reflecting_locally_never_asks_the_cloud(memory):
    local = json.dumps({"self_sheet": "I'm Kit."})
    reflector, book, claude, _ = make(memory, outputs=[local], reflect_with="local")
    assert asyncio.run(reflector.first_sheet())
    assert claude.calls == []


def test_a_day_becomes_a_journal_entry_a_new_sheet_and_notes(memory, clock):
    reflector, book, claude, _ = make(memory, [json.dumps(REFLECTION)])
    first = book.set_sheet("I'm Kit. I keep Dan company.", basis(Settings().persona))
    book.write_journal("2026-10-05", "Dan laughed at my tab count.")
    book.write_journal("2026-10-06", "The pun fell flat again.")
    a_day(memory, book)
    done = asyncio.run(reflector.reflect_day(DAY))
    assert done.journal == REFLECTION["journal"]
    assert book.journal(DAY).text == REFLECTION["journal"]
    assert book.sheet().text == REFLECTION["self_sheet"] == done.sheet
    assert book.sheet().meta["note"] == f"after {DAY}, by {done.by}"
    assert book.sheet_history()[-1].id == first  # the old sheet is kept
    assert book.quirks() == REFLECTION["quirks"] == done.quirks
    assert book.retired_quirks()[-1]["quirk"] == "you say righto"
    assert done.added == [
        "opinion: Flaky tests are worse than failing ones.",
        "moment: Dan cheered when the tests went green.",
        "want: Ask Dan whether the build stayed green overnight.",
    ]
    want = book.unsaid_wants()[0]
    assert want.meta["day"] == DAY and want.meta["after"] == "2026-10-08T07:00:00"
    assert book.open_wants() == []  # things for tomorrow wait till the morning
    clock.now += timedelta(hours=10)
    assert book.open_wants()[0].id == want.id
    asked = claude.calls[0]["messages"][-1]["content"]
    assert "Dan: The build failed again." in asked
    assert "(21:00, thought) Dan has been fighting that build" in asked
    assert "Your self-sheet so far: I'm Kit. I keep Dan company." in asked
    assert "- (2026-10-05) Dan laughed at my tab count.\n- (2026-10-06) The pun fell" in asked


def test_a_changed_persona_has_him_bring_his_sheet_in_line(memory):
    # His sheet was written from a persona that loved process plants; Dan's changed it.
    reflector, book, claude, _ = make(memory, [json.dumps(REFLECTION)] * 2)
    book.set_sheet("I'm Kit. I love process plants and pumps.", "an old persona")
    a_day(memory, book)
    asyncio.run(reflector.reflect_day(DAY))
    system = " ".join(block["text"] for block in claude.calls[0]["system"])
    assert "has changed how they describe you since you wrote it" in system
    assert "Dan's work is a job, not Dan's whole life" in system
    assert book.sheet().meta["basis"] == basis(Settings().persona)
    asyncio.run(reflector.reflect_day(DAY))
    system = " ".join(block["text"] for block in claude.calls[1]["system"])
    assert "has changed how they describe you" not in system


def test_an_unchanged_sheet_isnt_a_new_version(memory):
    same = {**REFLECTION, "self_sheet": "I'm Kit. I keep Dan company."}
    reflector, book, _, _ = make(memory, [json.dumps(same)])
    book.set_sheet("I'm Kit. I keep Dan company.", "b")
    a_day(memory, book)
    done = asyncio.run(reflector.reflect_day(DAY))
    assert done.sheet == "" and len(book.sheet_history()) == 1


def test_what_dan_undid_is_in_front_of_him_when_he_reflects(memory):
    reflector, book, claude, _ = make(memory, [json.dumps(REFLECTION)])
    book.retire_quirk("you count tabs", "Dan")
    a_day(memory, book)
    done = asyncio.run(reflector.reflect_day(DAY))
    assert "you count tabs" not in done.quirks  # taken away, so it can't come back
    assert "Dan took away your quirk 'you count tabs'" in claude.calls[0]["messages"][-1]["content"]


def test_quirks_change_by_one_at_most_and_banned_ones_stay_gone():
    current = ["a puns", "b tabs", "c righto"]
    assert next_quirks(["x new", "y newer", "z newest"], current, set()) == [
        "b tabs",
        "c righto",
        "x new",
    ]
    assert next_quirks(["a puns", "b tabs"], current, set()) == ["a puns", "b tabs"]
    assert next_quirks([], current, set()) == current  # can't wipe them all at once
    assert next_quirks("not a list", current, set()) == current
    banned = {"you count the open tabs"}
    assert next_quirks(["you count open tabs", "a puns"], ["a puns"], banned) == ["a puns"]


def test_a_day_he_wasnt_part_of_needs_no_model(memory):
    reflector, book, claude, model = make(memory)
    done = asyncio.run(reflector.reflect_day("2026-10-01"))
    assert done.by == "" and done.journal == "" and claude.calls == [] and model.calls == []


def test_nothing_readable_means_try_again_later(memory):
    reflector, book, claude, model = make(memory, ["Lovely day!"], outputs=["not json"])
    a_day(memory, book)
    assert asyncio.run(reflector.reflect_day(DAY)) is None
    assert book.journal(DAY) is None


def test_he_starts_from_today_and_catches_up_a_few_days_at_most(memory, clock):
    reflector, *_ = make(memory)
    assert reflector.days_to_reflect() == []
    assert memory.self_value(REFLECTED_KEY) == "2026-10-06"
    clock.now += timedelta(days=1)
    assert reflector.days_to_reflect() == [DAY]
    clock.now += timedelta(days=5)
    assert reflector.days_to_reflect() == ["2026-10-10", "2026-10-11", "2026-10-12"]


def test_weekly_review_by_the_expert_model(memory, clock):
    answer = '{"review": "He got cheekier and kept his warmth. Looks fine."}'
    reflector, book, claude, _ = make(memory, [answer])
    first = book.set_sheet("I'm Kit.", "b")
    assert asyncio.run(reflector.review_week()) is None  # not a week yet
    clock.now += timedelta(days=7)
    second = book.set_sheet("I'm Kit, and cheekier.", "b")
    review = asyncio.run(reflector.review_week())
    assert review.text == "He got cheekier and kept his warmth. Looks fine."
    assert review.meta["sheet_before"] == first and review.meta["sheet_after"] == second
    assert claude.calls[0]["model"] == Settings().profile("expert").model
    asked = claude.calls[0]["messages"][-1]["content"]
    assert "His self-sheet a week ago: I'm Kit." in asked
    assert asyncio.run(reflector.review_week()) is None  # one a week
    assert book.reviews()[0].id == review.id


def test_no_weekly_review_when_turned_off(memory, clock):
    reflector, book, claude, _ = make(memory, weekly_review=False)
    book.set_sheet("I'm Kit.", "b")
    clock.now += timedelta(days=8)
    assert asyncio.run(reflector.review_week()) is None and claude.calls == []


def test_reading_json_from_a_chatty_cloud_answer():
    text = 'Sure! ```json\n{"journal": "draft"}\n``` Actually: {"journal": "final", "x": 1}'
    assert json_with(text, "journal") == {"journal": "final", "x": 1}
    assert json_with("no json here", "journal") is None
    assert clean_sheet("As an AI, I don't have a self.") == ""
    assert clean_sheet(None) == ""
    long = "I like pumps. " * 200
    assert len(clean_sheet(long).split()) <= 270 and clean_sheet(long).endswith(".")


def brain_for(memory, claude, **life):
    s = Settings.model_validate({"life": life, "memory": {"min_similarity": 0.3}})
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    cloud = make_cloud(memory, claude)
    return Brain(lambda: s, memory, FakeModel(), cloud, recall)


def test_the_brain_writes_a_first_sheet_then_reflects_each_finished_day(memory, clock):
    sheet = json.dumps({"self_sheet": "I'm Kit. I keep Dan company."})
    claude = FakeAnthropic(answer=[sheet, json.dumps(REFLECTION)])
    brain = brain_for(memory, claude)
    assert asyncio.run(brain.reflect()) == []  # first sheet, and he starts from today
    assert brain.notebook.sheet().text == "I'm Kit. I keep Dan company."
    a_day(memory, brain.notebook)
    clock.now += timedelta(hours=4)  # past midnight
    assert asyncio.run(brain.reflect()) == [DAY]
    assert memory.self_value(REFLECTED_KEY) == DAY
    assert brain.notebook.journal(DAY).text == REFLECTION["journal"]
    assert asyncio.run(brain.reflect()) == []  # done until tomorrow night
    assert len(claude.calls) == 2


def test_no_reflection_when_turned_off(memory):
    claude = FakeAnthropic()
    brain = brain_for(memory, claude, reflect_with="off")
    assert asyncio.run(brain.reflect()) == [] and claude.calls == []
    assert brain.notebook.sheet() is None


def test_a_job_that_keeps_failing_is_given_up_rather_than_paid_for_every_hour(memory, clock):
    claude = FakeAnthropic(answer="Sorry, I can't do JSON today.")
    brain = brain_for(memory, claude)
    brain.model.outputs = ["not json"] * 20
    for _ in range(4):
        assert asyncio.run(brain.reflect()) == []
    assert len(claude.calls) == 3  # three tries at his first sheet, then no more
    assert memory.self_value(REFLECTED_KEY) == "2026-10-06"  # he starts from today
    a_day(memory, brain.notebook)
    clock.now += timedelta(days=1)
    for _ in range(2):
        assert asyncio.run(brain.reflect()) == []
        assert memory.self_value(REFLECTED_KEY) == "2026-10-06"  # he'll try again
    assert asyncio.run(brain.reflect()) == []
    assert memory.self_value(REFLECTED_KEY) == DAY  # given up after three tries
    assert len(claude.calls) == 6


def test_a_weekly_review_that_keeps_failing_waits_for_tomorrow(memory, clock):
    reflector, book, claude, _ = make(memory, ["no json"], outputs=["nope"] * 10)
    book.set_sheet("I'm Kit.", "b")
    clock.now += timedelta(days=8)
    for _ in range(4):
        assert asyncio.run(reflector.review_week()) is None
    assert len(claude.calls) == 3
    clock.now += timedelta(days=1)
    asyncio.run(reflector.review_week())
    assert len(claude.calls) == 4
