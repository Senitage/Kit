"""The scene: one up-to-date picture of what the camera sees, as plain data.

It takes the detector's people and objects (with track ids), the faces, hands
and poses, works out which face, hand and pose belongs to which person, keeps
a short history of events, and turns it all into the report the brain gets
(``Scene.report``) or a few lines of text (``describe``).

Plain Python, with no camera or model libraries: the tests drive it with
made-up detections. Boxes come in as pixels and go out as fractions of the
frame, so the brain never needs to know the frame size.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from kit.eyes.actions import ALL_ACTIONS, ActionDetector
from kit.eyes.body import Hand, Point, describe_pose
from kit.eyes.faces import Face

Box = tuple[int, int, int, int]
Detection = tuple[int, str, Box]  # track id, label, box in pixels

# Furniture and fittings: always there, and a detector loses and finds them as
# people move in front of them, so their comings and goings aren't news.
FIXTURES = {
    "chair",
    "couch",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "potted plant",
    "bench",
    "sink",
    "refrigerator",
    "oven",
    "microwave",
    "clock",
}

# Things a hand can rest on but not hold, so they never count as "holding".
NOT_HOLDABLE = {
    "chair",
    "couch",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "refrigerator",
    "oven",
    "sink",
    "bench",
    "car",
    "bus",
    "truck",
    "motorcycle",
    "bicycle",
    "potted plant",
}
# Detector classes that are pets or visitors rather than furniture.
ANIMALS = {"cat", "dog", "bird", "horse", "sheep", "cow"}


@dataclass
class Track:
    """Everything remembered about one tracked person or object."""

    id: int
    label: str
    box: Box
    first_seen: float
    last_seen: float
    frames_seen: int = 1
    confirmed: bool = False  # set once seen in enough frames to trust it

    def age(self, now: float) -> float:
        return now - self.first_seen


class TrackMemory:
    """Remembers tracked objects across frames and produces enter/leave events.

    ``confirm_frames``: an object must appear in this many frames before it's
    announced, so one-frame false detections don't create events.
    ``forget_after``: seconds out of view before it has left. Short gaps (someone
    walking behind a chair) don't count. ``visible_gap``: seconds since its last
    detection for a track to count as in view right now.
    """

    def __init__(
        self, confirm_frames: int = 5, forget_after: float = 3.0, visible_gap: float = 0.5
    ) -> None:
        self.confirm_frames = confirm_frames
        self.forget_after = forget_after
        self.visible_gap = visible_gap
        self.tracks: dict[int, Track] = {}

    def update(self, detections: Iterable[Detection], now: float) -> list[str]:
        """Feed one frame's detections. Returns the new event lines."""
        events = []
        for track_id, label, box in detections:
            track = self.tracks.get(track_id)
            if track is None:
                track = self.tracks[track_id] = Track(track_id, label, box, now, now)
            else:
                track.box = box
                track.last_seen = now
                track.frames_seen += 1
            if not track.confirmed and track.frames_seen >= self.confirm_frames:
                track.confirmed = True
                if label not in FIXTURES:
                    events.append(f"{label} #{track_id} entered")
        for track_id, track in list(self.tracks.items()):
            if now - track.last_seen > self.forget_after:
                if track.confirmed and track.label not in FIXTURES:
                    stayed = track.last_seen - track.first_seen
                    events.append(f"{track.label} #{track_id} left after {stayed:.0f}s")
                del self.tracks[track_id]
        return events

    def visible(self, now: float) -> list[Track]:
        """Confirmed tracks seen just now, oldest first."""
        current = [
            t for t in self.tracks.values() if t.confirmed and now - t.last_seen <= self.visible_gap
        ]
        return sorted(current, key=lambda t: t.first_seen)


class Stable:
    """Reports a value only after it stays the same for ``frames`` frames in a row,
    so one-frame flickers never become events."""

    def __init__(self, frames: int = 8) -> None:
        self.frames = frames
        self.candidate: object = None
        self.count = 0
        self.value: object = None

    def update(self, value):
        """The new value when it has just become steady and changed, else None."""
        if value == self.candidate:
            self.count += 1
        else:
            self.candidate, self.count = value, 1
        if self.count == self.frames and value != self.value:
            self.value = value
            return value
        return None


def area(box: Box) -> float:
    x1, y1, x2, y2 = box
    return (x2 - x1) * (y2 - y1)


def inside(point: tuple[float, float], box: Box, margin: float = 0.0) -> bool:
    """Is the point inside the box? ``margin`` grows the box by a fraction of its size."""
    x, y = point
    x1, y1, x2, y2 = box
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    return x1 - mx <= x <= x2 + mx and y1 - my <= y <= y2 + my


def owner(point: tuple[float, float], people: list[Track]) -> Track | None:
    """The person whose box contains the point. If boxes overlap, the smallest
    (usually the closest fit) wins. None if the point is outside every person."""
    containing = [p for p in people if inside(point, p.box)]
    return min(containing, key=lambda p: area(p.box), default=None)


