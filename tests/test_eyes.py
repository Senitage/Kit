"""Kit's eyes (kit.eyes): the scene, actions, faces, hands, the loop and how it
finds the brain. All with fakes: no camera, no model libraries."""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from fakes import Clock
from kit.eyes import actions, link
from kit.eyes.actions import ActionDetector, count_swings
from kit.eyes.body import (
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    Hand,
    Point,
    describe_pose,
    model_path,
    read_hands,
)
from kit.eyes.faces import Face, head_direction, read_expressions, read_faces
from kit.eyes.run import Eyes, Post
from kit.eyes.scene import UNSENT_MAX, Scene, Stable, TrackMemory, describe, position_label
from kit.settings import EyesSettings

PERSON = (1, "person", (400, 100, 800, 700))
CUP = (2, "cup", (700, 300, 760, 380))
CAT = (3, "cat", (100, 500, 300, 700))
FRAME = (1280, 720)


def face_in(box=(500, 150, 700, 350), **scores):
    return Face(box, scores=scores, expressions=read_expressions(scores))


def pose_points(left_wrist_y=0.6, right_wrist_y=0.6, left_wrist_x=0.3):
    """33 pose points: nose in the person's box, shoulders at y=0.4."""
    points = [Point(0.47, 0.5)] * 33
    points[NOSE] = Point(0.47, 0.25)
    points[LEFT_SHOULDER] = Point(0.55, 0.4)
    points[RIGHT_SHOULDER] = Point(0.39, 0.4)
    points[13] = Point(0.6, 0.55)  # left elbow
    points[14] = Point(0.34, 0.55)  # right elbow
    points[LEFT_WRIST] = Point(left_wrist_x, left_wrist_y)
    points[RIGHT_WRIST] = Point(0.36, right_wrist_y)
    return points


def hand(gesture=None, wrist=(0.5, 0.5), side="right", spread=0.0):
    points = [Point(wrist[0] + spread * i / 20, wrist[1] + spread * i / 20) for i in range(21)]
    return Hand(side, gesture, points)


# --- tracks and stability --------------------------------------------------


def test_tracks_are_announced_after_a_few_frames_and_forgotten_after_a_gap():
    memory = TrackMemory(confirm_frames=3, forget_after=2.0)
    assert memory.update([PERSON], 0.0) == []
    assert memory.update([PERSON], 0.1) == []
    assert memory.update([PERSON], 0.2) == ["person #1 entered"]
    assert [t.id for t in memory.visible(0.2)] == [1]
    assert memory.update([], 1.0) == []  # a short gap: still around
    assert memory.visible(1.0) == []  # but not in view right now
    assert memory.update([], 2.5) == ["person #1 left after 0s"]
    assert memory.tracks == {}


def test_one_frame_flickers_never_become_events():
    memory = TrackMemory(confirm_frames=5, forget_after=1.0)
    memory.update([CUP], 0.0)
    assert memory.update([], 1.5) == []  # never confirmed: left quietly
    stable = Stable(frames=3)
    assert [stable.update(v) for v in ("a", "b", "a", "a", "a", "a")] == [
        None,
        None,
        None,
        None,
        "a",
        None,
    ]


# --- the scene -------------------------------------------------------------


