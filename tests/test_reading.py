"""The reading of Dan's message: the words guess, the model's plan decides, and the
words fill in where the plan left a field out (kit.brain.Reading). Also the plain-words
history, the one-line speaking note, the private flag read once, and the shape of a turn."""

import asyncio
import inspect
import json
from datetime import timedelta

import pytest

from fakes import (
    Clock,
    FakeAnthropic,
    FakeEmbedder,
    FakeModel,
    chat_and_learn,
    collect,
    make_cloud,
    reply,
)
from kit.brain import Brain, Reading, route
from kit.memory import Memory, Message
from kit.pc_context import Snapshot
from kit.prompt import JSON_REMINDER, history_messages, speak_note
from kit.recall import Recall, private
from kit.reply import Action, early_plan, parse_plan, plan_schema, reading_read
from kit.scene_context import SceneReport
from kit.server import pipe_up_now
from kit.settings import Settings


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def make(memory, *outputs, settings=None, claude=None, vault=None):
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    s = settings or Settings.model_validate({"memory": {"min_similarity": 0.3}})
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude, key="k"), recall)
    return brain, model, claude


def snap():
    return Snapshot.model_validate(
        {
            "host": "DESK",
            "focus": {"app": "VS Code", "title": "pump.py"},
            "idle_seconds": 2,
            "windows": [{"app": "VS Code", "title": "pump.py"}],
        }
    )


def scene():
    return SceneReport.model_validate(
        {
            "camera": "desk",
            "mirrored": True,
            "off": False,
            "frame_size": [1280, 720],
            "fps": 14.0,
            "people": [
                {"id": 1, "position": "centre", "seen_for_s": 30, "box": [0.3, 0.1, 0.7, 0.9]}
            ],
            "objects": [],
            "events": [],
        }
    )


# The plan's shape


def test_the_plan_reads_the_message_before_its_action():
    fields = list(plan_schema()["properties"])
    assert fields.index("crisis_candidate") < fields.index("action")
    assert fields[:2] == ["emotion", "gesture"]
    read = list(plan_schema(True)["properties"])
    assert read.index("dan_mood") < read.index("intent") < read.index("action")


def test_a_plan_without_the_reading_still_parses():
    plan = parse_plan('{"emotion": "happy", "gesture": "nod", "action": {"kind": "none"}}')
    assert plan.reading() == {}
    full = parse_plan(
        '{"emotion": "happy", "gesture": "nod", "intent": "news", "said_it": false, '
        '"action": {"kind": "none"}}'
    )
    assert full.reading() == {"intent": "news", "said_it": False}


def test_the_early_stop_keeps_the_reading():
    raw = (
        '{"emotion": "happy", "gesture": "nod", "intent": "goodbye", "about_kit": true, '
        '"action": {"kind": "none"'
    )
    assert early_plan(raw).reading() == {"intent": "goodbye", "about_kit": True}
    assert reading_read('{"intent": "made_up", "crisis_candidate": true}') == {
        "crisis_candidate": True
    }


# Words guess, the model decides, the words fill in


def test_the_words_guess_and_the_model_lays_its_reading_over():
    words = Reading.of("Right, I'm off to lunch.")
    assert words.goodbye and not words.given
    read = words.with_model({"intent": "request", "about_kit": None})
    assert read.intent == "request" and not read.goodbye and read.given == {"intent"}
    assert Reading.of("Had a big one at the shops today, took ages.").news
    assert Reading.of("Can you see me?").about_kit and Reading.of("what's open?").wants_pc_look
    assert Reading.of("Sydney's the capital, isn't it?").tag_question


def test_said_it_decides_what_is_remembered_and_the_words_fill_in():
    said = ["Night.", "Thanks mate"]
    fact = "Dan's sister Sarah's birthday is 12 March."
    assert not Reading.of("Night.").remembers(fact, said, "Dan")  # the words: Dan never said it
    assert Reading.of("Night.").with_model({"said_it": True}).remembers(fact, said, "Dan")
    said = ["My sister Sarah's birthday is 12 March."]
    assert Reading.of(said[0]).remembers(fact, said, "Dan")
    assert not Reading.of(said[0]).with_model({"said_it": False}).remembers(fact, said, "Dan")
    assert not Reading.of("Good night.").named("pumps.py - flotation-model", "Good night.")
    assert Reading.of("Good night.").with_model({"said_it": True}).named("pumps.py", "Good night.")


def test_a_request_as_the_model_read_it_is_a_note_asked_for():
    text = "Jot this down for me: the pump curve is 40 metres head."
    assert Reading.of(text).asked_for_note(text)  # the words
    assert not Reading.of(text).with_model({"intent": "news"}).asked_for_note(text)
    assert Reading.of("Dan says 40 m head").with_model({"intent": "request"}).asked_for_note("x")


