"""Who's who: introducing people to Kit's eyes and recognising them
(kit.eyes.recognise, kit.eyes.enrol, kit.known_faces), the brain's side of it
(names in the scene, a hello for someone who isn't Dan) and the commands. All
with made-up face numbers: no camera, no model libraries."""

import json
import random
from datetime import timedelta
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from fakes import Clock
from kit.eyes import enrol
from kit.eyes.faces import Face
from kit.eyes.recognise import AGREE, UNKNOWN_AFTER, Gallery, Recogniser, normalise, similarity
from kit.eyes.run import Eyes
from kit.eyes.scene import Scene
from kit.known_faces import KEEP_PER_PERSON, KnownFaces, clean_name
from kit.life import Life, pipe_up_prompt
from kit.pc_context import PcContext
from kit.scene_context import SceneContext, SceneReport
from kit.settings import EyesSettings, Settings

FRAME = (1280, 720)
PERSON = (1, "person", (400, 100, 800, 700))


def vec(i: int, wobble: float = 0.0) -> list[float]:
    """A made-up face: mostly along axis ``i``, nudged a little by ``wobble``."""
    v = [0.0] * 128
    v[i] = 1.0
    v[(i + 1) % 128] = wobble
    return normalise(v)


DAN, SAM, STRANGER = vec(0), vec(10), vec(50)


def face(box=(500, 150, 700, 350), yaw=0.0) -> Face:
    f = Face(box, yaw=yaw)
    f.align_points = [520.0, 200.0, 680.0, 200.0, 600.0, 260.0, 540.0, 310.0, 660.0, 310.0]
    return f


# --- matching ----------------------------------------------------------------


def test_the_gallery_matches_the_closest_person_or_nobody():
    g = Gallery({"Dan": [DAN, vec(0, 0.3)], "Sam": [SAM]}, threshold=0.4)
    assert g.match(vec(0, 0.1))[0] == "Dan"
    assert g.match(vec(10, 0.2))[0] == "Sam"
    name, score = g.match(STRANGER)
    assert name is None and score < 0.4
    assert not Gallery() and not Gallery({"Odd": [[1.0, 2.0]]})  # wrong-sized numbers dropped
    assert similarity(normalise([3, 4]), normalise([3, 4])) == pytest.approx(1.0)


def seen_scene(frames=6, the_face=None):
    """A scene with one person in view, their face in it."""
    scene = Scene()
    the_face = the_face or face()
    for i in range(frames):
        scene.update(i * 0.1, FRAME, [PERSON], faces=[the_face])
    return scene


def test_a_name_needs_a_few_agreeing_looks():
    looks = []

    def embed(frame, f):
        looks.append(f)
        return SAM

    rec = Recogniser(embed, Gallery({"Dan": [DAN], "Sam": [SAM]}))
    scene = seen_scene()
    now = 1.0
    for _ in range(AGREE - 1):
        rec.update(None, scene, now)
        now += 0.31
    assert scene.name_of(1) is None  # not sure yet
    rec.update(None, scene, now)
    assert scene.name_of(1) == "Sam"
    report = scene.report()
    assert report["people"][0]["name"] == "Sam"
    assert report["events"][-1]["event"] == "recognised Sam (#1)"
    rec.update(None, scene, now + 1)  # known: only checked again now and then
    assert len(looks) == AGREE


def test_a_face_matching_nobody_is_someone_kit_doesnt_know_and_turned_faces_are_skipped():
    rec = Recogniser(lambda frame, f: STRANGER, Gallery({"Dan": [DAN]}))
    scene = seen_scene()
    for i in range(UNKNOWN_AFTER):
        rec.update(None, scene, 1 + i * 0.31)
    assert scene.name_of(1) is None and scene.report()["people"][0]["unknown"]

    calls = []
    rec = Recogniser(lambda frame, f: calls.append(f) or DAN, Gallery({"Dan": [DAN]}))
    rec.update(None, seen_scene(the_face=face(yaw=60)), 1.0)
    assert calls == []  # side-on faces give poor numbers
    rec = Recogniser(lambda frame, f: calls.append(f) or DAN)
    rec.update(None, seen_scene(), 1.0)
    assert calls == []  # nobody to know: no time spent looking


class FakeCamera:
    def read(self):
        return np.zeros((72, 128, 3), dtype=np.uint8)

    def release(self):
        pass