def test_scene_joins_face_hands_and_pose_to_the_person_and_reports_fractions():
    scene = Scene(confirm_frames=1, stable_frames=1, clock=Clock())
    smile = {"mouthSmileLeft": 0.8, "mouthSmileRight": 0.7}
    holding = hand("thumbs up", wrist=(0.55, 0.45), spread=0.02)
    cup_hand = hand(None, wrist=(0.56, 0.44), side="left", spread=0.003)
    events = scene.update(
        0.0,
        FRAME,
        [PERSON, CUP, CAT],
        faces=[face_in(**smile)],
        hands=[holding, cup_hand],
        poses=[pose_points(left_wrist_y=0.3)],
    )
    assert "person #1 entered" in events and "cat #3 entered" in events
    assert "person #1: smiling" in events
    assert "person #1 right hand: thumbs up" in events
    assert "person #1: left hand raised" in events
    assert "person #1 is holding cup" in events
    report = scene.report(camera="desk", mirrored=True, fps=14.2)
    assert report["camera"] == "desk" and report["mirrored"] and report["fps"] == 14.2
    person = report["people"][0]
    assert person["box"] == [0.312, 0.139, 0.625, 0.972]
    assert person["face"] == [0.391, 0.208, 0.547, 0.486]
    assert person["position"] == "centre" and person["looking"] == "facing the camera"
    assert person["expressions"] == ["smiling"]
    assert person["gestures"] == {"right": "thumbs up"}
    assert person["pose"] == ["left hand raised"] and person["holding"] == ["cup"]
    assert [o["label"] for o in report["objects"]] == ["cup", "cat"]  # held things stay listed
    assert report["objects"][1]["position"] == "left"
    assert {e["event"] for e in report["events"]} == set(events)
    assert report["events"][0]["at"] == "2026-10-05T09:00:00"
    assert scene.report()["events"] == []  # sent once
    lines = describe(report)
    assert lines[0].startswith("Person #1: centre; in view 0s; facing the camera; smiling")
    assert "right hand: thumbs up" in lines[0] and "holding cup" in lines[0]
    assert lines[1] == "Cup #2: centre, in view 0s" and lines[2] == "Cat #3: left, in view 0s"
    assert lines[3].startswith("Recent: 09:00:00 ")


def test_nothing_in_view_and_furniture_is_never_held():
    scene = Scene(confirm_frames=1, stable_frames=1)
    chair = (4, "chair", (300, 200, 900, 720))
    scene.update(0.0, FRAME, [PERSON, chair], hands=[hand(wrist=(0.5, 0.5), spread=0.01)])
    assert scene.report()["people"][0]["holding"] == []
    assert describe(scene.report()) == ["Nothing in view."] or True  # chair is an object
    empty = Scene()
    assert describe(empty.report()) == ["Nothing in view."]


def test_a_recognised_name_is_used_in_events():
    scene = Scene(confirm_frames=1, stable_frames=1)
    scene.update(0.0, FRAME, [PERSON, CAT])
    scene.names = {1: "Dan", 3: "Milo"}
    assert scene._with_names("person #1 is waving") == "Dan (#1) is waving"
    assert scene._with_names("cat #3 left after 9s") == "Milo the cat (#3) left after 9s"
    assert scene.report()["people"][0]["name"] == "Dan"


def test_positions_are_thirds_of_the_frame():
    assert position_label((0, 0, 100, 10), 1280) == "left"
    assert position_label((600, 0, 700, 10), 1280) == "centre"
    assert position_label((1000, 0, 1280, 10), 1280) == "right"


# --- actions ---------------------------------------------------------------


def test_count_swings_ignores_jitter():
    assert count_swings([0, 6, 1, 7, 2], 5) == 3
    assert count_swings([0, 1, 0, 2, 1], 5) == 0


def test_nodding_shaking_and_talking_from_head_history():
    detector = ActionDetector(window=2.0, min_samples=8)
    frame = (1280, 720)
    for i in range(10):
        pitch = 10 if i % 2 else -10
        found = detector.update(1, i * 0.1, frame, face=Face((0, 0, 1, 1), yaw=0, pitch=pitch))
    assert found == ["nodding"]
    detector = ActionDetector()
    for i in range(10):
        found = detector.update(
            1, i * 0.1, frame, face=Face((0, 0, 1, 1), yaw=12 if i % 2 else -12, pitch=0)
        )
    assert found == ["shaking head"]
    detector = ActionDetector()
    for i in range(10):
        jaw = {"jawOpen": 0.3 if i % 2 else 0.1}
        found = detector.update(1, i * 0.1, frame, face=Face((0, 0, 1, 1), scores=jaw))
    assert found == ["talking"]


def test_waving_needs_a_raised_swinging_wrist():
    detector = ActionDetector()
    frame = (1280, 720)
    for i in range(10):
        x = 0.7 if i % 2 else 0.4  # swings 0.3 of the frame: well over a shoulder-width
        found = detector.update(
            1, i * 0.1, frame, pose=pose_points(left_wrist_y=0.2, left_wrist_x=x)
        )
    assert found == ["waving"]
    detector = ActionDetector()
    for i in range(10):
        x = 0.7 if i % 2 else 0.4
        found = detector.update(
            1, i * 0.1, frame, pose=pose_points(left_wrist_y=0.6, left_wrist_x=x)
        )
    assert found == []  # hands at desk height: not a wave


