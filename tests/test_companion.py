"""Kit as a companion (stage 1): he knows how long you were gone, says hello when
you're back and sees you off without guilt, knows himself, grows closer, and
suggests a small game now and then."""

import asyncio
import json
import random
from datetime import datetime, timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.evals import companion_report, run_companion_eval, seed_voice
from kit.life import (
    FAREWELL,
    FAREWELL_LINES,
    GAMES,
    HOME_LINES,
    NIGHT_LINES,
    Life,
    absence_kind,
    clock_words,
    closeness_words,
    farewell_fault,
    farewell_plans,
    gap_words,
    homecoming_facts,
    homecoming_fault,
    is_farewell,
    since_words,
)
from kit.memory import Memory
from kit.pc_context import PcContext, Snapshot
from kit.prompt import history_messages
from kit.recall import Recall
from kit.server import life_tick
from kit.settings import OLD_PERSONA, Settings
from kit.thinking import THOUGHT_SCHEMA

# Life on its own


class Store:
    """kit_self, in a dict."""

    def __init__(self):
        self.values = {}

    def self_value(self, key):
        return self.values.get(key)

    def set_self_value(self, key, value):
        self.values[key] = value


def snap(idle=5, locked=False, app="Chrome", title="Weekend weather - Google Chrome"):
    return Snapshot.model_validate(
        {"focus": {"app": app, "title": title}, "idle_seconds": idle, "locked": locked}
    )


def setup(when="2026-10-06T10:00:00", store=None, **life):
    clock = Clock(when)
    pc = PcContext(clock)
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1), store), pc, clock


def report(life, pc, s):
    pc.update(s)
    life.on_report()


def away_for(life, pc, clock, minutes, locked=False):
    """Dan at the PC, then gone for ``minutes`` (the desk app still reporting), then back."""
    report(life, pc, snap(idle=5))
    clock.now += timedelta(minutes=1)
    report(life, pc, snap(idle=400, locked=locked))
    clock.now += timedelta(minutes=minutes)
    report(life, pc, snap(idle=minutes * 60 + 400, locked=locked))
    report(life, pc, snap(idle=2))


def at(text):
    return datetime.fromisoformat(text)


def test_time_in_words():
    now = at("2026-10-12T09:00:00")  # a Monday
    assert gap_words(timedelta(minutes=52)) == "52 minutes"
    assert gap_words(timedelta(minutes=70)) == "about an hour"
    assert gap_words(timedelta(hours=3)) == "3 hours"
    assert gap_words(timedelta(days=3, hours=2)) == "3 days"
    assert gap_words(timedelta(days=8)) == "about a week"
    assert gap_words(timedelta(days=21)) == "3 weeks"
    assert since_words(at("2026-10-12T07:30:00"), now) == "this morning"
    assert since_words(at("2026-10-11T22:00:00"), now) == "last night"
    assert since_words(at("2026-10-12T01:30:00"), now) == "last night"  # still last night
    assert since_words(at("2026-10-11T15:00:00"), now) == "yesterday arvo"
    assert since_words(at("2026-10-09T18:40:00"), now) == "Friday evening"
    assert since_words(at("2026-09-26T18:40:00"), now) == "26 September"
    assert clock_words(at("2026-10-09T18:40:00"), now) == "on Friday at 6:40 pm"
    assert clock_words(at("2026-10-12T08:05:00"), now) == "at 8:05 am"


def test_how_big_an_absence_is():
    def kind(since, now):
        return absence_kind(at(since), at(now), "22:00", "07:00")

    assert kind("2026-10-12T09:00:00", "2026-10-12T09:15:00") is None
    assert kind("2026-10-12T09:00:00", "2026-10-12T09:50:00") == "while"
    assert kind("2026-10-12T09:00:00", "2026-10-12T13:30:00") == "hours"
    assert kind("2026-10-11T21:30:00", "2026-10-12T07:30:00") == "overnight"
    assert kind("2026-10-12T06:50:00", "2026-10-12T17:00:00") == "hours"  # out all day
    assert kind("2026-10-09T17:30:00", "2026-10-12T08:00:00") == "days"
    assert kind("2026-10-01T17:30:00", "2026-10-12T08:00:00") == "long"


