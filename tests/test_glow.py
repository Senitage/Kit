"""The Glow painter, drawn into an image without a screen. Needs the desk extra."""

import os
from dataclasses import replace

import pytest

pytest.importorskip("PySide6.QtGui", reason="desk extra (PySide6) not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

from kit.desk.glow import paint_glow  # noqa: E402
from kit.face import Face  # noqa: E402

SIZE = 200


@pytest.fixture(scope="module")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def render(frame):
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    paint_glow(p, QRectF(0, 0, SIZE, SIZE), frame)
    p.end()
    return img


def lit(img):
    """Pixels bright enough to be eye glow."""
    return sum(
        1
        for y in range(0, SIZE, 2)
        for x in range(0, SIZE, 2)
        if QColor(img.pixel(x, y)).green() > 150
    )


def neutral():
    return Face().tick(0)


def test_open_eyes_glow_and_closed_eyes_do_not(app):
    f = replace(neutral(), look_x=0, look_y=0)
    open_ = lit(render(f))
    shut = lit(render(replace(f, open_left=0, open_right=0)))
    assert open_ > 200
    assert shut < open_ * 0.2


def test_happy_squint_and_sad_lids_cut_into_the_eyes(app):
    f = replace(neutral(), look_x=0, look_y=0)
    full = lit(render(f))
    assert lit(render(replace(f, squint=0.6))) < full * 0.85
    assert lit(render(replace(f, tilt=0.75))) < full * 0.95


def test_eye_centre_is_the_glow_colour(app):
    img = render(replace(neutral(), look_x=0, look_y=0))
    c = QColor(img.pixel(int(SIZE * 0.345), int(SIZE * 0.5)))
    assert c.green() > 200 and c.blue() > 180 and c.red() < 180