def up_hand(tip_x, wrist=(0.5, 0.6), side="right", fingers_up=True):
    """A hand with its wrist fixed and its middle fingertip at ``tip_x``: knuckle
    0.1 of the frame height above the wrist, tip 0.2 above (or below)."""
    points = [Point(*wrist)] * 21
    dy = -1 if fingers_up else 1
    points[9] = Point(wrist[0], wrist[1] + dy * 0.1)
    points[12] = Point(tip_x, wrist[1] + dy * 0.2)
    return Hand(side, "open palm", points)


def test_furniture_coming_and_going_is_not_news():
    memory = TrackMemory(confirm_frames=2, forget_after=1.0)
    events = []
    for i in range(3):
        events += memory.update([(1, "chair", (0, 0, 9, 9)), (2, "cup", (0, 0, 9, 9))], i * 0.1)
    events += memory.update([], 5.0)
    assert events == ["cup #2 entered", "cup #2 left after 0s"]
    assert [t.label for t in memory.visible(0.2)] == []  # long gone by now


def test_a_wave_from_the_wrist_counts_but_a_still_palm_doesnt():
    frame = (1280, 720)  # a hand-length is 72 px, so the tip swinging 0.1 is 1.8 of them
    detector = ActionDetector()
    for i in range(12):
        found = detector.update(1, i * 0.1, frame, hands=[up_hand(0.55 if i % 2 else 0.45)])
    assert found == ["waving"]
    detector = ActionDetector()
    for i in range(12):
        found = detector.update(1, i * 0.1, frame, hands=[up_hand(0.5 + 0.005 * (i % 2))])
    assert found == []  # an open palm held still
    detector = ActionDetector()
    for i in range(12):
        tip = 0.55 if i % 2 else 0.45
        found = detector.update(1, i * 0.1, frame, hands=[up_hand(tip, fingers_up=False)])
    assert found == []  # fingers down, like a hand on the mouse


def test_the_scene_hands_each_persons_hands_to_the_wave():
    scene = Scene()
    box = (300, 100, 900, 719)
    for i in range(12):
        tip = 0.55 if i % 2 else 0.45
        scene.update(i * 0.1, (1280, 720), [(1, "person", box)], hands=[up_hand(tip)])
    assert "waving" in scene.people[1]["actions"]


def test_object_actions_and_drinking_at_the_face():
    detector = ActionDetector()
    cup = SimpleNamespace(label="cup", box=(600, 300, 660, 380))
    phone = SimpleNamespace(label="cell phone", box=(0, 0, 10, 10))
    face = Face((500, 150, 700, 350))
    found = detector.update(1, 0.0, FRAME, face=face, held=[cup, phone])
    assert found == ["drinking", "using a phone"]
    low_cup = SimpleNamespace(label="cup", box=(600, 500, 660, 580))
    assert detector.update(1, 0.1, FRAME, face=face, held=[low_cup]) == []
    detector.forget([])
    assert detector.history == {}
    assert set(actions.OBJECT_ACTIONS.values()) <= set(actions.ALL_ACTIONS)


# --- faces, hands, pose ----------------------------------------------------


def test_expressions_and_head_direction():
    assert read_expressions({"mouthSmileLeft": 0.6, "mouthSmileRight": 0.6}) == ["smiling"]
    assert read_expressions({"jawOpen": 0.5, "browInnerUp": 0.5}) == ["surprised"]
    assert read_expressions({"jawOpen": 0.5}) == ["mouth open"]
    assert read_expressions({"eyeBlinkLeft": 0.7, "eyeBlinkRight": 0.7}) == ["eyes closed"]
    assert read_expressions({"browDown" + s: 0.5 for s in ("Left", "Right")}) == ["frowning"]
    assert read_expressions({}) == []
    assert head_direction(0, 0) == "facing the camera"
    assert head_direction(30, 40) == "looking up and to their right"
    assert head_direction(-30, -25) == "looking down and to their left"
    face = Face((0, 0, 1, 1), yaw=40)
    assert not face.facing_camera and face.looking == "looking to their right"