def test_only_what_dan_said_is_remembered_unless_the_plan_says_he_said_it(memory):
    own_line = "You've said good night at 10:42 PM. I'll keep watch while you sleep."
    brain, _, _ = make(
        memory,
        reply("Night!", action="remember", text=own_line),
        reply("Noted.", action="remember", text="Dan's mate Al rides a Triumph.", said_it=True),
        reply("Ok.", action="remember", text="Dan drives a Ranger.", said_it=False),
    )
    _, learned = chat_and_learn(brain, "Good night.")
    assert learned == []  # no field: the words decide, and Dan never said it
    _, learned = chat_and_learn(brain, "Al came over on his new bike")  # other words, said_it
    assert [e["fact"] for e in learned] == ["Dan's mate Al rides a Triumph."]
    _, learned = chat_and_learn(brain, "I drive a Ranger now")  # the words agree, the plan doesn't
    assert learned == []


def test_a_thing_is_offered_only_when_dan_named_it_or_the_plan_says_so(memory):
    brain, _, _ = make(
        memory,
        reply("Shall I add it?", action="thing", text="Biscuit"),
        reply("Shall I add it?", action="thing", text="Biscuit", said_it=True),
    )
    events = collect(brain.chat("ok, cheers for that"))
    assert "thing_suggested" not in [e["type"] for e in events]
    events = collect(brain.chat("the little dog next door came over again"))
    assert "thing_suggested" in [e["type"] for e in events]


def test_the_plan_can_ask_for_a_look_at_the_pc_the_words_missed(memory):
    brain, model, _ = make(
        memory,
        reply("Let me see.", wants_pc_look=True),
        reply("The pump code, mostly."),
    )
    brain.pc.update(snap())
    events = collect(brain.chat("what am I even running"))
    assert "looked_at_pc" in [e["type"] for e in events]
    assert "What you can see on Dan's PC" in model.calls[1][-1]["content"]


def test_the_plan_can_ask_for_a_look_around_the_words_missed(memory):
    brain, model, _ = make(memory, reply("Let me see.", wants_camera_look=True), reply("Just you."))
    brain.saw(scene())
    events = collect(brain.chat("anyone else about"))
    assert "looked_around" in [e["type"] for e in events]
    assert "What you can see:" in model.calls[1][-1]["content"]


def test_a_look_the_words_already_took_is_not_taken_twice(memory):
    brain, model, _ = make(memory, reply("The pump code.", wants_pc_look=True))
    brain.pc.update(snap())
    events = collect(brain.chat("what's open on my PC?"))
    assert [e["type"] for e in events].count("looked_at_pc") == 1
    assert len(model.calls) == 1


def test_the_prompt_explains_the_reading_and_offers_looks_only_where_there_is_something_to_see(
    memory,
):
    brain, model, _ = make(memory, reply("Hi."), reply("Hi."))
    collect(brain.chat("hello"))
    system = model.calls[0][0]["content"]
    assert "Your reading of Dan's message" in system and "crisis_candidate" in system
    assert "wants_pc_look" not in system and "wants_camera_look" not in system
    brain.pc.update(snap())
    collect(brain.chat("hello again"))
    assert "wants_pc_look" in model.calls[1][0]["content"]


def test_a_cloud_reply_carries_the_reading_too(memory):
    s = Settings.model_validate({"routing": {"mode": "cloud-only"}})
    claude = FakeAnthropic(
        reply("Got it.", action="remember", text="Dan's mate Al rides a Triumph.", said_it=True)
    )
    brain, _, _ = make(memory, settings=s, claude=claude)
    _, learned = chat_and_learn(brain, "Al came over on his new bike")
    assert [e["fact"] for e in learned] == ["Dan's mate Al rides a Triumph."]
    assert "intent" in claude.calls[0]["system"][0]["text"]


# The private flag, read once


def test_keep_it_local_is_read_once_and_stored_with_the_message(memory):
    brain, model, claude = make(memory, reply("Sure."), reply("Ok."))
    collect(brain.chat("keep it local: the doctor rang about my results"))
    collect(brain.chat("thanks"))
    said = memory.recent(10)
    assert [m.private for m in said] == [True, False, False, False]
    assert [m.text for m in memory.shared(said)] == ["thanks", "Ok."]
    exchange = memory.index.items("conversation")[0]
    assert exchange.meta["private"] and private(exchange)
    assert not claude.calls


def test_the_flag_wins_over_the_words_and_old_rows_are_marked_from_theirs(memory):
    memory.add_message("user", "Keep it local: results day.")  # no flag given: the words
    memory.add_message("user", "Nothing secret here.", private=True)  # the flag given
    said = memory.recent(5)
    assert [m.private for m in said] == [True, True]
    assert memory.shared(said) == []
    assert route("plain question", Settings(), private=True) == ("local", True)
    assert route("keep it local", Settings()) == ("local", True)


def test_message_rows_round_trip_the_flag():
    row = (1, "2026-10-12T09:00:00", "user", "Hi", None, None, "desk", None, 1)
    m = Message.from_row(row)
    assert m.private is True and m.channel == "desk"


# History as words, the speaking note as a pointer