def position_label(box: Box, frame_width: int) -> str:
    """Which third of the view the box centre is in."""
    centre = (box[0] + box[2]) / 2 / max(frame_width, 1)
    return "left" if centre < 1 / 3 else "right" if centre > 2 / 3 else "centre"


def fractions(box: Box, frame_size: tuple[int, int]) -> list[float]:
    w, h = max(frame_size[0], 1), max(frame_size[1], 1)
    x1, y1, x2, y2 = box
    return [round(x1 / w, 3), round(y1 / h, 3), round(x2 / w, 3), round(y2 / h, 3)]


def format_duration(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


class Scene:
    def __init__(
        self,
        forget_after: float = 3.0,
        confirm_frames: int = 5,
        stable_frames: int = 8,
        max_events: int = 20,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.memory = TrackMemory(confirm_frames=confirm_frames, forget_after=forget_after)
        self.stable_frames = stable_frames
        self.clock = clock
        self.events: deque[tuple[datetime, str]] = deque(maxlen=max_events)
        self._unsent: list[tuple[datetime, str]] = []  # events since the last report
        self.people: dict[int, dict] = {}  # track id -> what's known this frame
        self.stable: dict[tuple[int, str], Stable] = {}
        self.names: dict[int, str | None] = {}  # track id -> agreed name (kit.eyes.recognise)
        self.recognising = False  # kit.eyes.recognise knows some faces
        self.unknown: set[int] = set()  # people checked often enough to say Kit doesn't know them
        self.labels: dict[int, str] = {}
        self.actions = ActionDetector()
        self.frame_size = (1, 1)
        self.now = 0.0

    def update(
        self,
        now: float,
        frame_size: tuple[int, int],
        detections: Iterable[Detection],
        faces: Iterable[Face] = (),
        hands: Iterable[Hand] = (),
        poses: Iterable[list[Point]] = (),
    ) -> list[str]:
        """Feed in one frame of results. Returns the new event lines."""
        self.now, self.frame_size = now, frame_size
        w, h = frame_size
        events = self.memory.update(detections, now)

        visible = self.memory.visible(now)
        people = [t for t in visible if t.label == "person"]
        objects = [t for t in visible if t.label != "person"]
        self.people = {
            p.id: {
                "face": None,
                "expressions": [],
                "looking": None,
                "gestures": {},
                "pose_points": None,
                "pose": [],
                "held": {},
                "hands": [],
                "actions": [],
            }
            for p in people
        }

        # Faces: whoever's box contains the centre of the face.
        for face in faces:
            x1, y1, x2, y2 = face.box
            if person := owner(((x1 + x2) / 2, (y1 + y2) / 2), people):
                info = self.people[person.id]
                info.update(face=face, expressions=face.expressions, looking=face.looking)

        # Hands: whoever's box contains the wrist. A hand is "holding" an object if
        # several of its 21 points fall inside that object's box.
        for hand in hands:
            points = [(p.x * w, p.y * h) for p in hand.points]
            person = owner(points[0], people)  # point 0 = wrist
            if person is None:
                continue
            self.people[person.id]["hands"].append(hand)
            if hand.gesture:
                self.people[person.id]["gestures"][hand.side] = hand.gesture
            for obj in objects:
                if obj.label in NOT_HOLDABLE:
                    continue
                if sum(inside(p, obj.box, margin=0.1) for p in points) >= 5:
                    self.people[person.id]["held"][obj.id] = obj

        # Pose: whoever's box contains the nose.
        for points in poses:
            nose = (points[0].x * w, points[0].y * h)
            if person := owner(nose, people):
                self.people[person.id]["pose_points"] = points
                self.people[person.id]["pose"] = describe_pose(points)

        # Actions: patterns over the last couple of seconds (kit.eyes.actions).
        for pid, info in self.people.items():
            info["actions"] = self.actions.update(
                pid,
                now,
                frame_size,
                face=info["face"],
                pose=info["pose_points"],
                held=info["held"].values(),
                hands=info["hands"],
            )

        # Turn changes into events, once they've been steady for a few frames.
        for pid, info in self.people.items():
            if expressions := self._changed(pid, "expressions", tuple(info["expressions"])):
                events.append(f"person #{pid}: {', '.join(expressions)}")
            for side in ("left", "right"):
                if gesture := self._changed(pid, side, info["gestures"].get(side)):
                    events.append(f"person #{pid} {side} hand: {gesture}")
            if pose := self._changed(pid, "pose", tuple(info["pose"])):
                events.append(f"person #{pid}: {', '.join(pose)}")
            holding = tuple(sorted({obj.label for obj in info["held"].values()}))
            if holding := self._changed(pid, "holding", holding):
                events.append(f"person #{pid} is holding {', '.join(holding)}")
            for action in ALL_ACTIONS:  # one event when each action starts
                if self._changed(pid, action, action in info["actions"]):
                    events.append(f"person #{pid} is {action}")

        for track in visible:
            self.labels[track.id] = track.label
        events = [self._with_names(e) for e in events]

        # Forget the history of people and things that have left.
        alive = self.memory.tracks
        self.stable = {k: v for k, v in self.stable.items() if k[0] in alive}
        self.names = {k: v for k, v in self.names.items() if k in alive}
        self.unknown &= set(alive)
        self.labels = {k: v for k, v in self.labels.items() if k in alive}
        self.actions.forget(alive)

        stamp = self.clock()
        stamped = [(stamp, e) for e in events]
        self.events.extend(stamped)
        self._unsent.extend(stamped)
        return events

    def recognise(self, track_id: int, name: str) -> None:
        """``kit.eyes.recognise`` has agreed who this person is."""
        self.names[track_id] = name
        self.unknown.discard(track_id)
        self.labels.setdefault(track_id, "person")
        stamped = (self.clock(), f"recognised {name} (#{track_id})")
        self.events.append(stamped)
        self._unsent.append(stamped)

    def name_of(self, track_id: int) -> str | None:
        """The recognised name for a track, or None."""
        return self.names.get(track_id)

    def _with_names(self, event: str) -> str:
        """Names in events: "person #1 waved" becomes "Dan (#1) waved", and "cat #5 left"
        becomes "Milo the cat (#5) left"."""
        for tid, name in self.names.items():
            if name:
                label = self.labels.get(tid, "person")
                display = (
                    f"{name} (#{tid})" if label == "person" else f"{name} the {label} (#{tid})"
                )
                event = re.sub(rf"\b{re.escape(label)} #{tid}\b", display, event)
        return event

    def _changed(self, pid: int, topic: str, value):
        """The value when it has just become steady and is non-empty."""
        stable = self.stable.setdefault((pid, topic), Stable(frames=self.stable_frames))
        return stable.update(value)

    def in_view(self) -> list[Track]:
        return self.memory.visible(self.now)

    def report(self, camera: str = "desk", mirrored: bool = True, fps: float | None = None) -> dict:
        """What the brain receives: the scene as plain data, boxes as fractions of
        the frame, and the events since the last report."""
        size = self.frame_size
        w, _ = size
        people, objects = [], []
        for track in self.memory.visible(self.now):
            entry = {
                "id": track.id,
                "label": track.label,
                "name": self.names.get(track.id),
                "position": position_label(track.box, w),
                "seen_for_s": round(track.age(self.now)),
                "box": fractions(track.box, size),
            }
            if track.label == "person":
                info = self.people.get(track.id, {})
                face = info.get("face")
                entry["face"] = fractions(face.box, size) if face is not None else None
                entry["looking"] = info.get("looking") or ""
                entry["expressions"] = list(info.get("expressions", []))
                entry["gestures"] = dict(info.get("gestures", {}))
                entry["pose"] = list(info.get("pose", []))
                entry["holding"] = sorted({obj.label for obj in info.get("held", {}).values()})
                entry["actions"] = list(info.get("actions", []))
                entry["unknown"] = track.id in self.unknown
                people.append(entry)
            else:
                objects.append(entry)
        events = [{"at": t.isoformat(timespec="seconds"), "event": e} for t, e in self._unsent]
        self._unsent = []
        return {
            "camera": camera,
            "mirrored": mirrored,
            "frame_size": list(size),
            "fps": round(fps, 1) if fps else None,
            "recognising": self.recognising,
            "people": people,
            "objects": objects,
            "events": events,
        }


def describe(report: dict, max_events: int = 5) -> list[str]:
    """A report as short lines of plain English, for the preview and ``kit eyes``."""
    lines = []
    for p in report["people"]:
        details = [p["position"], f"in view {format_duration(p['seen_for_s'])}"]
        if p.get("face"):
            details += [p.get("looking") or "", *p.get("expressions", [])]
        else:
            details.append("face not visible")
        details += [f"{side} hand: {g}" for side, g in p.get("gestures", {}).items()]
        details += p.get("actions", []) + p.get("pose", [])
        if p.get("holding"):
            details.append("holding " + ", ".join(p["holding"]))
        who = f"{p['name']} (#{p['id']})" if p.get("name") else f"Person #{p['id']}"
        if p.get("unknown"):
            who += " (not anyone Kit knows)"
        lines.append(f"{who}: " + "; ".join(d for d in details if d))
    for o in report["objects"]:
        who = (
            f"{o['name']} the {o['label']} (#{o['id']})"
            if o.get("name")
            else f"{o['label'].capitalize()} #{o['id']}"
        )
        lines.append(f"{who}: {o['position']}, in view {format_duration(o['seen_for_s'])}")
    if not lines:
        lines.append("Nothing in view.")
    events = report.get("events", [])[-max_events:] if max_events else []
    if events:
        lines.append("Recent: " + "; ".join(f"{e['at'][11:19]} {e['event']}" for e in events))
    return lines
