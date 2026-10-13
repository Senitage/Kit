"""One voice: the prompt says how Kit sounds once, in plain neutral English, with
at most two asides on a message, moods put the right way for replying and for being
alone, no guilt in his example lines, the reading fields kept private, and a goodbye
only when the goodbye is the whole of what Dan said."""

import random
import re
from datetime import datetime, timedelta

import pytest

from fakes import Clock, collect, reply
from kit.brain import PIPE_UP
from kit.life import (
    FAREWELL_HOOKS,
    FEELINGS,
    GUILT,
    HUFF,
    VOICE_LINES,
    Life,
    cheek_band,
    homecoming_prompt,
    is_farewell,
    pipe_up_prompt,
)
from kit.memory import Memory
from kit.notebook import Notebook
from kit.pc_context import PcContext
from kit.prompt import ASIDES_BUDGET, PRIVATE_FIELDS, system_prompt, within_budget
from kit.recall import Recalled
from kit.settings import OLD_PERSONA, PersonaSettings, Settings
from kit.thinking import thinking_messages
from test_companion import away_for, make

NOW = datetime(2026, 10, 7, 14, 30)
# Slang and regional words Kit's register rules out: none belongs in a prompt.
BANNED = re.compile(r"\b(arvo|mate|reckon|righto|oi|larrikin|aussie|australian|bloke)\b", re.I)
# The farewell hooks without the question mark: his examples may ask things.
HOOK_WORDS = re.compile(FAREWELL_HOOKS.pattern.replace(r"\?|", "", 1), re.I)


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-06T10:00:00"))
    yield m
    m.close()


def life_at(when=NOW, **settings) -> Life:
    s = Settings.model_validate({"life": settings})
    clock = Clock(when.isoformat())
    return Life(lambda: s, PcContext(clock), clock, random.Random(3))


def full_prompt(role: str, replying: bool = True, **kw) -> str:
    """The whole system prompt for one role, with his voice built the way the brain
    builds it: a mood, example lines from the pool, his last lines, his mind."""
    persona = PersonaSettings()
    life = life_at()
    life.drives.social = 0.9  # lonely: the mood with a phrasing for each case
    life.last_chat = NOW - timedelta(hours=3)
    voice = life.voice(
        "Dan",
        [(e.user, e.kit) for e in persona.examples],
        ["Morning.", "Not much."],
        ["you rate things out of ten"],
        "hey",
        ["(an hour ago) The rain's settled in."],
        ["Winter's the best time of year."],
        replying=replying,
    )
    return system_prompt(
        persona,
        Recalled([], [], []),
        NOW,
        role=role,
        voice=voice,
        sheet="I'm Kit. I live on the desk and I like a bad pun.",
        traits=False,
        two_pass=role == "local",
        pc="Dan is in VS Code.",
        read_mood=True,
        **kw,
    )


@pytest.mark.parametrize("role", ["chat", "local"])
def test_the_prompt_says_how_he_sounds_once(role):
    prompt = full_prompt(role)
    speech = PersonaSettings().speech
    assert prompt.count(speech) == 1
    assert prompt.lower().count("your voice") == 1  # "Your voice: ...", and nowhere else
    assert "Above all" not in prompt and "help desk" not in prompt
    assert "in your own voice" not in prompt
    # The old register pushes are gone: the persona decides it, nowhere else.
    assert not BANNED.search(prompt), BANNED.search(prompt)
    assert "casual" not in prompt
    assert "Plain, neutral English" in prompt


@pytest.mark.parametrize("role", ["chat", "local"])
def test_the_reading_fields_are_private_and_no_guilt_example_is_shown(role):
    prompt = full_prompt(role)
    assert PRIVATE_FIELDS.format(owner="Dan") in prompt
    for line in prompt.splitlines():
        if line.startswith("Kit: "):
            assert not GUILT.search(line) and not HOOK_WORDS.search(line), line


def test_the_voice_is_as_plain_in_a_hello_and_a_pipe_up():
    from kit.life import Homecoming

    home = Homecoming("hours", NOW - timedelta(hours=4), NOW)
    speech = PersonaSettings().speech
    for prompt in (
        homecoming_prompt(home, "Dan", 0.9, NOW, speech=speech),
        pipe_up_prompt("bored", "Dan", 0.9, "", 2.0, speech=speech),
    ):
        assert not BANNED.search(prompt), BANNED.search(prompt)
        assert prompt.count(speech) == 1


def test_the_old_default_voice_is_read_as_the_new_one():
    for old in OLD_PERSONA["speech"]:
        assert PersonaSettings.model_validate({"speech": old}).speech == PersonaSettings().speech


# Feelings: one phrasing for answering Dan, one for being on his own


def test_a_mood_is_put_for_replying_or_for_being_alone():
    life = life_at()
    life.drives.social = 0.9
    life.last_chat = NOW - timedelta(hours=3)
    assert (
        life.feeling_line("Dan") == "pleased to hear from Dan: you two haven't talked for 3 hours"
    )
    alone = life.feeling_line("Dan", replying=False)
    assert alone == "a bit lonely: you two haven't talked for 3 hours, and you'd like to"
    life.drives.social = 0.3
    life.drives.boredom = 0.8
    assert "glad of the company" in life.feeling_line("Dan")
    assert (
        life.feeling_line("Dan", replying=False) == "bored: nothing much has happened for a while"
    )
    for mood, (_, by_himself) in FEELINGS.items():
        assert "hear from" not in by_himself and "company" not in by_himself, mood


