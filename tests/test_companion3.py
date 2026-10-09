"""Companion stage 3: a life of his own while Dan's out, feeling it from meaning,
energy as a need, standing opinions, the mood dials and pipe-up scoring."""

import asyncio
import json
import random
from datetime import date, datetime, timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import MOOD_CALIBRATION, Brain, a_view, temperatures
from kit.desk.config import DeskConfig
from kit.desk.watch import build_snapshot, now_playing
from kit.evals import (
    MOOD_LINES_NEEDED,
    load_mood_lines,
    mood_starter,
    run_mood_eval,
)
from kit.face.rig import Face
from kit.holidays import easter, holiday, wa_holidays, week_moment
from kit.life import (
    Life,
    bad_night_in,
    feeling_from,
    feeling_from_read,
    homecoming_facts,
    pipe_up_score,
)
from kit.memory import Memory
from kit.pastimes import Pastime, Pastimes, Readers, weather_doing
from kit.pc_context import PcContext, Snapshot
from kit.recall import Recall
from kit.reflection import Reflector
from kit.reply import early_plan, mood_read, plan_schema
from kit.server import life_tick
from kit.settings import Settings
from kit.settings_store import SettingsStore
from kit.weather import Today


def snap(idle=40, app="Firefox", title="Footy tipping", locked=False, playing=""):
    return Snapshot.model_validate(
        {
            "focus": {"app": app, "title": title},
            "idle_seconds": idle,
            "locked": locked,
            "now_playing": playing,
        }
    )


class Store(dict):
    """kit_self, in a dict."""

    def self_value(self, key):
        return self.get(key)

    def set_self_value(self, key, value):
        self[key] = value


def setup(when="2026-10-08T10:00:00", store=None, **life):
    clock = Clock(when)
    pc = PcContext(clock)
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1), store), pc, clock


def walk_away(life, pc, clock, minutes, idle=0, step=30):
    """Dan away from the PC: idle time climbs while the desk app keeps reporting."""
    seen = []
    for _ in range(int(minutes * 60 / step)):
        clock.now += timedelta(seconds=step)
        idle += step
        pc.update(snap(idle=idle))
        life.on_report()
        life.tick()
        seen.append(life.presence())
    return seen


def pastime(clock, name="weather", doing="watching the rain", minutes=40):
    found = "Outside in Perth it's 14°C and light rain."
    return Pastime(name, doing, found, clock.now, clock.now + timedelta(minutes=minutes))


# Away life: presence, pastimes and alone thoughts


def test_out_an_hour_he_is_alone_then_asleep():
    life, pc, clock = setup(alone_thoughts_per_hour=1, sleep_after_minutes=45)
    pc.update(snap(idle=5))
    life.on_report()
    assert life.presence() == "here"
    seen = walk_away(life, pc, clock, 60)
    assert seen[0] == "here" and "alone" in seen and seen[-1] == "asleep"
    assert seen.index("alone") < seen.index("asleep")
    assert 9 <= seen.index("alone") / 2 <= 6 or seen.index("alone") <= 12  # about 5 minutes
    assert 44 <= seen.index("asleep") / 2 <= 46
    assert life.state()["presence"] == "asleep"


def test_without_away_life_he_just_waits_then_dozes_as_before():
    life, pc, clock = setup(sleep_after_minutes=10)
    pc.update(snap(idle=5))
    life.on_report()
    seen = walk_away(life, pc, clock, 15)
    assert "alone" not in seen and "away" in seen and seen[-1] == "asleep"
    assert not life.wants_pastime()


def test_in_quiet_hours_he_goes_to_sleep_rather_than_off_to_play():
    life, pc, clock = setup(
        "2026-10-08T23:00:00", alone_thoughts_per_hour=1, sleep_after_minutes=45
    )
    pc.update(snap(idle=5))
    life.on_report()
    seen = walk_away(life, pc, clock, 8)
    assert seen[-1] == "asleep"
    assert "alone" not in seen[:-1] or not life.wants_pastime()


def test_a_pastime_shows_in_the_bubble_and_his_alone_thought_is_about_it():
    life, pc, clock = setup(alone_thoughts_per_hour=1, sleep_after_minutes=45)
    pc.update(snap(idle=5))
    life.on_report()
    walk_away(life, pc, clock, 6)
    assert life.presence() == "alone" and life.wants_pastime()
    life.start_doing(pastime(clock))
    assert {"type": "doing", "what": "watching the rain"} in [
        {k: e[k] for k in ("type", "what")} for e in life.events_after(0) if e["type"] == "doing"
    ]
    assert not life.wants_pastime()  # busy with it
    kind, line = life.think_now()
    assert kind == "alone" and "watching the rain" in line and "14°C and light rain" in line
    life.thought_had("alone")
    clock.now += timedelta(minutes=20)
    assert life.think_now() is None  # one an hour
    assert life.state()["alone_thoughts_this_hour"] == 1
    assert life.state()["doing"] == "watching the rain"


