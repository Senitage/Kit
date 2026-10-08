"""Kit as a companion (stage 1): he knows how long you were gone, says hello when
you're back and sees you off without guilt, knows himself, grows closer, and
suggests a small game now and then."""

import asyncio
import json
import random
from datetime import datetime, timedelta

import anthropic
import httpx
import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import LOCAL, SELF_Q, TAG_Q, Brain, Job, is_news
from kit.evals import companion_clock, companion_report, run_companion_eval, seed_voice
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
    farewell_aside,
    farewell_fault,
    farewell_line,
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
        "Heading to the dentist, back in an hour.",
        "back in 5",
        "talk later",
        "just popping out",
        "Lunch time, back soon",
        "Heading home, see you tomorrow",
        "Have a good night mate",
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
        "I see you've fixed the bug",
        "I need to run the tests first",
        "I have to run this script again",
        "Just off the phone with mum",
        "I'm off on Friday",
        "I had a good night, thanks",
        "My monitor keeps going to sleep",
        "The results should be back in an hour",
        "I'm going to sleep on it",
    ],
)
def test_other_things_are_not_goodbyes(text):
    assert not FAREWELL.search(text)  # nor is it kept as where he's off to
    assert not is_farewell(text)


def test_see_you_tomorrow_is_not_a_goodnight():
    text = "Heading home, see you tomorrow"
    assert "for the night" not in farewell_aside(text, "Dan")
    assert farewell_line(text, random.Random(1)) in FAREWELL_LINES
    assert "for the night" in farewell_aside("Night Kit", "Dan")


def test_a_goodbye_that_says_where_he_is_off_to():
    assert farewell_plans("Off to lunch")
    assert farewell_plans("Heading to the dentist, back in an hour.")
    assert not farewell_plans("Night Kit.")
    assert not farewell_plans("Right, bye mate")
    assert not farewell_plans("Back in an hour")


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
    assert homecoming_fault("Finally! I missed you. How was it?", kind="days") == ""
    assert homecoming_fault("It's been so long! How was the trip?") == ""
    assert homecoming_fault("Where have you been?", kind="long")  # guilt is guilt


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


def test_never_miffed_about_an_evening_out_or_a_gap_between_messages():
    life, pc, clock = setup("2026-10-06T18:30:00")
    life.companion_since -= timedelta(days=8)
    away_for(life, pc, clock, 4 * 60)  # 6:30 to 10:30 pm
    assert life.homecoming.kind == "hours" and not life.homecoming.miffed
    assert life.feeling_now().name == "glad"
    life, pc, clock = setup("2026-10-06T09:00:00")  # no desk app: Dan's on his phone
    life.companion_since -= timedelta(days=8)
    clock.now += timedelta(hours=4)
    home = life.homecoming_for_chat()
    assert home.by_chat and home.kind == "hours" and not home.miffed


def test_the_hello_is_claimed_while_its_being_said():
    life, pc, clock = setup()
    away_for(life, pc, clock, 50)
    home = life.take_homecoming()
    assert life.homecoming_for_chat() is None  # Dan typing meanwhile: no second hello
    life.held_back("back", home)  # it didn't come out: his next reply says it
    assert life.homecoming is home and home.tried
    home = life.take_homecoming()
    life.note_chat("hey")  # Dan spoke meanwhile: the moment's gone
    life.held_back("back", home)
    assert life.homecoming is None


def test_no_hello_on_the_first_start_after_the_upgrade():
    store = Store()
    old = {"saved": "2026-10-06T09:59:00", "last_chat": "2026-10-06T05:00:00"}
    store.values["life"] = json.dumps(old)  # an older Kit's save: no last_seen in it
    life, pc, clock = setup(store=store)
    report(life, pc, snap(idle=2))
    assert life.homecoming is None


@pytest.mark.parametrize(
    "damage",
    [
        {"homecoming": "x"},
        {"feeling": "glad"},
        {"drives": [1]},
        {"goodbye": "off to lunch"},
        {"came_back": [1]},
    ],
)
def test_a_damaged_save_only_loses_the_damaged_part(damage):
    store = Store()
    life, pc, clock = setup(store=store)
    life.companion_since -= timedelta(days=8)
    life.closeness = 0.6
    life.save()
    data = {**json.loads(store.values["life"]), **damage}
    store.values["life"] = json.dumps(data)
    life, pc, clock = setup(store=store)
    assert life.closeness == 0.6 and clock.now - life.companion_since >= timedelta(days=8)


