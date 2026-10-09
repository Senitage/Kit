"""Kit's inner life: drives, fidgets, piping up with manners, quirks."""

import asyncio
import random
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, plan, reply
from kit.brain import Brain
from kit.life import Life, energy_at, feeling_from, in_quiet_hours, my_quirks
from kit.memory import Memory
from kit.pc_context import PcContext, Snapshot
from kit.recall import Recall
from kit.server import create_app, life_tick
from kit.settings import Settings
from kit.settings_store import SettingsStore


def snap(idle=40, app="VS Code", title="pumps.py", site="", locked=False):
    return Snapshot.model_validate(
        {
            "focus": {"app": app, "title": title, "site": site},
            "idle_seconds": idle,
            "locked": locked,
        }
    )


def setup(when="2026-10-06T10:00:00", **life):
    clock = Clock(when)
    pc = PcContext(clock)
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1)), pc, clock


def run(life, pc, clock, minutes, report):
    """Half-minute ticks with the desk app reporting, as the server does."""
    reasons = []
    for _ in range(int(minutes * 2)):
        clock.now += timedelta(seconds=30)
        pc.update(report)
        reasons.append(life.tick())
    return [r for r in reasons if r]


def test_boredom_builds_until_kit_pipes_up_in_a_pause():
    life, pc, clock = setup(chattiness=0.5)
    assert run(life, pc, clock, 10, snap(idle=2)) == []  # Dan typing away: never interrupts
    reasons = run(life, pc, clock, 20, snap(idle=40))
    assert reasons and reasons[0] == "bored"
    assert life.mood() == "bored"


def test_manners_quiet_hours_calls_away_and_snooze():
    for when, report in [
        ("2026-10-06T23:00:00", snap()),  # quiet hours
        ("2026-10-06T10:00:00", snap(app="Teams", title="Call with site")),
        ("2026-10-06T10:00:00", snap(app="Chrome", site="meet.google.com")),
        ("2026-10-06T10:00:00", snap(app="PowerPoint", title="PowerPoint Slide Show")),
        ("2026-10-06T10:00:00", snap(idle=900)),  # away
        ("2026-10-06T10:00:00", snap(locked=True)),
    ]:
        life, pc, clock = setup(when, chattiness=1)
        life.drives.boredom = 1
        assert run(life, pc, clock, 30, report) == [], (when, report)
    life, pc, clock = setup(chattiness=1)
    life.snooze(60)
    assert run(life, pc, clock, 55, snap()) == []
    assert run(life, pc, clock, 30, snap())


def test_never_speaks_first_when_chattiness_is_zero_but_still_fidgets():
    life, pc, clock = setup(chattiness=0)
    assert run(life, pc, clock, 60, snap()) == []
    fidgets = [e for e in life.events_after(0) if e["type"] != "mood"]
    assert fidgets and all(e["type"] == "fidget" for e in fidgets)
    assert len({e["gesture"] for e in fidgets}) > 2  # not the same move every time


def test_being_ignored_makes_him_wait_longer_and_sulk():
    life, pc, clock = setup(chattiness=1, max_per_hour=6)
    first = run(life, pc, clock, 60, snap())
    assert first
    life.piped_up()
    run(life, pc, clock, 11, snap())
    assert life.ignored == 1 and life.mood() == "sulky"
    assert any(e.get("mood") == "sulky" for e in life.events_after(0))
    assert life.feeling_now().why.startswith("Dan didn't answer when you piped up at ")
    life.note_chat()  # Dan finally answers
    assert life.ignored == 0 and life.mood() != "sulky"


def test_hourly_limit():
    life, pc, clock = setup(chattiness=1, max_per_hour=2)
    said = 0
    for _ in range(120):
        clock.now += timedelta(seconds=30)
        pc.update(snap())
        if life.tick():
            life.piped_up()
            life.awaiting_reply = False  # pretend Dan nodded along
            said += 1
    assert said <= 2