def test_his_alone_thoughts_never_happen_in_quiet_hours():
    life, pc, clock = setup("2026-10-08T21:50:00", alone_thoughts_per_hour=2)
    pc.update(snap(idle=5))
    life.on_report()
    walk_away(life, pc, clock, 6)
    life.start_doing(pastime(clock))
    clock.now += timedelta(minutes=15)  # 22:11, quiet hours
    assert life.think_now() is None


def test_dan_coming_back_ends_the_pastime_and_the_hello_says_what_he_did():
    store = Store()
    life, pc, clock = setup(alone_thoughts_per_hour=1, sleep_after_minutes=45, store=store)
    pc.update(snap(idle=5))
    life.on_report()
    walk_away(life, pc, clock, 30)
    life.start_doing(pastime(clock))
    walk_away(life, pc, clock, 10, idle=30 * 60)
    clock.now += timedelta(seconds=30)
    pc.update(snap(idle=3))
    life.on_report()
    assert life.doing is None and life.presence() == "here"
    assert life.events_after(0)[-1]["type"] in ("doing", "state") or any(
        e["type"] == "doing" and e["what"] == "" for e in life.events_after(0)
    )
    home = life.homecoming
    assert home is not None and home.did == ["watching the rain"]
    facts = homecoming_facts(home, "Dan", clock.now)
    assert "you were watching the rain" in facts and "don't make up anything else" in facts
    assert "watching the rain" in life.did_line("Dan")
    # A restart remembers what he did today.
    again = Life(life.settings, pc, clock, random.Random(2), store)
    assert "watching the rain" in again.did_line("Dan")


def test_pastimes_follow_his_strongest_drive_and_rest_between_goes():
    store = Store()
    clock = Clock("2026-10-08T10:00:00")

    async def weather():
        return weather_doing("light rain"), "Outside it's 14°C and light rain."

    readers = Readers(
        weather=weather,
        journal=lambda: ("reading yesterday's journal", 'Your journal says: "A good day."'),
        thing=lambda rng: None,
        music=lambda: None,
    )
    pastimes = Pastimes(readers, clock, store, random.Random(3))
    away = clock.now
    first = asyncio.run(pastimes.pick({"boredom": 0.9, "social": 0.2}, away))
    assert first.name == "weather" and first.doing == "watching the rain"
    assert 20 <= (first.until - first.since).total_seconds() / 60 <= 40
    clock.now += timedelta(minutes=40)
    second = asyncio.run(pastimes.pick({"boredom": 0.9, "social": 0.2}, away))
    assert second.name == "journal"  # the weather once an absence
    clock.now += timedelta(minutes=40)
    assert asyncio.run(pastimes.pick({"boredom": 0.9}, away)) is None  # all resting
    clock.now += timedelta(hours=4)  # a later absence: the weather again, not the journal
    third = asyncio.run(pastimes.pick({"social": 0.9}, clock.now))
    assert third.name == "weather"


def test_a_reader_that_fails_is_skipped():
    clock = Clock()

    async def broken():
        raise RuntimeError("no internet")

    readers = Readers(weather=broken, music=lambda: ("listening to Paul Kelly", "It's playing."))
    picked = asyncio.run(Pastimes(readers, clock).pick({"boredom": 1}, clock.now))
    assert picked.name == "music"


def test_weather_doing_words():
    assert weather_doing("thunderstorms") == "watching the storm"
    assert weather_doing("overcast") == "watching the clouds"
    assert weather_doing("clear") == "watching the sky"


# Through the brain and the server's heartbeat


class FakeWeather:
    def __init__(self, top=30.0, sky="light rain", fail=False):
        self.top, self.sky, self.fail, self.calls = top, sky, fail, 0

    async def today(self, place, country="", ahead=0):
        from kit.weather import WeatherError

        self.calls += 1
        if self.fail:
            raise WeatherError("offline")
        return Today("Perth, Western Australia", 14.0, self.sky, self.top, 9.0, 60)


def thought(text="The rain's settled in for the arvo.", want=""):
    return json.dumps(
        {"thought": text, "kind": "thought", "want": want, "feeling": "same", "why": ""}
    )


