"""The Glow face: two glowing pill eyes on a dark rounded screen.

``paint_glow`` draws one ``FaceFrame`` with QPainter and nothing else, so the
same frame can be painted in the helper window, in a test image, or (ported to
C++) on the arm's round GC9A01 screen. ``FaceWidget`` runs a ``Face`` at 60 fps
and makes the eyes follow the mouse. Colours and sizes come from the look in
Kit's character sheet (kit.face.character), so the painter only knows shapes.
A look can add brows, a mouth and a shaded shell (Kit 2D, the 3D face drawn
flat); docs/face.md lays out the shapes for other painters.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from kit.desk.scenes import Scene, scene_for
from kit.face import Face, FaceFrame
from kit.face.character import Character, current


def _eye_path(
    cx: float,
    cy: float,
    w: float,
    h: float,
    s: float,
    f: FaceFrame,
    side: int,
    corner: float,
    lift: float = 0.85,
    round_: float = 1.15,
):
    """One eye as a rounded pill, with the lids cut away by path subtraction.
    ``lift`` is how far the lower lid rises at full squint and ``round_`` its size
    against the eye's width (Kit 2D's thinner "^ ^" eyes rise further)."""
    eye = QPainterPath()
    h = max(h, s * 0.012)
    eye.addRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), s * corner, min(s * corner, h / 2))
    hh = max(h, s * 0.03)
    if abs(f.tilt) > 0.02:
        # Upper lid: a sloped edge. Sad lifts the inner corners; focused drops them.
        slope = f.tilt * 0.55 * (-1 if side < 0 else 1)
        y0 = cy - hh / 2 + hh * 0.32 * abs(f.tilt)
        x0, x1 = cx - w * 1.5, cx + w * 1.5
        lid = QPainterPath(QPointF(x0, y0 + slope * (x0 - cx)))
        lid.lineTo(x1, y0 + slope * (x1 - cx))
        lid.lineTo(x1, cy - hh * 2)
        lid.lineTo(x0, cy - hh * 2)
        lid.closeSubpath()
        eye = eye.subtracted(lid)
    if f.squint > 0.02:
        # Lower lid: a big circle rising from below gives happy "^ ^" eyes.
        r = w * round_
        lid = QPainterPath()
        lid.addEllipse(QPointF(cx, cy + hh / 2 + r - hh * f.squint * lift), r, r)
        eye = eye.subtracted(lid)
    return eye


def paint_glow(
    p: QPainter,
    rect: QRectF,
    f: FaceFrame,
    background: QColor | None = None,
    eye: QColor | None = None,
    character: Character | None = None,
    shown: float = 1.0,
    inside: Callable[[QPainter, float, QColor], None] | None = None,
) -> None:
    """Paint one frame of the Glow face into ``rect`` (drawn square, centred), with
    the eyes in ``eye`` (the character's own colour unless Dan picked another on the
    Look page). ``character`` defaults to the one Kit is using now; its 2D look for
    the desk is drawn (a 3D look's 2D fallback until the desk can draw 3D).
    ``shown`` fades the eyes out (0) for a scene, and ``inside`` paints the scene on
    his screen, moving with his head (kit.desk.scenes)."""
    look = (character or current()).look("desk")
    colours = {k: QColor(v) for k, v in look["colours"].items()}
    scr, eyes, glow, blush = look["screen"], look["eyes"], look["glow"], look["blush"]
    neck = look["neck"]
    s = min(rect.width(), rect.height())
    ox = rect.x() + (rect.width() - s) / 2
    oy = rect.y() + (rect.height() - s) / 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if background is not None:
        p.fillRect(rect, background)

    if "shell" in look:
        p.save()
        p.translate(ox, oy)
        _paint_shadow(p, s, scr, look["shell"])
        p.restore()

    # Head motion: tilt, bob, squash and lean, pivoting below centre like a neck.
    p.translate(ox + s / 2 + f.dx * s, oy + s * neck + f.dy * s)
    p.rotate(f.rot * 57.2958)
    p.scale(f.sx * f.scale, f.sy * f.scale)
    p.translate(-s / 2, -s * neck)

    screen = QRectF(s * scr["x"], s * scr["y"], s * scr["width"], s * scr["height"])
    if "shell" in look:
        _paint_shell(p, screen, s * scr["corner"], look["shell"], colours, s)
    else:
        bezel = s * scr["bezel"]
        p.setPen(QPen(colours["bezel"], bezel) if bezel > 0 else Qt.PenStyle.NoPen)
        p.setBrush(colours["screen"])
        p.drawRoundedRect(screen, s * scr["corner"], s * scr["corner"])

    pulse = 1 + f.talk * eyes["talk_pulse"]
    # A character with mood colours glows in the mood's colour, like the 3D face;
    # otherwise the eye colour picked on the Look page (or the look's own).
    mood = QColor(f.colour) if f.colour and character_moods(character) else None
    colour = colours["eye_offline"] if f.offline else (mood or eye or colours["eye"])
    if inside is not None:
        inside(p, s, colour)
    for side, open_ in ((-1, f.open_left), (1, f.open_right)) if shown > 0.01 else ():
        cx = s / 2 + side * s * eyes["apart"] + f.look_x * s * eyes["reach_x"]
        cy = s * eyes["y"] + f.look_y * s * eyes["reach_y"]
        w = s * eyes["width"] * f.size
        h = s * eyes["height"] * f.size * open_ * pulse
        eye = _eye_path(
            cx,
            cy,
            w,
            h,
            s,
            f,
            side,
            eyes["corner"],
            eyes.get("squint_lift", 0.85),
            eyes.get("squint_round", 1.15),
        )
        # Glow: the eye's outline stroked in widening, fading rings, then the eye itself.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, alpha in enumerate(glow["rings"]):
            halo = QColor(colour)
            halo.setAlpha(int(alpha * f.glow * shown))
            p.setPen(
                QPen(
                    halo,
                    s * glow["ring_width"] * (i + 1),
                    c=Qt.PenCapStyle.RoundCap,
                    j=Qt.PenJoinStyle.RoundJoin,
                )
            )
            p.drawPath(eye)
        fill = QColor(colour)
        fill.setAlphaF((glow["dim"] + (1 - glow["dim"]) * f.glow) * shown)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPath(eye)
        if "brows" in look:
            _paint_brow(p, cx, cy, w, s, f, side, look["brows"], fill)

    if "mouth" in look and shown > 0.01:
        fill = QColor(colour)
        fill.setAlphaF((glow["dim"] + (1 - glow["dim"]) * f.glow) * shown)
        reach_x, reach_y = eyes["reach_x"] * 0.5, eyes["reach_y"] * 0.5
        mx = s / 2 + f.look_x * s * reach_x
        my = s * look["mouth"]["y"] + f.look_y * s * reach_y
        _paint_mouth(p, mx, my, s, f, look["mouth"], fill)

    if f.blush > blush["from"] and not f.offline:
        p.setPen(Qt.PenStyle.NoPen)
        cheek = QColor(colours["blush"])
        cheek.setAlphaF(min(1.0, f.blush * blush["strength"] * f.glow * shown))
        p.setBrush(cheek)
        for side in (-1, 1):
            centre = QPointF(s / 2 + side * s * blush["apart"], s * blush["y"])
            p.drawEllipse(centre, s * blush["width"], s * blush["height"])
    p.restore()


def character_moods(character: Character | None) -> bool:
    return bool((character or current()).sheet.get("mood_colours"))


def _paint_shell(p: QPainter, body: QRectF, corner: float, shell: dict, colours: dict, s: float):
    """His screen shaded like a rounded body: dark from top to bottom and a soft
    shine up and to the left."""
    p.setPen(Qt.PenStyle.NoPen)
    fill = QLinearGradient(0, body.top(), 0, body.bottom())
    fill.setColorAt(0, colours.get("shell_top", colours["screen"]))
    fill.setColorAt(0.45, colours["screen"])
    fill.setColorAt(1, colours.get("shell_bottom", colours["screen"]))
    p.setBrush(fill)
    p.drawRoundedRect(body, corner, corner)
    centre = QPointF(body.x() + body.width() * 0.33, body.y() + body.height() * 0.15)
    shine = QRadialGradient(centre, s * 0.32)
    shine.setColorAt(0, QColor(255, 255, 255, int(255 * shell.get("shine", 0.13))))
    shine.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(shine)
    p.drawRoundedRect(body, corner, corner)


def _paint_shadow(p: QPainter, s: float, screen: dict, shell: dict) -> None:
    """A soft shadow on the ground under the shell. It stays put while he moves."""
    x = screen["x"] + screen["width"] / 2
    centre = QPointF(s * x, s * (screen["y"] + screen["height"] + 0.07))
    shadow = QRadialGradient(centre, s * 0.4)
    shadow.setColorAt(0, QColor(0, 0, 0, int(255 * shell.get("shadow", 0.27))))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(shadow)
    p.drawEllipse(centre, s * screen["width"] * 0.47, s * 0.045)


def _paint_brow(p: QPainter, cx, cy, w, s, f: FaceFrame, side: int, brows: dict, colour: QColor):
    """A thin arched brow above an eye. ``brow`` + lifts the inner end (sad or
    worried), - drops it (cross); ``brow_up`` raises both."""
    y = cy - s * brows["above"] * max(1.0, f.size) - f.brow_up * s * brows["lift"]
    half = s * brows["width"] / 2
    slant = f.brow * s * brows["slant"]
    inner = -side  # the inner end points toward the nose
    start = QPointF(cx - inner * half, y + slant * 0.4)
    end = QPointF(cx + inner * half, y - slant)
    path = QPainterPath(start)
    path.quadTo(QPointF(cx, y - s * brows["arch"] + slant * 0.2), end)
    c = QColor(colour)
    c.setAlphaF(c.alphaF() * brows.get("alpha", 0.85))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(c, s * brows["thick"], c=Qt.PenCapStyle.RoundCap))
    p.drawPath(path)


def mouth_shape(f: FaceFrame, mouth: dict) -> tuple[str, float]:
    """Which mouth to draw and how much: ("o", size) for a round mouth, ("open",
    depth) for an open "D", or ("line", curve) for a smile, flat line or frown.
    Talking opens it a little, on and off."""
    talk = f.talk * mouth.get("talk", 0.8)
    if f.mouth_o > 0.2:
        return "o", f.mouth_o
    opened = max(f.mouth_open, talk)
    if opened > 0.12:
        return "open", opened
    return "line", f.mouth


def _paint_mouth(p: QPainter, mx, my, s, f: FaceFrame, mouth: dict, colour: QColor):
    kind, amount = mouth_shape(f, mouth)
    w = s * mouth["width"]
    p.setPen(Qt.PenStyle.NoPen)
    if kind == "o":
        r = s * mouth["round"] * (0.45 + 0.55 * amount)
        p.setBrush(colour)
        p.drawEllipse(QPointF(mx, my), r * 0.85, r)
    elif kind == "open":
        d = s * mouth["open"] * amount
        w *= 0.8 + 0.4 * amount
        path = QPainterPath(QPointF(mx - w / 2, my - d * 0.25))
        path.quadTo(QPointF(mx, my - d * 0.05), QPointF(mx + w / 2, my - d * 0.25))
        path.cubicTo(
            QPointF(mx + w / 2, my + d * 0.9),
            QPointF(mx - w / 2, my + d * 0.9),
            QPointF(mx - w / 2, my - d * 0.25),
        )
        p.setBrush(colour)
        p.drawPath(path)
    else:
        c = amount * s * mouth["curve"]
        path = QPainterPath(QPointF(mx - w / 2, my - c * 0.3))
        path.quadTo(QPointF(mx, my + c), QPointF(mx + w / 2, my - c * 0.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(colour, s * mouth["thick"], c=Qt.PenCapStyle.RoundCap))
        p.drawPath(path)


class FaceWidget(QWidget):
    """A live Glow face. The eyes follow the mouse while it moves, and
    ``play_show`` plays a scene from the brain (the time, the weather) on and around him."""

    def __init__(self, face: Face | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.face = face or Face()
        self.background: QColor | None = None
        self.eye: QColor | None = None
        self.follow_mouse = True
        self.margin = 0.0  # room around his face to move into, as a fraction of its size
        self.spin, self.squash = 0.0, 1.0  # set by a body move (kit.desk.alive.Body)
        self._frame = self.face.tick(time.monotonic())
        self.scene: Scene | None = None
        self._scene_at = 0.0
        self._cursor = QCursor.pos()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(16)
        self.setMinimumSize(120, 120)

    def _step(self) -> None:
        now = time.monotonic()
        pos = QCursor.pos()
        if self.follow_mouse and pos != self._cursor:
            self._cursor = pos
            centre = self.mapToGlobal(self.rect().center())
            reach = max(self.width(), 300)
            self.face.look_at((pos.x() - centre.x()) / reach, (pos.y() - centre.y()) / reach, now)
        self._frame = self.face.tick(now)
        if self.scene is not None and now - self._scene_at > self.scene.seconds:
            self.scene = None
        self.update()

    def play_show(self, what: dict) -> bool:
        """Play a show from the brain (kit.shows) as a scene; False if Glow can't
        draw that kind yet."""
        scene = scene_for(what)
        if scene is None:
            return False
        self.scene, self._scene_at = scene, time.monotonic()
        if scene.gesture and self.face.state not in ("sleeping", "offline"):
            self.face.play(scene.gesture, self._scene_at)
        return True

    def scene_time(self) -> float:
        return time.monotonic() - self._scene_at

    def face_rect(self) -> QRectF:
        """Where his face is drawn: a square in the middle, leaving ``margin`` around
        it for big moves, which would otherwise be cut off at the window's edge."""
        side = min(self.width(), self.height()) / (1 + 2 * self.margin)
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        if self.background is not None:
            p.fillRect(self.rect(), self.background)
        rect = self.face_rect()
        frame = self._frame
        if self.spin or self.squash != 1.0:  # a body move (kit.face.body)
            frame = replace(
                frame,
                rot=frame.rot + self.spin,
                sy=frame.sy * self.squash,
                sx=frame.sx * (2 - self.squash),
            )
        scene = self.scene
        if scene is None:
            paint_glow(p, rect, frame, None, self.eye)
        else:
            t = self.scene_time()
            paint_glow(
                p,
                rect,
                frame,
                None,
                self.eye,
                shown=scene.eyes(t),
                inside=lambda q, s, colour: scene.inside(q, s, t, colour),
            )
            p.translate(rect.topLeft())
            scene.over(p, rect.width(), t)
        p.end()
