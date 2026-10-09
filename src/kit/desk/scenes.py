"""Glow's scenes: what his face shows when the brain sends a ``show`` (kit.shows).

Ask the time and his eyes turn into the time. Ask about the weather and the sky
does it on him: rain falls from a little cloud over his head, the sun comes out
at his corner, snow drifts, and his eyes show the temperature first.

A scene paints in two layers, both called every frame by ``FaceWidget``:

- ``inside``: on his dark screen, moving with his head (the digits).
- ``over``: in front of him, staying put like real weather (rain, sun, fog).

and ``eyes`` says how much of his eyes show (0 while the digits are up).

To add one: write a ``Scene`` subclass and put it in ``SCENES`` under the
show's kind (and, for the weather, the sky in ``SKIES``). The brain side is in
``kit.shows``. Painting is QPainter only, in face-relative units, so it can be
ported to the arm's face screen like ``paint_glow``.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTransform

RAIN = QColor(150, 205, 255)
CLOUD = QColor(214, 222, 232)
STORM_CLOUD = QColor(120, 130, 146)
SUN = QColor(255, 206, 84)
MOON = QColor(255, 236, 170)
SNOW = QColor(245, 250, 255)
FOG = QColor(200, 210, 220)


def ramp(t: float, start: float, end: float, fade: float = 0.35) -> float:
    """0 before ``start``, rising to 1, then back to 0 by ``end``."""
    if t <= start or t >= end:
        return 0.0
    return min(1.0, (t - start) / fade, (end - t) / fade)


def glow_path(p: QPainter, path: QPainterPath, colour: QColor, s: float, alpha: float) -> None:
    """Fill a shape the way Glow's eyes are drawn: fading halos, then the shape."""
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i, a in enumerate((40, 26, 16, 9)):
        halo = QColor(colour)
        halo.setAlpha(int(a * alpha))
        p.setPen(QPen(halo, s * 0.016 * (i + 1), c=Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
    fill = QColor(colour)
    fill.setAlphaF(alpha)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(fill)
    p.drawPath(path)


def text_path(text: str, box: QRectF, bold: bool = True) -> QPainterPath:
    """``text`` as a shape, scaled to fit ``box`` and centred in it."""
    font = QFont()
    font.setPointSizeF(100)
    font.setBold(bold)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    r = path.boundingRect()
    if r.width() <= 0 or r.height() <= 0:
        return QPainterPath()
    k = min(box.width() / r.width(), box.height() / r.height())
    t = QTransform()
    t.translate(box.center().x(), box.center().y())
    t.scale(k, k)
    t.translate(-r.center().x(), -r.center().y())
    return t.map(path)


class Scene:
    seconds = 6.0
    gesture: str | None = None  # played as the scene starts

    def __init__(self, show: dict) -> None:
        self.show = show

    def eyes(self, t: float) -> float:
        return 1.0

    def inside(self, p: QPainter, s: float, t: float, colour: QColor) -> None:
        """On his screen; ``s`` is the face's size, the screen is 0.1..0.9 by 0.17..0.83."""

    def over(self, p: QPainter, s: float, t: float) -> None:
        """In front of him, in the face window (``s`` square)."""


class Digits(Scene):
    """His eyes become words: the time ("3:07" with a small "pm") or the date
    ("9 OCT" under a small "FRI")."""

    seconds = 6.5
    gesture = "perk_up"
    SHOWN = (0.25, 6.2)

    def eyes(self, t: float) -> float:
        return 1.0 - ramp(t, *self.SHOWN, fade=0.3)

    def inside(self, p: QPainter, s: float, t: float, colour: QColor) -> None:
        self.digits(p, s, ramp(t, *self.SHOWN, fade=0.3), colour, t)

    def digits(self, p: QPainter, s: float, alpha: float, colour: QColor, t: float) -> None:
        if alpha <= 0.01:
            return
        text = str(self.show.get("text") or "")
        small = str(self.show.get("small") or "")
        if self.show.get("kind") == "time" and int(t * 2) % 2:
            text = text.replace(":", " ")  # the colon blinks, like a clock's
        if small and self.show.get("kind") == "time":
            big = QRectF(s * 0.16, s * 0.34, s * 0.54, s * 0.27)
            under = QRectF(s * 0.71, s * 0.53, s * 0.12, s * 0.08)
        elif small:
            under = QRectF(s * 0.38, s * 0.27, s * 0.24, s * 0.09)  # over it, for the date
            big = QRectF(s * 0.2, s * 0.4, s * 0.6, s * 0.24)
        else:
            big, under = QRectF(s * 0.2, s * 0.35, s * 0.6, s * 0.3), QRectF()
        glow_path(p, text_path(text, big), colour, s, alpha)
        if small:
            glow_path(p, text_path(small, under), colour, s, alpha * 0.8)


class Weather(Digits):
    """The sky, on and around him. The temperature takes his eyes' place first."""

    seconds = 9.5
    SHOWN = (0.2, 3.2)
    FADE = 0.6

    def __init__(self, show: dict) -> None:
        super().__init__(show)
        self.sky = SKIES.get(str(show.get("sky")), Clouds)(show)
        self.gesture = self.sky.gesture

    def eyes(self, t: float) -> float:
        return super().eyes(t) if self.show.get("text") else 1.0

    def inside(self, p: QPainter, s: float, t: float, colour: QColor) -> None:
        if self.show.get("text"):
            self.digits(p, s, ramp(t, *self.SHOWN, fade=0.3), colour, t)

    def over(self, p: QPainter, s: float, t: float) -> None:
        alpha = ramp(t, 0.0, self.seconds, self.FADE)
        if alpha > 0.01:
            p.save()
            p.setOpacity(alpha)
            self.sky.over(p, s, t)
            p.restore()


# The skies. Each is a Scene's ``over`` layer, used by Weather.


def cloud_path(cx: float, cy: float, w: float) -> QPainterPath:
    """A puffy cloud ``w`` wide, centred on (cx, cy)."""
    path = QPainterPath()
    h = w * 0.42
    path.addRoundedRect(QRectF(cx - w / 2, cy - h * 0.1, w, h * 0.55), h * 0.27, h * 0.27)
    for dx, dy, r in ((-0.22, 0.02, 0.18), (0.0, -0.05, 0.22), (0.22, 0.0, 0.17)):
        bump = QPainterPath()
        bump.addEllipse(QPointF(cx + dx * w, cy + dy * w), r * w, r * w)
        path = path.united(bump)
    return path


class Clouds(Scene):
    gesture = "look_up"
    colour = CLOUD

    def cloud(self, p: QPainter, s: float, t: float, x: float = 0.5, w: float = 0.42) -> float:
        """Draw the cloud over his head, drifting a little; returns its bottom."""
        cx = s * (x + 0.04 * math.sin(t * 0.7))
        cy = s * 0.14
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.colour)
        p.drawPath(cloud_path(cx, cy, s * w))
        return cy + s * w * 0.18

    def over(self, p: QPainter, s: float, t: float) -> None:
        self.cloud(p, s, t)


class Sun(Scene):
    gesture = "bounce"

    def over(self, p: QPainter, s: float, t: float) -> None:
        sun(p, s, t)


def sun(p: QPainter, s: float, t: float, cx: float = 0.84, cy: float = 0.13) -> None:
    c, r = QPointF(s * cx, s * cy), s * 0.075
    p.save()
    p.translate(c)
    p.rotate(t * 25)  # the rays turn slowly
    p.setPen(QPen(SUN, s * 0.018, c=Qt.PenCapStyle.RoundCap))
    for i in range(8):
        a = i * math.pi / 4
        reach = 1.55 + 0.12 * math.sin(t * 3 + i)
        p.drawLine(
            QPointF(math.cos(a) * r * 1.3, math.sin(a) * r * 1.3),
            QPointF(math.cos(a) * r * reach, math.sin(a) * r * reach),
        )
    p.restore()
    halo = QColor(SUN)
    for i, a in enumerate((50, 30, 15)):
        halo.setAlpha(a)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, r * (1.15 + 0.2 * i), r * (1.15 + 0.2 * i))
    p.setBrush(SUN)
    p.drawEllipse(c, r, r)