def test_something_new_makes_him_curious():
    life, pc, clock = setup()
    run(life, pc, clock, 1, snap())
    run(life, pc, clock, 1, snap(app="Chrome", site="youtube.com", title="lofi"))
    assert life.curious_about == "youtube.com" and life.mood() == "curious"


def test_clock_helpers():
    assert in_quiet_hours(Clock("2026-10-06T23:30:00")(), "22:00", "07:00")
    assert in_quiet_hours(Clock("2026-10-06T06:59:00")(), "22:00", "07:00")
    assert not in_quiet_hours(Clock("2026-10-06T07:00:00")(), "22:00", "07:00")
    assert not in_quiet_hours(Clock("2026-10-06T12:00:00")(), "13:00", "14:00")
    assert energy_at(Clock("2026-10-06T23:30:00")()) < 0.5


def make_brain(paths, *outputs):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    return brain, memory, model, store


def test_quirks_are_picked_once_and_kept(paths):
    brain, memory, model, _ = make_brain(paths, reply("Hi."))
    assert len(brain.quirks) == 3
    assert my_quirks(memory) == brain.quirks  # same ones next start
    collect(brain.chat("hi"))
    assert "Quirks you picked for yourself" in model.calls[0][0]["content"]
    memory.close()


def test_pipe_up_is_written_by_the_model_and_lands_in_the_conversation(paths):
    brain, memory, model, _ = make_brain(
        paths, reply("Still on pumps.py? It's been an hour, mate.", emotion="playful")
    )
    brain.pc.update(snap())
    asyncio.run(life_tick_with(brain, "bored"))
    prompt = model.calls[0][-1]["content"]
    assert prompt.startswith("[Not from Dan.") and "bored" in prompt and "cheek" in prompt
    assert 'VS Code: "pumps.py"' in model.calls[0][0]["content"]
    event = brain.life.events_after(0)[-1]
    assert event["type"] == "pipe_up" and event["reason"] == "bored"
    assert event["reply"]["emotion"] == "playful"
    last = memory.recent(5)[-1]
    assert last.role == "kit" and last.source == "pipe_up"
    assert brain.life.awaiting_reply
    memory.close()


async def life_tick_with(brain, reason):
    brain.life.tick = lambda: reason
    await life_tick(brain)


def test_a_pipe_up_that_only_repeats_him_gets_two_more_goes_then_he_keeps_quiet(paths):
    old = "You got a minute? I think the weather's trying to be a drama queen."
    brain, memory, model, _ = make_brain(paths, reply(old), reply(old), old, old)
    brain.pc.update(snap())
    asyncio.run(life_tick_with(brain, "bored"))
    events = collect(brain.pipe_up("bored"))
    assert [e["type"] for e in events] == ["kept_quiet"]
    assert len(model.speak_calls) == 4  # one for the first pipe-up, three goes at the next
    assert f'Not "{old}"' in model.speak_calls[-1][-1]["content"]
    assert [m.text for m in memory.recent(5)] == [old]  # nothing new said or kept
    assert [e["type"] for e in brain.life.events_after(0)].count("pipe_up") == 1
    assert brain.life.held_until is not None
    memory.close()


def test_a_pipe_up_is_judged_whole_and_has_nothing_written_under_it(paths):
    old = "Still on pumps.py? It's been an hour, mate."
    new = "Bet the impeller's winning that argument today.\n\n1. Impeller\n2. Dan"
    brain, memory, model, _ = make_brain(paths, reply(old), plan(), f"Hmm. {old}", new)
    brain.pc.update(snap())
    asyncio.run(life_tick_with(brain, "bored"))
    asyncio.run(life_tick_with(brain, "nag"))
    # "Hmm." alone isn't an old line, but the rest of it is: he has another go.
    assert 'Not "Hmm. Still on pumps.py?' in model.speak_calls[-1][-1]["content"]
    event = brain.life.events_after(0)[-1]
    assert event["type"] == "pipe_up" and event["reason"] == "nag"
    said = " ".join(s["say"] for s in event["reply"]["segments"])
    assert said == "Bet the impeller's winning that argument today."
    assert event["reply"]["detail"] == ""
    memory.close()