def test_running_eyes_fetch_who_they_know_when_it_changes():
    fetched = []

    def load():
        fetched.append(1)
        return {"version": 3, "people": {"Sam": [SAM]}}

    answers = iter([{"faces_version": 3}, {"faces_version": 3}, {"faces_version": 4}])
    clock = Clock()
    t = {"now": 0.0}

    def tick():
        t["now"] += 0.5
        return t["now"]

    eyes = Eyes(
        lambda: FakeCamera(),
        SimpleNamespace(detect=lambda frame: [(1, "person", (40, 10, 90, 70))]),
        lambda report: next(answers),
        EyesSettings(),
        recogniser=Recogniser(lambda frame, f: None),
        load_faces=load,
        clock=tick,
        wall=clock,
        sleep=lambda s: None,
    )
    for _ in range(6):
        eyes.step()
    assert len(fetched) == 2  # once for version 3, again for 4
    assert set(eyes.recogniser.gallery.people) == {"Sam"}
    assert eyes.scene.recognising and eyes.scene.report()["recognising"]
    eyes.apply({"settings": EyesSettings(match=0.6).model_dump()})
    assert eyes.recogniser.gallery.threshold == 0.6


# --- introducing someone -----------------------------------------------------


def test_enrolling_from_the_camera_takes_varied_looks_of_one_face():
    faces = [[], [face(), face()], *[[face()] for _ in range(40)]]
    axes = iter([0, 0, *range(1, 60)])  # the first two looks are the same: one is dropped
    t = {"now": 0.0}

    def clock():
        t["now"] += 0.3
        return t["now"]

    said = []
    looks = enrol.from_camera(
        enrol.Enroller(lambda frame: faces.pop(0), lambda frame, f: vec(next(axes))),
        lambda: "frame" if faces else None,
        shots=6,
        say=said.append,
        clock=clock,
    )
    assert len(looks) == 6
    assert all(similarity(a, b) < enrol.SAME_LOOK for a, b in zip(looks, looks[1:], strict=False))
    assert "Kit can't see a face yet" in said and any("more than one face" in s for s in said)


def test_enrolling_from_photos_uses_only_clear_single_faces(tmp_path):
    for name in ("a.jpg", "b.JPEG", "group.png", "side.jpg", "broken.jpg", "notes.txt"):
        (tmp_path / name).write_text("x")
    photos = enrol.photos_in(tmp_path)
    assert [p.name for p in photos] == ["a.jpg", "b.JPEG", "broken.jpg", "group.png", "side.jpg"]
    found = {"a.jpg": [face()], "group.png": [face(), face()]}
    found["b.JPEG"] = [face((0, 0, 600, 600)), face((900, 0, 950, 50))]  # someone far behind
    found["side.jpg"] = [face(yaw=70)]
    enroller = enrol.Enroller(
        look=lambda image: found.get(image, []),
        embed=lambda image, f: SAM,
        read_photo=lambda p: None if p.name == "broken.jpg" else p.name,
    )
    said = []
    assert len(enrol.from_photos(enroller, photos, say=said.append)) == 2
    assert said == [
        "skipped 3 photo(s): broken.jpg (can't open it); group.png (2 faces, none clearly "
        "theirs); side.jpg (face turned away)"
    ]


def test_yunet_rows_become_faces_with_the_points_sface_wants():
    square = [100, 50, 80, 100, 120, 90, 160, 90, 140, 115, 125, 130, 155, 130, 0.9]
    turned = [100, 50, 80, 100, 120, 90, 160, 90, 158, 115, 125, 130, 155, 130, 0.9]
    a, b = enrol.yunet_faces(np.array([square, turned]))
    assert a.box == (100, 50, 180, 150) and a.align_points == [float(v) for v in square[4:14]]
    assert a.facing_camera and not b.facing_camera
    assert enrol.yunet_faces(None) == []
    (big,) = enrol.yunet_faces(np.array([square]), scale=2.0)  # found in a half-size copy
    assert big.box == (200, 100, 360, 300) and big.align_points[:2] == [240.0, 180.0]


# --- the brain keeps who's who ---------------------------------------------