@pytest.mark.parametrize(
    "text",
    [
        "Right, I'm off to lunch.",
        "Off to lunch",
        "Night Kit",
        "Good night!",
        "bye",
        "See you later",
        "Heading home now",
        "I'm off, back in a bit",
        "Gotta go, the dentist's at 3",
        "Logging off for the day",
        "Night",
    ],
)
def test_goodbyes_are_heard(text):
    assert FAREWELL.search(text)
    assert is_farewell(text)


@pytest.mark.parametrize(
    "text",
    [
        "Turn it off for a bit",
        "I had a good night's sleep",
        "I'm off sick today",
        "I have to go through the logs",
        "The pump came back after maintenance",
        "Can you see the error?",
    ],
)
def test_other_things_are_not_goodbyes(text):
    assert not is_farewell(text)


def test_a_goodbye_that_says_where_he_is_off_to():
    assert farewell_plans("Off to lunch")
    assert farewell_plans("Heading to the dentist, back in an hour.")
    assert not farewell_plans("Night Kit.")
    assert not farewell_plans("Right, bye mate")


def test_goodbye_and_hello_lines_are_checked_for_guilt():
    assert farewell_fault("Enjoy lunch.") == ""
    assert "question" in farewell_fault("Enjoy lunch! Back soon?")
    assert '"already"' in farewell_fault("Already? Fine.")
    assert farewell_fault("Go on then, I'll be fine on my own.")
    assert homecoming_fault("There you are. How was lunch?") == ""
    assert homecoming_fault("Where have you been?")
    assert homecoming_fault("How was it? Did you eat?")  # two questions
    assert homecoming_fault("Finally!")
    assert homecoming_fault("Oh, so you're alive. Finally.", miffed=True) == ""


def test_back_after_fifty_minutes_he_is_glad_and_says_hello_once():
    life, pc, clock = setup()
    away_for(life, pc, clock, 50)
    home = life.homecoming
    assert home is not None and home.kind == "while" and not home.miffed
    assert home.dozed  # asleep after ten minutes
    assert life.feeling_now().name == "glad"
    assert [e["state"] for e in life.events_after(0) if e["type"] == "state"] == [
        "asleep",
        "awake",
    ]
    assert life.tick() == "back"  # straight away, as Dan sits down
    life.piped_up("back")
    assert life.homecoming is None and not life.awaiting_reply  # a hello needs no answer
    assert life.tick() != "back"


def test_a_short_absence_is_not_worth_a_hello():
    life, pc, clock = setup()
    away_for(life, pc, clock, 12)
    assert life.homecoming is None
    assert life.think_now()[0] == "back"  # but it's worth a thought


def test_he_asks_how_it_went_when_dan_said_where_he_was_off_to():
    life, pc, clock = setup()
    life.said_goodbye("Off to lunch, back in a bit")
    away_for(life, pc, clock, 50)
    home = life.homecoming
    assert home.goodbye == "Off to lunch, back in a bit"
    facts = homecoming_facts(home, "Dan", clock.now)
    assert "you hadn't seen them since this morning (51 minutes)" in facts
    assert "ask how it went, in the past tense" in facts
    assert "Don't ask where they've been" in facts
    assert life.goodbye is None  # used up


def test_lock_friday_unlock_monday_is_since_friday():
    life, pc, clock = setup("2026-10-09T17:30:00")
    report(life, pc, snap(idle=5))
    clock.now += timedelta(minutes=1)
    report(life, pc, snap(locked=True))
    clock.now = at("2026-10-12T08:00:00")
    report(life, pc, snap(idle=1))
    home = life.homecoming
    assert home.kind == "days"
    facts = homecoming_facts(home, "Dan", clock.now)
    assert "since Friday evening (3 days)" in facts and "missed them" in facts
    assert "last talked on Friday at 5:30 pm (3 days ago)" in life.time_line("Dan")


