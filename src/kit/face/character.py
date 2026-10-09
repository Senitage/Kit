"""Kit's character sheet: the one file that says how he looks and moves.

``character.json`` (next to this module) holds his look (colours and the sizes of
his screen, eyes, glow and blush), a pose for every emotion, how each state
bends that pose, and every gesture as a set of moves. The rig and the Glow
painter read it here; the brain serves the same file at ``/api/face`` so the
desk app, home_app and the robot screens all draw the same Kit. Redesigning
him is an edit to that file, not to each app.

A gesture move is a list of terms per channel. Each term is an amount times a
product of shapes over the clip's time ``t`` (0..1)::

    "dy": [[0.035, ["bump", 0.05, 0.4]], [0.025, ["bump", 0.45, 0.8]]]

Shapes: ``bump a b [cap]`` a smooth hump between a and b (times cap, capped at
1); ``hold rise fall`` ease in, hold, ease out; ``sin k`` sin(pi k t);
``abs_sin k``; ``line a b`` a + b t; ``jolt at`` a fast rise to ``at`` then a
slow ease back. Channels ``sx``, ``sy`` and ``scale`` start at 1, the rest at 0.
"""

from __future__ import annotations

import functools
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources

POSE_KEYS = (
    "open",
    "squint",
    "tilt",
    "asym",
    "size",
    "look_x",
    "look_y",
    "blush",
    "head_tilt",
    "head_y",
)
CHANNELS = (
    "dx",
    "dy",
    "rot",
    "sx",
    "sy",
    "scale",
    "look_x",
    "look_y",
    "open",
    "squint",
    "size",
    "wink",
)
ONE_BASED = ("sx", "sy", "scale")
# Each shape's name and how many numbers it takes (fewest, most).
SHAPES = {
    "bump": (2, 3),
    "hold": (2, 2),
    "sin": (1, 1),
    "abs_sin": (1, 1),
    "line": (2, 2),
    "jolt": (1, 1),
}
LOOK_KEYS = ("colours", "neck", "screen", "eyes", "glow", "blush")


class CharacterError(ValueError):
    """The character sheet is missing something or has a value Kit can't use."""