def test_known_faces_are_kept_capped_counted_and_forgotten(tmp_path):
    path = tmp_path / "state" / "faces.json"
    known = KnownFaces(path)
    assert known.add("sam ", [SAM] * 3) == ("Sam", 3)
    assert known.add("SAM", [SAM] * (KEEP_PER_PERSON + 5)) == ("Sam", KEEP_PER_PERSON)
    known.add("Dan", [DAN, [1.0, 2.0]])
    assert known.names() == {"Dan": 1, "Sam": KEEP_PER_PERSON}
    again = KnownFaces(path)
    assert again.names() == known.names() and again.version == 3
    assert again.forget("sam") == "Sam" and again.forget("Lou") is None
    assert KnownFaces(path).names() == {"Dan": 1}
    for bad in ("", "42", "Robert'); DROP", "x" * 41):
        with pytest.raises(ValueError):
            clean_name(bad)
    with pytest.raises(ValueError):
        known.add("Lou", [[1.0, 2.0]])
    assert clean_name("mary-jane o'neil") == "Mary-jane o'neil"


def test_the_brain_takes_lists_and_forgets_faces(paths):
    from fakes import FakeEmbedder, FakeModel, make_cloud
    from kit.brain import Brain
    from kit.memory import Memory
    from kit.recall import Recall
    from kit.server import create_app
    from kit.settings_store import SettingsStore

    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, FakeModel(), make_cloud(memory, key="k"), recall)
    app = create_app(store, memory, brain, "t", summarise_every_s=None, paths=paths)
    auth = {"Authorization": "Bearer t"}
    with TestClient(app) as client:
        r = client.post("/api/eyes/faces", json={"name": "Sam", "embeddings": [SAM]}, headers=auth)
        assert r.json() == {"name": "Sam", "count": 1, "version": 1}
        assert (paths.state_dir / "faces.json").is_file()  # in Kit's data folder, nowhere else
        assert (
            client.post(
                "/api/eyes/faces", json={"name": "4", "embeddings": [SAM]}, headers=auth
            ).status_code
            == 422
        )
        known = client.get("/api/eyes/faces", headers=auth).json()
        assert known["names"] == {"Sam": 1} and len(known["people"]["Sam"][0]) == 128
        answer = client.post("/api/eyes/scene", json={"people": []}, headers=auth).json()
        assert answer["faces_version"] == 1
        assert client.delete("/api/eyes/faces/sam", headers=auth).json() == {
            "forgot": "Sam",
            "version": 2,
        }
        assert client.delete("/api/eyes/faces/Sam", headers=auth).status_code == 404
        assert client.get("/api/eyes/faces").status_code == 401


# --- names on the brain's side ---------------------------------------------


def report(*names, recognising=True, unknown=False):
    people = [
        {
            "id": i + 1,
            "name": n,
            "position": "centre",
            "face": [0.4, 0.2, 0.6, 0.5],
            "unknown": unknown,
        }
        for i, n in enumerate(names)
    ]
    return SceneReport.model_validate({"people": people, "recognising": recognising})


def test_an_arrival_waits_a_moment_for_a_name():
    clock = Clock()
    scene = SceneContext(clock)
    assert scene.update(report(None)) == []  # the eyes are still having a look
    clock.now += timedelta(seconds=1)
    (arrived,) = scene.update(report("Sam"))
    assert arrived.kind == "arrived" and arrived.who == ["Sam"]
    assert arrived.text.startswith("Sam is at the desk")
    assert scene.now_line("Dan").startswith("Through the desk camera: Sam (centre")
    clock.now += timedelta(minutes=5)
    scene.update(report("Sam"))
    (left,) = scene.update(report())
    assert left.text == "The desk is empty: Sam left after 5 min." and left.who == ["Sam"]
    assert "Sam from" in scene.detail("Dan")

    clock.now += timedelta(hours=1)
    assert scene.update(report(None)) == []
    clock.now += timedelta(seconds=5)  # nobody named in time: it's "someone" as before
    (arrived,) = scene.update(report(None))
    assert arrived.who == [] and arrived.text.startswith("Someone just sat down")

    clock.now += timedelta(hours=1)
    scene.update(report())
    clock.now += timedelta(minutes=5)
    (arrived,) = scene.update(report(None, unknown=True))
    assert arrived.text.startswith("Someone you don't know just sat down")
    assert "nobody you know" in scene.now_line("Dan") and "most likely" not in scene.now_line("Dan")
    assert "isn't anyone you've been introduced to" in scene.detail("Dan")


def test_eyes_that_dont_recognise_anyone_say_arrivals_straight_away():
    scene = SceneContext(Clock())
    (arrived,) = scene.update(report(None, recognising=False))
    assert arrived.kind == "arrived" and arrived.who == []


def setup_life(**life):
    clock = Clock("2026-10-06T10:00:00")
    pc = PcContext(clock)
    scene = SceneContext(clock)
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1), scene=scene), scene, clock


