"""Kit's character sheet: the one file that says how he looks and moves.

Each character is one sheet in ``characters/`` next to this module (``retro``
is the original Glow pill eyes). The ``face.character`` setting picks which
one Kit is; switching back is just changing it back. A sheet holds his looks, which look each app
or body uses, a pose for every emotion, how each state bends that pose, and
every gesture as a set of moves.

A look is 2D or 3D. The ``glow`` style is the 2D pill eyes: colours and the
sizes of his screen, eyes, glow and blush. The ``model`` style is a 3D model
(a glTF ``.glb`` file) whose head bone and morph targets the same poses and
gestures drive. ``use`` picks a look per app or body (``desk``, ``home_app``,
``robot``, falling back to ``default``), so the desk app can be 3D while a
small robot screen stays 2D. A 3D look names a 2D ``fallback`` for anything
that can't draw 3D. The rig and the Glow
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
# What each look style needs. Glow is 2D; a model is 3D.
STYLES = {
    "glow": ("colours", "neck", "screen", "eyes", "glow", "blush"),
    "model": ("file", "fallback", "head_bone", "morphs"),
}
TWO_D = ("glow",)


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

    def look_name(self, app: str = "default") -> str:
        """The look ``app`` (desk, home_app, robot...) is set to use."""
        use = self.sheet["use"]
        return use.get(app, use["default"])

    def look(self, app: str = "default", styles: tuple[str, ...] = TWO_D) -> dict:
        """The look ``app`` should draw, given the ``styles`` it can draw: the one
        ``use`` picks for it, or that look's 2D fallback if it can't draw that."""
        looks = self.sheet["looks"]
        chosen = looks[self.look_name(app)]
        if chosen["style"] not in styles and "fallback" in chosen:
            chosen = looks[chosen["fallback"]]
        if chosen["style"] not in styles:
            raise CharacterError(f"this app can't draw a {chosen['style']!r} look")
        return chosen

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
    for key in ("name", "use", "looks", "pose_default", "poses", "states", "gestures"):
        if key not in sheet:
            problems.append(f"missing {key!r}")
    if problems:
        return problems
    looks = sheet["looks"]
    for name, look in looks.items():
        needs = STYLES.get(look.get("style"))
        if needs is None:
            problems.append(f"look {name!r} needs a style: {', '.join(STYLES)}")
            continue
        problems += [f"look {name!r} is missing {k!r}" for k in needs if k not in look]
        for part, colour in look.get("colours", {}).items():
            if not (isinstance(colour, str) and colour.startswith("#") and len(colour) in (7, 9)):
                problems.append(f"colour {part!r} should be like #7EF3E6, not {colour!r}")
        if look["style"] == "model":
            if not str(look.get("file", "")).lower().endswith((".glb", ".gltf")):
                problems.append(f"look {name!r} needs a .glb (glTF) model file")
            fallback = looks.get(look.get("fallback"), {})
            if fallback.get("style") not in TWO_D:
                problems.append(f"look {name!r} needs a 2D look as its fallback")
            bad = [k for k in look.get("morphs", {}) if k not in POSE_KEYS]
            problems += [f"look {name!r} morphs unknown {k!r}" for k in bad]
    if "default" not in sheet["use"]:
        problems.append("use needs a 'default' look")
    for app, name in sheet["use"].items():
        if name not in looks:
            problems.append(f"use: {app!r} picks unknown look {name!r}")
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


DEFAULT = "retro"


def _folder():
    return resources.files("kit.face").joinpath("characters")


def presets() -> list[str]:
    """The characters Kit ships with, by name (the file names in ``characters/``)."""
    names = [f.name[:-5] for f in _folder().iterdir() if f.name.endswith(".json")]
    return sorted(names, key=lambda n: (n != DEFAULT, n))


@functools.cache
def preset(name: str) -> Character:
    """One of Kit's characters (read once; don't change its sheet)."""
    if name not in presets():
        raise CharacterError(f"no character called {name!r} ({', '.join(presets())})")
    text = _folder().joinpath(f"{name}.json").read_text(encoding="utf-8")
    return from_sheet(json.loads(text))


def builtin() -> Character:
    """The default character, Retro: what a face shows before it hears otherwise."""
    return preset(DEFAULT)


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