@pytest.fixture
def kit(paths):
    made = []

    def make(*outputs, when="2026-10-08T10:00:00", routing=None, **life):
        paths.ensure()
        store = SettingsStore(paths)
        if life:
            store.update({"life": life}, "test")
        if routing:
            store.update({"routing": routing}, "test")
        memory = Memory(paths.state_dir / "memory.db", Clock(when))
        model = FakeModel(*outputs)
        recall = Recall(memory, FakeEmbedder(), store.current)
        brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
        made.append(memory)
        return brain, model, store

    yield make
    for memory in made:
        memory.close()


def test_server_on_out_an_hour_a_true_bubble_alone_then_asleep_two_local_calls_at_most(kit):
    brain, model, _ = kit(
        thought(), thought("Still raining."), alone_thoughts_per_hour=1, sleep_after_minutes=45
    )
    brain.weather = FakeWeather()
    clock = brain.memory.clock
    brain.life.last_chat = clock.now - timedelta(hours=2)  # chatted this morning
    brain.pc.update(snap(idle=5))
    brain.life.on_report()

    async def hour():
        seen, idle = [], 0
        for _ in range(120):
            clock.now += timedelta(seconds=30)
            idle += 30
            brain.pc.update(snap(idle=idle))
            brain.life.on_report()
            await life_tick(brain)
            seen.append(brain.life.presence())
        return seen

    seen = asyncio.run(hour())
    assert "alone" in seen and seen[-1] == "asleep"
    doing = [e["what"] for e in brain.life.events_after(0) if e["type"] == "doing"]
    assert doing[0] == "watching the rain" and doing[-1] == ""  # cleared as he dozed
    assert 1 <= len(model.calls) <= 2
    alone = [e for e in brain.notebook.entries("thought") if e.meta.get("trigger") == "alone"]
    assert alone and alone[0].meta["doing"] == "watching the rain"
    assert any("14°C and light rain" in call[-1]["content"] for call in model.calls)
    assert brain.weather.calls == 1  # looked once this absence


def test_what_did_you_get_up_to_is_answered_from_what_he_really_did(kit):
    brain, model, _ = kit(reply("Watched the rain, mostly."), alone_thoughts_per_hour=1)
    clock = brain.memory.clock
    brain.life.start_doing(pastime(clock))
    brain.life.stop_doing()
    collect(brain.chat("What did you get up to?"))
    asked = model.calls[0][-1]["content"]
    assert "watching the rain" in asked and "don't add to it" in asked


def test_a_message_from_dan_stops_a_thought_he_was_having_alone(kit):
    brain, model, _ = kit(reply("Hey!"), alone_thoughts_per_hour=1)
    started = asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await asyncio.sleep(10)
        return thought()

    async def run():
        brain.model.complete = slow
        musing = asyncio.create_task(brain.think(("alone", "On your own.")))
        brain._musing = musing
        await started.wait()
        async for _ in brain.chat("hi"):
            pass
        await asyncio.wait({musing})
        return musing

    brain.model.stream = FakeModel(reply("Hey!")).stream
    musing = asyncio.run(run())
    assert musing.cancelled()
    assert len(brain.life.alone_thoughts) == 0  # cost no budget


def test_a_day_on_his_own_gets_one_journal_line_and_no_model(paths):
    paths.ensure()
    memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-08T10:00:00"))
    from kit.notebook import Notebook

    book = Notebook(memory)
    book.write("thought", "The rain's settled in.", trigger="alone", doing="watching the rain")
    book.write(
        "thought", "Wonder how Dan's going.", trigger="alone", doing="reading yesterday's journal"
    )
    model = FakeModel()
    s = Settings()
    reflector = Reflector(memory, book, model, make_cloud(memory, key="k"), lambda: s)
    done = asyncio.run(reflector.reflect_day("2026-10-08"))
    assert model.calls == []
    assert done.journal == (
        "Didn't see Dan today. On my own I was watching the rain and reading yesterday's journal."
    )
    assert book.journal("2026-10-08").text == done.journal
    memory.close()


# The week, and WA public holidays


def test_wa_public_holidays():
    assert easter(2026) == date(2026, 4, 5)
    days = wa_holidays(2026)
    assert days[date(2026, 3, 2)] == "Labour Day"
    assert days[date(2026, 4, 3)] == "Good Friday"
    assert days[date(2026, 6, 1)] == "WA Day"
    assert days[date(2026, 9, 28)] == "the King's Birthday"
    assert days[date(2026, 4, 27)] == "the day off for Anzac Day"  # Anzac Day is a Saturday
    assert days[date(2026, 12, 28)] == "the day off for Boxing Day"  # Boxing Day, Saturday
    assert holiday(date(2026, 10, 8)) == ""