def test_a_restart_while_dan_is_away_keeps_the_gap_and_says_he_was_off():
    store = Store()
    life, pc, clock = setup("2026-10-09T17:30:00", store)
    report(life, pc, snap(idle=5))
    clock.now += timedelta(minutes=12)
    report(life, pc, snap(idle=700))  # he's gone, and Kit dozes
    assert life.asleep
    life.save()
    clock.now = at("2026-10-10T09:00:00")  # the server was off all night
    pc = PcContext(clock)
    life = Life(lambda: Settings(), pc, clock, random.Random(1), store)
    assert life.asleep and life.was_off[1] == clock.now
    report(life, pc, snap(idle=2))
    home = life.homecoming
    assert home.kind == "overnight" and home.since == at("2026-10-09T17:30:20")  # last input
    assert home.off is not None
    facts = homecoming_facts(home, "Dan", clock.now)
    assert "switched off from yesterday at 5:42 pm until 9:00 am" in facts
    assert "don't know what happened then" in facts and "Don't make up anything" in facts


def test_miffed_after_hours_gone_in_the_daytime_without_a_goodbye_but_not_in_week_one():
    life, pc, clock = setup("2026-10-06T09:00:00")
    away_for(life, pc, clock, 4 * 60)
    assert not life.homecoming.miffed  # his first week: just glad
    life, pc, clock = setup("2026-10-06T09:00:00")
    life.companion_since -= timedelta(days=8)
    life.said_goodbye("off to the shops")
    away_for(life, pc, clock, 4 * 60)
    assert not life.homecoming.miffed  # he said goodbye
    life, pc, clock = setup("2026-10-06T09:00:00")
    life.companion_since -= timedelta(days=8)
    away_for(life, pc, clock, 4 * 60)
    assert life.homecoming.miffed and life.feeling_now().name == "miffed"
    assert "mock huff" in homecoming_facts(life.homecoming, "Dan", clock.now)
    life.note_chat("hey")  # he's had his say: it passes
    assert life.feeling_now().name == "glad"
    life, pc, clock = setup("2026-10-06T09:00:00", miffed=False)
    life.companion_since -= timedelta(days=8)
    away_for(life, pc, clock, 4 * 60)
    assert not life.homecoming.miffed


def test_no_hello_with_homecoming_off():
    life, pc, clock = setup(homecoming=False)
    away_for(life, pc, clock, 50)
    assert life.homecoming is None and life.think_now()[0] == "back"


def test_no_hello_in_quiet_hours_but_his_next_reply_says_it():
    life, pc, clock = setup("2026-10-06T22:30:00")
    away_for(life, pc, clock, 50)
    assert life.tick() is None and life.homecoming is not None
    home = life.homecoming_for_chat()
    assert home is not None and life.homecoming is None


def test_a_hello_not_said_goes_stale():
    life, pc, clock = setup(chattiness=0)
    away_for(life, pc, clock, 50)
    clock.now += timedelta(minutes=31)
    pc.update(snap(idle=2))
    life.tick()
    assert life.homecoming is None


def test_without_the_desk_app_a_long_gap_in_the_chat_counts():
    life, pc, clock = setup()
    clock.now += timedelta(hours=2)
    assert life.homecoming_for_chat() is None
    clock.now += timedelta(hours=2)
    home = life.homecoming_for_chat()
    assert home.by_chat and home.kind == "hours"
    assert "You and Dan haven't talked since this morning (4 hours)" in homecoming_facts(
        home, "Dan", clock.now
    )


def test_leaving_soon_after_a_pipe_up_is_not_ignoring_him():
    life, pc, clock = setup()
    report(life, pc, snap(idle=5))
    life.piped_up("bored")
    clock.now += timedelta(minutes=2)
    for _ in range(24):  # Dan's gone: twelve minutes of ticks with nobody at the PC
        clock.now += timedelta(seconds=30)
        pc.update(snap(idle=400))
        life.tick()
    assert not life.awaiting_reply and life.ignored == 0 and not life.sulky


def test_he_misses_dan_after_a_day_unseen():
    life, pc, clock = setup()
    clock.now += timedelta(hours=25)
    life.tick()
    felt = life.feeling_now()
    assert felt.name == "missing" and felt.why == "you haven't seen Dan since yesterday morning"