def test_someone_else_kit_knows_gets_their_own_hello_and_dan_is_still_away():
    life, scene, clock = setup_life()
    life.on_scene(scene.update(report("Dan")))
    clock.now += timedelta(minutes=1)
    life.on_scene(scene.update(report()))
    clock.now += timedelta(hours=2)
    life.on_scene(scene.update(report("Sam")))
    assert life.homecoming is None
    assert life.visitor == ("Sam", clock.now)
    assert ("visitor", "Sam just sat down at the desk after 2.0 h with nobody there.") in list(
        life._to_think
    )
    assert life.tick() == "visitor"
    life.piped_up("visitor")
    assert life.visitor is None and not life.awaiting_reply

    clock.now += timedelta(minutes=10)
    life.on_scene(scene.update(report()))
    clock.now += timedelta(hours=1)
    life.on_scene(scene.update(report("Dan")))  # Dan himself: the usual hello
    assert life.homecoming is not None and life.visitor is None


def test_a_visitors_hello_goes_stale():
    life, scene, clock = setup_life()
    life.on_scene(scene.update(report("Sam")))
    assert life.visitor is not None
    clock.now += timedelta(minutes=6)
    life.tick()
    assert life.visitor is None


def test_the_visitor_hello_is_to_them_by_name():
    prompt = pipe_up_prompt("visitor", "Dan", 0.5, "Sam", 0.0)
    assert "Say hi to Sam by name" in prompt and "it's Sam, not Dan" in prompt


# --- the commands ------------------------------------------------------------


def faces_transport():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        path = request.url.path
        if path == "/api/status":
            return httpx.Response(200, json={"name": "Kit"})
        if path == "/api/settings":
            settings = {"eyes": {"camera": 0}, "persona": {"owner": "Dan"}}
            return httpx.Response(200, json={"settings": settings, "problem": None})
        if path == "/api/eyes/faces" and request.method == "GET":
            return httpx.Response(200, json={"version": 1, "people": {}, "names": {"Sam": 24}})
        if path == "/api/eyes/faces":
            body = json.loads(request.content)
            return httpx.Response(
                200, json={"name": body["name"], "count": len(body["embeddings"]), "version": 2}
            )
        if path.startswith("/api/eyes/faces/"):
            return httpx.Response(200, json={"forgot": "Sam", "version": 3})
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def faces_args(action, **over):
    import argparse

    base = {
        "eyes_action": action,
        "brain": "http://kit-server:8600",
        "token": "tok",
        "camera": None,
        "name": "desk",
        "show": False,
        "frames": None,
        "who": None,
        "photos": None,
        "shots": 24,
    }
    return argparse.Namespace(**{**base, **over})


def test_enrol_faces_and_forget_commands(paths, capsys, tmp_path):
    from kit.cli import cmd_eyes

    transport, calls = faces_transport()
    (tmp_path / "pics").mkdir()
    for n in range(4):
        (tmp_path / "pics" / f"{n}.jpg").write_text("x")
    enroller = enrol.Enroller(lambda image: [face()], lambda image, f: SAM, lambda p: p)
    args = faces_args("enrol", who="me", photos=tmp_path / "pics")
    assert cmd_eyes(paths, args, transport=transport, enroller=enroller) == 0
    assert "Kit's eyes know Dan now (4 looks)" in capsys.readouterr().out
    sent = json.loads(calls[-1][2])
    assert sent["name"] == "Dan" and len(sent["embeddings"]) == 4  # numbers only, no pictures

    blank = enrol.Enroller(lambda image: [], lambda image, f: None, lambda p: p)
    args = faces_args("enrol", who="Sam", photos=tmp_path / "pics")
    assert cmd_eyes(paths, args, transport=transport, enroller=blank) == 1
    assert "only got 0 good look(s) at Sam's face" in capsys.readouterr().out
    args = faces_args("enrol", who="Sam", photos=tmp_path / "nowhere")
    assert cmd_eyes(paths, args, transport=transport, enroller=blank) == 1

    assert cmd_eyes(paths, faces_args("faces"), transport=transport) == 0
    assert "Sam: 24 looks" in capsys.readouterr().out
    assert cmd_eyes(paths, faces_args("forget", who="Sam"), transport=transport) == 0
    assert "forgotten Sam's face" in capsys.readouterr().out
    assert ("DELETE", "/api/eyes/faces/Sam") in [c[:2] for c in calls]