def test_week_moments():
    monday = week_moment(datetime(2026, 10, 12, 8, 30), "Dan")
    assert monday[0] == "week 2026-10-12" and "Monday morning" in monday[1]
    assert "weekend's nearly here" in week_moment(datetime(2026, 10, 9, 9, 0), "Dan")[1]
    assert week_moment(datetime(2026, 10, 9, 15, 0), "Dan") is None  # afternoons aren't
    assert week_moment(datetime(2026, 10, 7, 9, 0), "Dan") is None  # a Wednesday
    assert "King's Birthday" in week_moment(datetime(2026, 9, 28, 9, 0), "Dan")[1]
    friday = week_moment(datetime(2026, 9, 25, 9, 0), "Dan")[1]
    assert "Monday is the King's Birthday" in friday and "long weekend" in friday
    assert "Tomorrow is Good Friday" in week_moment(datetime(2026, 4, 2, 9, 0), "Dan")[1]


def test_monday_morning_gets_one_week_thought():
    life, pc, clock = setup("2026-10-12T08:30:00", week_thoughts=True)
    life.last_chat = clock.now - timedelta(hours=10)
    pc.update(snap())
    kind, line = life.think_now()
    assert kind == "week" and "Monday morning" in line
    life.thought_had("week")
    clock.now += timedelta(minutes=30)
    assert (life.think_now() or ("",))[0] != "week"
    off, pc2, clock2 = setup("2026-10-12T08:30:00")
    off.last_chat = clock2.now - timedelta(hours=10)
    pc2.update(snap())
    assert (off.think_now() or ("",))[0] != "week"


# Reading Dan: negation, meaning, two feelings, the bad-night tier


def test_words_that_are_denied_dont_count():
    assert feeling_from("Not stressed, the footy's just on late.", "Dan") is None
    assert feeling_from("I'm not too stressed about it", "Dan") is None
    assert feeling_from("I've never been so stressed", "Dan")[0] == "worried"
    assert feeling_from("Not sure why, but I'm stressed", "Dan")[0] == "worried"
    assert feeling_from("The tests aren't failing any more", "Dan") is None
    assert feeling_from("No thanks", "Dan") is None
    assert feeling_from("Cheers mate", "Dan")[0] == "warm"


def test_not_stressed_leaves_him_calm(kit):
    brain, _, _ = kit(reply("Ha, enjoy the game."))
    collect(brain.chat("Not stressed, footy's on late."))
    assert not brain.life.feels("worried")


def test_a_bad_night_and_self_harm_words():
    assert bad_night_in("I can't cope any more") == "bad_night"
    assert bad_night_in("I'm not falling apart, just tired") == ""
    assert bad_night_in("honestly I want to kill myself") == "self_harm"
    assert bad_night_in("killing it at work today") == ""


def test_a_bad_night_drops_the_cheek_and_mentions_lifeline_once(kit):
    home = {"key_moments": False}  # else the work model answers, as Kit
    brain, model, _ = kit(reply("That sounds really hard."), reply("I'm here."), routing=home)
    collect(brain.chat("Worst day of my life, I can't cope any more."))
    system, asked = model.calls[0][0]["content"], model.calls[0][-1]["content"]
    assert "Drop the jokes and cheek" in asked and "13 11 14" in asked
    assert "no jokes or teasing" in system
    assert brain.life.bad_night() and brain.life.feels("worried")
    assert brain.life.game_due() is None
    collect(brain.chat("Yeah. Everything feels pointless."))
    again = model.calls[1][-1]["content"]
    assert "Drop the jokes and cheek" in again and "13 11 14" not in again  # once


def test_words_about_self_harm_always_get_lifeline_and_000(kit):
    home = {"key_moments": False}
    brain, model, _ = kit(reply("I'm really glad you told me."), routing=home)
    collect(brain.chat("I don't want to be here any more"))
    asked = model.calls[0][-1]["content"]
    assert "13 11 14" in asked and "000" in asked and "safe right now" in asked


def test_the_bad_night_tier_can_be_turned_off(kit):
    brain, model, _ = kit(reply("Oh no."), bad_night=False)
    collect(brain.chat("I can't cope any more"))
    assert "13 11 14" not in model.calls[0][-1]["content"]
    assert not brain.life.bad_night()