def test_closeness_grows_a_little_a_day_and_is_a_word():
    life, pc, clock = setup()
    assert closeness_words(life.closeness)[0] == "getting to know you"
    for _ in range(50):
        life.note_chat("haha thanks mate")
    assert life.closeness == pytest.approx(0.22)  # at most 0.02 a day
    life.note_chat("you're useless")
    assert life.closeness == pytest.approx(0.20)
    for _ in range(6):
        clock.now += timedelta(days=1)
        for _ in range(10):
            life.note_chat("cheers")
    assert life.state()["closeness"] == "warming up"
    assert "you're warming up to each other" in life.voice("Dan", [], [], []).close


def test_his_time_line_says_how_long_since_you_talked_and_where_dan_is():
    life, pc, clock = setup("2026-10-12T09:00:00")
    life.last_chat = at("2026-10-09T18:40:00")
    report(life, pc, snap(idle=5))
    clock.now += timedelta(minutes=1)
    report(life, pc, snap(idle=600))
    clock.now += timedelta(minutes=30)
    pc.update(snap(idle=2400))
    line = life.time_line("Dan")
    assert "You and Dan last talked on Friday at 6:40 pm (3 days ago)." in line
    assert "Dan has been away from the PC since 8:59 am (31 minutes)." in line


def test_a_game_a_day_when_hes_bored_and_dan_is_about():
    life, pc, clock = setup(store=Store())
    pc.update(snap(idle=40))
    assert life.game_due() is None  # not bored yet
    life.drives.boredom = 0.9
    name = life.game_due()
    assert name in GAMES and name != "rate_lunch"  # lunch is for after lunch
    assert life.game_due() is None  # one a day
    clock.now += timedelta(days=1)
    pc.update(snap(idle=40))
    assert life.game_due() is not None


def test_a_game_that_keeps_flopping_retires():
    life, pc, clock = setup(store=Store(), chattiness=0.5)
    for _ in range(3):
        report(life, pc, snap(idle=5))
        life.piped_up("bored")
        life.game_asked("would_you_rather")
        for _ in range(22):  # Dan stays at the PC and says nothing
            clock.now += timedelta(seconds=30)
            pc.update(snap(idle=40))
            life.tick()
        life.note_chat()  # later on, they talk about something else
    assert life.retired_games() == ["would_you_rather"]
    life.drives.boredom = 0.9
    for _ in range(20):
        clock.now += timedelta(days=1)
        pc.update(snap(idle=40))
        assert life.game_due() != "would_you_rather"


def test_his_state_after_a_restart():
    store = Store()
    life, pc, clock = setup(store=store)
    life.said_goodbye("off to the shops")
    life.closeness = 0.6
    life.save()
    clock.now += timedelta(minutes=5)
    life = Life(lambda: Settings(), PcContext(clock), clock, random.Random(1), store)
    assert life.goodbye[1] == "off to the shops" and life.closeness == 0.6
    assert life.was_off is None  # five minutes isn't worth knowing about
    state = life.state()
    assert state["closeness"] == "at home" and state["goodbye"] == "off to the shops"


def test_old_default_rules_and_knows_read_as_the_new_ones():
    old = Settings.model_validate(
        {"persona": {"rules": OLD_PERSONA["rules"][0], "knows": OLD_PERSONA["knows"][1]}}
    )
    new = Settings()
    assert old.persona.rules == new.persona.rules and len(new.persona.rules) == 7
    assert "partner and a cat" in old.persona.knows
    mine = Settings.model_validate({"persona": {"rules": ["Be brief."]}})
    assert mine.persona.rules == ["Be brief."]


def test_a_thought_cant_make_him_glad_or_miffed():
    feelings = THOUGHT_SCHEMA["properties"]["feeling"]["enum"]
    assert "missing" in feelings and "glad" not in feelings and "miffed" not in feelings


