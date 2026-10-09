"""Kit's character sheet: one file for how he looks and moves, read by every app."""

import copy
import json
import random

import pytest

from kit.face import Face
from kit.face import character as ch
from kit.reply import EMOTIONS, GESTURES

# A 3D look: a glTF model whose head bone and morph targets the rig drives.
MODEL = {
    "style": "model",
    "file": "kit.glb",
    "fallback": "glow",
    "head_bone": "head",
    "morphs": {"open": "EyesOpen", "squint": "Squint", "blush": "Blush"},
}


@pytest.fixture
def sheet():
    return copy.deepcopy(ch.builtin().sheet)


@pytest.fixture(autouse=True)
def restore_current():
    yield
    ch.use(ch.builtin())


def test_the_shipped_sheet_is_valid_and_covers_every_emotion_and_gesture(sheet):
    assert ch.check(sheet) == []
    assert set(sheet["poses"]) == set(EMOTIONS)
    assert set(sheet["gestures"]) == set(GESTURES)


def test_shapes_do_what_the_sheet_says():
    at = ch.move_at
    assert at({"dy": [[0.5, ["bump", 0, 1]]]}, 0.5)["dy"] == pytest.approx(0.5)
    assert at({"dy": [[0.5, ["bump", 0.2, 0.4]]]}, 0.6)["dy"] == 0
    assert at({"dy": [[1, ["bump", 0, 1, 3]]]}, 0.25)["dy"] == 1  # capped at 1
    assert at({"dy": [[1, ["hold", 0.2, 0.8]]]}, 0.5)["dy"] == 1
    assert at({"dy": [[1, ["jolt", 0.1]]]}, 0.1)["dy"] == pytest.approx(1)
    assert at({"dy": [[2, ["line", 1, -1]]]}, 0.25)["dy"] == pytest.approx(1.5)
    assert at({"sy": [[0.1, ["hold", 0.2, 0.8]]]}, 0.5)["sy"] == pytest.approx(1.1)
    assert at({}, 0.5)["scale"] == 1 and at({}, 0.5)["dx"] == 0


@pytest.mark.parametrize(
    "spoil, problem",
    [
        (lambda s: s.pop("poses"), "missing 'poses'"),
        (lambda s: s["poses"]["happy"].update(grin=1), "unknown 'grin'"),
        (lambda s: s["looks"]["glow"]["colours"].update(eye="teal"), "should be like #7EF3E6"),
        (lambda s: s["use"].update(desk="clay"), "unknown look 'clay'"),
        (lambda s: s["looks"].update(clay={"style": "clay"}), "needs a style"),
        (lambda s: s["looks"].update(kit3d={**MODEL, "file": "kit.png"}), "needs a .glb"),
        (lambda s: s["looks"].update(kit3d={**MODEL, "fallback": "kit3d"}), "a 2D look"),
        (lambda s: s["gestures"]["nod"]["moves"].update(spin=[[1]]), "unknown 'spin'"),
        (lambda s: s["gestures"]["nod"]["moves"]["dy"].append([1, ["wobble", 2]]), "bad shape"),
        (lambda s: s["states"]["offline"].update(pose="gone"), "unknown pose 'gone'"),
    ],
)
def test_a_broken_sheet_is_refused_in_plain_words(sheet, spoil, problem):
    spoil(sheet)
    with pytest.raises(ch.CharacterError, match=problem):
        ch.from_sheet(sheet)


def test_a_redesigned_sheet_changes_the_face(sheet):
    sheet["poses"]["happy"]["squint"] = 0.0
    sheet["gestures"]["nod"]["seconds"] = 3.0
    face = Face(rng=random.Random(1), character=ch.from_sheet(sheet))
    face.set_emotion("happy", 0)
    frames = [face.tick(i / 60) for i in range(120)]
    assert frames[-1].squint < 0.05  # the stock happy face squints at 0.6
    face.play("nod", 2)
    face.tick(4)
    assert face.gesture == "nod"  # still nodding: the new nod lasts 3 s


def test_using_a_sheet_reaches_every_face(sheet):
    sheet["poses"]["sad"]["open"] = 0.2
    ch.use(ch.from_sheet(sheet))
    face = Face(rng=random.Random(1))
    face.set_emotion("sad", 0)
    settled = [face.tick(i / 60) for i in range(180)][-1]
    assert settled.open_left < 0.4


def test_the_sheet_is_plain_json(sheet):
    assert json.loads(json.dumps(sheet)) == sheet


def test_each_app_or_body_picks_2d_or_3d(sheet):
    sheet["looks"]["kit3d"] = MODEL
    sheet["use"].update(desk="kit3d", robot="glow")
    kit = ch.from_sheet(sheet)
    assert kit.look("desk", styles=("glow", "model"))["file"] == "kit.glb"
    assert kit.look("robot", styles=("glow", "model"))["style"] == "glow"
    # An app that can only draw 2D gets the 3D look's 2D fallback.
    assert kit.look("desk")["style"] == "glow"
    assert kit.look("phone") == kit.look("default")  # unnamed apps use the default