def test_damaged_game_records_dont_stop_the_games():
    store = Store()
    life, pc, clock = setup("2026-10-06T10:00:00", store=store)
    store.values["games"] = json.dumps({"played": [1]})
    assert life.retired_games() == []
    store.values["games"] = json.dumps(
        {"played": {"weather_bet": "x", "rate_lunch": {"flops": "3"}}}
    )
    assert life.retired_games() == []
    pc.update(snap(idle=40))
    life.drives.boredom = 0.9
    assert life.game_due() is not None


def test_a_game_out_only_survives_a_restart_while_hes_waiting_to_hear():
    store = Store()
    life, pc, clock = setup(store=store)
    life.game_asked("weather_bet")
    life.save()
    assert setup(store=store)[0].game_out == ""  # not waiting on an answer
    life.piped_up("bored")
    life.game_asked("weather_bet")
    clock.now += timedelta(minutes=5)
    life, pc, clock = setup("2026-10-06T10:05:00", store=store)
    assert life.awaiting_reply and life.game_out == "weather_bet"


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
    memory.clock.now = memory.clock.now.replace(hour=17)  # as companion_clock does
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


def test_a_message_while_the_hello_is_being_written_gets_no_hello_too(memory):
    brain, model, _ = make(memory, reply("There you are."), reply("Not much. You?"))
    away_for(brain.life, brain.pc, memory.clock, 50)

    async def race():
        hello = brain.pipe_up("back")
        events = [await hello.__anext__()]  # he's saying hello
        await _drain(brain.chat("hey"))  # Dan types meanwhile
        return events + [e async for e in hello]

    events = asyncio.run(race())
    assert said(events) == ["There you are."]
    assert "Dan is back" not in model.calls[-1][-1]["content"]
    assert brain.life.homecoming is None


async def _drain(events):
    return [e async for e in events]


def test_bad_news_on_his_return_gets_no_huff(memory):
    brain, model, _ = make(memory, reply("Oh no. I'm so sorry."), life={"miffed_after_days": 0})
    brain.life.companion_since -= timedelta(days=8)
    memory.clock.now = memory.clock.now.replace(hour=9)
    away_for(brain.life, brain.pc, memory.clock, 4 * 60)
    assert brain.life.homecoming.miffed
    collect(brain.chat("Rough day. My dog died this morning."))
    turn = model.calls[0][-1]["content"]
    assert "Dan is back" in turn and "mock huff" not in turn
    assert "look_away" not in reactions(brain) and "perk_up" not in reactions(brain)
    assert brain.life.feeling_now().name != "miffed"


def test_if_the_cloud_fails_the_local_answer_still_says_hello(memory):
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    brain, model, _ = make(
        memory,
        reply("Lima, and welcome back."),
        claude=FakeAnthropic(error=error),
        routing={"mode": "cloud-first"},
    )
    away_for(brain.life, brain.pc, memory.clock, 50)
    collect(brain.chat("What's the capital of Peru?"))
    assert "Dan is back" in model.calls[-1][-1]["content"]


@pytest.mark.parametrize(
    "text",
    [
        "Why'd you go quiet?",
        "Do you miss me?",
        "Are you ok?",
        "Can you see me?",
        "What can you see?",
        "How are you feeling?",
        "Why did you stop?",
    ],
)
def test_questions_about_himself(text):
    assert SELF_Q.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "How do you feel about Python vs Rust?",
        "Are you ok with me changing the settings?",
        "are you happy with the result",
        "Why did you get the weather wrong?",
        "Why did you say Perth?",
        "what can you see in this log file",
        "Why did you go with the blue one?",
    ],
)
def test_questions_about_other_things(text):
    assert not SELF_Q.search(text)


def test_he_names_the_browser_he_can_see(memory):
    brain, model, _ = make(memory, reply("Only your screen."))
    brain.pc.update(
        Snapshot.model_validate(
            {"focus": {"app": "Firefox", "title": "News"}, "browser": {"name": "Firefox"}}
        )
    )
    collect(brain.chat("Can you see me?"))
    assert "the tabs open in Firefox" in model.calls[0][-1]["content"]


def test_one_pass_goodbyes_and_hellos_are_checked_too(memory):
    brain, model, _ = make(
        memory,
        reply("Already? Don't leave me alone! Back soon?"),
        reply("Enjoy lunch."),
        ollama={"speak_pass": False},
    )
    events = collect(brain.chat("Right, I'm off to lunch."))
    assert said(events) == ["Enjoy lunch."]
    assert [e["type"] for e in events].count("say") == 1
    assert 'no "already" in a goodbye' in model.calls[1][-1]["content"]
    brain.model = FakeModel(error="down")
    assert said(collect(brain.chat("Night Kit")))[0] in NIGHT_LINES