class PartCloud(Clouds):
    gesture = "perk_up"

    def over(self, p: QPainter, s: float, t: float) -> None:
        sun(p, s, t, cx=0.7, cy=0.1)
        self.cloud(p, s, t, x=0.45, w=0.36)


class Moon(Scene):
    gesture = "look_up"

    def over(self, p: QPainter, s: float, t: float) -> None:
        c, r = QPointF(s * 0.82, s * 0.12), s * 0.07
        moon = QPainterPath()
        moon.addEllipse(c, r, r)
        bite = QPainterPath()
        bite.addEllipse(c + QPointF(r * 0.55, -r * 0.3), r * 0.9, r * 0.9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(MOON)
        p.drawPath(moon.subtracted(bite))
        for i, (x, y) in enumerate(((0.2, 0.06), (0.36, 0.13), (0.6, 0.05))):
            twinkle = 0.4 + 0.6 * abs(math.sin(t * 1.7 + i * 2.1))
            star = QColor(MOON)
            star.setAlphaF(twinkle)
            p.setBrush(star)
            p.drawEllipse(QPointF(s * x, s * y), s * 0.012, s * 0.012)


class Falling(Clouds):
    """Something falls from the cloud over his head, on him and past him."""

    count = 26
    speed = 0.9  # face sizes a second
    colour = STORM_CLOUD

    def __init__(self, show: dict) -> None:
        super().__init__(show)
        rng = random.Random(7)  # the same pattern each time, so it's never patchy
        self.drops = [
            (rng.uniform(0.2, 0.8), rng.random(), rng.uniform(0.8, 1.2)) for _ in range(self.count)
        ]

    def over(self, p: QPainter, s: float, t: float) -> None:
        top = self.cloud(p, s, t, w=0.5) / s
        for x, phase, pace in self.drops:
            y = top + ((phase + t * self.speed * pace) % 1.0) * (1.0 - top)
            self.drop(p, s, x, y, t, phase)

    def drop(self, p: QPainter, s: float, x: float, y: float, t: float, phase: float) -> None:
        p.setPen(QPen(RAIN, s * 0.012, c=Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * x, s * y), QPointF(s * (x - 0.008), s * (y + 0.05)))


class Rain(Falling):
    gesture = "look_up"


class Storm(Rain):
    gesture = "startle"
    count = 34
    speed = 1.3
    FLASHES = (1.4, 4.6, 7.2)

    def over(self, p: QPainter, s: float, t: float) -> None:
        flash = max((ramp(t, f, f + 0.35, 0.08) for f in self.FLASHES), default=0.0)
        if flash > 0:  # the lightning lights up his screen
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(60 * flash)))
            p.drawRoundedRect(QRectF(s * 0.1, s * 0.17, s * 0.8, s * 0.66), s * 0.16, s * 0.16)
            bolt = QPainterPath(QPointF(s * 0.55, s * 0.17))
            for x, y in ((0.48, 0.3), (0.56, 0.3), (0.46, 0.48)):
                bolt.lineTo(s * x, s * y)
            p.setPen(QPen(QColor(255, 244, 160, int(255 * flash)), s * 0.02))
            p.drawPath(bolt)
        super().over(p, s, t)


