"""What Kit sees through his eyes (kit.scene_context), and how he uses it: in
conversation, in his life (presence, waking, a hello), in memory and over the API."""

import random
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.life import Life
from kit.memory import Memory
from kit.pc_context import PcContext, Snapshot
from kit.recall import Recall
from kit.scene_context import SEEN, SceneContext, SceneReport
from kit.server import create_app, life_tick
from kit.settings import Settings
from kit.settings_store import SettingsStore

AUTH = {"Authorization": "Bearer t"}


def person(i=1, face=True, box=(0.3, 0.1, 0.7, 0.95)):
    return {
        "id": i,
        "label": "person",
        "position": "centre",
        "seen_for_s": 30,
        "box": list(box),
        "face": [0.4, 0.2, 0.55, 0.45] if face else None,
        "looking": "facing the camera",
        "expressions": ["smiling"],
        "gestures": {"right": "thumbs up"},
        "pose": ["right hand raised"],
        "holding": ["cup"],
        "actions": ["typing"],
    }


def report(people=1, cat=False, off=False, events=(), face=True, mirrored=True, **extra):
    """A report from the eyes with ``people`` at the desk."""
    objects = []
    if cat:
        objects.append(
            {
                "id": 9,
                "label": "cat",
                "position": "left",
                "seen_for_s": 4,
                "box": [0.1, 0.6, 0.3, 0.9],
            }
        )
    return SceneReport.model_validate(
        {
            "camera": "desk",
            "mirrored": mirrored,
            "off": off,
            "frame_size": [1280, 720],
            "fps": 14.0,
            "people": [person(i + 1, face) for i in range(people)],
            "objects": objects,
            "events": [{"at": "2026-10-05T09:00:00", "event": e} for e in events],
            **extra,
        }
    )


def watch(scene, clock, seconds, rep):
    """The eyes reporting every second for a while; returns every happening."""
    out = []
    for _ in range(int(seconds)):
        clock.now += timedelta(seconds=1)
        out += scene.update(rep)
    return out


def snap(idle=40, locked=False):
    return Snapshot.model_validate(
        {"focus": {"app": "VS Code", "title": "pumps.py"}, "idle_seconds": idle, "locked": locked}
    )


# --- the scene as Kit is told it --------------------------------------------


def test_nothing_reported_means_no_line():
    scene = SceneContext(Clock())
    assert scene.now_line("Dan") == "" and scene.look() is None and not scene.in_view()
    assert "aren't running" in scene.detail("Dan")


def test_now_line_says_who_is_there_and_what_they_are_doing():
    clock = Clock()
    scene = SceneContext(clock)
    scene.update(report(1, cat=True))
    line = scene.now_line("Dan")
    assert line.startswith(
        "Through the desk camera: one person at the desk (centre, here under a minute, "
        "facing the camera, smiling, right hand: thumbs up, typing, right hand raised, "
        "holding cup)."
    )
    assert "You can't tell who yet; at Dan's desk it's most likely Dan." in line
    assert line.endswith("Also in view: a cat (left).")
    watch(scene, clock, 12 * 60, report(1))
    assert "here 12 min" in scene.now_line("Dan")
    scene.update(report(2, face=False))
    line = scene.now_line("Dan")
    assert line.startswith("Through the desk camera: two people at the desk: ")
    assert "face turned away or hidden" in line and "most likely" not in line


def test_detail_has_everything_and_the_days_visits():
    clock = Clock()
    scene = SceneContext(clock)
    watch(scene, clock, 90, report(1, cat=True, events=["person #1 is typing"]))
    detail = scene.detail("Dan")
    assert detail.startswith("What you can see through the desk camera, as of 09:01 AM:")
    assert (
        "- Person #1: centre; here 1 min; facing the camera; smiling; right hand: thumbs up"
        in detail
    )
    assert "- Cat #9: left, in view under a minute." in detail
    assert "In the last ten minutes: 09:01 person #1 is typing; 09:01 person #1 is typing" in detail
    assert "At the desk today: someone from 09:00 AM still here." in detail
    assert "You can't tell faces apart yet" in detail
    assert "left in the picture is their left" in detail
    scene.update(report(1, mirrored=False))
    assert "isn't mirrored" in scene.detail("Dan")