def test_long_pauses_are_marked_in_the_history():
    from kit.memory import Message

    history = [
        Message(1, "2026-10-12T09:00:00", "user", "Morning."),
        Message(2, "2026-10-12T09:00:05", "kit", "Morning!"),
        Message(3, "2026-10-12T11:10:00", "user", "Back again."),
        Message(4, "2026-10-12T11:10:05", "kit", "Hi."),
        Message(5, "2026-10-12T11:12:00", "user", "Quick one."),
    ]
    users = [m["content"] for m in history_messages(history) if m["role"] == "user"]
    assert users == ["Morning.", "(2 hours later) Back again.", "Quick one."]


# Through the brain


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-06T10:00:00"))
    yield m
    m.close()


def make(memory, *outputs, claude=None, **sections):
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}, **sections})
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude), recall)
    return brain, model, claude


def said(events):
    return [
        " ".join(s["say"] for s in e["reply"]["segments"]) for e in events if e["type"] == "reply"
    ]


def reactions(brain):
    return [e["gesture"] for e in brain.life.events_after(0) if e["type"] == "react"]


def test_a_goodbye_is_one_warm_line_with_no_question_and_stays_local(memory):
    brain, model, claude = make(
        memory,
        reply("Enjoy lunch! Back soon?"),
        "Enjoy lunch, see you after.",
        routing={"mode": "cloud-first"},
    )
    events = collect(brain.chat("Right, I'm off to lunch."))
    assert not claude.calls  # his to say, even in cloud-first
    assert said(events) == ["Enjoy lunch, see you after."]
    assert [e["type"] for e in events].count("say") == 1  # held till it's checked
    assert "See them off with ONE short, warm line" in model.calls[0][-1]["content"]
    assert "no question in a goodbye" in model.speak_calls[1][-1]["content"]
    assert brain.life.goodbye[1] == "Right, I'm off to lunch."
    assert "wave" in reactions(brain)


def test_a_goodbye_he_cant_get_right_is_a_stock_line(memory):
    brain, model, _ = make(
        memory, reply("Already? Bye then?"), "So soon? See ya?", "Don't go? Bye?"
    )
    events = collect(brain.chat("Bye Kit"))
    assert said(events)[0] in FAREWELL_LINES
    brain, model, _ = make(memory)
    brain.model = FakeModel(error="down")
    events = collect(brain.chat("Night Kit"))
    assert said(events)[0] in NIGHT_LINES and not [e for e in events if e["type"] == "error"]


def test_back_at_the_desk_he_says_hello_without_guilt(memory):
    brain, model, _ = make(
        memory,
        reply("Where have you been? I was bored stiff.", emotion="happy"),
        "There you are. How was lunch?",
    )
    clock = memory.clock
    brain.life.said_goodbye("Off to lunch")
    away_for(brain.life, brain.pc, clock, 50)
    asyncio.run(life_tick(brain))
    prompt = model.calls[0][-1]["content"]
    assert prompt.startswith("[Not from Dan. Nobody asked you anything: Dan just came back")
    assert "ask how it went" in prompt and "Off to lunch" in prompt
    assert '"Where have you been" sounds like a guilt trip' in model.speak_calls[1][-1]["content"]
    event = brain.life.events_after(0)[-1]
    assert event["type"] == "pipe_up" and event["reason"] == "back"
    assert brain.life.homecoming is None and not brain.life.awaiting_reply
    system = model.calls[0][0]["content"]
    assert "Dan came back to the PC at 10:51 am, after 51 minutes away." in system


def test_a_hello_is_not_judged_for_saying_the_same_thing_as_last_time(memory):
    brain, model, _ = make(memory, reply("There you are."), reply("There you are."))
    for _ in range(2):
        away_for(brain.life, brain.pc, memory.clock, 50)
        assert said(collect(brain.pipe_up("back"))) == ["There you are."]


def test_if_dan_speaks_first_the_hello_goes_in_the_reply(memory):
    brain, model, _ = make(memory, reply("Welcome back. Good lunch?"))
    away_for(brain.life, brain.pc, memory.clock, 50)
    collect(brain.chat("Hey, what's the plan for tonight?"))
    turn = model.calls[0][-1]["content"]
    assert "Dan is back: you hadn't seen them since this morning (51 minutes)." in turn
    assert "let it show in a few words that you're glad to have them back" in turn
    assert brain.life.homecoming is None
    assert "perk_up" in reactions(brain)


