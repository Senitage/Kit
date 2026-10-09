"""The Mood page of Kit's window: how Kit is, at a glance, like a Sims needs panel.

His face as he is now, with a little mood gem over his head, the word for his
mood, what he's feeling and why, and bars for his needs and mood dials. It's a
window onto ``kit.life`` on the brain (``GET /api/life``) and nothing more: the
bars move by themselves as his day goes, and nothing here can set them.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kit.desk import theme
from kit.desk.client import BrainClient
from kit.desk.glow import FaceWidget

REFRESH_MS = 4000

# The Sims colours: red when a need is low, amber in the middle, green when full.
LOW, MIDDLE, FULL = QColor("#e5534b"), QColor("#e8a33d"), QColor("#4cc35a")

MOODS = {
    "content": ("Content", "happy"),
    "curious": ("Curious", "curious"),
    "bored": ("Bored", "tired"),
    "lonely": ("Lonely", "sad"),
    "sleepy": ("Sleepy", "tired"),
    "sulky": ("Sulking", "grumpy"),
    "asleep": ("Asleep", "neutral"),
}
# How each feeling (kit.life.FEELING_KINDS) shows on his face here.
FEELING_FACES = {
    "chuffed": "happy",
    "warm": "fond",
    "proud": "proud",
    "pleased": "happy",
    "excited": "excited",
    "amused": "playful",
    "worried": "concerned",
    "sympathetic": "concerned",
    "sad": "sad",
    "put_out": "grumpy",
    "hurt": "sad",
    "glad": "happy",
    "missing": "sad",
    "miffed": "grumpy",
}
PRESENCE = {
    "here": "Here with you",
    "away": "Waiting for you to come back",
    "alone": "Keeping himself busy",
    "asleep": "Fast asleep",
}


def blend(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def need_colour(value: float) -> QColor:
    """Red to amber to green as a need fills."""
    if value < 0.5:
        return blend(LOW, MIDDLE, value / 0.5)
    return blend(MIDDLE, FULL, (value - 0.5) / 0.5)


def needs(life: dict) -> list[tuple[str, float, bool, str]]:
    """(name, 0..1, whether full is good, a few words) for each bar, from /api/life.
    Full is good for a need (energy, fun, company, happiness); liveliness and
    curiosity are just how he is, so they're drawn in the accent colour."""
    d = life.get("drives") or {}
    energy = float(life.get("energy", d.get("energy", 1.0)))
    rows = [
        ("Energy", energy, True, _words(energy, "worn out", "flagging", "fine", "full of beans")),
        (
            "Fun",
            1 - float(d.get("boredom", 0.0)),
            True,
            _words(
                1 - float(d.get("boredom", 0.0)), "bored stiff", "a bit bored", "fine", "having fun"
            ),
        ),
        (
            "Company",
            1 - float(d.get("social", 0.0)),
            True,
            _words(
                1 - float(d.get("social", 0.0)), "lonely", "missing you", "fine", "good company"
            ),
        ),
    ]
    dials = life.get("dials")
    if dials:
        happy = (float(dials.get("valence", 0.0)) + 1) / 2
        lively = float(dials.get("arousal", 0.5))
        rows.append(("Happiness", happy, True, _words(happy, "low", "a bit flat", "okay", "happy")))
        rows.append(
            ("Liveliness", lively, False, _words(lively, "very calm", "calm", "lively", "buzzing"))
        )
    curious = float(d.get("curiosity", 0.0))
    rows.append(
        (
            "Curiosity",
            curious,
            False,
            _words(curious, "settled", "a little", "curious", "itching to know"),
        )
    )
    return rows


def _words(value: float, *steps: str) -> str:
    return steps[min(len(steps) - 1, int(value * len(steps)))]


def overall(life: dict) -> float:
    """How he is overall (0..1): the average of the needs where full is good."""
    good = [v for _, v, full_good, _ in needs(life) if full_good]
    return sum(good) / len(good) if good else 0.5