def test_answering_a_pipe_up_he_knows_why_he_piped_up(paths):
    brain, memory, model, _ = make_brain(
        paths,
        reply("Oi! I've been counting your tabs."),
        reply("Forty-one, mate. A personal best."),
        reply("Ha."),
    )
    memory.clock.now += timedelta(days=1)  # a Tuesday: no weekend to ask about first
    brain.notebook.write("want", "Tell Dan I counted forty-one open tabs.")
    brain.pc.update(snap())
    asyncio.run(life_tick_with(brain, "want"))
    collect(brain.chat("yeah whats up?"))
    asked = model.calls[-1][-1]["content"]
    assert asked.startswith(
        "yeah whats up?\n\n[Dan is answering what you piped up with: \"Oi! I've been counting"
    )
    assert 'You piped up because you wanted to tell Dan: "I counted forty-one' in asked
    collect(brain.chat("ha, fair enough"))
    assert "piped up" not in model.calls[-1][-1]["content"]  # that's answered now
    memory.close()


def test_with_nothing_new_to_say_he_waits_without_expecting_an_answer():
    life, pc, clock = setup(chattiness=0.5, max_per_hour=4)
    life.drives.boredom = 1.0
    life.held_back("bored")
    assert not life.awaiting_reply and life.drives.boredom == 0.2
    pc.update(snap())
    assert life.tick() is None and "nothing new to say" in life.quiet_because
    clock.now += timedelta(minutes=16)  # four an hour: a quarter of an hour apart
    life.drives.boredom = 1.0
    pc.update(snap())
    assert life.tick() == "bored"
    life.held_back("nag")
    assert life.nags == 1  # a nag he couldn't word still counts
    life.note_chat()
    assert life.held_until is None


def test_shush_snoozes_without_asking_a_model(paths):
    brain, memory, model, _ = make_brain(paths)
    events = collect(brain.chat("shush"))
    assert events[-1]["reply"]["segments"][0]["say"] == "Righto, zipping it for an hour."
    assert brain.life.snoozed_until is not None and model.calls == []
    collect(brain.chat("ok you can talk again"))
    assert brain.life.snoozed_until is None
    memory.close()


def test_life_api_waits_for_events(paths):
    brain, memory, _, store = make_brain(paths)
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    auth = {"Authorization": "Bearer t"}
    with TestClient(app) as client:
        state = client.get("/api/life", headers=auth).json()
        assert state["mood"] and len(state["quirks"]) == 3 and state["settings"]["cheek"] == 0.6
        assert client.get("/api/life/events?wait=0", headers=auth).json()["events"] == []
        brain.life.publish({"type": "fidget", "gesture": "yawn"})
        got = client.get("/api/life/events?after=0&wait=1", headers=auth).json()
        assert got["events"][0]["gesture"] == "yawn" and got["last"] == 1
        assert client.post("/api/life/snooze", json={"minutes": 30}, headers=auth).json()[
            "snoozed_until"
        ]
        assert (
            client.post("/api/life/snooze", json={"minutes": 0}, headers=auth).json()[
                "snoozed_until"
            ]
            is None
        )
    memory.close()


def test_the_brain_decides_when_kit_sleeps_and_wakes():
    life, pc, clock = setup(sleep_after_minutes=10)
    pc.update(snap(idle=300))
    life.on_report()
    assert not life.asleep
    pc.update(snap(idle=601))
    life.on_report()
    assert life.asleep and life.mood() == "asleep"
    run(life, pc, clock, 5, snap(idle=900))
    assert not [e for e in life.events_after(0) if e["type"] == "fidget"]  # no fidgets asleep
    pc.update(snap(idle=2))
    life.on_report()
    states = [e["state"] for e in life.events_after(0) if e["type"] == "state"]
    assert states == ["asleep", "awake"] and not life.asleep


