"""The little things Glow does on the desk by himself, between conversations.

The brain decides moods and when to pipe up (``kit.life``). These happen right
here, every second, with no network or model, so they're instant:

- every so often he glances at the window you're working in, as if reading
  over your shoulder;
- after you've been away a while (or the PC is locked) he dozes off and slides
  down to lie on the bottom of the screen;
- when you come back he startles awake, perks up and climbs back to his spot.

Timings are random within limits, so it never feels like a loop.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QTimer

from kit.desk.glow import FaceWidget

WAKE_IDLE_S = 3.0


class Alive(QObject):
    def __init__(
        self,
        face: FaceWidget,
        snapshot: Callable[[], dict | None],
        focused_rect: Callable[[], tuple[int, int, int, int] | None],
        sleep_after_s: Callable[[], float],
        busy: Callable[[], bool],
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(face)
        self.face = face
        self.snapshot = snapshot
        self.focused_rect = focused_rect
        self.sleep_after_s = sleep_after_s
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
        snap = self.snapshot()
        if snap is None:
            return
        idle = snap.get("idle_seconds", 0.0)
        away = snap.get("locked") or idle >= self.sleep_after_s()
        if away and not self.asleep and not self.busy():
            self.fall_asleep()
        elif self.asleep and not snap.get("locked") and idle < WAKE_IDLE_S:
            self.wake_up()
        elif not self.asleep and time.monotonic() >= self._next_glance:
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