def _ease(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def _shape(t: float, shape: list) -> float:
    name, *args = shape
    if name == "bump":
        a, b = args[0], args[1]
        v = 0.0 if t < a or t > b else math.sin(math.pi * (t - a) / (b - a))
        return min(1.0, v * args[2]) if len(args) > 2 else v
    if name == "hold":
        rise, fall = args
        if t < rise:
            return _ease(t / rise)
        if t > fall:
            return 1 - _ease((t - fall) / (1 - fall))
        return 1.0
    if name == "sin":
        return math.sin(math.pi * args[0] * t)
    if name == "abs_sin":
        return abs(math.sin(math.pi * args[0] * t))
    if name == "line":
        return args[0] + args[1] * t
    at = args[0]  # jolt
    return t / at if t < at else 1 - _ease((t - at) / (1 - at))


def move_at(moves: Mapping[str, list], t: float) -> dict[str, float]:
    """Every channel's value for a gesture's ``moves`` at time ``t`` (0..1)."""
    out = {c: 1.0 if c in ONE_BASED else 0.0 for c in CHANNELS}
    for channel, terms in moves.items():
        for amount, *shapes in terms:
            v = amount
            for shape in shapes:
                v *= _shape(t, shape)
            out[channel] += v
    return out


@dataclass(frozen=True)
class Character:
    """A loaded, checked character sheet. ``sheet`` is the file as it was read."""

    sheet: dict

    @property
    def name(self) -> str:
        return self.sheet["name"]

    @property
    def look(self) -> dict:
        return self.sheet["look"]

    def pose(self, emotion: str) -> dict[str, float]:
        """An emotion's pose with every key filled in from the defaults."""
        return {**self.sheet["pose_default"], **self.sheet["poses"][emotion]}

    @property
    def emotions(self) -> list[str]:
        return list(self.sheet["poses"])

    @property
    def gestures(self) -> list[str]:
        return list(self.sheet["gestures"])

    def gesture_seconds(self, gesture: str) -> float:
        return float(self.sheet["gestures"][gesture]["seconds"])

    def gesture_at(self, gesture: str, t: float) -> dict[str, float]:
        return move_at(self.sheet["gestures"][gesture]["moves"], t)

    def state_pose(self, state: str, emotion: str, pose: dict[str, float]) -> dict[str, float]:
        """``pose`` (the emotion's) as ``state`` bends it: asleep, offline, listening..."""
        rule = self.sheet["states"].get(state)
        if not rule:
            return pose
        if "pose" in rule:
            only = rule.get("only_from")
            if only is not None and emotion != only:
                return pose
            pose = self.pose(rule["pose"])
        pose = dict(pose)
        for k, v in rule.get("add", {}).items():
            pose[k] += v
        pose.update(rule.get("set", {}))
        return pose

    def state_glow(self, state: str) -> float:
        return float(self.sheet["states"].get(state, {}).get("glow", 1.0))


def check(sheet: Mapping) -> list[str]:
    """Everything wrong with a character sheet, in words; empty when it's fine."""
    problems: list[str] = []
    for key in ("name", "look", "pose_default", "poses", "states", "gestures"):
        if key not in sheet:
            problems.append(f"missing {key!r}")
    if problems:
        return problems
    look = sheet["look"]
    problems += [f"look is missing {k!r}" for k in LOOK_KEYS if k not in look]
    for name, colour in look.get("colours", {}).items():
        if not (isinstance(colour, str) and colour.startswith("#") and len(colour) in (7, 9)):
            problems.append(f"colour {name!r} should be like #7EF3E6, not {colour!r}")
    if set(sheet["pose_default"]) != set(POSE_KEYS):
        problems.append(f"pose_default needs exactly {', '.join(POSE_KEYS)}")
    poses = sheet["poses"]
    if "neutral" not in poses:
        problems.append("poses need a 'neutral'")
    for name, pose in poses.items():
        problems += [f"pose {name!r} has unknown {k!r}" for k in pose if k not in POSE_KEYS]
    for state, rule in sheet["states"].items():
        if "pose" in rule and rule["pose"] not in poses:
            problems.append(f"state {state!r} uses unknown pose {rule['pose']!r}")
        for part in ("add", "set"):
            bad = [k for k in rule.get(part, {}) if k not in POSE_KEYS]
            problems += [f"state {state!r} {part}s unknown {k!r}" for k in bad]
    for name, g in sheet["gestures"].items():
        if not isinstance(g.get("seconds"), int | float) or g["seconds"] < 0:
            problems.append(f"gesture {name!r} needs seconds")
        for channel, terms in g.get("moves", {}).items():
            if channel not in CHANNELS:
                problems.append(f"gesture {name!r} moves unknown {channel!r}")
                continue
            for term in terms:
                if not term or not isinstance(term[0], int | float):
                    problems.append(f"gesture {name!r} {channel}: a term starts with an amount")
                    continue
                for shape in term[1:]:
                    lo_hi = SHAPES.get(shape[0]) if shape else None
                    if lo_hi is None or not lo_hi[0] <= len(shape) - 1 <= lo_hi[1]:
                        problems.append(f"gesture {name!r} {channel}: bad shape {shape!r}")
    return problems


def from_sheet(sheet: Mapping) -> Character:
    problems = check(sheet)
    if problems:
        raise CharacterError("; ".join(problems))
    return Character(json.loads(json.dumps(sheet)))  # a private copy


@functools.cache
def builtin() -> Character:
    """The character sheet that ships with Kit (read once; don't change its sheet)."""
    text = resources.files("kit.face").joinpath("character.json").read_text(encoding="utf-8")
    return from_sheet(json.loads(text))


_current: Character | None = None


def current() -> Character:
    """The character every face and painter uses unless told otherwise."""
    global _current
    if _current is None:
        _current = builtin()
    return _current


def use(character: Character) -> None:
    """Make ``character`` the one every face and painter uses, e.g. the sheet the
    brain sent, so a redesign reaches the desk app without a reinstall."""
    global _current
    _current = character