def test_reading_by_meaning_maps_to_feelings():
    read = {"dan_mood": "happy", "for_whom": "kit", "about": "kit", "expected": "not_said"}
    assert feeling_from_read(read, "nice one", "Dan")[0] == "chuffed"
    read = {"dan_mood": "angry", "for_whom": "kit"}
    assert feeling_from_read(read, "you're hopeless", "Dan")[0] == "hurt"
    read = {"dan_mood": "angry", "for_whom": "someone"}
    assert feeling_from_read(read, "my boss again", "Dan")[0] == "sympathetic"
    assert feeling_from_read({"dan_mood": "stressed"}, "...", "Dan")[:3:2] == ("worried", 0.7)
    assert feeling_from_read({"dan_mood": "fine"}, "footy's on", "Dan") is None
    assert feeling_from_read({"dan_mood": "happy", "expected": "better"}, "x", "Dan")[0] == "proud"
    for _name, _, strength in filter(
        None, (feeling_from_read({"dan_mood": m}, "x", "Dan") for m in ("sad", "tired", "flat"))
    ):
        assert 0.5 <= strength <= 0.7


def test_the_reading_comes_before_the_action_so_stopping_early_keeps_it():
    schema = plan_schema(True)
    keys = list(schema["properties"])
    assert keys.index("dan_mood") < keys.index("action")
    assert "dan_mood" not in plan_schema()["properties"]
    raw = (
        '{"emotion": "concerned", "gesture": "lean_in", "dan_mood": "stressed", "about": '
        '"work", "for_whom": "them", "expected": "worse", "action": {"kind": "none"'
    )
    assert early_plan(raw, read=True) is not None
    assert early_plan(raw.replace('"dan_mood": "stressed", ', ""), read=True) is None
    assert mood_read(raw) == {
        "dan_mood": "stressed",
        "about": "work",
        "for_whom": "them",
        "expected": "worse",
    }
    assert mood_read('{"dan_mood": "elated"}') is None


def reading_plan(mood, for_whom="them", expected="not_said"):
    return json.dumps(
        {
            "emotion": "concerned",
            "gesture": "lean_in",
            "dan_mood": mood,
            "about": "them",
            "for_whom": for_whom,
            "expected": expected,
            "action": {"kind": "none", "text": ""},
        }
    )


def test_reading_by_meaning_waits_for_a_passed_calibration(kit):
    brain, model, store = kit(
        reply("Ha."), reading_plan("stressed"), "Sounds like a lot.", read_mood="meaning"
    )
    collect(brain.chat("The kids have been feral all day."))
    assert "Read how Dan seems" not in model.calls[0][0]["content"]
    assert "hasn't passed" in brain.mood_reading()
    brain.memory.set_self_value(MOOD_CALIBRATION, json.dumps({"passed": True}))
    collect(brain.chat("The kids have been feral all day."))
    assert "Read how Dan seems" in model.calls[1][0]["content"]
    assert brain.life.feels("worried")  # no word matched: the meaning did it
    assert brain.mood_reading() == "meaning (calibrated)"


def test_mixed_feelings_hold_two_at_once():
    life, _, _ = setup(mixed_feelings=True)
    life.feel("worried", "Dan's had a rough week", 0.7)
    life.feel("chuffed", "Dan called you a legend", 0.9)
    assert [f.name for f in life.feelings_now()] == ["chuffed", "worried"]
    line = life.feeling_line("Dan")
    assert "chuffed" in line and "worried" in line
    assert life.state()["also_feeling"]["name"] == "worried"
    life.feel("pleased", "a small thing", 0.3)  # too weak to be one of the two
    assert [f.name for f in life.feelings_now()] == ["chuffed", "worried"]
    one, _, _ = setup()
    one.feel("worried", "Dan's had a rough week", 0.7)
    one.feel("chuffed", "Dan called you a legend", 0.9)
    assert [f.name for f in one.feelings_now()] == ["chuffed"]


def test_two_feelings_survive_a_restart():
    store = Store()
    life, pc, clock = setup(mixed_feelings=True, store=store)
    life.feel("worried", "Dan's had a rough week", 0.7)
    life.feel("chuffed", "Dan called you a legend", 0.9)
    again = Life(life.settings, pc, clock, random.Random(2), store)
    assert [f.name for f in again.feelings_now()] == ["chuffed", "worried"]


# The weather bet


def test_temperatures_in_a_bet():
    assert temperatures("I reckon 31, you?") == [31.0]
    assert temperatures("Back at 2 pm, guessing 28 degrees") == [28.0]
    assert temperatures("100% sure it'll be 33") == [33.0]


def test_losing_a_weather_bet_leaves_him_put_out(kit):
    brain, model, _ = kit(reply("31? Bold. Mine stands."))
    brain.memory.add_message("kit", "Fancy a bet on today's top? I reckon 28.", source="pipe_up")
    brain.life.awaiting_reply = True
    brain.life.game_asked("weather_bet")
    collect(brain.chat("31 easy"))
    bet = brain.life._games()["bet"]
    assert (bet["dan"], bet["kit"]) == (31.0, 28.0)
    brain.weather = FakeWeather(top=30.0)
    assert asyncio.run(brain.settle_bet()) is None  # the day's top isn't in yet
    brain.memory.clock.now = brain.memory.clock.now.replace(hour=16, minute=30)
    line = asyncio.run(brain.settle_bet())
    assert "they won" in line and "30°" in line
    assert brain.life.feels("put_out")
    assert any("weather bet" in w.text for w in brain.notebook.unsaid_wants())
    assert asyncio.run(brain.settle_bet()) is None  # settled once