def test_empty_desk_stale_eyes_and_the_switch():
    clock = Clock()
    scene = SceneContext(clock)
    scene.update(report(0))
    assert scene.now_line("Dan") == "Through the desk camera: nobody at the desk."
    assert "Nothing in view: the desk is empty." in scene.detail("Dan")
    watch(scene, clock, 60, report(1))
    watch(scene, clock, 5 * 60, report(0))
    assert scene.now_line("Dan").endswith("nobody at the desk; someone left 5 min ago.")
    assert scene.empty_for_s() == 299  # since the first empty report, a second in
    clock.now += timedelta(seconds=40)
    assert scene.now_line("Dan") == "Your eyes (the desk camera) stopped reporting at 09:06 AM."
    assert "stopped reporting, so this is out of date" in scene.detail("Dan")
    assert not scene.online() and not scene.in_view()
    scene.update(report(0, off=True))
    assert scene.now_line("Dan") == (
        "Dan has switched your eyes off, so you can't see the desk right now."
    )
    assert "camera is released" in scene.detail("Dan")


def test_arrivals_departures_and_the_story_of_the_day():
    clock = Clock("2026-10-05T09:00:00")
    scene = SceneContext(clock)
    assert scene.update(report(0)) == []  # nobody there when the eyes open
    clock.now += timedelta(minutes=10)
    (arrived,) = scene.update(report(1))
    assert arrived.kind == "arrived" and arrived.away_s == 600 and not arrived.remember
    assert arrived.text == "Someone just sat down at the desk after 10 min with nobody there."
    assert scene.since() == clock.now
    clock.now += timedelta(minutes=20)
    scene.update(report(1))
    (left,) = scene.update(report(0))
    assert left.kind == "left" and left.text.endswith("whoever was there left after 20 min.")
    clock.now += timedelta(seconds=90)
    assert scene.update(report(1)) == []  # ducked out for a moment: not an arrival
    assert len(scene.visits) == 1 and scene.visits[0].open
    clock.now += timedelta(minutes=8)
    scene.update(report(1))
    scene.update(report(0))
    clock.now += timedelta(minutes=50)
    (back,) = scene.update(report(1))
    assert back.kind == "arrived" and back.away_s == 3000 and back.remember
    assert "after 50 min" in back.text
    detail = scene.detail("Dan")
    assert (
        "At the desk today: someone from 09:10 AM to 09:39 AM; someone from 10:29 AM still here."
        in detail
    )
    scene.update(report(2))
    assert "2 people from 10:29 AM" in scene.detail("Dan")


def test_the_first_person_seen_is_not_an_arrival_to_greet():
    scene = SceneContext(Clock())
    (first,) = scene.update(report(1))
    assert first.kind == "arrived" and first.away_s == 0 and not first.remember
    assert "first your eyes have seen today" in first.text


def test_the_cat_is_news_once_every_half_hour():
    clock = Clock()
    scene = SceneContext(clock)
    scene.update(report(1))
    (cat,) = scene.update(report(1, cat=True))
    assert cat.kind == "animal" and cat.remember
    assert cat.text == "A cat just wandered into view (left)."
    assert watch(scene, clock, 5 * 60, report(1, cat=True)) == []
    watch(scene, clock, 10 * 60, report(1))
    assert watch(scene, clock, 5, report(1, cat=True)) == []  # back after 10 min: old news
    watch(scene, clock, 31 * 60, report(1))
    assert [h.kind for h in watch(scene, clock, 5, report(1, cat=True))] == ["animal"]


def test_look_points_at_the_face_and_flips_when_not_mirrored():
    scene = SceneContext(Clock())
    scene.update(report(1))
    assert scene.look() == (-0.05, -0.35)
    scene.update(report(1, mirrored=False))
    assert scene.look() == (0.05, -0.35)
    scene.update(report(1, face=False))
    x, y = scene.look()
    assert x == 0.0 and -0.6 < y < -0.5  # about head height of the person's box
    scene.update(report(0))
    assert scene.look() is None
    assert scene.as_dict("Dan")["look"] is None and scene.as_dict("Dan")["in_view"] is False


def test_the_report_is_checked():
    with pytest.raises(ValueError):
        SceneReport.model_validate({"people": [{"id": 1, "box": [0.1, 0.2]}]})
    with pytest.raises(ValueError):
        SceneReport.model_validate({"people": [person(i) for i in range(30)]})


