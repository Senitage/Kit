"""Glow's scenes (kit.desk.scenes): the time, the date and the weather on his face."""

import os

import pytest

pytest.importorskip("PySide6.QtWidgets", reason="desk extra (PySide6) not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kit.desk.face_preview import SHOW_SAMPLES  # noqa: E402
from kit.desk.glow import FaceWidget, paint_glow  # noqa: E402
from kit.desk.scenes import SKIES, scene_for  # noqa: E402
from kit.face import Face  # noqa: E402
from kit.shows import SKIES as BRAIN_SKIES  # noqa: E402

SIZE = 160


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def render(show=None, t=0.0):
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    frame = Face().tick(0.0)
    scene = scene_for(show) if show else None
    if scene is None:
        paint_glow(p, QRectF(0, 0, SIZE, SIZE), frame)
    else:
        paint_glow(
            p,
            QRectF(0, 0, SIZE, SIZE),
            frame,
            eyes=scene.eyes(t),
            inside=lambda q, s, c: scene.inside(q, s, t, c),
        )
        scene.over(p, SIZE, t)
    p.end()
    return img


def test_every_sky_the_brain_can_send_has_a_picture():
    assert {kind for _, kind in BRAIN_SKIES} | {"moon"} <= set(SKIES)


@pytest.mark.parametrize("name", list(SHOW_SAMPLES))
def test_each_show_draws_something_different_from_his_plain_face(qapp, name):
    plain = render()
    for t in (1.5, 5.0):
        assert render(SHOW_SAMPLES[name], t) != plain


def test_the_time_takes_his_eyes_then_gives_them_back():
    scene = scene_for(SHOW_SAMPLES["time"])
    assert scene.eyes(0.0) == 1.0 and scene.eyes(3.0) == 0.0 and scene.eyes(scene.seconds) == 1.0
    weather = scene_for(SHOW_SAMPLES["rain"])
    assert weather.eyes(1.5) == 0.0 and weather.eyes(6.0) == 1.0  # temperature first, then eyes
    no_temp = scene_for({"kind": "weather", "sky": "rain"})
    assert no_temp.eyes(1.5) == 1.0


def test_a_show_glow_cant_draw_yet_is_ignored(qapp):
    face = FaceWidget()
    assert face.play_show({"kind": "fireworks"}) is False and face.scene is None
    assert face.play_show(SHOW_SAMPLES["sun"]) is True and face.face.gesture == "bounce"
    face.grab()  # paints with the scene
    face.close()