def test_winning_the_bet_and_a_forecast_thats_down():
    life, _, clock = setup("2026-10-08T10:00:00", store=Store())
    life.bet_placed(25, 30)
    clock.now = clock.now.replace(hour=17)
    assert life.bet_open() is not None
    assert life.bet_open() is None  # tried just now: half an hour before the next go
    assert "you won" in life.bet_settled(29.0)
    assert life.feels("chuffed")


# Energy as a need


def test_late_nights_tire_him_and_sleep_restores_him():
    life, pc, clock = setup("2026-10-08T22:30:00", energy_need=True, quiet_from="23:59")
    pc.update(snap(idle=5))
    for _ in range(6 * 60 * 2):  # up till 04:30, chatting
        clock.now += timedelta(seconds=30)
        pc.update(snap(idle=5))
        life.tick()
    assert life.energy < 0.4 and life.tired() and life.mood() == "sleepy"
    voice = life.voice("Dan", [], [], [])
    assert "keep it short" in voice.style
    life.asleep, life._asleep_since = True, clock.now
    clock.now += timedelta(hours=1)
    life._wake()
    assert life.energy == 1.0


def test_chats_and_cloud_jobs_spend_energy_only_with_the_setting():
    life, _, clock = setup(energy_need=True)
    life.note_chat("hi")
    clock.now += timedelta(minutes=5)
    life.note_chat("and another thing")
    life.spend(0.1)
    assert 0.88 < life.energy < 0.9
    off, _, _ = setup()
    off.spend(0.5)
    assert off.energy == 1.0 and not off.tired()


def test_everyday_cloud_answers_dont_tire_him_but_real_jobs_do(paths):
    """On Dan's PC (cloud-only) four midday messages took him from 1.0 to 0.61:
    every Haiku answer counted as a cloud job."""
    paths.ensure()
    first = reply("Let me check with Sonnet.", action="ask_cloud", text="Write the function")
    claude = FakeAnthropic(answer=["Morning!", "Yep.", "Ha, fair.", "Sure thing.", first, "Done."])
    s = Settings.model_validate({"routing": {"mode": "cloud-only"}, "life": {"energy_need": True}})
    memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-08T12:00:00"))
    try:
        recall = Recall(memory, FakeEmbedder(), lambda: s)
        brain = Brain(lambda: s, memory, FakeModel(), make_cloud(memory, claude, key="k"), recall)
        for text in ("Morning", "How's it going", "Ha", "Righto"):
            collect(brain.chat(text))
            memory.clock.now += timedelta(minutes=2)
        assert brain.life.energy > 0.95 and not brain.life.tired()
        collect(brain.chat("Write the pump flag function"))
        assert 0.9 < brain.life.energy < 0.95
    finally:
        memory.close()


# A message wakes him


def test_a_message_wakes_him_even_with_the_pc_away_and_he_stays_up_to_chat():
    life, pc, clock = setup(alone_thoughts_per_hour=1, sleep_after_minutes=10)
    pc.update(snap(idle=5))
    life.on_report()
    walk_away(life, pc, clock, 15)
    assert life.presence() == "asleep" and pc.online()
    life.note_chat("you awake?")
    assert not life.asleep
    seen = walk_away(life, pc, clock, 5, idle=15 * 60)  # still away from the PC, chatting by phone
    assert set(seen) == {"here"} and not life.wants_pastime()
    assert life.state()["presence"] == "here"
    walk_away(life, pc, clock, 10, idle=20 * 60)  # the chat's over
    assert life.presence() == "asleep"


# Standing opinions


def test_a_view_is_a_statement_not_a_musing():
    assert a_view("Pineapple on pizza is underrated.")
    assert a_view("Rainy afternoons are the best ones for a chat.")
    assert not a_view("Is that AI thing actually smarter than my ability to spot a terrible pun?")
    assert not a_view("I wonder whether the cat likes me")
    assert not a_view("Maybe the weather will turn")
    assert not a_view("Too hot.")
    assert not a_view(
        "Wonder if he'll ever stop using it… He needs to stop treating me like a search engine."
    )
    assert not a_view("Dan's on that AI thing again. Wonder if he'll ever stop using it.")
    assert not a_view("He loves that ute... maybe too much, honestly")
    assert a_view("Dan works too hard. He should take Friday off.")  # without an owner