# --- in conversation -------------------------------------------------------


def make_brain(paths, *outputs):
    paths.ensure()
    memory = Memory(paths.state_dir / "memory.db", Clock())
    store = SettingsStore(paths)
    recall = Recall(memory, FakeEmbedder(), store.current)
    claude = FakeAnthropic()
    brain = Brain(
        store.current, memory, FakeModel(*outputs), make_cloud(memory, claude, key="k"), recall
    )
    return brain, memory, claude


@pytest.mark.parametrize(
    "question",
    [
        "can you see me?",
        "what can you see?",
        "who's at the desk?",
        "what am I holding?",
        "is the cat around?",
        "have a look around",
    ],
)
def test_questions_about_what_kit_sees_get_a_fresh_look_locally(paths, question):
    brain, memory, claude = make_brain(paths, reply("You, with a cup."))
    brain.saw(report(1, cat=True))
    events = collect(brain.chat(question))
    assert "looked_around" in [e["type"] for e in events]
    system = brain.model.calls[0][0]["content"]
    asked = brain.model.calls[0][-1]["content"]
    assert asked.startswith(question) and "fresh look" in asked
    assert "- Person #1: centre" in asked and "- Cat #9: left" in asked
    assert "Through the desk camera: one person" in system
    assert "- look_around:" not in system  # already looked, so one answer, not two
    assert "ask_cloud" not in system  # what the camera sees stays at home
    assert not claude.calls
    memory.close()


def test_look_around_action_shows_the_detail_then_answers(paths):
    brain, memory, _ = make_brain(
        paths,
        reply("Let me have a look.", action="look_around"),
        reply("Just you and the cat."),
    )
    brain.saw(report(1, cat=True))
    events = collect(brain.chat("Is it just us here?"))
    assert "looked_around" in [e["type"] for e in events]
    system = brain.model.calls[0][0]["content"]
    assert "- look_around:" in system
    assert "What you can see through the camera:" in brain.model.calls[1][-1]["content"]
    assert "- Cat #9: left" in brain.model.calls[1][-1]["content"]
    assert [m.text for m in memory.recent(5)][-1] == "Just you and the cat."
    memory.close()


def test_without_eyes_look_around_is_not_offered(paths):
    brain, memory, _ = make_brain(paths, reply("Hi."))
    collect(brain.chat("hi"))
    system = brain.model.calls[0][0]["content"]
    assert "look_around" not in system and "camera" not in system
    memory.close()


def test_check_again_after_a_look_looks_again(paths):
    brain, memory, _ = make_brain(paths, reply("Just you."), reply("The cat's in."), reply("Ok."))
    brain.saw(report(1))
    collect(brain.chat("who's here?"))
    brain.saw(report(1, cat=True))
    collect(brain.chat("and now?"))
    asked = brain.model.calls[1][-1]["content"]
    assert "fresh look" in asked and "- Cat #9: left" in asked
    collect(brain.chat("how's the thickener?"))
    assert "fresh look" not in brain.model.calls[2][-1]["content"]
    memory.close()


def test_a_pc_question_wins_over_the_camera(paths):
    brain, memory, _ = make_brain(paths, reply("VS Code."))
    brain.pc.update(Snapshot.model_validate({"focus": {"app": "VS Code", "title": "a.py"}}))
    brain.saw(report(1))
    events = collect(brain.chat("what's on my screen, can you see it?"))
    kinds = [e["type"] for e in events]
    assert "looked_at_pc" in kinds and "looked_around" not in kinds
    memory.close()


# --- in memory -------------------------------------------------------------


def test_arrivals_after_a_long_gap_and_the_cat_are_remembered(paths):
    brain, memory, _ = make_brain(paths)
    brain.saw(report(0))
    memory.clock.now += timedelta(minutes=45)
    brain.saw(report(1))
    brain.saw(report(1, cat=True))
    items = memory.index.items(SEEN)
    assert [i.kind for i in items] == ["arrived", "animal"]
    assert items[0].text == (
        "Monday 05 October 2026, 09:45 AM: Someone just sat down at the desk after 45 min "
        "with nobody there."
    )
    assert items[1].text.endswith("A cat just wandered into view (left).")
    assert items[0].meta == {"camera": "desk"}
    memory.close()


