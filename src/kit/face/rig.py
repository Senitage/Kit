"""Kit's expression rig: turns emotions, gestures and states into face numbers.

The rig knows nothing about pixels. Every tick it returns a ``FaceFrame``: eye
openness, squint, lid tilt, where the eyes look, glow, and how the whole head
is moved. A painter draws that frame: the Glow painter in the desk app now, a
small round screen on the arm's face head later. Keeping the rig free of any
drawing code is what lets both share one character.

Three layers make up each frame:

1. Reflexes run all the time: blinks, quick eye darts, breathing, and following
   whatever ``look_at`` was last given (the mouse now, Dan's face later).
2. The emotion from each reply sets a pose that the face eases toward and holds.
3. Gestures play on top of the pose for a second or so, then hand back.

Time is passed in (seconds, any monotonic clock) and randomness is injected, so
tests can drive it frame by frame.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace


@dataclass(frozen=True)
class Pose:
    """What an emotion does to the face. Everything eases toward these values."""

    open: float = 1.0  # eye height, 1 = normal, 0 = shut
    squint: float = 0.0  # lower lid rising, 0..1; makes happy "^ ^" eyes
    tilt: float = 0.0  # upper lid angle; + sad or worried, - focused or cross
    asym: float = 0.0  # + left eye bigger than right (curious, wink-ish)
    size: float = 1.0  # overall eye size
    look_x: float = 0.0  # resting gaze, -1 left .. 1 right
    look_y: float = 0.0  # resting gaze, -1 up .. 1 down
    blush: float = 0.15  # cheek glow, 0..1
    head_tilt: float = 0.0  # radians, + leans right
    head_y: float = 0.0  # head height offset, + lower (fraction of face size)


POSES: dict[str, Pose] = {
    "neutral": Pose(),
    "happy": Pose(open=0.95, squint=0.6, size=1.02, blush=0.7, head_y=-0.006),
    "curious": Pose(
        open=1.12, tilt=-0.1, asym=0.22, size=1.05, look_y=-0.25, blush=0.2, head_tilt=0.16
    ),
    "thinking": Pose(
        open=0.78,
        squint=0.05,
        tilt=-0.35,
        asym=-0.18,
        size=0.96,
        look_x=0.65,
        look_y=-0.7,
        blush=0.1,
        head_tilt=-0.08,
    ),
    "surprised": Pose(open=1.3, size=1.16, head_y=-0.016),
    "concerned": Pose(open=0.88, tilt=0.75, look_y=0.12, blush=0.0, head_tilt=0.05, head_y=0.006),
    "playful": Pose(
        open=0.95, squint=0.35, tilt=-0.15, asym=0.55, size=1.02, blush=0.6, head_tilt=-0.12
    ),
    "tired": Pose(
        open=0.45,
        tilt=0.35,
        asym=0.05,
        size=0.97,
        look_y=0.35,
        blush=0.0,
        head_tilt=0.06,
        head_y=0.02,
    ),
    "proud": Pose(
        open=0.82, squint=0.45, tilt=-0.05, size=1.03, look_y=-0.35, blush=0.45, head_y=-0.016
    ),
    "excited": Pose(open=1.18, squint=0.3, size=1.1, blush=0.65, head_y=-0.02),
    "sad": Pose(
        open=0.72, tilt=0.95, size=0.95, look_y=0.5, blush=0.0, head_tilt=0.08, head_y=0.025
    ),
    "confused": Pose(open=1.0, tilt=-0.2, asym=0.35, look_x=-0.2, look_y=-0.15, head_tilt=0.22),
    "shy": Pose(
        open=0.85,
        squint=0.4,
        size=0.95,
        look_x=-0.6,
        look_y=0.4,
        blush=1.0,
        head_tilt=-0.1,
        head_y=0.01,
    ),
    "grumpy": Pose(open=0.62, tilt=-0.7, size=0.95, look_y=0.1, blush=0.0, head_y=0.01),
    "focused": Pose(open=0.85, tilt=-0.4, size=0.92, look_y=0.2, blush=0.05),
    "relieved": Pose(open=0.7, squint=0.35, tilt=0.3, blush=0.3, head_y=0.01),
    "fond": Pose(open=0.9, squint=0.7, size=1.02, blush=0.9, head_tilt=0.1),
}

STATES = ("idle", "sleeping", "listening", "thinking", "speaking", "working", "offline")


@dataclass(frozen=True)
class FaceFrame:
    """One frame of Kit's face, ready to paint. Units are relative to the face size."""

    open_left: float
    open_right: float
    squint: float
    tilt: float
    size: float
    look_x: float  # -1..1
    look_y: float  # -1..1
    blush: float  # 0..1
    glow: float  # brightness 0..1 (dim when asleep or offline)
    talk: float  # 0..1, a pulse while speaking
    offline: bool
    dx: float  # head offset, fraction of face size
    dy: float
    rot: float  # head tilt, radians
    sx: float  # squash and stretch
    sy: float
    scale: float  # leaning in makes the face bigger