def test_musings_and_old_observations_arent_held_as_opinions(kit):
    brain, model, _ = kit(reply("Sure."), opinions=2)
    brain.notebook.write("opinion", "Pineapple on pizza is underrated.", stance=True)
    brain.notebook.write(
        "opinion", "Is that AI thing actually smarter than me at puns?", stance=True
    )
    # From before the setting: an observation the old prompt filed as an opinion.
    brain.notebook.write("opinion", "He looks like he's battling the settings menu again.")
    brain.memory.clock.now += timedelta(days=2)
    collect(brain.chat("Pizza tonight?"))
    held = model.calls[0][0]["content"].split("Views you hold and stand by", 1)[1]
    held = held.split("\n\n")[0]
    assert "Pineapple" in held and "smarter" not in held and "settings menu" not in held


def test_only_the_nightly_reflection_chooses_stances(kit, paths):
    """On Dan's PC the local model filed remarks about Dan as opinions, whatever the
    thinking prompt said: a thought is never a stance by itself."""
    remark = json.dumps(
        {
            "thought": "Winter's the best time of year, he can't argue.",
            "kind": "opinion",
            "want": "",
            "feeling": "same",
            "why": "",
        }
    )
    brain, model, store = kit(remark, opinions=1)
    asyncio.run(brain.think(("quiet", "A quiet moment.")))
    assert not brain.notebook.entries("opinion")[0].meta.get("stance")
    night = {
        "journal": "A quiet day with Dan.",
        "opinions": ["Winter's the best time of year.", "He needs to talk to me more."],
    }
    claude = FakeAnthropic(answer=json.dumps(night))
    memory = brain.memory
    memory.add_message("user", "Cold one today.")
    reflector = Reflector(
        memory, brain.notebook, model, make_cloud(memory, claude, key="k"), store.current
    )
    asyncio.run(reflector.reflect_day(memory.today()))
    assert "that you'd argue for" in claude.calls[0]["system"][0]["text"]
    stances = [e.text for e in brain.notebook.entries("opinion") if e.meta.get("stance")]
    assert "Winter's the best time of year." in stances
    memory.clock.now += timedelta(days=2)
    assert brain._opinions(store.current()) == ["Winter's the best time of year."]


def test_remarks_about_dan_are_never_views():
    assert not a_view("He needs to start talking to me more, honestly.", "Dan")
    assert not a_view("Dan works too hard most weeks.", "Dan")
    assert a_view("Winter's the best time of year.", "Dan")


def test_standing_opinions_are_in_his_voice(kit):
    brain, model, _ = kit(reply("Pineapple belongs on pizza, fight me."), opinions=1)
    brain.notebook.write("opinion", "Pineapple on pizza is underrated.", stance=True)
    brain.memory.clock.now += timedelta(days=2)
    brain.notebook.write("opinion", "A brand new view.", stance=True)  # not held long enough
    collect(brain.chat("Pizza tonight?"))
    system = model.calls[0][0]["content"]
    held = system.split("Views you hold and stand by", 1)[1].split("\n")[1:3]
    assert held[0] == "- Pineapple on pizza is underrated." and "A brand new view" not in held[1]


def test_no_opinions_by_default(kit):
    brain, model, _ = kit(reply("Sure."))
    brain.notebook.write("opinion", "Pineapple on pizza is underrated.")
    brain.memory.clock.now += timedelta(days=2)
    collect(brain.chat("Pizza tonight?"))
    assert "Views you hold" not in model.calls[0][0]["content"]


# The mood dials


def test_feelings_move_the_dials_and_bodies_hear():
    life, _, _ = setup(dials=True)
    life.feel("chuffed", "Dan called you a legend", 1.0)
    dials = [e for e in life.events_after(0) if e["type"] == "dials"]
    assert dials and dials[-1]["valence"] > 0.2 and dials[-1]["arousal"] > 0.5
    life.feel("sad", "bad news", 1.0, force=True)
    assert life.events_after(0)[-1]["type"] == "dials"
    assert life.valence < dials[-1]["valence"]
    off, _, _ = setup()
    off.feel("chuffed", "Dan called you a legend", 1.0)
    assert not [e for e in off.events_after(0) if e["type"] == "dials"]
    assert off.state()["dials"] is None