def test_kit_says_why_hes_keeping_quiet():
    life, pc, clock = setup(chattiness=0.5)
    run(life, pc, clock, 1, snap(idle=2))
    assert "typing" in life.state()["quiet_because"]
    life.note_chat()
    run(life, pc, clock, 1, snap(idle=40))
    assert "min after a chat" in life.quiet_because
    run(life, pc, clock, 10, snap(idle=40))
    assert "not bored enough yet" in life.quiet_because


def test_poke_makes_kit_pipe_up_now(paths):
    brain, memory, model, store = make_brain(paths, reply("Oi. Still on pumps?"))
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as client:
        got = client.post("/api/life/poke", headers={"Authorization": "Bearer t"}).json()
    said = " ".join(seg["say"] for seg in got["reply"]["segments"])
    assert got["ok"] and said == "Oi. Still on pumps?"
    assert brain.life.events_after(0)[-1]["type"] == "pipe_up"
    memory.close()


def test_examples_like_the_message_or_already_said_are_left_out():
    life, _, _ = setup()
    for _ in range(20):
        voice = life.voice(
            "Dan", [], ["Watching the cursor blink. Riveting stuff."], [], "i broke the build again"
        )
        users = [u for u, _ in voice.examples]
        assert "The build failed again." not in users
        assert "What are you up to?" not in users


def test_a_chatty_kit_speaks_up_soon_and_often():
    life, pc, clock = setup(chattiness=1, max_per_hour=20)
    said = 0
    for _ in range(120):  # an hour, Dan at the PC but not chatting
        clock.now += timedelta(seconds=30)
        pc.update(snap())
        if life.tick():
            life.piped_up()
            life.awaiting_reply = False
            said += 1
    assert said >= 5
    calm, pc, clock = setup(chattiness=0.5)
    assert sum(1 for _ in range(1) if run(calm, pc, clock, 15, snap())) == 0


def test_a_chatty_kit_follows_along_with_switches():
    life, pc, clock = setup(chattiness=1, work_triggers=True)
    run(life, pc, clock, 3, snap(title="pumps.py"))
    reasons = run(life, pc, clock, 1, snap(title="cyclones.py"))
    reasons += run(life, pc, clock, 3, snap(title="cyclones.py"))
    assert life.curious_about == "cyclones.py"
    assert "watching" in reasons


def test_work_on_screen_sets_nothing_off_unless_asked():
    # Dan's "just a normal guy": code in VS Code and a CI page aren't talking points.
    life, pc, clock = setup(chattiness=1)
    run(life, pc, clock, 3, snap(title="pumps.py"))
    reasons = run(life, pc, clock, 4, snap(title="cyclones.py"))
    assert life.curious_about == "" and "watching" not in reasons
    run(life, pc, clock, 0.5, snap(app="Chrome", title="Build failed · Kit", site="github.com"))
    assert life.feeling_now() is None
    # Something that isn't work still gets a look.
    run(life, pc, clock, 1, snap(app="Chrome", title="Footy tipping", site="footytips.com.au"))
    assert life.curious_about != "" or life.drives.curiosity > 0


def test_a_chatty_kit_nags_twice_then_sulks():
    life, pc, clock = setup(chattiness=1, max_per_hour=30)
    life.piped_up("bored")
    reasons = []
    for _ in range(60):
        clock.now += timedelta(seconds=30)
        pc.update(snap())
        reason = life.tick()
        if reason:
            reasons.append(reason)
            life.piped_up(reason)
        if life.sulky:
            break
    assert reasons[:2] == ["nag", "nag"] and life.sulky


def test_a_chatty_kit_sometimes_butts_in_while_dan_types():
    life, pc, clock = setup(chattiness=1, max_per_hour=30)
    life.drives.boredom = 1
    clock.now += timedelta(minutes=30)
    life.last_chat = clock.now - timedelta(hours=1)
    butted = 0
    for _ in range(400):
        clock.now += timedelta(seconds=30)
        pc.update(snap(idle=2))
        if life.tick():
            butted += life.butting_in
            life.piped_up()
            life.awaiting_reply = False
            life.drives.boredom = 1
    assert 0 < butted


