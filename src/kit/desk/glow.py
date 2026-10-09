"""The Glow face: two glowing pill eyes on a dark rounded screen.

``paint_glow`` draws one ``FaceFrame`` with QPainter and nothing else, so the
same frame can be painted in the helper window, in a test image, or (ported to
C++) on the arm's round GC9A01 screen. ``FaceWidget`` runs a ``Face`` at 60 fps
and makes the eyes follow the mouse. Colours and sizes come from the look in
Kit's character sheet (kit.face.character), so the painter only knows shapes.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from kit.face import Face, FaceFrame
from kit.face.character import Character, current


def _eye_path(
    cx: float, cy: float, w: float, h: float, s: float, f: FaceFrame, side: int, corner: float
):
    """One eye as a rounded pill, with the lids cut away by path subtraction."""
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
        r = w * 1.15
        lid = QPainterPath()
        lid.addEllipse(QPointF(cx, cy + hh / 2 + r - hh * f.squint * 0.85), r, r)
        eye = eye.subtracted(lid)
    return eye


def paint_glow(
    p: QPainter,
    rect: QRectF,
    f: FaceFrame,
    background: QColor | None = None,
    eye: QColor | None = None,
    character: Character | None = None,
) -> None:
    """Paint one frame of the Glow face into ``rect`` (drawn square, centred), with
    the eyes in ``eye`` (the character's own colour unless Dan picked another on the
    Look page). ``character`` defaults to the one Kit is using now; its 2D look for
    the desk is drawn (a 3D look's 2D fallback until the desk can draw 3D)."""
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

    # Head motion: tilt, bob, squash and lean, pivoting below centre like a neck.
    p.translate(ox + s / 2 + f.dx * s, oy + s * neck + f.dy * s)
    p.rotate(f.rot * 57.2958)
    p.scale(f.sx * f.scale, f.sy * f.scale)
    p.translate(-s / 2, -s * neck)

    screen = QRectF(s * scr["x"], s * scr["y"], s * scr["width"], s * scr["height"])
    p.setPen(QPen(colours["bezel"], s * scr["bezel"]))
    p.setBrush(colours["screen"])
    p.drawRoundedRect(screen, s * scr["corner"], s * scr["corner"])

    pulse = 1 + f.talk * eyes["talk_pulse"]
    colour = colours["eye_offline"] if f.offline else (eye or colours["eye"])
    for side, open_ in ((-1, f.open_left), (1, f.open_right)):
        cx = s / 2 + side * s * eyes["apart"] + f.look_x * s * eyes["reach_x"]
        cy = s * eyes["y"] + f.look_y * s * eyes["reach_y"]
        w = s * eyes["width"] * f.size
        h = s * eyes["height"] * f.size * open_ * pulse
        eye = _eye_path(cx, cy, w, h, s, f, side, eyes["corner"])
        # Glow: the eye's outline stroked in widening, fading rings, then the eye itself.
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, alpha in enumerate(glow["rings"]):
            halo = QColor(colour)
            halo.setAlpha(int(alpha * f.glow))
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
        fill.setAlphaF(glow["dim"] + (1 - glow["dim"]) * f.glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPath(eye)

    if f.blush > blush["from"] and not f.offline:
        cheek = QColor(colours["blush"])
        cheek.setAlphaF(min(1.0, f.blush * blush["strength"] * f.glow))
        p.setBrush(cheek)
        for side in (-1, 1):
            centre = QPointF(s / 2 + side * s * blush["apart"], s * blush["y"])
            p.drawEllipse(centre, s * blush["width"], s * blush["height"])
    p.restore()


class FaceWidget(QWidget):
    """A live Glow face. The eyes follow the mouse while it moves."""

    def __init__(self, face: Face | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.face = face or Face()
        self.background: QColor | None = None
        self.eye: QColor | None = None
        self.follow_mouse = True
        self._frame = self.face.tick(time.monotonic())
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
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        paint_glow(p, QRectF(self.rect()), self._frame, self.background, self.eye)
        p.end()