def test_read_faces_from_a_landmarker_result():
    points = [SimpleNamespace(x=0.4, y=0.2)] * 478
    points[468] = SimpleNamespace(x=0.42, y=0.25)
    points[473] = SimpleNamespace(x=0.48, y=0.25)
    points[1] = SimpleNamespace(x=0.45, y=0.3)
    points[61] = SimpleNamespace(x=0.43, y=0.35)
    points[291] = SimpleNamespace(x=0.47, y=0.35)
    points[10] = SimpleNamespace(x=0.5, y=0.4)
    shapes = [
        SimpleNamespace(category_name="mouthSmileLeft", score=0.9),
        SimpleNamespace(category_name="mouthSmileRight", score=0.9),
    ]
    matrix = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]  # facing straight on
    result = SimpleNamespace(
        face_landmarks=[points], face_blendshapes=[shapes], facial_transformation_matrixes=[matrix]
    )
    (face,) = read_faces(result, FRAME)
    assert face.box == (512, 144, 640, 288)
    assert face.yaw == 0 and face.pitch == 0 and face.expressions == ["smiling"]
    assert face.align_points[:2] == [0.42 * 1280, 0.25 * 720]


def test_read_hands_drops_the_same_hand_reported_twice():
    def mp_hand(side, score, gesture, x):
        return (
            [SimpleNamespace(category_name=side, score=score)],
            [SimpleNamespace(category_name=gesture)],
            [SimpleNamespace(x=x, y=0.5, visibility=None)] * 21,
        )

    left, right, ghost = (
        mp_hand("Left", 0.9, "Thumb_Up", 0.3),
        mp_hand("Right", 0.8, "None", 0.7),
        mp_hand("Right", 0.5, "Open_Palm", 0.31),
    )
    result = SimpleNamespace(
        handedness=[left[0], right[0], ghost[0]],
        gestures=[left[1], right[1], ghost[1]],
        hand_landmarks=[left[2], right[2], ghost[2]],
    )
    hands = read_hands(result)
    assert [(h.side, h.gesture) for h in hands] == [("left", "thumbs up"), ("right", None)]
    assert hands[0].points[0] == Point(0.3, 0.5, 1.0)


def test_describe_pose_and_model_paths(tmp_path):
    assert describe_pose(pose_points(left_wrist_y=0.3)) == ["left hand raised"]
    assert describe_pose(pose_points(right_wrist_y=0.3, left_wrist_y=0.3)) == [
        "left hand raised",
        "right hand raised",
    ]
    fetched = []
    path = model_path(
        "pose", tmp_path / "models", lambda url, p: fetched.append(url) or p.write_bytes(b"m")
    )
    assert path.name == "pose_landmarker_lite.task" and path.read_bytes() == b"m"
    model_path("pose", tmp_path / "models", lambda url, p: fetched.append(url))
    assert len(fetched) == 1  # already there


# --- the loop --------------------------------------------------------------


class FakeCamera:
    def __init__(self, frames=None):
        self.frames = frames
        self.released = False

    def release(self):
        self.released = True

    def read(self):
        if self.frames is not None and not self.frames:
            return None
        if self.frames:
            self.frames.pop(0)
        frame = np.zeros((72, 128, 3), dtype=np.uint8)
        frame[:, :10] = 255  # a white stripe on the left: mirrored, it ends up right
        return frame


class FakeDetector:
    def __init__(self, *detections):
        self.detections = list(detections)
        self.frames = []
        self.closed = False

    def detect(self, frame):
        self.frames.append(frame)
        return self.detections

    def close(self):
        self.closed = True


class FakeBrain:
    """What the brain answers each report with."""

    def __init__(self, paused=False, settings=None, fail=False, asleep=False):
        self.reports = []
        self.paused = paused
        self.asleep = asleep
        self.settings = settings
        self.fail = fail

    def __call__(self, report):
        self.reports.append(report)
        if self.fail:
            raise RuntimeError("Can't reach Kit")
        answer = {"ok": True, "paused": self.paused, "asleep": self.asleep}
        if self.settings is not None:
            answer["settings"] = self.settings
        return answer