# Feelings with a cause, thoughts on a schedule, and remembering it all


class Saved:
    """Where Life keeps itself between restarts (memory's kit_self in Kit)."""

    def __init__(self):
        self.values = {}

    def self_value(self, key):
        return self.values.get(key)

    def set_self_value(self, key, value):
        self.values[key] = value


def test_what_dan_says_makes_kit_feel_something_and_he_knows_why():
    assert feeling_from("You're a legend, Kit", "Dan")[0] == "chuffed"
    assert feeling_from("The build failed again", "Dan") == (
        "sympathetic",
        'Dan said "The build failed again"',
        0.6,
    )
    assert feeling_from("I'm stressed about the shutdown", "Dan")[0] == "worried"
    assert feeling_from("you're useless", "Dan")[0] == "hurt"
    assert feeling_from("tests are all green finally", "Dan")[0] == "proud"
    assert feeling_from("thanks mate", "Dan")[0] == "warm"
    assert feeling_from("what's the time?", "Dan") is None


def test_a_feeling_shows_fades_and_isnt_pushed_out_by_a_weaker_one():
    life, _, clock = setup()
    assert life.feel("chuffed", "Dan called you a legend")
    fidget = life.events_after(0)[-1]
    assert fidget["type"] == "fidget" and fidget["mood"] == "chuffed"
    assert not life.feel("pleased", "something small", 0.3)
    assert life.feeling_now().name == "chuffed"
    assert life.feeling_line("Dan") == "chuffed, because Dan called you a legend (just now)"
    assert life.state()["feeling"]["why"] == "Dan called you a legend"
    clock.now += timedelta(minutes=85)  # chuffed lasts an hour and a half
    assert life.feeling_now() is None and life.state()["feeling"] is None
    assert not life.feel("nonsense", "why") and not life.feel("sad", "  ")


def test_how_kit_feels_survives_a_restart():
    clock = Clock("2026-10-06T10:00:00")
    pc, saved, s = PcContext(clock), Saved(), Settings()
    life = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    life.note_chat()
    life.feel("worried", 'Dan said "stressed about the shutdown"')
    life.drives.boredom = 0.5
    life.save()
    clock.now += timedelta(minutes=30)
    again = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert again.feeling_now().why == 'Dan said "stressed about the shutdown"'
    assert again.last_chat == datetime(2026, 10, 6, 10, 0)
    assert again.drives.boredom == 0.5 and again.drives.social == pytest.approx(0.125)
    clock.now += timedelta(hours=3)
    later = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert later.feeling_now() is None  # it faded while he was off
    assert later.drives.boredom == 0.2  # a long break is a fresh start
    sulky = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    sulky.sulky, sulky.ignored = True, 1
    sulky.feel("put_out", "Dan didn't answer when you piped up at 13:00", 0.6, show=False)
    clock.now += timedelta(minutes=5)  # restarted straight away
    restarted = Life(lambda: s, pc, clock, random.Random(1), store=saved)
    assert restarted.mood() == "sulky" and restarted.ignored == 1
    assert "because Dan didn't answer when you piped up at 13:00" in restarted.feeling_line("Dan")
    saved.values["life"] = "{damaged"
    assert Life(lambda: s, pc, clock, store=saved).feeling is None


def test_kit_thinks_in_quiet_moments_while_dan_is_around():
    life, pc, clock = setup(think_every_minutes=8, thoughts_per_hour=2)
    pc.update(snap())
    assert life.think_now() is None  # just started: not yet
    clock.now += timedelta(minutes=9)
    pc.update(snap())
    assert life.think_now() == ("quiet", "A quiet moment: nothing in particular is happening.")
    life.thought_had()
    assert life.think_now() is None  # not straight after one
    clock.now += timedelta(minutes=12)
    pc.update(snap())
    assert life.think_now()[0] == "quiet"
    life.thought_had()
    clock.now += timedelta(minutes=12)
    pc.update(snap())
    assert life.think_now() is None  # two an hour is the limit here
    assert life.state()["thoughts_this_hour"] == 2
    clock.now += timedelta(hours=2)
    pc.update(snap(idle=900))
    assert life.think_now() is None  # nobody around: he dozes rather than muses


