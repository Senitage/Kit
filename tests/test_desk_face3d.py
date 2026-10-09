"""The desk app's 3D face: the brain's face page laid over Glow (kit.desk.face3d)."""

import json

import pytest

pytest.importorskip("PySide6.QtCore", reason="desk extra (PySide6) not installed")

from kit.desk import face3d  # noqa: E402
from kit.face import Face  # noqa: E402

MODEL = {"style": "model", "file": "kit_face.glb", "fallback": "glow"}
GLOW = {"style": "glow"}


def test_the_page_is_the_brains_face_page_for_the_desk():
    assert face3d.page_url("http://100.1.2.3:8600/") == "http://100.1.2.3:8600/face/?app=desk"


def test_the_mirror_sends_everything_first_then_only_what_changed():
    face = Face()
    mirror = face3d.Mirror(face)
    assert mirror.calls() == ['kit.setEmotion("neutral");', 'kit.setState("idle");']
    assert mirror.calls() == []

    face.set_emotion("happy", 1.0)
    face.play("laugh", 1.0)
    face.look_at(0.5, -0.25, 1.0)
    assert mirror.calls() == [
        'kit.setEmotion("happy");',
        'kit.play("laugh");',
        "kit.lookAt(0.5, -0.25);",
    ]
    assert mirror.calls() == []  # the same laugh still playing isn't sent again
    face.play("laugh", 2.0)
    face.set_state("listening")
    assert mirror.calls() == ['kit.setState("listening");', 'kit.play("laugh");']

    mirror.reset()  # the page reloaded: send the face as it is now, but not old gestures
    assert mirror.calls() == [
        'kit.setEmotion("happy");',
        'kit.setState("listening");',
        "kit.lookAt(0.5, -0.25);",
    ]


def test_shows_go_to_the_page_as_json():
    show = {"kind": "weather", "text": "18°", "sky": "storm"}
    call = face3d._call("show", show)
    assert call.startswith("kit.show(") and json.loads(call[9:-2]) == show


class FakeFace3D:
    made = []

    def __init__(self, widget, brain_url):
        self.url = face3d.page_url(brain_url)
        self.detached = False
        FakeFace3D.made.append(self)

    def detach(self):
        self.detached = True


@pytest.fixture
def fake_view(monkeypatch):
    FakeFace3D.made = []
    monkeypatch.setattr(face3d, "Face3D", FakeFace3D)
    monkeypatch.setattr(face3d, "available", lambda: True)
    return FakeFace3D


def test_a_3d_look_attaches_the_page_and_a_2d_look_puts_glow_back(fake_view):
    shown = face3d.sync(None, "http://kit:8600", MODEL, None)
    assert isinstance(shown, FakeFace3D)
    assert face3d.sync(None, "http://kit:8600", MODEL, shown) is shown  # nothing changed
    moved = face3d.sync(None, "http://other:8600", MODEL, shown)  # a different brain
    assert shown.detached and moved is not shown
    assert face3d.sync(None, "http://other:8600", GLOW, moved) is None and moved.detached
    assert face3d.sync(None, None, MODEL, None) is None  # no brain set up yet


def test_without_qts_web_engine_glow_stays(fake_view, monkeypatch):
    monkeypatch.setattr(face3d, "available", lambda: False)
    assert face3d.sync(None, "http://kit:8600", MODEL, None) is None
    assert fake_view.made == []


def test_a_broken_web_engine_leaves_glow(fake_view, monkeypatch):
    def broken(widget, url):
        raise RuntimeError("no GPU")

    monkeypatch.setattr(face3d, "Face3D", broken)
    assert face3d.sync(None, "http://kit:8600", MODEL, None) is None


def test_glow_stops_only_while_kits_model_is_on_screen():
    """Glow's 60 fps repaint makes the web view flash on Windows, so it stops while
    the 3D face covers it, and comes back while the page loads or can't draw."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kit.desk.glow import FaceWidget

    QApplication.instance() or QApplication([])
    widget = FaceWidget()
    shown = face3d.Face3D.__new__(face3d.Face3D)  # no web view: just the hand-over
    shown.widget, shown.covering, shown._ready = widget, False, True
    shown._no_paint = face3d._NoPaint(widget)
    assert widget._timer.isActive()

    shown._drawn(True)
    assert shown.covering and not widget._timer.isActive()
    widget.face.tick(0.0)
    shown._tick_face()  # the rig still runs: moods expire, gaze follows the mouse
    assert widget.face._last > 0.0

    shown._loading()  # a reload: Glow comes back until the model is drawn again
    assert not shown.covering and widget._timer.isActive()
    shown._drawn(True)  # not loaded yet, so it stays Glow
    assert not shown.covering