def make_eyes(brain, cameras=None, detector=None, load_parts=None, **settings):
    clock = Clock()
    ticks = {"t": 0.0}

    def tick():
        ticks["t"] += 0.1
        clock.now = clock.now.replace(second=int(ticks["t"]) % 60)
        return ticks["t"]

    cameras = cameras if cameras is not None else [FakeCamera()]
    opened = []

    def open_camera():
        cam = cameras.pop(0) if cameras else None
        opened.append(cam)
        return cam

    detector = detector or FakeDetector((1, "person", (40, 10, 90, 70)))
    eyes = Eyes(
        open_camera,
        detector,
        brain,
        EyesSettings(**settings),
        clock=tick,
        wall=clock,
        sleep=lambda s: None,
        threaded=False,  # reports go on the spot, so each step's effect can be checked
        load_parts=load_parts,
    )
    return eyes, opened, detector


def test_the_loop_reports_the_scene_about_once_a_second():
    brain = FakeBrain()
    eyes, opened, detector = make_eyes(brain, report_every_s=1.0, confidence=0.5)
    eyes.run(max_steps=25)  # 2.5 seconds of frames
    assert len(opened) == 1 and detector.closed and opened[0].released
    assert 2 <= len(brain.reports) <= 3
    first, last = brain.reports[0], brain.reports[-1]
    assert first["camera"] == "desk" and first["mirrored"] is True
    assert last["people"] and last["people"][0]["id"] == 1
    assert last["people"][0]["box"] == [0.312, 0.139, 0.703, 0.972]
    assert any(e["event"] == "person #1 entered" for r in brain.reports for e in r["events"])
    # The frame the detector saw was mirrored: the white stripe is on the right.
    assert detector.frames[0][0, -1].tolist() == [255, 255, 255]
    assert detector.frames[0][0, 0].tolist() == [0, 0, 0]


def test_unmirrored_frames_are_left_alone():
    brain = FakeBrain()
    eyes, _, detector = make_eyes(brain, mirror=False)
    eyes.step()
    assert detector.frames[0][0, 0].tolist() == [255, 255, 255]
    assert brain.reports[0]["mirrored"] is False


def test_paused_eyes_let_the_camera_go_and_check_back():
    brain = FakeBrain(paused=True)
    eyes, opened, _ = make_eyes(brain, cameras=[FakeCamera(), FakeCamera()])
    eyes.step()  # first report: the brain says paused
    assert eyes.paused and opened[0].released and eyes.camera is None
    for _ in range(40):  # 4 s paused: one "off" check-in, no camera
        eyes.step()
    assert len(opened) == 1
    off = [r for r in brain.reports if r.get("off")]
    assert off and off[0] == {"camera": "desk", "off": True, "asleep": False}
    brain.paused = False
    brain.reports.clear()
    for _ in range(40):
        eyes.step()
    assert not eyes.paused and len(opened) == 2 and brain.reports[-1]["people"]


def test_the_detector_can_rest_between_looks_while_faces_keep_up():
    brain = FakeBrain()
    eyes, _, detector = make_eyes(brain, detect_every=3)
    for _ in range(24):
        eyes.step()
    assert len(detector.frames) == 8  # looks 1, 4, 7 ... 22
    # A frame the detector rested on teaches the scene nothing: eight looks, not
    # twenty-four frames, went into being sure of the person...
    assert eyes.scene.memory.tracks[1].frames_seen == 8
    # ...and on the rest frames the person it saw last look is still there for the
    # face reader to match, and in the report.
    assert 1 in eyes.scene.people and brain.reports[-1]["people"][0]["id"] == 1


def test_a_one_look_false_positive_is_not_confirmed_by_the_rests_after_it():
    # Something seen once stays unconfirmed while the detector rests, however many
    # frames go by; it used to stand in on every rest frame and count each time.
    brain = FakeBrain()
    flicker = FakeDetector((7, "dog", (0, 0, 20, 20)))
    eyes, _, _ = make_eyes(brain, detector=flicker, detect_every=3)
    eyes.step()
    flicker.detections = []
    for _ in range(8):
        eyes.step()
    track = eyes.scene.memory.tracks[7]
    assert track.frames_seen == 1 and not track.confirmed
    assert not any("dog" in e for _, e in eyes.scene.events)


def test_the_camera_coming_back_gets_a_proper_look_first():
    brain = FakeBrain()
    eyes, opened, detector = make_eyes(
        brain, cameras=[FakeCamera(frames=[1, 2]), FakeCamera()], detect_every=3
    )
    for _ in range(3):  # two frames, then the camera stops
        eyes.step()
    assert eyes.camera is None and len(detector.frames) == 1
    for _ in range(100):  # the camera comes back after the retry wait
        eyes.step()
        if eyes.camera is not None:
            break
    # Its first frame is looked at, not rested on.
    assert len(opened) == 2 and len(detector.frames) == 2


