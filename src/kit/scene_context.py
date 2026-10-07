"""What Kit sees through his eyes (kit.eyes), as the brain keeps it.

The eyes run beside a camera and send a small report about once a second: who
and what is in view (as boxes, positions, expressions, gestures, actions),
what has just happened, and never a picture. This module keeps the latest
report and the day's comings and goings, writes the one-line "right now" for
every prompt, answers the ``look_around`` action with the full picture, and
tells ``kit.life`` what just happened (someone arrived, someone left, the cat
wandered in) so Kit can greet, wake up or have a thought about it.

Kit can't tell faces apart yet (that's stage 2), so for now it's "someone at
the desk". Plain Python with no camera libraries, like ``kit.pc_context``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

SEEN = "seen"  # knowledge source: arrivals and sightings worth remembering
STALE_AFTER = timedelta(seconds=30)  # the eyes report every second or so
KEEP_FOR = timedelta(hours=16)
SHORT_GAP = timedelta(minutes=2)  # ducking out of view this briefly isn't leaving
REMEMBER_AWAY_AFTER = timedelta(minutes=30)  # an arrival after this long goes in memory
ANIMAL_AGAIN_AFTER = timedelta(minutes=30)  # the cat is news again after this long away
MAX_EVENTS = 60
ANIMALS = {"cat", "dog", "bird", "horse", "sheep", "cow"}
MAX_PEOPLE = 20


def _box() -> list[float]:
    return [0.0, 0.0, 0.0, 0.0]


class SeenPerson(BaseModel):
    id: int
    label: str = Field("person", max_length=50)
    name: str | None = Field(None, max_length=100)
    position: str = Field("", max_length=20)
    seen_for_s: float = 0.0
    box: list[float] = Field(default_factory=_box, min_length=4, max_length=4)
    face: list[float] | None = Field(None, min_length=4, max_length=4)
    looking: str = Field("", max_length=100)
    expressions: list[str] = Field(default_factory=list, max_length=10)
    gestures: dict[str, str] = Field(default_factory=dict)
    pose: list[str] = Field(default_factory=list, max_length=10)
    holding: list[str] = Field(default_factory=list, max_length=10)
    actions: list[str] = Field(default_factory=list, max_length=20)


class SeenObject(BaseModel):
    id: int
    label: str = Field(max_length=50)
    name: str | None = Field(None, max_length=100)
    position: str = Field("", max_length=20)
    seen_for_s: float = 0.0
    box: list[float] = Field(default_factory=_box, min_length=4, max_length=4)


class SceneEvent(BaseModel):
    at: str = Field("", max_length=40)
    event: str = Field(max_length=300)


class SceneReport(BaseModel):
    """One report from the eyes. ``off`` means the eyes are running but paused
    (the camera is released), so nothing is in view by choice."""

    camera: str = Field("desk", max_length=50)
    mirrored: bool = True
    off: bool = False
    frame_size: list[int] = Field(default_factory=lambda: [0, 0], max_length=2)
    fps: float | None = None
    people: list[SeenPerson] = Field(default_factory=list, max_length=MAX_PEOPLE)
    objects: list[SeenObject] = Field(default_factory=list, max_length=50)
    events: list[SceneEvent] = Field(default_factory=list, max_length=100)


@dataclass
class Visit:
    """A stretch of time with someone (anyone) in view."""

    start: datetime
    end: datetime
    open: bool = True  # still going
    people: int = 1  # the most people seen at once


@dataclass
class Happening:
    """Something the scene just told the brain, for Kit's life and memory."""

    kind: str  # "arrived", "left" or "animal"
    text: str  # a line for Kit's thoughts
    away_s: float = 0.0  # arrived: how long nobody was there before
    remember: bool = False  # worth keeping in the `seen` source


def _mins(minutes: float) -> str:
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return f"{round(minutes)} min"
    return f"{minutes / 60:.1f} h"


def _a(label: str) -> str:
    return ("an " if label[:1] in "aeiou" else "a ") + label


def _person_bits(p: SeenPerson, since: datetime | None, now: datetime) -> list[str]:
    bits = [p.position]
    if since is not None:
        bits.append(f"here {_mins((now - since).total_seconds() / 60)}")
    if p.face is not None:
        bits += [p.looking, *p.expressions]
    else:
        bits.append("face turned away or hidden")
    bits += [f"{side} hand: {g}" for side, g in p.gestures.items()]
    bits += p.actions
    bits += [f for f in p.pose if f not in p.actions]
    if p.holding:
        bits.append("holding " + ", ".join(p.holding))
    return [b for b in bits if b]


