"""Actions: what each person is doing, from how they move over the last few seconds.

A single frame can show a raised hand, but not a wave: waving is the hand going
back and forth. So for every tracked person a short history of measurements
(head angles, jaw opening, wrist positions) is kept and searched for patterns:

    nodding         head pitch swings up and down
    shaking head    head yaw swings left and right
    waving          a raised wrist swings side to side
    talking         the jaw opens and closes repeatedly
    drinking        holding a cup, bottle or glass up at the face
    using a phone, typing, reading...   what their hands are on

These are hand-written rules on top of the models, so they cost nothing. Plain
Python: ``kit.eyes.scene`` feeds it, the tests drive it with made-up numbers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from kit.eyes.body import (
    LEFT_ELBOW,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ELBOW,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    Point,
)
from kit.eyes.faces import Face

MIDDLE_KNUCKLE, MIDDLE_TIP = 9, 12  # MediaPipe hand landmarks

DRINKS = {"cup", "bottle", "wine glass"}

# Holding one of these means the person is doing the matching activity.
OBJECT_ACTIONS = {
    "cell phone": "using a phone",
    "keyboard": "typing",
    "laptop": "using a laptop",
    "mouse": "using the mouse",
    "book": "reading",
    "remote": "using the remote",
}

ALL_ACTIONS = ["nodding", "shaking head", "waving", "talking", "drinking", *OBJECT_ACTIONS.values()]

Box = tuple[int, int, int, int]


@dataclass
class Sample:
    """What was measured about one person in one frame (None = not visible)."""

    t: float
    yaw: float | None = None
    pitch: float | None = None
    jaw: float | None = None
    # Wrist x position in shoulder-widths from the body's centre, but only while
    # the wrist is raised above the shoulder (otherwise missing).
    raised_wrist_x: dict[str, float] | None = None
    # Middle fingertip x in hand-lengths, per hand, while the fingers point up
    # (a hand held up, palm out). Catches a wave from the wrist, which the pose's
    # wrist point hardly sees.
    fingertip_x: dict[str, float] | None = None


def count_swings(values: list[float], min_move: float) -> int:
    """Count direction changes in a series, ignoring wiggles smaller than min_move.

    With min_move=5: 0, 6, 1, 7, 2 -> 3 swings (up, down, up, down). Noise like
    0, 1, 0, 2, 1 -> 0 swings. This hysteresis keeps tiny head jitters from
    looking like a nod.
    """
    swings, direction = 0, 0
    low = high = pivot = values[0]
    for v in values[1:]:
        if direction == 0:  # wait for the first real move, in either direction
            low, high = min(low, v), max(high, v)
            if high - low >= min_move:
                direction = 1 if v == high else -1
                pivot = v
        elif direction == 1:  # going up: track the peak until it drops far enough
            if v > pivot:
                pivot = v
            elif pivot - v >= min_move:
                swings, direction, pivot = swings + 1, -1, v
        else:  # going down
            if v < pivot:
                pivot = v
            elif v - pivot >= min_move:
                swings, direction, pivot = swings + 1, 1, v
    return swings


def value_range(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def overlaps(a: Box, b: Box) -> bool:
    """Do two boxes (x1, y1, x2, y2) overlap?"""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Held:
    """What an action detector needs to know about a held object."""

    label: str
    box: Box


class ActionDetector:
    def __init__(self, window: float = 2.0, min_samples: int = 8) -> None:
        """``window``: seconds of history to look at. ``min_samples``: frames needed
        in that window before movement-based actions are judged."""
        self.window = window
        self.min_samples = min_samples
        self.history: dict[int, deque[Sample]] = {}

    def update(
        self,
        pid: int,
        now: float,
        frame_size: tuple[int, int],
        face: Face | None = None,
        pose: list[Point] | None = None,
        held: Iterable = (),
        hands: Iterable = (),
    ) -> list[str]:
        """Record this frame for one person and return their current actions.
        ``held`` are the tracked objects (with ``label`` and ``box``) the person's
        hands are on."""
        sample = Sample(now)
        if face is not None:
            sample.yaw, sample.pitch, sample.jaw = face.yaw, face.pitch, face.jaw
        if pose is not None:
            sample.raised_wrist_x = self._raised_wrists(pose, frame_size)
        sample.fingertip_x = self._fingertips(list(hands), frame_size)

        history = self.history.setdefault(pid, deque())
        history.append(sample)
        while history and now - history[0].t > self.window:
            history.popleft()

        actions = self._movement_actions(history) if len(history) >= self.min_samples else []
        actions += self._object_actions(face, list(held))
        return actions

    def forget(self, keep_ids: Iterable[int]) -> None:
        """Drop the history of people who are no longer tracked."""
        keep = set(keep_ids)
        self.history = {pid: h for pid, h in self.history.items() if pid in keep}

    @staticmethod
    def _raised_wrists(pose: list[Point], frame_size: tuple[int, int]) -> dict[str, float] | None:
        w, _ = frame_size
        ls, rs = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
        if min(ls.visibility, rs.visibility) < 0.5:
            return None
        shoulder_width = abs(ls.x - rs.x) * w
        if shoulder_width < 1:
            return None
        centre_x = (ls.x + rs.x) / 2 * w
        raised = {}
        # A real wave happens up around head height. Hands at elbow height (typing,
        # gesturing while talking) caused false waves, so the wrist must be above the
        # shoulder (y grows downwards) and above its elbow.
        sides = (("left", LEFT_WRIST, LEFT_ELBOW, ls), ("right", RIGHT_WRIST, RIGHT_ELBOW, rs))
        for side, wrist, elbow, shoulder in sides:
            wr, el = pose[wrist], pose[elbow]
            if wr.visibility > 0.5 and wr.y < el.y and wr.y < shoulder.y:
                raised[side] = (wr.x * w - centre_x) / shoulder_width
        return raised

    @staticmethod
    def _fingertips(hands: list, frame_size: tuple[int, int]) -> dict[str, float] | None:
        w, h = frame_size
        tips = {}
        for hand in hands:
            pts = hand.points
            if len(pts) <= MIDDLE_TIP:
                continue
            wrist, knuckle, tip = pts[0], pts[MIDDLE_KNUCKLE], pts[MIDDLE_TIP]
            length = ((knuckle.x - wrist.x) * w) ** 2 + ((knuckle.y - wrist.y) * h) ** 2
            if length < 1 or tip.y >= wrist.y:  # too small, or fingers not pointing up
                continue
            tips[hand.side] = tip.x * w / length**0.5
        return tips or None

    @staticmethod
    def _movement_actions(history: deque[Sample]) -> list[str]:
        actions = []
        yaws = [s.yaw for s in history if s.yaw is not None]
        pitches = [s.pitch for s in history if s.pitch is not None]
        jaws = [s.jaw for s in history if s.jaw is not None]

        # Head: two or more swings of at least 6 degrees, mostly in one direction.
        if (
            len(pitches) >= 8
            and count_swings(pitches, 6) >= 2
            and value_range(pitches) > value_range(yaws)
        ):
            actions.append("nodding")
        elif (
            len(yaws) >= 8
            and count_swings(yaws, 8) >= 2
            and value_range(yaws) > value_range(pitches)
        ):
            actions.append("shaking head")

        # Waving: a raised wrist swinging at least 0.25 shoulder-widths, twice or more,
        # and raised for most of the window.
        for side in ("left", "right"):
            xs = [
                s.raised_wrist_x[side]
                for s in history
                if s.raised_wrist_x and side in s.raised_wrist_x
            ]
            if len(xs) >= 0.7 * len(history) and count_swings(xs, 0.25) >= 2:
                actions.append("waving")
                break
        else:
            # Or a hand held up with its fingertips swinging side to side, at least
            # half a hand-length, twice. The hand reader misses frames when a hand
            # moves fast, so it only needs to be seen in half the window.
            for side in ("left", "right"):
                tips = [
                    s.fingertip_x[side] for s in history if s.fingertip_x and side in s.fingertip_x
                ]
                if len(tips) >= max(6, 0.5 * len(history)) and count_swings(tips, 0.5) >= 2:
                    actions.append("waving")
                    break

        # Talking: the jaw opening and closing by 0.08+ at least 3 times.
        if len(jaws) >= 8 and count_swings(jaws, 0.08) >= 3:
            actions.append("talking")
        return actions

    @staticmethod
    def _object_actions(face: Face | None, held: list) -> list[str]:
        actions = []
        labels = {obj.label for obj in held}
        # Drinking = holding a drink that is up at the face, not just in a hand.
        if face is not None and any(
            obj.label in DRINKS and overlaps(obj.box, face.box) for obj in held
        ):
            actions.append("drinking")
        actions += [action for label, action in OBJECT_ACTIONS.items() if label in labels]
        return actions