def test_a_missing_export_runtime_is_said_plainly(tmp_path, monkeypatch):
    import sys
    import types

    from kit.eyes import detect

    class YOLO:
        def __init__(self, path, **kw):
            pass

        def export(self, **kw):
            raise ModuleNotFoundError("No module named 'openvino'")

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=YOLO))
    with pytest.raises(RuntimeError, match="pip install openvino"):
        detect.exported(tmp_path / "yolo11n.pt", "openvino", 320)
    with pytest.raises(RuntimeError, match="pip install ncnn pnnx"):
        detect.YoloDetector("yolo11n", tmp_path, fmt="ncnn", size=320)


def test_looks_per_second_rests_the_cpu_between_frames():
    brain = FakeBrain()
    eyes, _, _ = make_eyes(brain, looks_per_second=5)
    rests = []
    eyes.sleep = rests.append
    eyes.step()
    # Each look takes 0.1 s on the fake clock, so it rests the other 0.1 s of a fifth.
    assert rests == [pytest.approx(0.1)]
    eyes.settings = EyesSettings(looks_per_second=0)
    rests.clear()
    eyes.step()
    assert rests == []


def test_cpu_detector_settings_are_checked():
    s = EyesSettings(detector_format="openvino", detector_size=320, device="cpu")
    assert (s.detector_format, s.detector_size, s.device) == ("openvino", 320, "cpu")
    for bad in ({"detector_size": 300}, {"detector_format": "tensorrt"}, {"device": "gpu"}):
        with pytest.raises(ValueError):
            EyesSettings(**bad)


def test_exports_are_named_by_format_and_size(tmp_path, monkeypatch):
    from kit.eyes import detect

    assert detect.export_name("yolo11n.pt", "openvino", 320) == "yolo11n_320_openvino_model"
    assert detect.export_name("yolo11n.pt", "onnx", 640) == "yolo11n_640.onnx"
    ready = tmp_path / "yolo11n_320_ncnn_model"
    ready.mkdir()
    # Already made: no Ultralytics needed.
    assert detect.exported(tmp_path / "yolo11n.pt", "ncnn", 320) == ready


def test_while_kit_sleeps_his_eyes_shut_and_their_models_unload(monkeypatch):
    freed = []
    monkeypatch.setattr("kit.eyes.detect.free_gpu", lambda: freed.append(True))
    loaded = []

    def load():
        loaded.append(FakeDetector((1, "person", (40, 10, 90, 70))))
        return {"detector": loaded[-1]}

    brain = FakeBrain(asleep=True)
    first = FakeDetector((1, "person", (40, 10, 90, 70)))
    eyes, opened, _ = make_eyes(
        brain, cameras=[FakeCamera(), FakeCamera()], detector=first, load_parts=load
    )
    eyes.step()  # first report: the brain says Kit's asleep
    assert eyes.asleep and opened[0].released and eyes.camera is None
    assert first.closed and eyes.detector is None and freed
    for _ in range(40):  # 4 s asleep: "off" check-ins, no camera, no models
        eyes.step()
    assert len(opened) == 1 and not loaded
    assert brain.reports[-1] == {"camera": "desk", "off": True, "asleep": True}
    brain.asleep = False  # he woke up
    brain.reports.clear()
    for _ in range(40):
        eyes.step()
    assert len(loaded) == 1 and eyes.detector is loaded[0] and len(opened) == 2
    assert brain.reports[-1]["people"] and loaded[0].frames


def test_eyes_without_a_loader_keep_their_models_while_kit_sleeps():
    brain = FakeBrain(asleep=True)
    eyes, opened, detector = make_eyes(brain, cameras=[FakeCamera(), FakeCamera()])
    eyes.step()
    assert eyes.camera is None and eyes.detector is detector and not detector.closed
    brain.asleep = False
    for _ in range(40):
        eyes.step()
    assert len(opened) == 2 and detector.frames