class Snow(Falling):
    gesture = "wiggle"
    count = 22
    speed = 0.22
    colour = CLOUD

    def drop(self, p: QPainter, s: float, x: float, y: float, t: float, phase: float) -> None:
        sway = 0.025 * math.sin(t * 2 + phase * 9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(SNOW)
        p.drawEllipse(QPointF(s * (x + sway), s * y), s * 0.014, s * 0.014)


class Fog(Scene):
    gesture = "look_away"

    def over(self, p: QPainter, s: float, t: float) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        for i, y in enumerate((0.3, 0.5, 0.7)):
            band = QColor(FOG)
            band.setAlpha(70)
            p.setBrush(band)
            x = s * (0.02 + 0.12 * math.sin(t * 0.5 * (1 + i * 0.3) + i * 2))
            p.drawRoundedRect(QRectF(x, s * y, s * 0.8, s * 0.07), s * 0.035, s * 0.035)


SKIES: dict[str, type[Scene]] = {
    "sun": Sun,
    "part_cloud": PartCloud,
    "cloud": Clouds,
    "rain": Rain,
    "storm": Storm,
    "snow": Snow,
    "fog": Fog,
    "moon": Moon,
}
SCENES: dict[str, type[Scene]] = {"time": Digits, "date": Digits, "weather": Weather}


def scene_for(show: dict) -> Scene | None:
    """The scene for a show from the brain, or None for a kind Glow can't draw yet."""
    kind = SCENES.get(str(show.get("kind")))
    return kind(show) if kind else None