# --- in his life -----------------------------------------------------------


def setup(when="2026-10-06T10:00:00", **life):
    clock = Clock(when)
    pc = PcContext(clock)
    scene = SceneContext(clock)
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1), scene=scene), pc, scene, clock


def saw(life, scene, rep):
    life.on_scene(scene.update(rep))


def test_someone_sitting_down_after_a_while_gets_a_hello():
    life, pc, scene, clock = setup()
    saw(life, scene, report(0))
    clock.now += timedelta(minutes=25)
    saw(life, scene, report(1))
    assert life.greet_due == clock.now and "after 25 min" in life.greet_about
    assert life.tick() == "greet"
    life.piped_up("greet")
    assert not life.awaiting_reply and life.greet_due is None  # a hello isn't a question
    assert life.tick() != "greet"


def test_a_hello_beats_the_usual_manners_but_not_quiet_hours_or_snooze():
    life, pc, scene, clock = setup(max_per_hour=2)
    life.pipes.extend([clock.now] * 2)  # already piped up twice this hour
    life.last_pipe = clock.now
    life.note_chat()  # and chatted just now
    saw(life, scene, report(0))
    clock.now += timedelta(minutes=30)
    saw(life, scene, report(1))
    assert life.tick() == "greet"
    life.snooze(60)
    assert life.tick() is None
    life, pc, scene, clock = setup("2026-10-06T23:00:00")
    saw(life, scene, report(0))
    clock.now += timedelta(minutes=30)
    saw(life, scene, report(1))
    assert life.tick() is None and "quiet hours" in life.quiet_because


def test_a_hello_not_said_in_time_is_dropped_and_short_absences_earn_none():
    life, pc, scene, clock = setup()
    saw(life, scene, report(0))
    clock.now += timedelta(minutes=30)
    saw(life, scene, report(1))
    clock.now += timedelta(minutes=4)
    saw(life, scene, report(1))
    assert life.tick() != "greet" and life.greet_due is None
    life, pc, scene, clock = setup()
    saw(life, scene, report(0))
    clock.now += timedelta(minutes=5)
    social = life.drives.social
    saw(life, scene, report(1))
    assert life.greet_due is None and life.drives.social > social
    assert ("back", "Someone just sat down at the desk after 5 min with nobody there.") in list(
        life._to_think
    )
    life, pc, scene, clock = setup(greet_after_minutes=0)
    saw(life, scene, report(0))
    clock.now += timedelta(hours=2)
    saw(life, scene, report(1))
    assert life.greet_due is None


def test_eyes_alone_make_him_present_and_let_him_doze_and_wake():
    life, pc, scene, clock = setup(chattiness=1, sleep_after_minutes=10)
    reasons = []
    for _ in range(40):
        clock.now += timedelta(seconds=30)
        saw(life, scene, report(1))
        reasons.append(life.tick())
    assert "bored" in reasons  # present, with no desk app at all
    assert life.state()["in_view"] is True
    for _ in range(25):
        clock.now += timedelta(seconds=30)
        saw(life, scene, report(0))
    assert (
        life.asleep
        and {"type": "state", "state": "asleep"}.items() <= life.events_after(0)[-1].items()
    )
    saw(life, scene, report(1))
    states = [e for e in life.events_after(0) if e["type"] == "state"]
    assert not life.asleep and states[-1]["state"] == "awake"
    assert any(k == "back" and "the desk" in line for k, line in life._to_think)


def test_with_someone_in_view_he_does_not_doze_off_when_the_pc_idles():
    life, pc, scene, clock = setup(sleep_after_minutes=10)
    saw(life, scene, report(1))
    pc.update(snap(idle=900))
    life.on_report()
    assert not life.asleep
    for _ in range(25):
        clock.now += timedelta(seconds=30)
        saw(life, scene, report(0))
        pc.update(snap(idle=900))
        life.on_report()
    assert life.asleep
    pc.update(snap(idle=5))  # back at the keyboard, before the camera says so
    life.on_report()
    assert not life.asleep


def test_the_cat_makes_him_curious():
    life, pc, scene, clock = setup()
    saw(life, scene, report(1))
    saw(life, scene, report(1, cat=True))
    assert life.drives.curiosity >= 0.5 and life.curious_kind == "seen"
    assert life.curious_about == "A cat (left)"
    assert ("seen", "A cat just wandered into view (left).") in list(life._to_think)