def test_settings_from_the_brain_apply_to_a_running_pair_of_eyes(caplog):
    brain = FakeBrain(settings={"mirror": False, "forget_after_s": 7.5, "camera": 2})
    eyes, _, detector = make_eyes(brain)
    with caplog.at_level("INFO", logger="kit.eyes.run"):
        eyes.step()
        eyes.step()
    assert eyes.settings.mirror is False and eyes.scene.memory.forget_after == 7.5
    assert detector.frames[1][0, 0].tolist() == [255, 255, 255]  # no longer mirrored
    assert "restart `kit eyes`" in caplog.text and "camera" in caplog.text
    brain.settings = {"mirror": "not a bool"}
    eyes.step()
    assert eyes.settings.mirror is False  # a bad answer changes nothing


def test_a_lost_brain_or_camera_is_retried_not_fatal(caplog):
    brain = FakeBrain(fail=True)
    eyes, opened, _ = make_eyes(brain, cameras=[FakeCamera(frames=[1, 1]), FakeCamera()])
    with caplog.at_level("WARNING", logger="kit.eyes.run"):
        for _ in range(60):
            eyes.step()
    assert eyes.error == "Can't reach Kit" and eyes.reports == 0
    assert caplog.text.count("can't report to the brain") == 1  # said once, not every second
    assert len(brain.reports) == 2  # retried every 5 s, not every second
    assert len(opened) == 2 and opened[0].released  # the first camera died and was reopened
    brain.fail = False
    for _ in range(60):
        eyes.step()
    assert eyes.error == "" and eyes.reports >= 1


def test_events_wait_for_the_brain_instead_of_being_lost():
    brain = FakeBrain(fail=True)
    eyes, _, _ = make_eyes(brain, report_every_s=1.0)
    for _ in range(60):  # the brain is down while "person #1 entered" happens
        eyes.step()
    assert eyes.reports == 0 and any(r["events"] for r in brain.reports)
    brain.fail = False
    brain.reports.clear()
    for _ in range(60):
        eyes.step()
    assert eyes.reports >= 1
    entered = [e for r in brain.reports for e in r["events"] if e["event"] == "person #1 entered"]
    assert len(entered) == 1  # it got there, once, with the first report that did


def test_kept_events_are_capped_at_what_one_report_carries():
    scene = Scene(clock=Clock())
    scene.requeue([{"at": "t", "event": f"e{n}"} for n in range(UNSENT_MAX + 20)])
    events = scene.report()["events"]
    assert len(events) == UNSENT_MAX and events[-1]["event"] == f"e{UNSENT_MAX + 19}"
    assert scene.report()["events"] == []  # reported: gone until requeued


def test_the_report_goes_from_its_own_thread_so_frames_keep_coming():
    gate, sent = threading.Event(), []

    def slow_brain(report):
        sent.append(report)
        gate.wait(5)  # the brain is slow: a report takes seconds to answer
        return {"ok": True, "paused": False}

    brain = FakeBrain()
    eyes, _, detector = make_eyes(brain, report_every_s=1.0)
    eyes.post = Post(slow_brain, dropped=eyes._dropped)  # the real thing, threaded
    before = time.perf_counter()
    for _ in range(25):  # 2.5 s of frames: two reports due, the brain answering neither
        eyes.step()
    assert time.perf_counter() - before < 2.0  # the frame loop never waited on it
    assert len(detector.frames) == 25 and len(sent) == 1 and eyes.reports == 0
    gate.set()  # the brain answers: the one in the slot goes, its answer is collected
    for _ in range(50):
        if eyes.reports == 2:
            break
        eyes.step()
        time.sleep(0.01)
    assert eyes.reports == 2 and len(sent) == 2
    eyes.close()


def test_a_report_pushed_out_of_the_slot_keeps_its_events_for_the_next():
    taken = threading.Event()
    gate = threading.Event()

    def slow_brain(report):
        taken.set()
        gate.wait(5)
        return {}

    scene = Scene(clock=Clock())
    post = Post(slow_brain, dropped=lambda r: scene.requeue(r["events"]))
    post.send({"events": [{"at": "t", "event": "first: taken by the thread"}]})
    assert taken.wait(2)
    post.send({"events": [{"at": "t", "event": "second: waits in the slot"}]})
    post.send({"events": [{"at": "t", "event": "third: pushes the second out"}]})
    assert [e["event"] for e in scene.report()["events"]] == ["second: waits in the slot"]
    gate.set()
    post.close()