class NeedBar(QWidget):
    """One need: its name, a rounded bar that glides to new values, and its words."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.value = 0.0  # what's drawn, easing toward ``target``
        self.target = 0.0
        self.good_when_full = True
        self.words = ""
        self.palette_ = theme.palette()
        self.setMinimumHeight(46)
        self._ease = QTimer(self)
        self._ease.timeout.connect(self._step)

    def set(self, value: float, good_when_full: bool, words: str) -> None:
        self.target = max(0.0, min(1.0, value))
        self.good_when_full = good_when_full
        self.words = words
        self.setToolTip(f"{self.name}: {words} ({round(self.target * 100)}%)")
        if not self.isVisible():
            self.value = self.target
        self._ease.start(16)

    def _step(self) -> None:
        self.value += (self.target - self.value) * 0.12
        if abs(self.target - self.value) < 0.002:
            self.value = self.target
            self._ease.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette_
        w, h = self.width(), self.height()
        p.setPen(QColor(pal.text))
        font = p.font()
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(0, 0, w * 0.6, 18), Qt.AlignmentFlag.AlignLeft, self.name)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor(pal.muted))
        p.drawText(QRectF(w * 0.4, 0, w * 0.6, 18), Qt.AlignmentFlag.AlignRight, self.words)
        track = QRectF(0, 24, w, h - 30)
        r = track.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal.line))
        p.drawRoundedRect(track, r, r)
        fill = need_colour(self.value) if self.good_when_full else QColor(pal.accent)
        if self.value > 0.01:
            bar = QRectF(
                track.x(),
                track.y(),
                max(track.height(), track.width() * self.value),
                track.height(),
            )
            p.setBrush(fill)
            p.drawRoundedRect(bar, r, r)
            shine = QColor(255, 255, 255, 50)  # a little gloss along the top
            p.setBrush(shine)
            p.drawRoundedRect(
                bar.adjusted(r * 0.6, 2, -r * 0.6, -track.height() * 0.55), r / 2, r / 2
            )
        p.end()


class MoodGem(QWidget):
    """The mood gem over his head, as in The Sims: green when he's doing well,
    through amber to red when he isn't. It turns and bobs."""

    def __init__(self) -> None:
        super().__init__()
        self.level = 0.75
        self.setFixedSize(40, 58)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        now = time.monotonic()
        turn = math.cos(now * 1.6)  # -1..1: how much of the front face shows
        bob = math.sin(now * 2.2) * 3
        colour = need_colour(self.level)
        cx, top, mid, bottom = self.width() / 2, 5 + bob, 20 + bob, 52 + bob
        half = 13 * max(0.25, abs(turn))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gem = QPainterPath(QPointF(cx, top))
        gem.lineTo(cx + half, mid)
        gem.lineTo(cx, bottom)
        gem.lineTo(cx - half, mid)
        gem.closeSubpath()
        p.setPen(QPen(colour.darker(150), 1.2))
        p.setBrush(colour)
        p.drawPath(gem)
        facet = QPainterPath(QPointF(cx, top))  # the lit side
        facet.lineTo(cx + half * turn, mid)
        facet.lineTo(cx, bottom)
        facet.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour.lighter(135))
        p.drawPath(facet)
        p.end()


