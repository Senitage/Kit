"""Try Kit's Glow face without the brain: ``python -m kit.desk.face_preview``.

Buttons set each emotion, play each gesture, switch each state and play each
show (the time, the date, each kind of weather), and
"Play a Kit reply" acts out sample replies the way the helper will. Add
``--float`` to see it as a small frameless always-on-top face you can drag.
"""

from __future__ import annotations

import sys
import time
from itertools import cycle

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kit.desk.glow import FaceWidget
from kit.face import CLIPS, POSES, STATES, plan_reply

SAMPLES = [
    {
        "emotion": "excited",
        "segments": [
            {"say": "The new servos shipped!", "gesture": "wiggle"},
            {"say": "Tracking says Thursday.", "gesture": "nod"},
        ],
    },
    {
        "emotion": "confused",
        "segments": [
            {"say": "Wait, the tax return from 2023?", "gesture": "double_take"},
            {"say": "Let me think where you filed it.", "gesture": "look_up"},
        ],
    },
    {
        "emotion": "fond",
        "segments": [
            {"say": "I won't tell anyone about the third coffee.", "gesture": "wink"},
        ],
    },
    {
        "emotion": "happy",
        "segments": [
            {"say": "Oh, you're back.", "gesture": "perk_up"},
            {"say": "Did the pump table fix work?", "gesture": "tilt_head"},
        ],
    },
    {
        "emotion": "thinking",
        "segments": [
            {"say": "Give me a second with the flotation notes.", "gesture": "look_away"},
            {"say": "Found it. Tuesday's run.", "gesture": "nod"},
        ],
    },
    {
        "emotion": "concerned",
        "segments": [
            {"say": "That's the third failed build today.", "gesture": "lean_in"},
            {"say": "Want me to ask Claude to read the log?", "gesture": "tilt_head"},
        ],
    },
    {
        "emotion": "proud",
        "segments": [
            {"say": "Tests are green.", "gesture": "bounce"},
            {"say": "All twelve of them.", "gesture": "nod"},
        ],
    },
    {
        "emotion": "playful",
        "segments": [
            {"say": "You said that about the last coffee too.", "gesture": "shrug"},
            {"say": "Go on then.", "gesture": "wave"},
        ],
    },
    {
        "emotion": "tired",
        "segments": [
            {"say": "It's nearly midnight, Dan.", "gesture": "droop"},
            {"say": "Save and call it a night?", "gesture": "nod"},
        ],
    },
]


# What the brain sends when Dan asks the time or about the weather (kit.shows).
SHOW_SAMPLES = {
    "time": {"kind": "time", "text": "3:07", "small": "pm"},
    "date": {"kind": "date", "small": "FRI", "text": "9 OCT"},
    **{
        sky: {"kind": "weather", "sky": sky, "text": temp}
        for sky, temp in (
            ("sun", "31°"),
            ("part_cloud", "22°"),
            ("cloud", "17°"),
            ("rain", "14°"),
            ("storm", "24°"),
            ("snow", "-2°"),
            ("fog", "9°"),
            ("moon", "12°"),
        )
    },
}


class Performer:
    """Acts out a reply's cues on a face widget, and shows the words.

    The words build up in the caption as he says them (a long reply shows one
    sentence at a time) and stay up long enough to read once he's finished."""

    WHOLE_UP_TO = 220  # characters: longer replies show a sentence at a time

    def __init__(self, widget: FaceWidget, caption: QLabel) -> None:
        self.widget = widget
        self.caption = caption
        self._timers: list[QTimer] = []
        self._said: list[str] = []

    def perform(self, reply: dict) -> None:
        self.stop()
        self._said = []
        cues = plan_reply(reply)
        hold = cues[-1].at + 2.5
        for cue in cues:
            timer = QTimer(singleShot=True)
            timer.timeout.connect(lambda c=cue: self._run(c, hold))
            timer.start(int(cue.at * 1000))
            self._timers.append(timer)

    def stop(self) -> None:
        for t in self._timers:
            t.stop()
        self._timers.clear()

    @staticmethod
    def linger(text: str) -> float:
        """Seconds the words stay up after he's said them: time to read them."""
        return min(14.0, 4.0 + 0.05 * len(text))

    def _run(self, cue, hold: float) -> None:
        face, now = self.widget.face, time.monotonic()
        if cue.kind == "emotion":
            face.set_emotion(cue.value, now, hold_s=hold)
        elif cue.kind == "gesture":
            face.play(cue.value, now)
        elif cue.kind == "say":
            face.set_state("speaking")
            self._said.append(cue.value)
            whole = " ".join(self._said)
            self.caption.setText(whole if len(whole) <= self.WHOLE_UP_TO else cue.value)
            done = QTimer(singleShot=True)
            done.timeout.connect(lambda: face.set_state("idle"))
            done.start(int(cue.seconds * 1000))
            self._timers.append(done)
        elif cue.kind == "done":
            face.set_state("idle")
            clear = QTimer(singleShot=True)
            clear.timeout.connect(lambda: self.caption.setText(""))
            clear.start(int(self.linger(self.caption.text()) * 1000))
            self._timers.append(clear)


class FloatingFace(FaceWidget):
    """Frameless, see-through, always on top; drag it anywhere."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(180, 180)
        self._drag: QPoint | None = None

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._drag = None


def _buttons(title: str, names, action) -> QWidget:
    box = QWidget()
    grid = QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.addWidget(QLabel(f"<b>{title}</b>"), 0, 0, 1, 6)
    for i, name in enumerate(names):
        b = QPushButton(name)
        b.clicked.connect(lambda _=False, n=name: action(n))
        grid.addWidget(b, 1 + i // 6, i % 6)
    return box


def main() -> int:
    float_mode = "--float" in sys.argv
    app = QApplication(sys.argv)

    if float_mode:
        widget = FloatingFace()
    else:
        widget = FaceWidget()
        widget.background = QColor(207, 214, 222)
    caption = QLabel("")
    caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
    performer = Performer(widget, caption)
    samples = cycle(SAMPLES)

    panel = QWidget()
    panel.setWindowTitle("Kit face preview")
    layout = QVBoxLayout(panel)
    if not float_mode:
        widget.setMinimumSize(320, 320)
        layout.addWidget(widget, 1)
    layout.addWidget(caption)
    face = widget.face
    layout.addWidget(
        _buttons("Emotion", list(POSES), lambda n: face.set_emotion(n, time.monotonic(), hold_s=9))
    )
    layout.addWidget(
        _buttons(
            "Gesture", [g for g in CLIPS if g != "none"], lambda n: face.play(n, time.monotonic())
        )
    )
    layout.addWidget(_buttons("State", list(STATES), face.set_state))
    layout.addWidget(
        _buttons("Show", list(SHOW_SAMPLES), lambda n: widget.play_show(SHOW_SAMPLES[n]))
    )
    row = QHBoxLayout()
    say = QPushButton("Play a Kit reply")
    say.clicked.connect(lambda: performer.perform(next(samples)))
    row.addWidget(say)
    layout.addLayout(row)
    panel.resize(560, 720 if not float_mode else 320)
    panel.show()
    if float_mode:
        widget.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