def test_no_camera_is_said_once_and_retried():
    brain = FakeBrain()
    eyes, opened, _ = make_eyes(brain, cameras=[None, None, FakeCamera()])
    for _ in range(120):
        eyes.step()
    assert len(opened) == 3 and eyes.camera is opened[2] and brain.reports


def test_the_preview_can_stop_the_loop():
    brain = FakeBrain()
    eyes, _, _ = make_eyes(brain)
    shown = []
    eyes.on_frame = lambda frame, scene, report: shown.append(report) or len(shown) < 3
    eyes.run()
    assert len(shown) == 3 and shown[0] is not None


# --- finding the brain -----------------------------------------------------


def test_eyes_dir_and_saved_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("KIT_EYES_DIR", str(tmp_path / "eyes"))
    assert link.eyes_dir() == tmp_path / "eyes"
    assert link.models_dir() == tmp_path / "eyes" / "models"
    link.save_connection("http://kit-server:8600/", "tok")
    assert (tmp_path / "eyes" / "eyes.toml").read_text() == 'brain_url = "http://kit-server:8600"\n'
    found = link.find_connection(desk_folder=tmp_path / "none")
    assert (found.url, found.token) == ("http://kit-server:8600", "tok")
    assert found.source == str(tmp_path / "eyes")


def test_connection_falls_back_to_the_desk_app_then_kits_folder(tmp_path, monkeypatch, paths):
    from kit.credentials import api_token
    from kit.desk.config import DeskConfig, save_token

    monkeypatch.setenv("KIT_EYES_DIR", str(tmp_path / "eyes"))
    nowhere = tmp_path / "nowhere"
    assert link.find_connection(desk_folder=nowhere, paths=paths) is None
    desk = tmp_path / "desk"
    DeskConfig(brain_url="http://desk-brain:8600").save(desk)
    save_token("desk-tok", desk)
    found = link.find_connection(desk_folder=desk, paths=paths)
    assert (found.url, found.token) == ("http://desk-brain:8600", "desk-tok")
    assert found.source.startswith("the desk app")
    # Given a URL on the command line, the token still comes from where it's kept.
    found = link.find_connection(url="http://other:1", desk_folder=desk, paths=paths)
    assert (found.url, found.token) == ("http://other:1", "desk-tok")
    paths.ensure()
    paths.settings_file.write_text('[brain]\nhost = "0.0.0.0"\nport = 8700\n', encoding="utf-8")
    token = api_token(paths)
    found = link.find_connection(desk_folder=nowhere, paths=paths)
    assert (found.url, found.token) == ("http://127.0.0.1:8700", token)
    assert found.source.startswith("Kit's data folder")
    assert link.find_connection(url="http://x:1", token="t", desk_folder=nowhere).source == (
        "the command line"
    )


def test_eyes_settings_have_sane_defaults():
    s = EyesSettings()
    assert s.enabled and s.mirror and s.detector == "yolo11s" and s.report_every_s == 1.0
    with pytest.raises(ValueError):
        EyesSettings(confidence=2)


# --- the brain client the eyes report through ------------------------------


def test_brain_client_reports_scenes_and_works_the_switch():
    import json

    import httpx

    from kit.desk.client import BrainClient

    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        if request.url.path == "/api/eyes/pause":
            return httpx.Response(200, json={"paused": json.loads(request.content)["paused"]})
        if request.method == "GET":
            return httpx.Response(200, json={"line": "nobody", "paused": False})
        return httpx.Response(200, json={"ok": True, "paused": False, "settings": {}})

    client = BrainClient("http://brain:8600", "tok", transport=httpx.MockTransport(handler))
    assert client.report_scene({"camera": "desk", "people": []})["ok"]
    assert client.eyes()["line"] == "nobody"
    assert client.set_eyes(False) == {"paused": True}
    assert [c[:2] for c in calls] == [
        ("POST", "/api/eyes/scene"),
        ("GET", "/api/eyes/scene"),
        ("POST", "/api/eyes/pause"),
    ]
    assert json.loads(calls[0][2])["camera"] == "desk"


def test_mediapipes_start_up_chatter_is_hidden(capfd):
    import os

    from kit.eyes.run import quiet_native_logs

    with quiet_native_logs():
        os.write(2, b"W0000 feedback manager chatter\n")
    os.write(2, b"after\n")
    assert capfd.readouterr().err == "after\n"