def test_history_shows_his_turns_as_words_with_one_reminder_of_the_shape():
    kit_json = reply("Morning!", detail="- one\n- two")
    history = [
        Message(1, "2026-10-12T09:00:00", "user", "Morning."),
        Message(2, "2026-10-12T09:00:05", "kit", "Morning!", kit_json),
        Message(3, "2026-10-12T09:01:00", "user", "Again."),
        Message(4, "2026-10-12T09:01:05", "kit", "Hi.", reply("Hi.")),
    ]
    shown = history_messages(history)
    assert shown[1]["content"] == "Morning!"  # words, no JSON, older detail dropped
    assert shown[3]["content"] == f"Hi.\n\n{JSON_REMINDER}"  # the latest turn reminds
    plain = history_messages(history, plain=True)
    assert plain[3]["content"] == "Hi." and "{" not in "".join(m["content"] for m in plain)


def test_the_speaking_note_is_one_reminder_not_a_second_copy():
    note = speak_note(
        Action(kind="none"),
        "Dan",
        "sonnet",
        "opus",
        heard="hey",
        mind="",
        speech="Talk like a pirate.",
    )
    assert "pirate" not in note and "Keep to the notes above" in note
    carried = speak_note(
        Action(kind="none"), "Dan", "sonnet", "opus", mind="[About yourself: you feel fine.]"
    )
    assert "Also: About yourself: you feel fine." in carried


# The turn's shape


def test_a_turn_is_five_short_steps():
    steps = ["_read", "_recall", "_route", "_converse_turn", "_afterwards"]
    source = inspect.getsource(Brain._run_turn)
    assert len(source.splitlines()) < 80
    assert all(f"self.{step}(" in source for step in steps)
    for step in steps:
        assert len(inspect.getsource(getattr(Brain, step)).splitlines()) < 90


def test_a_long_quiet_still_picks_up_one_thing_from_last_time(memory, clock):
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}, "life": {"chat_opener": True}})
    brain, model, _ = make(
        memory, reply("Good luck."), reply("Hey. How did the inspection go?"), settings=s
    )
    collect(brain.chat("Big inspection at the plant this afternoon, bit nervous about it"))
    clock.now += timedelta(hours=3)
    collect(brain.chat("hey"))
    asked = model.calls[1][-1]["content"]
    assert asked.startswith("(3 hours later) hey") and "When you two last talked" in asked
    assert len(model.calls[1]) > 2  # and the conversation itself is still there


THOUGHT = json.dumps({"thought": "Quiet today.", "kind": "thought", "want": "", "feeling": "same"})


def test_keep_it_local_in_cloud_only_routing_never_reaches_the_cloud(memory, clock):
    """Every cloud entry point stays home for a message Dan kept local, even when the
    cloud does everything else: the answer, the fact check and learning on the turn
    itself, then the next answers (an everyday one and a key moment), his thoughts,
    pipe-ups, the day's summary and his nightly reflection. Nothing he was told, nor
    what he said back or learned from it, is in anything a cloud model is sent."""
    s = Settings.model_validate(
        {
            "routing": {"mode": "cloud-only", "background": "chat", "check_facts": True},
            "memory": {"min_similarity": 0.3, "day_pass": "work"},
            "life": {"reflect_with": "cloud"},
        }
    )
    day = json.dumps({"summary": "Dan heard from the doctor.", "facts": []})
    night = json.dumps({"journal": "A quiet one.", "self_sheet": "I'm Kit.", "dan": "Waiting."})
    brain, model, claude = make(
        memory,
        reply("Fingers crossed.", action="remember", text="Dan's biopsy is Friday.", said_it=True),
        THOUGHT,
        day,
        night,
        settings=s,
        claude=FakeAnthropic(answer=reply("Sure thing.")),
    )
    _, learned = chat_and_learn(brain, "keep it local: the biopsy results come Friday, eh?")
    assert not claude.calls and model.calls  # the local model answered, and checked nothing
    assert learned and memory.facts()[0].meta["private"]
    assert "biopsy" in json.dumps(model.calls)  # at home, he knows

    chat_and_learn(brain, "What should I have for lunch?")
    chat_and_learn(brain, "My dog died this morning.")  # a key moment: the work model
    before = len(claude.calls)
    asyncio.run(pipe_up_now(brain, "bored"))
    assert len(claude.calls) > before  # pipe-ups go to the cloud
    assert asyncio.run(brain.think(("quiet", "A quiet moment."))) is not None  # at home
    clock.now += timedelta(days=1)
    assert asyncio.run(brain.summarise_past_days()) == ["2026-10-05"]
    before = len(claude.calls)
    assert asyncio.run(brain.reflector.reflect_day("2026-10-05")) is not None
    assert len(claude.calls) > before  # his reflection goes to the cloud first
    chat_and_learn(brain, "Any news on the results?")  # recall finds the kept fact

    assert len(claude.calls) >= 5  # the cloud did answer everything else
    sent = json.dumps(claude.calls, default=str).lower()
    assert "biopsy" not in sent and "fingers crossed" not in sent