def test_a_pipe_up_and_a_thought_feel_the_mood_as_he_is_alone():
    prompt = full_prompt("local", replying=False)
    assert "a bit lonely: you two haven't talked for 3 hours" in prompt
    assert "pleased to hear from" not in prompt
    messages = thinking_messages(
        "Kit",
        "Dan",
        "I'm Kit.",
        [],
        "friendly",
        NOW,
        "A quiet moment.",
        "",
        "a bit sleepy",
        [],
        [],
        [],
    )
    assert "helps out" not in messages[0]["content"]
    assert "You feel a bit sleepy." in messages[1]["content"]


def test_a_feeling_that_explains_the_mood_is_not_said_twice():
    life = life_at()
    life.feel("put_out", "Dan didn't answer when you piped up at 2:05 pm", 0.8)
    life.sulky = True
    line = life.feeling_line("Dan")
    assert line.startswith("a bit put out, because Dan didn't answer")
    assert "underneath" not in line and "ignored you" not in line
    other = life_at()
    other.feel("chuffed", "Dan called you a legend", 0.8)
    other.sulky = True
    assert "; underneath, a little sulky" in other.feeling_line("Dan")


# Example lines: none of them is a guilt trip or a huff


def test_no_example_line_is_a_guilt_trip_or_a_huff():
    for band, pairs in VOICE_LINES.items():
        for _, kit in pairs:
            assert not GUILT.search(kit), (band, kit)
            assert not HUFF.search(kit), (band, kit)
            assert not HOOK_WORDS.search(kit), (band, kit)
            assert not BANNED.search(kit), (band, kit)
        work = [u for u, _ in pairs if "build" in u.lower() or "fixed" in u.lower()]
        assert not work, (band, work)
    assert cheek_band(0.9) == "cheeky"


# The asides budget


def test_at_most_two_asides_ride_with_a_message_the_best_ranked_first():
    asides = ["[pipe-up]", "[interview]", "[homecoming]", "[bedtime]", "[goodbye]", "[bad night]"]
    kinds = ["pipe_up", "interview", "homecoming", "bedtime", None, "bad_night"]
    sent = within_budget(asides, kinds)
    assert sent == ["[pipe-up]", "", "", "", "[goodbye]", "[bad night]"]  # in their places
    assert ASIDES_BUDGET == 2
    # Without a bad night, the pipe-up answer and the hello go; blanks don't count.
    kinds = ["pipe_up", "interview", "homecoming", "bedtime", None]
    assert within_budget(["", "[i]", "[h]", "[b]", "[g]"], kinds) == ["", "", "[h]", "[b]", "[g]"]
    # Of the rest, in order: bedtime, news, opener, interview.
    assert within_budget(["[i]", "[n]", "[o]"], ["interview", "news", "opener"]) == [
        "",
        "[n]",
        "[o]",
    ]


def test_a_message_carries_two_asides_at_most(memory):
    """A bad night, the answer to a pipe-up, a hello and a bedtime nudge all at once:
    the bad night and the pipe-up go with the message, the hello and the nudge don't."""
    brain, model, _ = make(memory, reply("I'm here."))
    clock = memory.clock
    clock.now = datetime(2026, 10, 7, 23, 30)
    memory.add_message("kit", "Still up?", reply("Still up?"), source=PIPE_UP)
    brain.notebook.write("want", "Tell Dan to get to bed.", nudge="sleep")
    brain.life.start_bad_night("Dan said 'I can't cope'")
    away_for(brain.life, brain.pc, clock, 50)
    assert brain.life.homecoming is not None
    collect(brain.chat("yeah. it's all a bit much tonight"))
    asked = model.calls[0][-1]["content"]
    assert "[Dan is having a really hard time." in asked
    assert "answering what you piped up with" in asked
    assert "bedtime" not in asked and "is back:" not in asked
    assert asked.count("[") == 2


# A goodbye is the whole message, or the whole last sentence


@pytest.mark.parametrize(
    "text",
    [
        "heading to lunch, check the pump logs while I'm gone",
        "ok heading to lunch, check the pump logs",
        "Check the pump logs. Off to lunch.",
        "Night Kit, don't leave the PC on",
        "Off to bed, remind me tomorrow about the dentist",
        "Off to lunch, can you look at the forecast",
    ],
)
def test_a_goodbye_with_a_request_in_it_is_a_request(text):
    assert not is_farewell(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fixed it. Off to lunch.",
        "Gotta go, the dentist's at 3",
        "Lunch time, back soon",
        "Thanks Kit, heading off",
        "Off to lunch, see ya",
        "Right, that's me done. Night Kit.",
    ],
)
def test_a_goodbye_with_only_a_goodbye_in_it_is_one(text):
    assert is_farewell(text)


# Smaller things said once


def test_held_and_butting_in_are_not_both_said():
    prompt = pipe_up_prompt("bored", "Dan", 0.5, "", 1, butting_in=True, held="7 minutes")
    assert "held this back for 7 minutes" in prompt and "butting in" not in prompt
    prompt = pipe_up_prompt("bored", "Dan", 0.5, "", 1, butting_in=True)
    assert "butting in" in prompt


def test_the_reflection_describes_how_cheeky_he_was_set(memory):
    brain, _, _ = make(memory, reply("Hi."))
    line = brain.reflector._persona()
    assert "How cheeky Dan set you: friendly, with a bit of cheek." in line
    assert "wants you" not in line and "Australian" not in line


def test_a_want_for_later_is_not_on_his_mind_till_it_is_due(memory):
    book = Notebook(memory)
    book.write("want", "Tomorrow, ask Dan how the shutdown went.", after="2026-10-08T07:00:00")
    assert book.mind("Dan") == []
    memory.clock.now = datetime(2026, 10, 8, 7, 1)
    assert book.mind("Dan") == ["(you want to ask Dan) how the shutdown went."]