def test_ok_bye_while_hes_busy_is_a_goodbye_not_a_check_in(memory):
    brain, model, _ = make(memory)
    brain.jobs[1] = Job(1, "the cabbage question", "Claude")
    note = brain._with_busy_note("ok bye", LOCAL)
    assert "checking in" not in note and "Answer this message normally" in note
    assert "checking in" in brain._with_busy_note("you there?", LOCAL)


def test_the_companion_eval_runs_at_five_in_the_afternoon():
    clock = Clock("2026-10-06T03:10:00")
    eval_clock = companion_clock(clock)
    assert eval_clock() == datetime(2026, 10, 6, 17, 0)
    clock.now += timedelta(minutes=2)
    assert eval_clock() == datetime(2026, 10, 6, 17, 2)


def test_what_is_true_about_him_reaches_his_spoken_words(memory):
    brain, model, _ = make(memory, reply("Nope, no camera yet."))
    brain.pc.update(snap(idle=5))
    collect(brain.chat("Can you see me?"))
    note = model.speak_calls[0][-1]["content"]
    assert "Keep in mind: About yourself" in note and "no camera or microphone yet" in note


def test_a_goodbye_reaches_his_spoken_words_too(memory):
    brain, model, _ = make(memory, reply("Enjoy it."))
    collect(brain.chat("Right, I'm off to lunch."))
    assert "No question" in model.speak_calls[0][-1]["content"]


def test_a_hello_reaches_his_spoken_words(memory):
    brain, model, _ = make(memory, reply("There you are. How was lunch?"))
    brain.pc.update(snap(idle=5))
    brain.life.said_goodbye("Off to lunch")
    brain.life.last_seen = brain.life.last_chat = memory.clock() - timedelta(minutes=50)
    brain.life.on_report()
    collect(brain.pipe_up("back"))
    assert "lunch" in model.speak_calls[0][-1]["content"].split("Keep in mind:")[1]


@pytest.mark.parametrize(
    "text",
    [
        "Perth's the capital of Australia, isn't it?",
        "Tomatoes are a vegetable, aren't they?",
        "The game's on tonight, right?",
        "That was a good one, wasn't it?",
    ],
)
def test_wanting_him_to_agree(text):
    assert TAG_Q.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Had a big one at the shops today. Took forever to find a park.",
        "My boss moved the deadline up again.",
        "Rough day. The shutdown ran over and everyone was cranky.",
        "I finally fixed the pump curve script.",
    ],
)
def test_news(text):
    assert is_news(text) and not TAG_Q.search(text)


@pytest.mark.parametrize(
    "text",
    ["Is it going to rain?", "I want you to open VS Code", "Open the shutdown notes", "Thanks"],
)
def test_not_news(text):
    assert not is_news(text)


def test_a_wrong_fact_and_news_get_an_honest_friend_aside(memory):
    brain, model, _ = make(memory, reply("Nah, Canberra."), reply("Oof. Find a park in the end?"))
    collect(brain.chat("Perth's the capital of Australia, isn't it?"))
    collect(brain.chat("Had a big one at the shops today. Took forever to find a park."))
    assert "say so kindly and give the right answer" in model.calls[0][-1]["content"]
    assert "Show in a few words that you got it" in model.calls[1][-1]["content"]
    assert "about this and nothing else" in model.speak_calls[1][-1]["content"]


def test_the_companion_eval_wants_a_huff_when_miffed_and_a_fresh_chat_each_time(memory):
    brain, model, _ = make(
        memory,
        reply("Enjoy it."),
        reply("Sleep tight."),
        reply("Good luck with the drill."),
        reply("There you are again. How was the dentist?"),
        reply("Morning, sleepyhead."),
        reply("Four days! I missed you. How was it?"),
        reply("Oh hey, good to see you."),  # miffed, but no huff
    )
    seed_voice(brain)
    memory.clock.now = memory.clock.now.replace(hour=17)
    report = asyncio.run(run_companion_eval(brain, "fake"))
    miffed = report.lines[7]
    assert miffed.prompt.endswith("(miffed)") and not miffed.passed
    assert miffed.why == "miffed, but no huff in it"
    # The morning-after hello doesn't see the dentist goodbye from the case before.
    morning = model.calls[4]
    assert not any("dentist" in m["content"] for m in morning if m["role"] != "system")