@dataclass
class Offsets:
    """What a gesture adds on top of the pose at one moment."""

    dx: float = 0.0
    dy: float = 0.0
    rot: float = 0.0
    sx: float = 1.0
    sy: float = 1.0
    scale: float = 1.0
    look_x: float = 0.0
    look_y: float = 0.0
    open: float = 0.0
    squint: float = 0.0
    size: float = 0.0
    wink: float = 0.0  # 0..1, closes the right eye only


def _ease(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def _bump(t: float, a: float, b: float) -> float:
    """A smooth hump from 0 up to 1 and back to 0 between t=a and t=b."""
    return 0.0 if t < a or t > b else math.sin(math.pi * (t - a) / (b - a))


def _hold(t: float, rise: float, fall: float) -> float:
    """Ease in until ``rise``, hold at 1, ease out after ``fall``."""
    if t < rise:
        return _ease(t / rise)
    if t > fall:
        return 1 - _ease((t - fall) / (1 - fall))
    return 1.0


def _nod(t: float) -> Offsets:
    return Offsets(
        dy=0.035 * _bump(t, 0.05, 0.4) + 0.025 * _bump(t, 0.45, 0.8), look_y=0.5 * _bump(t, 0, 0.85)
    )


def _shake(t: float) -> Offsets:
    s = math.sin(t * math.pi * 4) * (1 - t)
    return Offsets(dx=0.04 * s, look_x=-0.7 * s)


def _tilt_head(t: float) -> Offsets:
    h = _hold(t, 0.25, 0.8)
    return Offsets(rot=0.28 * h, open=0.1 * h, look_y=-0.2 * h)


def _perk_up(t: float) -> Offsets:
    # Anticipation: a small squash down first, then stretch up.
    return Offsets(
        sy=1 - 0.08 * _bump(t, 0, 0.18) + 0.1 * _bump(t, 0.15, 0.6),
        sx=1 + 0.06 * _bump(t, 0, 0.18) - 0.05 * _bump(t, 0.15, 0.6),
        dy=-0.045 * _bump(t, 0.15, 0.7),
        open=0.25 * _bump(t, 0.12, 1),
    )


def _droop(t: float) -> Offsets:
    h = _hold(t, 0.3, 0.75)
    return Offsets(
        dy=0.045 * h, sy=1 - 0.06 * h, sx=1 + 0.03 * h, open=-0.35 * h, look_y=0.6 * h, rot=0.06 * h
    )


def _look_away(t: float) -> Offsets:
    h = _hold(t, 0.15, 0.8)
    return Offsets(look_x=0.95 * h, look_y=-0.55 * h, rot=-0.07 * h, dx=0.02 * h)


def _shrug(t: float) -> Offsets:
    return Offsets(
        dy=-0.03 * _bump(t, 0.1, 0.6), rot=0.12 * math.sin(t * math.pi * 2) * _bump(t, 0, 1)
    )


def _wave(t: float) -> Offsets:
    return Offsets(
        rot=0.13 * math.sin(t * math.pi * 6) * _bump(t, 0, 1), squint=0.45 * _bump(t, 0, 1)
    )


def _bounce(t: float) -> Offsets:
    hop = abs(math.sin(t * math.pi * 2))
    land = (1 - hop) * _bump(t, 0, 1)
    return Offsets(
        dy=-0.06 * hop * (1 - t * 0.4),
        sy=1 - 0.07 * land,
        sx=1 + 0.05 * land,
        squint=0.45 * _bump(t, 0, 1),
    )


def _lean_in(t: float) -> Offsets:
    h = _hold(t, 0.25, 0.8)
    return Offsets(scale=1 + 0.13 * h, open=0.12 * h)


def _wink(t: float) -> Offsets:
    h = _hold(t, 0.2, 0.65)
    return Offsets(wink=h, squint=0.3 * h, rot=-0.06 * h)


def _laugh(t: float) -> Offsets:
    h = _bump(t, 0, 1)
    return Offsets(
        dy=0.012 * math.sin(t * math.pi * 10) * h,
        squint=0.8 * min(1, 3 * h),
        rot=0.04 * h,
        look_y=-0.3 * h,
    )


def _sigh(t: float) -> Offsets:
    # A breath in (rise and stretch), then a long breath out (sink and squash).
    rise, fall = _bump(t, 0, 0.35), _bump(t, 0.3, 1)
    return Offsets(
        dy=-0.02 * rise + 0.03 * fall,
        sy=1 + 0.05 * rise - 0.05 * fall,
        open=0.1 * rise - 0.4 * fall,
        look_y=-0.3 * rise + 0.4 * fall,
    )


def _startle(t: float) -> Offsets:
    # A fast jolt back (smaller, wide eyes), then a slow recovery.
    jolt = t / 0.1 if t < 0.1 else 1 - _ease((t - 0.1) / 0.9)
    return Offsets(
        scale=1 - 0.12 * jolt,
        dy=-0.03 * jolt,
        open=0.4 * jolt,
        size=0.12 * jolt,
        dx=0.01 * math.sin(t * math.pi * 14) * jolt,
    )


def _yawn(t: float) -> Offsets:
    h = _hold(t, 0.3, 0.75)
    return Offsets(
        sy=1 + 0.09 * h, sx=1 - 0.04 * h, squint=0.6 * h, open=-0.5 * h, rot=-0.08 * h, dy=-0.02 * h
    )


def _double_take(t: float) -> Offsets:
    away = _bump(t, 0, 0.3)
    back = _bump(t, 0.35, 1)
    return Offsets(
        look_x=0.8 * away,
        rot=-0.05 * away,
        open=0.35 * back,
        size=0.1 * back,
        scale=1 + 0.06 * back,
        dy=-0.02 * _bump(t, 0.35, 0.55),
    )


def _wiggle(t: float) -> Offsets:
    h = _bump(t, 0, 1)
    return Offsets(
        rot=0.15 * math.sin(t * math.pi * 8) * h,
        dy=-0.015 * abs(math.sin(t * math.pi * 8)) * h,
        squint=0.5 * h,
        dx=0.015 * math.sin(t * math.pi * 4) * h,
    )


def _peek(t: float) -> Offsets:
    h = _hold(t, 0.25, 0.75)
    return Offsets(dx=0.05 * h, rot=0.12 * h, look_x=0.9 * h, open=-0.15 * h, squint=0.2 * h)


def _look_up(t: float) -> Offsets:
    h = _hold(t, 0.2, 0.8)
    return Offsets(look_x=-0.5 * h, look_y=-0.9 * h, rot=-0.06 * h, dy=-0.01 * h)


@dataclass(frozen=True)
class GestureClip:
    seconds: float
    at: Callable[[float], Offsets]  # t runs 0..1 over the clip


CLIPS: dict[str, GestureClip] = {
    "none": GestureClip(0.0, lambda t: Offsets()),
    "nod": GestureClip(0.9, _nod),
    "shake": GestureClip(1.0, _shake),
    "tilt_head": GestureClip(1.5, _tilt_head),
    "perk_up": GestureClip(0.9, _perk_up),
    "droop": GestureClip(1.6, _droop),
    "look_away": GestureClip(1.7, _look_away),
    "shrug": GestureClip(1.2, _shrug),
    "wave": GestureClip(1.3, _wave),
    "bounce": GestureClip(1.0, _bounce),
    "lean_in": GestureClip(1.6, _lean_in),
    "wink": GestureClip(0.8, _wink),
    "laugh": GestureClip(1.2, _laugh),
    "sigh": GestureClip(2.0, _sigh),
    "startle": GestureClip(1.3, _startle),
    "yawn": GestureClip(2.2, _yawn),
    "double_take": GestureClip(1.4, _double_take),
    "wiggle": GestureClip(1.4, _wiggle),
    "peek": GestureClip(1.8, _peek),
    "look_up": GestureClip(1.8, _look_up),
}

_POSE_KEYS = [f.name for f in fields(Pose)]


@dataclass
class Face:
    """Kit's face. Tell it what is happening; call ``tick`` once per frame."""

    rng: random.Random = field(default_factory=random.Random)
    ease_s: float = 0.11  # how quickly the face settles into a new pose
    look_hold_s: float = 3.0  # how long a look_at target holds before idle gaze resumes

    def __post_init__(self) -> None:
        self.emotion = "neutral"
        self.state = "idle"
        self._target = POSES["neutral"]
        self._cur = {k: getattr(self._target, k) for k in _POSE_KEYS}
        self._emotion_until: float | None = None
        self._clip: tuple[str, float] | None = None  # (gesture, start time)
        self._last: float | None = None
        self._blink_at: float | None = None
        self._blink_start: float | None = None
        self._double = False
        self._dart = (0.0, 0.0)
        self._dart_at = 0.0
        self._look: tuple[float, float, float] | None = None  # x, y, until
        self._glow = 1.0
        # The mood dials (kit.life, life.dials): 0.5 and 0 are how he's always been.
        self.arousal, self.valence = 0.5, 0.0
        self._dials = [0.5, 0.0]  # eased toward the values above
        self._breath: float | None = None  # breathing phase, radians

    # ---- what the desk app (or the arm) tells the face ----

    def set_emotion(self, name: str, now: float, hold_s: float | None = None) -> None:
        """Ease toward an emotion's pose; after ``hold_s`` seconds drift back to neutral."""
        if name not in POSES:
            raise ValueError(f"unknown emotion {name!r}")
        self.emotion = name
        self._target = POSES[name]
        self._emotion_until = None if hold_s is None else now + hold_s

    def play(self, gesture: str, now: float) -> None:
        if gesture not in CLIPS:
            raise ValueError(f"unknown gesture {gesture!r}")
        self._clip = None if gesture == "none" else (gesture, now)

    def set_state(self, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        self.state = state

    def set_dials(self, arousal: float, valence: float) -> None:
        """How lively (0 flat .. 1 up) and how happy (-1 low .. 1 happy) Kit is. The
        face eases there over a few seconds: slower breaths, slower and heavier
        blinks and smaller gestures when he's flat; a touch of glow when he's happy."""
        self.arousal = _clamp(arousal, 0, 1)
        self.valence = _clamp(valence, -1, 1)

    def look_at(self, x: float, y: float, now: float) -> None:
        """Look toward a point, -1..1 each way from the face's centre."""
        self._look = (_clamp(x, -1, 1), _clamp(y, -1, 1), now + self.look_hold_s)

    @property
    def gesture(self) -> str | None:
        return self._clip[0] if self._clip else None

    # ---- the frame loop ----

    def tick(self, now: float) -> FaceFrame:
        dt = 0.0 if self._last is None else max(0.0, min(now - self._last, 0.1))
        self._last = now
        if self._emotion_until is not None and now >= self._emotion_until:
            self.set_emotion("neutral", now)

        target = self._state_pose()
        a = 1 - math.exp(-dt / self.ease_s) if dt else 0.0
        for k in _POSE_KEYS:
            self._cur[k] += (getattr(target, k) - self._cur[k]) * a
        glow_target = {"sleeping": 0.45, "offline": 0.3}.get(self.state, 1.0)
        self._glow += (glow_target - self._glow) * (1 - math.exp(-dt / 0.4) if dt else 0.0)

        k = 1 - math.exp(-dt / 2.0) if dt else 0.0  # the dials glide over seconds
        self._dials[0] += (self.arousal - self._dials[0]) * k
        self._dials[1] += (self.valence - self._dials[1]) * k
        arousal, valence = self._dials
        g = _scaled(self._gesture(now), 0.7 + 0.6 * arousal)  # 1 at the middle
        look_x, look_y = self._gaze(now)
        period = 7.0 if self.state == "sleeping" else 4.2 * (1 + (0.5 - arousal) * 0.6)
        if self._breath is None:
            self._breath = now * 2 * math.pi / period
        self._breath += dt * 2 * math.pi / period
        breath = math.sin(self._breath)
        blink = self._blink(now)
        c = self._cur
        open_ = max(0.0, (c["open"] + g.open) * blink)
        talk = 0.0
        if self.state == "speaking":
            talk = 0.25 + 0.55 * abs(math.sin(now * 11.8) * math.sin(now * 18.9 + 1))
        return FaceFrame(
            open_left=open_ * max(0.0, 1 + c["asym"] * 0.45),
            open_right=open_ * max(0.0, 1 - c["asym"] * 0.45) * (1 - g.wink),
            squint=_clamp(c["squint"] + g.squint, 0, 0.95),
            tilt=c["tilt"],
            size=c["size"] + g.size,
            look_x=_clamp(look_x + g.look_x, -1, 1),
            look_y=_clamp(look_y + g.look_y, -1, 1),
            blush=_clamp(c["blush"] + 0.15 * valence, 0, 1),
            glow=self._glow,
            talk=talk,
            offline=self.state == "offline",
            dx=g.dx,
            dy=c["head_y"] + g.dy + breath * 0.005,
            rot=c["head_tilt"] + g.rot,
            sx=g.sx * (1 - breath * 0.006),
            sy=g.sy * (1 + breath * 0.012),
            scale=g.scale,
        )

    def _state_pose(self) -> Pose:
        pose = self._target
        if self.state == "sleeping":
            return replace(pose, open=0.06, squint=0.0, tilt=0.2, look_y=0.4, head_y=0.03)
        if self.state == "offline":
            return replace(POSES["tired"], blush=0.0)
        if self.state == "thinking" and self.emotion == "neutral":
            return POSES["thinking"]
        if self.state == "listening":
            return replace(pose, open=pose.open + 0.1, size=pose.size + 0.03)
        return pose

    def _gesture(self, now: float) -> Offsets:
        if not self._clip:
            return Offsets()
        name, start = self._clip
        clip = CLIPS[name]
        t = (now - start) / clip.seconds
        if t >= 1:
            self._clip = None
            return Offsets()
        return clip.at(max(t, 0.0))

    def _gaze(self, now: float) -> tuple[float, float]:
        c = self._cur
        if self.state == "sleeping":
            return c["look_x"], c["look_y"]
        if self.state == "working":
            # Reading across the screen: a slow left-to-right sweep with quick returns.
            phase = (now / 1.6) % 1
            return -0.6 + 1.2 * phase, 0.3
        if self._look and now < self._look[2] and self.state != "thinking":
            return self._look[0], self._look[1]
        if now >= self._dart_at:
            far = self.rng.random() < 0.25 and self.state != "listening"
            reach = (0.9, 0.6) if far else (0.35, 0.25)
            self._dart = (self.rng.uniform(-1, 1) * reach[0], self.rng.uniform(-1, 1) * reach[1])
            self._dart_at = now + self.rng.uniform(0.9, 3.7)
        return c["look_x"] + self._dart[0], c["look_y"] + self._dart[1]

    def _blink(self, now: float) -> float:
        """1 when the eyes are open, dipping to 0 through a blink."""
        if self.state in ("sleeping", "offline") and self._blink_start is None:
            self._blink_at = None
            return 1.0
        if self._blink_at is None:
            self._blink_at = now + self.rng.uniform(1.0, 3.0)
        if self._blink_start is None and now >= self._blink_at:
            self._blink_start = now
            self._double = self.rng.random() < 0.2
        if self._blink_start is None:
            return 1.0
        length = 0.42 if self._double else 0.17
        t = (now - self._blink_start) / length
        if t >= 1:
            self._blink_start = None
            slower = 1 + (0.5 - self._dials[0]) * 0.8  # a flat Kit blinks less often
            self._blink_at = now + self.rng.uniform(2.0, 6.2) * slower
            return 1.0
        phase = (t * 2) % 1 if self._double else t
        return 1 - math.sin(math.pi * phase)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _scaled(g: Offsets, k: float) -> Offsets:
    """A gesture made bigger or smaller (``k`` 1 leaves it as it is)."""
    if k == 1:
        return g
    return Offsets(
        dx=g.dx * k,
        dy=g.dy * k,
        rot=g.rot * k,
        sx=1 + (g.sx - 1) * k,
        sy=1 + (g.sy - 1) * k,
        scale=1 + (g.scale - 1) * k,
        look_x=g.look_x * k,
        look_y=g.look_y * k,
        open=g.open * k,
        squint=g.squint * k,
        size=g.size * k,
        wink=g.wink,
    )


@dataclass(frozen=True)
class Cue:
    """One timed step of acting out a reply: set the emotion, play a gesture, say words."""

    at: float  # seconds from the start of the reply
    kind: str  # "emotion", "gesture", "say" or "done"
    value: str = ""
    seconds: float = 0.0  # how long the words take (for "say")


def plan_reply(
    reply: Mapping, seconds_per_char: float = 0.06, lead_s: float = 0.25, gap_s: float = 0.45
) -> list[Cue]:
    """Turn a reply (as the brain sends it) into timed cues for the face.

    Each segment's gesture starts ``lead_s`` before its words, so the move
    anticipates the sentence the way a person's would. Speech length is
    estimated from the text until stage 3's voice reports real timings.
    """
    cues = [Cue(0.0, "emotion", reply.get("emotion", "neutral"))]
    t = 0.0
    for seg in reply.get("segments", []):
        say = seg.get("say", "")
        gesture = seg.get("gesture", "none")
        if gesture != "none":
            cues.append(Cue(t, "gesture", gesture))
        speak = len(say) * seconds_per_char
        cues.append(Cue(t + lead_s, "say", say, speak))
        t += lead_s + speak + gap_s
    cues.append(Cue(t, "done"))
    return cues