class SceneContext:
    """The latest report from the eyes, and today's comings and goings."""

    def __init__(self, clock: Callable[[], datetime] = datetime.now) -> None:
        self.clock = clock
        self.latest: SceneReport | None = None
        self.seen: datetime | None = None  # when the eyes last reported
        self.visits: list[Visit] = []
        self.events: deque[tuple[datetime, str]] = deque(maxlen=MAX_EVENTS)
        self._empty_since: datetime | None = None  # nobody in view since
        self._animals: dict[str, datetime] = {}  # when each animal was last in view

    def update(self, report: SceneReport) -> list[Happening]:
        """Take a report. Returns what just happened, if anything."""
        now = self.clock()
        self.latest, self.seen = report, now
        self.visits = [v for v in self.visits if now - v.end <= KEEP_FOR]
        if report.off:
            self._close_visit(now)
            self._empty_since = self._empty_since or now
            return []
        for e in report.events:
            self.events.append((now, e.event))
        happenings: list[Happening] = []
        last = self.visits[-1] if self.visits else None
        if report.people:
            if last and last.open:
                last.end = now
            elif last and now - last.end < SHORT_GAP:
                last.end, last.open = now, True  # ducked out of view for a moment
            else:
                gone_since = last.end if last else self._empty_since
                away = (now - gone_since).total_seconds() if gone_since else 0.0
                self.visits.append(Visit(now, now))
                last = self.visits[-1]
                happenings.append(self._arrival(now, away))
            last.people = max(last.people, len(report.people))
            self._empty_since = None
        else:
            left = self._close_visit(now)
            if left is not None:
                happenings.append(left)
            self._empty_since = self._empty_since or now
        for obj in report.objects:
            if obj.label not in ANIMALS:
                continue
            before = self._animals.get(obj.label)
            self._animals[obj.label] = now
            if before is None or now - before >= ANIMAL_AGAIN_AFTER:
                who = f"{obj.name} the {obj.label}" if obj.name else _a(obj.label)
                where = f" ({obj.position})" if obj.position else ""
                text = f"{who.capitalize()} just wandered into view{where}."
                happenings.append(Happening("animal", text, remember=True))
        return happenings

    def _arrival(self, now: datetime, away_s: float) -> Happening:
        if away_s <= 0:
            text = "Someone is at the desk (the first your eyes have seen today)."
            return Happening("arrived", text)
        gone = _mins(away_s / 60)
        text = f"Someone just sat down at the desk after {gone} with nobody there."
        remember = away_s >= REMEMBER_AWAY_AFTER.total_seconds()
        return Happening("arrived", text, away_s=away_s, remember=remember)

    def _close_visit(self, now: datetime) -> Happening | None:
        last = self.visits[-1] if self.visits else None
        if last is None or not last.open:
            return None
        last.open = False
        stayed = _mins((last.end - last.start).total_seconds() / 60)
        return Happening("left", f"The desk is empty: whoever was there left after {stayed}.")

    # What Kit is told

    def online(self) -> bool:
        return self.seen is not None and self.clock() - self.seen <= STALE_AFTER

    def in_view(self) -> bool:
        """Someone is in view right now."""
        return bool(self.online() and self.latest and not self.latest.off and self.latest.people)

    def empty_for_s(self) -> float | None:
        """How long nobody has been in view, or None while someone is."""
        if self._empty_since is None:
            return None
        return (self.clock() - self._empty_since).total_seconds()

    def since(self) -> datetime | None:
        """When the current visit began, if someone is in view."""
        last = self.visits[-1] if self.visits else None
        return last.start if last and last.open else None

    def look(self) -> tuple[float, float] | None:
        """Where a body should look to face the first person, -1..1 each way from
        the centre (x to the viewer's right, y down), or None."""
        if not self.in_view():
            return None
        p = self.latest.people[0]
        if p.face is not None:
            x1, y1, x2, y2 = p.face
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        else:
            x1, y1, x2, y2 = p.box
            cx, cy = (x1 + x2) / 2, y1 + 0.15 * (y2 - y1)  # about head height
        x = (cx - 0.5) * 2
        if not self.latest.mirrored:
            x = -x  # a camera facing you: your left is the picture's right
        return round(max(-1.0, min(1.0, x)), 2), round(max(-1.0, min(1.0, (cy - 0.5) * 2)), 2)

    def now_line(self, owner: str) -> str:
        """One line for every prompt; empty if the eyes have never reported."""
        r = self.latest
        if r is None or self.seen is None:
            return ""
        camera = f"the {r.camera} camera"
        if not self.online():
            return f"Your eyes ({camera}) stopped reporting at {self.seen:%I:%M %p}."
        if r.off:
            return f"{owner} has switched your eyes off, so you can't see the desk right now."
        now = self.clock()
        if not r.people:
            line = f"Through {camera}: nobody at the desk"
            last = self.visits[-1] if self.visits else None
            if last and not last.open:
                line += f"; someone left {_mins((now - last.end).total_seconds() / 60)} ago"
            line += "."
        else:
            since = self.since()
            seen = [
                f"{p.name} ({', '.join(_person_bits(p, since, now))})"
                if p.name
                else ", ".join(_person_bits(p, since, now))
                for p in r.people
            ]
            if len(r.people) == 1 and not r.people[0].name:
                line = f"Through {camera}: one person at the desk ({seen[0]})."
                line += f" You can't tell who yet; at {owner}'s desk it's most likely {owner}."
            else:
                count = {2: "two", 3: "three"}.get(len(r.people), str(len(r.people)))
                line = f"Through {camera}: {count} people at the desk: " + "; ".join(seen) + "."
        if r.objects:
            things = ", ".join(
                f"{o.name} the {o.label}" if o.name else f"{_a(o.label)} ({o.position})"
                for o in r.objects[:6]
            )
            line += f" Also in view: {things}."
        return line

    def detail(self, owner: str) -> str:
        """The full picture, for the look_around action."""
        r = self.latest
        if r is None or self.seen is None:
            return (
                f"Your eyes aren't running ({owner} hasn't started `kit eyes`), so you can't see."
            )
        now = self.clock()
        lines = [f"What you can see through the {r.camera} camera, as of {self.seen:%I:%M %p}:"]
        if not self.online():
            lines.append("The eyes have stopped reporting, so this is out of date.")
        if r.off:
            lines.append(
                f"{owner} has switched your eyes off: the camera is released, nothing is seen."
            )
            return "\n".join(lines + self._today(now))
        since = self.since()
        for p in r.people:
            who = f"{p.name} (#{p.id})" if p.name else f"Person #{p.id}"
            lines.append(f"- {who}: " + "; ".join(_person_bits(p, since, now)) + ".")
        for o in r.objects:
            who = (
                f"{o.name} the {o.label} (#{o.id})" if o.name else f"{o.label.capitalize()} #{o.id}"
            )
            lines.append(f"- {who}: {o.position}, in view {_mins(o.seen_for_s / 60)}.")
        if not r.people and not r.objects:
            lines.append("Nothing in view: the desk is empty.")
        recent = [(t, e) for t, e in self.events if now - t <= timedelta(minutes=10)][-10:]
        if recent:
            lines.append(
                "In the last ten minutes: " + "; ".join(f"{t:%H:%M} {e}" for t, e in recent) + "."
            )
        lines += self._today(now)
        if any(not p.name for p in r.people):
            lines.append(
                f"You can't tell faces apart yet, so you don't know who this is; at {owner}'s "
                f"desk it's most likely {owner}."
            )
        side = "left in the picture is their left" if r.mirrored else "the picture isn't mirrored"
        lines.append(f"Positions are as seen from the camera ({side}).")
        return "\n".join(lines)

    def _today(self, now: datetime) -> list[str]:
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today = [v for v in self.visits if v.end >= start_of_day]
        if not today:
            return []
        spans = []
        for v in today:
            end = "still here" if v.open else f"to {v.end:%I:%M %p}"
            who = "someone" if v.people == 1 else f"{v.people} people"
            spans.append(f"{who} from {v.start:%I:%M %p} {end}")
        return ["At the desk today: " + "; ".join(spans) + "."]

    def as_dict(self, owner: str) -> dict:
        return {
            "seen": self.seen.isoformat() if self.seen else None,
            "online": self.online(),
            "in_view": self.in_view(),
            "report": self.latest.model_dump() if self.latest else None,
            "look": self.look(),
            "line": self.now_line(owner),
            "detail": self.detail(owner),
            "today": self._today(self.clock()),
        }
