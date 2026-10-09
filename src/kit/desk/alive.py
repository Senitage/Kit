"""How Glow's body acts out what Kit's brain decides, plus one reflex.

The brain (``kit.life``) decides everything about Kit's inner life: moods,
fidgets, piping up, and when he falls asleep or wakes. The desk app is only a
body: ``fall_asleep`` and ``wake_up`` run when the brain says so (the arm will
lie down on the desk for the same event). The one thing decided here is a
reflex, like blinking: every so often he glances at the window you're working
in, at random times, because that needs the window's position on this screen.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QTimer

from kit.desk.glow import FaceWidget
from kit.face.body import step

FRAME_MS = 16


class Body(QObject):
    """Where Glow's window sits, as three parts added up: home (where Dan left
    him), a lift (hopping up to make room for his words under him) and a body move
    (a loop, a hop: kit.face.body). Only this moves him while he's awake, so the
    lift and a move can happen at once without fighting over his position.

    ``scale`` makes the moves bigger or smaller (0 turns them off)."""

    LIFT_EASE = 0.18  # how much of the way to the new lift each frame goes

    def __init__(self, face: FaceWidget, size: Callable[[], int]) -> None:
        super().__init__(face)
        self.face = face
        self.size = size  # his face's size in pixels (not the window's)
        self.scale = 1.0
        self.home: QPoint | None = None  # set while anything is moving him
        self.lift_to = 0.0  # pixels up
        self._lift = 0.0
        self._move: tuple[str, float] | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    @property
    def lifted(self) -> float:
        """Pixels he's up by right now (on his way to ``lift_to``)."""
        return self._lift

    @property
    def moving(self) -> str | None:
        return self._move[0] if self._move else None

    def play(self, name: str | None) -> None:
        """Start a body move, unless he's mid-move or moves are off."""
        if not name or self.scale <= 0 or self._move is not None or not self.face.isVisible():
            return
        self._move = (name, time.monotonic())
        self._start()

    def lift(self, pixels: float) -> None:
        """Hop up by ``pixels`` (0 settles back down)."""
        self.lift_to = max(0.0, pixels)
        if self.lift_to or self._lift:
            self._start()

    def stop(self, go_home: bool = True) -> None:
        """Stop moving him: back home first, unless Dan has grabbed him (then
        wherever he is becomes home as Dan drags him)."""
        self.timer.stop()
        if go_home and self.home is not None:
            self.face.move(self.home)
        self.home, self._move = None, None
        self.lift_to = self._lift = 0.0
        self.face.spin, self.face.squash = 0.0, 1.0

    def _start(self) -> None:
        if self.home is None:
            self.home = self.face.pos()
        if not self.timer.isActive():
            self.timer.start(FRAME_MS)

    def tick(self) -> None:
        if self.home is None:
            self.timer.stop()
            return
        self._lift += (self.lift_to - self._lift) * self.LIFT_EASE
        if abs(self.lift_to - self._lift) < 0.5:
            self._lift = self.lift_to
        x = y = spin = 0.0
        squash = 1.0
        if self._move is not None:
            at = step(self._move[0], time.monotonic() - self._move[1])
            if at is None:
                self._move = None
            else:
                k, size = self.scale, self.size()
                x, y = at.x * size * k, at.y * size * k
                spin, squash = at.spin * min(k, 1.5), 1 + (at.squash - 1) * k
        self.face.spin, self.face.squash = spin, squash
        to = self.home + QPoint(round(x), round(y - self._lift))
        screen = self.face.screen()
        if screen is not None:  # never off the screen's edge
            area = screen.availableGeometry()
            to.setX(max(area.left(), min(to.x(), area.right() - self.face.width())))
            to.setY(max(area.top(), min(to.y(), area.bottom() - self.face.height())))
        if to != self.face.pos():
            self.face.move(to)
        if self._move is None and self._lift == 0.0 and self.lift_to == 0.0:
            self.face.move(self.home)
            self.home = None
            self.timer.stop()


class Alive(QObject):
    def __init__(
        self,
        face: FaceWidget,
        focused_rect: Callable[[], tuple[int, int, int, int] | None],
        busy: Callable[[], bool],
        rng: random.Random | None = None,
        body: Body | None = None,
    ) -> None:
        super().__init__(face)
        self.face = face
        self.body = body
        self.focused_rect = focused_rect
        self.busy = busy
        self.rng = rng or random.Random()
        self.asleep = False
        self._awake_pos: QPoint | None = None
        self._next_glance = time.monotonic() + self.rng.uniform(15, 40)
        self._anim: QPropertyAnimation | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.step)
        self.timer.start(1000)

    def step(self) -> None:
        if not self.asleep and time.monotonic() >= self._next_glance:
            self._next_glance = time.monotonic() + self.rng.uniform(20, 70)
            if not self.busy():
                self.glance_at_work()

    def glance_at_work(self) -> None:
        """Look toward the middle of the focused window for a moment."""
        rect = self.focused_rect()
        if rect is None or not self.face.isVisible():
            return
        x, y, w, h = rect
        ratio = self.face.devicePixelRatioF() or 1.0
        cx, cy = (x + w / 2) / ratio, (y + h / 2) / ratio
        centre = self.face.mapToGlobal(self.face.rect().center())
        reach = 600.0
        self.face.face.look_at(
            (cx - centre.x()) / reach, (cy - centre.y()) / reach, time.monotonic()
        )

    def fall_asleep(self) -> None:
        if self.asleep:
            return
        self.asleep = True
        self.face.face.play("yawn", time.monotonic())
        QTimer.singleShot(1800, lambda: self.asleep and self.face.face.set_state("sleeping"))
        if not self.face.isVisible():
            return
        if self.body is not None:
            self.body.stop()  # back home first, so that's where he wakes up
        self._awake_pos = self.face.pos()
        screen = self.face.screen().availableGeometry()
        # Lie on the bottom of the screen, half tucked under its edge.
        f = self.face.face_rect()
        rest = QPoint(self.face.x(), screen.bottom() - int(f.top() + f.height() * 0.55))
        self._slide(rest, 2600, QEasingCurve.Type.InOutSine)

    def wake_up(self) -> None:
        if not self.asleep:
            return
        self.asleep = False
        face = self.face.face
        face.set_state("idle")
        face.play("startle", time.monotonic())
        QTimer.singleShot(1300, lambda: face.play("perk_up", time.monotonic()))
        if self._awake_pos is not None and self.face.isVisible():
            self._slide(self._awake_pos, 700, QEasingCurve.Type.OutBack)
        self._awake_pos = None
        self._next_glance = time.monotonic() + self.rng.uniform(5, 15)

    def _slide(self, to: QPoint, ms: int, curve: QEasingCurve.Type) -> None:
        self._anim = QPropertyAnimation(self.face, b"pos", self)
        self._anim.setDuration(ms)
        self._anim.setEndValue(to)
        self._anim.setEasingCurve(curve)
        self._anim.start()