def test_no_thoughts_mid_conversation_asleep_or_when_turned_off():
    life, pc, clock = setup()
    clock.now += timedelta(minutes=30)
    pc.update(snap())
    life.note_chat()
    assert life.think_now() is None  # listening, not musing
    life.asleep = True
    clock.now += timedelta(minutes=5)
    assert life.think_now() is None
    off, pc, clock = setup(thoughts_per_hour=0)
    clock.now += timedelta(minutes=30)
    pc.update(snap())
    assert off.think_now() is None


def test_something_new_on_screen_prompts_a_thought_sooner():
    life, pc, clock = setup()
    run(life, pc, clock, 3, snap(app="VS Code", title="pumps.py"))
    run(life, pc, clock, 0.5, snap(app="Chrome", title="Pump curves", site="pumpcurves.com"))
    assert life.think_now() == ("new", "Dan just opened pumpcurves.com, first time today.")


def test_a_failed_or_passing_build_on_screen_is_felt_and_thought_about():
    life, pc, clock = setup(work_triggers=True)
    run(life, pc, clock, 3, snap(app="Chrome", title="CI · Senitage/Kit", site="github.com"))
    run(life, pc, clock, 0.5, snap(app="Chrome", title="Build failed · Kit", site="github.com"))
    assert life.feeling_now().name == "sympathetic"
    assert life.think_now() == (
        "build_failed",
        'Something on Dan\'s screen failed: "Build failed · Kit".',
    )
    life.thought_had()
    clock.now += timedelta(minutes=3)
    run(life, pc, clock, 0.5, snap(app="Chrome", title="All checks have passed", site="github.com"))
    assert life.feeling_now().name == "proud"
    assert life.think_now()[0] == "build_passed"


def test_a_chat_that_has_wound_down_and_coming_back_are_worth_a_thought():
    life, pc, clock = setup()
    life.note_chat()
    run(life, pc, clock, 11, snap())
    kind, line = life.think_now()
    assert kind == "chat_ended" and line.startswith("You and Dan were chatting until")
    # Gone long enough to doze, not long enough for a hello (that's a homecoming).
    life, pc, clock = setup(sleep_after_minutes=10)
    pc.update(snap(idle=601))
    life.on_report()
    clock.now += timedelta(minutes=15)
    pc.update(snap(idle=2))
    life.on_report()
    assert life.think_now() == ("back", "Dan just came back to the PC after 15 minutes away.")
    assert life.homecoming is None


def test_a_pressing_want_makes_him_pipe_up():
    life, pc, clock = setup(chattiness=0.5)
    run(life, pc, clock, 10, snap())
    life.drives.boredom = 0.0
    life.wanting = 0.5
    clock.now += timedelta(seconds=30)
    pc.update(snap())
    assert life.tick() is None
    assert life.quiet_because.startswith("not keen to share something enough yet")
    life.drives.boredom = 0.0
    life.wanting = 1.0
    clock.now += timedelta(seconds=30)
    pc.update(snap())
    assert life.tick() == "want"
    life.piped_up("want")
    assert life.wanting == 0.0


def test_his_resting_face_follows_his_mood_and_feelings_and_bodies_hear_of_it():
    life, pc, clock = setup()
    run(life, pc, clock, 1, snap())
    assert life.face() == "happy" and life.state()["face"] == "happy"
    run(life, pc, clock, 1, snap(app="Chrome", site="youtube.com", title="lofi"))
    assert life.mood() == "curious" and life.face() == "curious"
    moods = [e for e in life.events_after(0) if e["type"] == "mood"]
    assert moods[-1] == {**moods[-1], "mood": "curious", "face": "curious"}
    life.feel("worried", "Dan sounded flat")  # a feeling shows over the mood
    assert life.face() == "concerned"
    assert [e for e in life.events_after(0) if e["type"] == "mood"][-1]["face"] == "concerned"