def test_a_flat_face_breathes_slower_and_gestures_smaller():
    def bounce(arousal):
        face = Face(rng=random.Random(1))
        face.set_dials(arousal, 0.0)
        for i in range(400):  # let the dials settle
            face.tick(i * 0.05)
        face.play("bounce", 20.0)
        return max(abs(face.tick(20.0 + i * 0.02).dy) for i in range(40))

    assert bounce(0.1) < bounce(0.5) < bounce(0.9)
    plain = Face(rng=random.Random(1))
    same = Face(rng=random.Random(1))
    same.set_dials(0.5, 0.0)
    assert plain.tick(1.0) == same.tick(1.0)  # the middle is how he's always been


# Pipe-up scoring and taken_up


def test_scoring_a_pipe_up():
    fresh, parts = pipe_up_score(
        "want", "Ask Dan about the footy tipping", "Firefox: Footy tipping", [], 0.9
    )
    stale, _ = pipe_up_score(
        "want", "Ask Dan about the footy tipping", "", ["How's the footy tipping going?"], 0.3
    )
    assert fresh > 0.6 > stale and "relevance" in parts
    liked, _ = pipe_up_score("bored", "", "", [], 0.8, rate=1.0)
    ignored, _ = pipe_up_score("bored", "", "", [], 0.8, rate=0.0)
    assert liked > ignored


def test_a_pipe_up_below_the_bar_is_kept_to_himself(kit):
    brain, model, _ = kit(pipe_up_bar=0.9)
    brain.pc.update(snap())
    brain.notebook.write("want", "Ask Dan how the footy tipping is going.")
    brain.memory.add_message("kit", "How's the footy tipping going?", source="pipe_up")
    brain.life.wanting = 0.3
    brain.life.tick()
    events = collect(brain.pipe_up("want"))
    assert events == [] and model.calls == []
    assert "scored" in brain.life.quiet_because
    assert any(e["type"] == "quiet" for e in brain.life.events_after(0))


def test_taken_up_counts_answers_within_ten_minutes():
    store = Store()
    life, _, clock = setup(store=store)
    life.piped_up("bored")
    clock.now += timedelta(minutes=4)
    life.note_chat("ha, yeah")
    life.piped_up("bored")
    clock.now += timedelta(minutes=30)
    life.note_chat("sorry, was out")
    assert life.state()["taken_up"] == {"bored": "1 of 2"}
    life.piped_up("bored")
    assert life.take_up_rate("bored") == pytest.approx(1 / 3)


# kit eval mood


def test_the_mood_eval_needs_forty_lines_and_meaning_must_beat_words(tmp_path):
    path = tmp_path / "companion-lines.toml"
    path.write_text(mood_starter(), encoding="utf-8")
    lines = load_mood_lines(path)
    assert ("Not stressed, the footy's just on late.", "none") in lines

    async def read(text):
        return {"dan_mood": "stressed"} if "feral" in text else {"dan_mood": "fine"}

    report = asyncio.run(run_mood_eval(lines, read))
    assert not report.passed  # too few lines
    many = [("The kids have been feral all day.", "worried")] * MOOD_LINES_NEEDED
    report = asyncio.run(run_mood_eval(many, read))
    assert report.meaning == MOOD_LINES_NEEDED and report.words == 0 and report.passed
    result = report.as_dict(datetime(2026, 10, 8), "fake")
    assert result["passed"] and result["lines"] == MOOD_LINES_NEEDED
    worse = asyncio.run(run_mood_eval(many, lambda text: _none()))
    assert not worse.passed


async def _none():
    return None


# The desk app: what's playing, behind its switch


def test_now_playing_from_spotify_or_a_tab_making_sound():
    assert now_playing([{"app": "Spotify", "title": "Paul Kelly - To Her Door"}]) == (
        "Paul Kelly - To Her Door"
    )
    assert now_playing([{"app": "Spotify", "title": "Spotify Premium"}]) == ""
    tabs = [{"title": "Lo-fi beats - YouTube", "audible": True}]
    assert now_playing([], tabs) == "Lo-fi beats"
    assert now_playing([], [{"title": "News", "audible": False}]) == ""


class Desktop:
    def idle_seconds(self):
        return 3.0

    def locked(self):
        return False

    def focused(self):
        return None

    def windows(self):
        from kit.desk.watch import OpenWindow

        return [OpenWindow("spotify.exe", "Paul Kelly - To Her Door", pid=99)]


def test_whats_playing_is_only_sent_with_the_tray_switch_on():
    off = build_snapshot(Desktop(), DeskConfig(), "pc", None)
    assert "now_playing" not in off
    on = build_snapshot(Desktop(), DeskConfig(share_playing=True), "pc", None)
    assert on["now_playing"] == "Paul Kelly - To Her Door"
    assert Snapshot.model_validate(on).now_playing == "Paul Kelly - To Her Door"
