"""Kit's inner life: drives, fidgets, piping up with manners, quirks."""

import asyncio
import random
from datetime import timedelta

from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.life import Life, energy_at, in_quiet_hours, my_quirks
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
    fidgets = life.events_after(0)
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
    assert "waits 10 minutes after a chat" in life.quiet_because
    run(life, pc, clock, 10, snap(idle=40))
    assert "not bored enough yet" in life.quiet_because


def test_poke_makes_kit_pipe_up_now(paths):
    brain, memory, model, store = make_brain(paths, reply("Oi. Still on pumps?"))
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as client:
        got = client.post("/api/life/poke", headers={"Authorization": "Bearer t"}).json()
    assert got["ok"] and got["reply"]["segments"][0]["say"] == "Oi. Still on pumps?"
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