class MoodPage(QWidget):
    """Kit's mood and needs, refreshed every few seconds while it's open."""

    def __init__(
        self,
        client: Callable[[], BrainClient | None],
        background: Callable[[Callable[[], object], Callable[[object], None]], None],
    ) -> None:
        super().__init__()
        self.client = client
        self.background = background
        self.life: dict | None = None
        self._palette = theme.palette()

        inner = QWidget()
        inner.setObjectName("scrollBody")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        title = QLabel("Mood")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("How Kit is right now. These move by themselves as his day goes.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        top = QHBoxLayout()
        head = QVBoxLayout()
        head.setSpacing(0)
        self.gem = MoodGem()
        head.addWidget(self.gem, 0, Qt.AlignmentFlag.AlignHCenter)
        self.face = FaceWidget()
        self.face.setFixedSize(150, 150)
        self.face.follow_mouse = False
        head.addWidget(self.face)
        top.addLayout(head)
        words = QVBoxLayout()
        words.addStretch(1)
        self.mood = QLabel("...")
        self.mood.setObjectName("title")
        self.presence = QLabel("")
        self.feeling = QLabel("")
        self.feeling.setWordWrap(True)
        self.closeness = QLabel("")
        self.closeness.setObjectName("muted")
        for label in (self.mood, self.presence, self.feeling, self.closeness):
            words.addWidget(label)
        words.addStretch(1)
        top.addLayout(words, 1)
        layout.addLayout(top)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(28)
        self.grid.setVerticalSpacing(10)
        self.bars: dict[str, NeedBar] = {}
        layout.addLayout(self.grid)
        self.mind = QLabel("")
        self.mind.setWordWrap(True)
        self.mind.setObjectName("muted")
        layout.addWidget(self.mind)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        layout.addWidget(self.note)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def apply_look(self, palette: theme.Palette, eye: str | None = None) -> None:
        self._palette = palette
        for bar in self.bars.values():
            bar.palette_ = palette
            bar.update()
        if eye:
            self.face.eye = QColor(eye)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().showEvent(event)
        self.timer.start(REFRESH_MS)

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt's name)
        super().hideEvent(event)
        self.timer.stop()

    def refresh(self) -> None:
        client = self.client()
        if client is None:
            self.note.setText("Kit isn't set up yet: fill in This PC first.")
            return
        self.background(client.life, self.show_life)

    def show_life(self, life) -> None:
        if isinstance(life, Exception):
            self.note.setText(f"Can't reach Kit: {life}")
            self.face.face.set_state("offline")
            return
        self.note.setText("")
        self.life = life
        mood = str(life.get("mood") or "content")
        word, emotion = MOODS.get(mood, (mood.capitalize(), "neutral"))
        self.mood.setText(word)
        presence = str(life.get("presence") or "here")
        line = PRESENCE.get(presence, presence)
        if life.get("doing"):
            line += f": {life['doing']}"
        self.presence.setText(line)
        felt = life.get("feeling")
        if felt:
            name = str(felt.get("name", "")).replace("_", " ")
            why = str(felt.get("why") or "")
            self.feeling.setText(f"Feeling {name}" + (f", because {why}" if why else ""))
            emotion = FEELING_FACES.get(str(felt.get("name")), emotion)
        else:
            self.feeling.setText("Nothing much on his mind.")
        self.closeness.setText(f"You two: {life['closeness']}" if life.get("closeness") else "")
        emotion = str(life.get("face") or emotion)  # the brain's say, as the desk face shows

        face, now = self.face.face, time.monotonic()
        face.set_state("sleeping" if mood == "asleep" else "idle")
        face.set_emotion(emotion, now)
        dials = life.get("dials")
        if dials:
            face.set_dials(float(dials.get("arousal", 0.5)), float(dials.get("valence", 0.0)))
        self.gem.level = overall(life)

        rows = needs(life)
        shown = {name for name, *_ in rows}
        for name in list(self.bars):
            if name not in shown:  # the dials were turned off
                self.bars.pop(name).deleteLater()
        for i, (name, value, good, words) in enumerate(rows):
            bar = self.bars.get(name)
            if bar is None:
                bar = self.bars[name] = NeedBar(name)
                bar.palette_ = self._palette
            self.grid.addWidget(bar, i // 2, i % 2)
            bar.set(value, good, words)
        thinking = life.get("thinking")
        wants = life.get("wants") or []
        mind = []
        if thinking:
            mind.append(f"On his mind: {thinking}")
        if wants:
            mind.append(
                f"Wants to tell you about {len(wants)} thing{'s' if len(wants) > 1 else ''}."
            )
        self.mind.setText("\n".join(mind))
