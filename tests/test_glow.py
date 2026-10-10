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


def test_the_eye_colour_comes_from_the_character_sheet(app):
    import copy

    from kit.face import character as ch

    sheet = copy.deepcopy(ch.builtin().sheet)
    sheet["looks"]["glow"]["colours"]["eye"] = "#FF4000"
    ch.use(ch.from_sheet(sheet))
    try:
        img = render(replace(neutral(), look_x=0, look_y=0))
    finally:
        ch.use(ch.builtin())
    c = QColor(img.pixel(int(SIZE * 0.345), int(SIZE * 0.5)))
    assert c.red() > 200 and c.blue() < 80


def render_kit2d(frame, robot=False):
    from kit.face import character as ch

    kit2d = ch.preset("kit2d")
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    paint_glow(p, QRectF(0, 0, SIZE, SIZE), frame, character=kit2d)
    p.end()
    return img


def kit2d_frame(emotion, **change):
    from kit.face import character as ch

    face = Face(character=ch.preset("kit2d"))
    face.set_emotion(emotion, 0.0)
    for i in range(40):
        frame = face.tick(i * 0.05)
    return replace(frame, look_x=0, look_y=0, open_left=1, open_right=1, **change)


def mouth_lit(img):
    """Glowing pixels in the mouth's strip, under the eyes."""
    return sum(
        1
        for y in range(int(SIZE * 0.58), int(SIZE * 0.69))
        for x in range(int(SIZE * 0.4), int(SIZE * 0.6))
        if QColor(img.pixel(x, y)).alpha() > 0 and QColor(img.pixel(x, y)).green() > 150
    )


def test_kit2d_draws_a_shaded_shell_brows_and_a_mood_coloured_mouth(app):
    img = render_kit2d(kit2d_frame("neutral"))
    top = QColor(img.pixel(SIZE // 2, int(SIZE * 0.2)))
    bottom = QColor(img.pixel(SIZE // 2, int(SIZE * 0.8)))
    assert top.lightness() > bottom.lightness()  # the shell is lit from above
    assert QColor(img.pixel(int(SIZE * 0.335), int(SIZE * 0.47))).green() > 200  # mint eye
    brow = QColor(img.pixel(int(SIZE * 0.335), int(SIZE * 0.305)))
    assert brow.green() > brow.red() + 40  # a brow above the eye
    shut = mouth_lit(render_kit2d(kit2d_frame("neutral")))
    opened = mouth_lit(render_kit2d(kit2d_frame("happy")))
    assert 0 < shut < opened  # a small smile, then an open "D"
    talking = mouth_lit(render_kit2d(kit2d_frame("neutral", talk=0.8)))
    assert talking > shut  # he moves his mouth as he talks
    red = QColor(render_kit2d(kit2d_frame("grumpy")).pixel(int(SIZE * 0.335), int(SIZE * 0.49)))
    assert red.red() > 200 and red.blue() < 140  # grumpy glows orange-red


def test_a_mouth_is_a_line_an_open_d_or_an_o():
    from kit.desk.glow import mouth_shape

    look = {"talk": 0.8}
    assert mouth_shape(kit2d_frame("neutral"), look) == ("line", 0.55)
    assert mouth_shape(kit2d_frame("happy"), look)[0] == "open"
    assert mouth_shape(kit2d_frame("surprised"), look)[0] == "o"
    assert mouth_shape(kit2d_frame("sad"), look)[1] < 0  # a frown