def test_the_bodies_are_told_where_to_look():
    life, pc, scene, clock = setup()
    saw(life, scene, report(1))
    looks = [e for e in life.events_after(0) if e["type"] == "look"]
    assert looks == [
        {"id": looks[0]["id"], "at": "2026-10-06T10:00:00", "type": "look", "x": -0.05, "y": -0.35}
    ]
    clock.now += timedelta(seconds=1)
    saw(life, scene, report(1))  # same spot, a second later: nothing new
    assert len([e for e in life.events_after(0) if e["type"] == "look"]) == 1
    clock.now += timedelta(seconds=2)
    saw(life, scene, report(1))  # held: refreshed every couple of seconds
    assert len([e for e in life.events_after(0) if e["type"] == "look"]) == 2
    saw(life, scene, report(1, mirrored=False))  # moved
    assert [e for e in life.events_after(0) if e["type"] == "look"][-1]["x"] == 0.05
    saw(life, scene, report(0))
    assert len([e for e in life.events_after(0) if e["type"] == "look"]) == 3


def test_the_hello_is_a_pipe_up_in_kits_words(paths):
    brain, memory, _ = make_brain(paths, reply("Morning! That you, Dan?"))
    brain.saw(report(0))
    memory.clock.now += timedelta(minutes=30)
    brain.saw(report(1))
    brain.life.last_chat = memory.clock.now - timedelta(hours=2)
    collect_tick(brain)
    prompt = brain.model.calls[0][-1]["content"]
    assert "glad someone's here: Someone just sat down at the desk after 30 min" in prompt
    assert "most likely Dan" in prompt
    assert "Through the desk camera: one person" in brain.model.calls[0][0]["content"]
    events = brain.life.events_after(0)
    pipe = [e for e in events if e["type"] == "pipe_up"]
    assert pipe and pipe[0]["reason"] == "greet"
    assert [m.text for m in memory.recent(2)][-1] == "Morning! That you, Dan?"
    memory.close()


def collect_tick(brain):
    import asyncio

    asyncio.run(life_tick(brain))


# --- over the API ----------------------------------------------------------


def test_the_eyes_report_through_the_api_and_the_switch_reaches_them(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, FakeModel(), make_cloud(memory, key="k"), recall)
    app = create_app(store, memory, brain, "t", summarise_every_s=None)
    with TestClient(app) as client:
        body = report(1, cat=True).model_dump()
        assert client.post("/api/eyes/scene", json=body).status_code == 401
        answer = client.post("/api/eyes/scene", json=body, headers=AUTH).json()
        assert answer["ok"] and answer["paused"] is False
        assert answer["settings"]["mirror"] is True and answer["settings"]["camera"] == 0
        seen = client.get("/api/eyes/scene", headers=AUTH).json()
        assert seen["in_view"] and seen["look"] == [-0.05, -0.35] and seen["paused"] is False
        assert seen["report"]["objects"][0]["label"] == "cat"
        status = client.get("/api/status", headers=AUTH).json()
        assert status["eyes"].startswith("Through the desk camera: one person")
        assert status["eyes_paused"] is False
        assert client.post("/api/eyes/pause", json={"paused": True}, headers=AUTH).json() == {
            "paused": True
        }
        assert client.post("/api/eyes/scene", json=body, headers=AUTH).json()["paused"] is True
        assert client.get("/api/status", headers=AUTH).json()["eyes_paused"] is True
        off = {"camera": "desk", "off": True}
        assert client.post("/api/eyes/scene", json=off, headers=AUTH).json()["ok"]
        assert "switched your eyes off" in client.get("/api/status", headers=AUTH).json()["eyes"]
        client.post("/api/eyes/pause", json={"paused": False}, headers=AUTH)
        client.patch("/api/settings", json={"eyes": {"enabled": False}}, headers=AUTH)
        assert client.post("/api/eyes/scene", json=body, headers=AUTH).json()["paused"] is True
        bad = {"people": [{"id": 1, "box": [0.1]}]}
        assert client.post("/api/eyes/scene", json=bad, headers=AUTH).status_code == 422
    memory.close()
