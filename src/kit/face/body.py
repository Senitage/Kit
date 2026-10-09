"""Kit's whole-body moves: a loop when he's excited, a hop, a jump back, a sway.

Gestures in ``kit.face.rig`` move his face within its own screen. Body moves
move all of him: on the desk the face's window travels around where Dan left
it; on the arm the same names become arm moves. Like the rig, this knows
nothing about pixels: each move is a path in face sizes (x right, y down) over
time, starting and ending at home.

Moves are picked from what the face is doing (``move_for``): a gesture that
has a bigger version, an emotion that wants one ("excited" loops), or a reason
the brain gave (a hello when Dan's back).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass


def _ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def _arc(t: float) -> float:
    """0 up to 1 and back, like a jump's height."""
    return math.sin(math.pi * max(0.0, min(1.0, t)))


@dataclass(frozen=True)
class Step:
    """Where he is at one moment of a move: offset from home in face sizes, and how
    much his face spins (radians) and squashes (1 is as he is)."""

    x: float = 0.0
    y: float = 0.0
    spin: float = 0.0
    squash: float = 1.0


def _loop(t: float) -> Step:
    # Up and round in a circle over where he sits, a little spin with it, then a
    # squash as he lands.
    a = 2 * math.pi * _ease_in_out(t)
    r = 0.42
    return Step(
        x=r * math.sin(a),
        y=-r * (1 - math.cos(a)),
        spin=0.35 * math.sin(a),
        squash=1 - 0.12 * _arc((t - 0.85) / 0.15) if t > 0.85 else 1.0,
    )


def _hop(t: float) -> Step:
    land = _arc((t - 0.8) / 0.2) if t > 0.8 else 0.0
    crouch = _arc(t / 0.15) if t < 0.15 else 0.0
    return Step(y=-0.4 * _arc((t - 0.12) / 0.7), squash=1 - 0.12 * (land + crouch))


def _hop_hop(t: float) -> Step:
    first = _hop(t * 2) if t < 0.5 else Step()
    second = _hop((t - 0.5) * 2) if t >= 0.5 else Step()
    return Step(y=first.y + second.y * 0.7, squash=first.squash * second.squash)


def _jump_back(t: float) -> Step:
    # A fast jolt up and away, with a shiver, then a slow drift back.
    out = t / 0.12 if t < 0.12 else 1 - _ease_in_out((t - 0.12) / 0.88)
    shiver = 0.025 * math.sin(t * math.pi * 18) * out
    return Step(x=-0.16 * out + shiver, y=-0.2 * out)


def _sway(t: float) -> Step:
    h = _arc(t)
    return Step(x=0.14 * math.sin(t * math.pi * 4) * h, spin=0.18 * math.sin(t * math.pi * 4) * h)


def _held(t: float, rise: float, fall: float) -> float:
    """Ease up to 1 by ``rise``, hold, ease back to 0 from ``fall``."""
    if t < rise:
        return _ease_in_out(t / rise)
    if t > fall:
        return 1 - _ease_in_out((t - fall) / (1 - fall))
    return 1.0


def _sink(t: float) -> Step:
    h = _held(t, 0.3, 0.75)
    return Step(y=0.18 * h, squash=1 - 0.08 * h)


def _bob(t: float) -> Step:
    return Step(y=0.07 * (_arc(t / 0.45) + 0.7 * _arc((t - 0.5) / 0.45)))


def _dash(t: float) -> Step:
    # A quick there-and-back to one side ("no, no").
    return Step(x=0.22 * math.sin(t * math.pi * 3) * (1 - t))


def _peek_out(t: float) -> Step:
    h = _held(t, 0.3, 0.7)
    return Step(x=0.2 * h, y=-0.05 * h, spin=0.2 * h)


@dataclass(frozen=True)
class BodyMove:
    seconds: float
    at: Callable[[float], Step]  # t runs 0..1


MOVES: dict[str, BodyMove] = {
    "loop": BodyMove(1.5, _loop),
    "hop": BodyMove(0.7, _hop),
    "hop_hop": BodyMove(1.1, _hop_hop),
    "jump_back": BodyMove(1.2, _jump_back),
    "sway": BodyMove(1.4, _sway),
    "sink": BodyMove(1.8, _sink),
    "bob": BodyMove(0.9, _bob),
    "dash": BodyMove(1.0, _dash),
    "peek_out": BodyMove(1.8, _peek_out),
}

# The gestures that have a bigger, whole-body version.
GESTURE_MOVES = {
    "bounce": "hop_hop",
    "perk_up": "hop",
    "laugh": "hop",
    "wiggle": "sway",
    "startle": "jump_back",
    "double_take": "jump_back",
    "droop": "sink",
    "nod": "bob",
    "shake": "dash",
    "peek": "peek_out",
}
# Feelings big enough to move all of him as he starts to say them.
EMOTION_MOVES = {"excited": "loop", "proud": "hop", "sad": "sink"}
# Why he piped up (kit.life), for the times that deserve a move of their own.
REASON_MOVES = {"back": "loop"}  # Dan's home: he's glad


def move_for(gesture: str = "", emotion: str = "", reason: str = "") -> str | None:
    """The body move for a gesture, an emotion or a pipe-up reason, if any."""
    return REASON_MOVES.get(reason) or EMOTION_MOVES.get(emotion) or GESTURE_MOVES.get(gesture)


def step(name: str, elapsed: float) -> Step | None:
    """Where a move is ``elapsed`` seconds in, or None once it's over."""
    move = MOVES[name]
    if elapsed >= move.seconds:
        return None
    return move.at(max(0.0, elapsed) / move.seconds)