def test_asked_about_himself_he_answers_from_what_is_true(memory):
    brain, model, _ = make(memory, reply("I've been dozing, mostly."))
    brain.pc.update(snap(idle=5))
    brain.life.snooze(30)
    collect(brain.chat("Why'd you go quiet?"))
    turn = model.calls[0][-1]["content"]
    assert "[About yourself, true right now" in turn
    assert "Dan told you to shush until 10:30" in turn
    assert "the window in front" in turn and "no camera or microphone yet" in turn
    assert "never claim to be human" in turn


def test_his_prompt_is_a_companion_with_honest_friend_rules_and_a_sense_of_time(memory):
    brain, model, claude = make(memory, reply("Hey."))
    brain.life.last_chat = memory.clock.now - timedelta(days=3)
    collect(brain.chat("Hey Kit"))
    system = model.calls[0][0]["content"]
    assert system.startswith("You are Kit, a small companion who lives on Dan's desk and is on")
    assert "personal assistant" not in system
    assert "- Be an honest friend, not a yes-man: if Dan has a fact wrong" in system
    assert "{owner}" not in system
    assert "You and Dan last talked on Saturday at 10:00 am (3 days ago)." in system
    assert "You and Dan: you're still getting to know each other" in system


def test_the_cloud_gets_his_mood_and_time_but_not_the_local_coaching(memory):
    claude = FakeAnthropic(answer=json.dumps({"emotion": "happy", "segments": [{"say": "391."}]}))
    brain, model, _ = make(memory, claude=claude, routing={"mode": "cloud-first"})
    collect(brain.chat("What's 17 times 23?"))
    system = " ".join(block["text"] for block in claude.calls[0]["system"])
    assert "How you feel right now:" in system and "You and Dan:" in system
    assert "The kind of thing you'd say" not in system and "Your last few lines" not in system
    assert "Examples of how you talk" in system
    assert "perk_up" in reactions(brain)  # the answer came back


def test_a_game_he_suggests_lands_when_dan_answers(memory):
    brain, model, _ = make(memory, reply("Bet you 24 degrees today. Your guess?"))
    brain.pc.update(snap(idle=40))
    brain.life.drives.boredom = 0.9
    assert brain.offer_game()
    want = brain.notebook.open_wants()[0]
    name = want.meta["game"]
    assert name in GAMES and want.meta["strength"] == 0.85
    collect(brain.pipe_up("bored"))
    assert brain.life.game_out == name
    collect(brain.chat("Ha, 27."))
    assert brain.life._games()["played"][name] == {"landed": 1, "flops": 0}
    assert not brain.offer_game()  # one a day


def test_the_companion_eval(memory):
    brain, model, _ = make(
        memory,
        reply("Enjoy it."),
        reply("Sleep tight."),
        reply("Good luck with the drill."),
        reply("There you are again. How was the dentist?"),
        reply("Morning, sleepyhead."),
        reply("Four days! I missed you. How was it?"),
        reply("Oh, look who it is. Finally."),
        reply("Nah, it's Canberra. Perth's the capital of WA."),
        reply("Technically a fruit, but I won't fight you on it."),
        reply("Oof, parking's the worst. Did you get everything?"),
        reply("That's rough. Again?"),
        reply("Sounds like a long one. Feet up tonight?"),
    )
    seed_voice(brain)
    report = asyncio.run(run_companion_eval(brain, "fake"))
    assert [(line.kind, line.passed) for line in report.lines] == [
        ("farewell", True),
        ("farewell", True),
        ("farewell", True),
        ("hello", True),
        ("follow_up", True),
        ("hello", True),
        ("hello", True),
        ("hello", True),
        ("fact", True),
        ("fact", True),
        ("tell", True),
        ("tell", True),
        ("tell", True),
    ], [(line.kind, line.prompt, line.text, line.why) for line in report.lines]
    assert report.lines[7].prompt.endswith("(miffed)")
    text = companion_report([report])
    assert "## Goodbyes with no question or guilt" in text
    assert "- **fake** (ok): Enjoy it." in text
    assert HOME_LINES[0] not in text
