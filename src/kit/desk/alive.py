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


class Alive(QObject):
    def __init__(
        self,
        face: FaceWidget,
        focused_rect: Callable[[], tuple[int, int, int, int] | None],
        busy: Callable[[], bool],
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(face)
        self.face = face
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
        self._awake_pos = self.face.pos()
        screen = self.face.screen().availableGeometry()
        # Lie on the bottom of the screen, half tucked under its edge.
        rest = QPoint(self.face.x(), screen.bottom() - int(self.face.height() * 0.55))
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
