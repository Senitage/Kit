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

The poses, how each state bends them, and the gesture moves all come from
Kit's character sheet (characters/*.json, see kit.face.character), so every app
that draws him uses the same numbers.

Time is passed in (seconds, any monotonic clock) and randomness is injected, so
tests can drive it frame by frame.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields

from kit.face.character import Character, builtin, current


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


# Every emotion's pose, from the default character's sheet (characters/retro.json).
POSES: dict[str, Pose] = {name: Pose(**builtin().pose(name)) for name in builtin().emotions}

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


@dataclass(frozen=True)
class GestureClip:
    seconds: float
    at: Callable[[float], Offsets]  # t runs 0..1 over the clip


def _clip(character: Character, name: str) -> GestureClip:
    return GestureClip(
        character.gesture_seconds(name), lambda t: Offsets(**character.gesture_at(name, t))
    )


# Every gesture, from the character sheet's moves.
CLIPS: dict[str, GestureClip] = {name: _clip(builtin(), name) for name in builtin().gestures}

_POSE_KEYS = [f.name for f in fields(Pose)]


@dataclass
class Face:
    """Kit's face. Tell it what is happening; call ``tick`` once per frame."""

    rng: random.Random = field(default_factory=random.Random)
    ease_s: float = 0.11  # how quickly the face settles into a new pose
    look_hold_s: float = 3.0  # how long a look_at target holds before idle gaze resumes
    # Whose poses and moves to use; None follows kit.face.character.current().
    character: Character | None = None

    def __post_init__(self) -> None:
        self.emotion = "neutral"
        self.resting = "neutral"  # what he settles back to between replies: his mood
        self.state = "idle"
        self._target = Pose(**self._ch.pose("neutral"))
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
        if name not in self._ch.emotions:
            raise ValueError(f"unknown emotion {name!r}")
        self.emotion = name
        self._target = Pose(**self._ch.pose(name))
        self._emotion_until = None if hold_s is None else now + hold_s

    def play(self, gesture: str, now: float) -> None:
        if gesture not in self._ch.gestures:
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

    def rest(self, name: str, now: float) -> None:
        """The face he wears between replies: his mood (kit.life's ``face``). A
        reply's emotion still plays over it and then settles back here, not to
        neutral. Unknown names (a character without that pose) leave it alone."""
        if name not in self._ch.emotions or name == self.resting:
            return
        was = self.resting
        self.resting = name
        if self._emotion_until is None and self.emotion == was:  # not mid-reply
            self.set_emotion(name, now)

    def look_at(self, x: float, y: float, now: float) -> None:
        """Look toward a point, -1..1 each way from the face's centre."""
        self._look = (_clamp(x, -1, 1), _clamp(y, -1, 1), now + self.look_hold_s)

    @property
    def _ch(self) -> Character:
        return self.character or current()

    @property
    def gesture(self) -> str | None:
        return self._clip[0] if self._clip else None

    # ---- the frame loop ----

    def tick(self, now: float) -> FaceFrame:
        dt = 0.0 if self._last is None else max(0.0, min(now - self._last, 0.1))
        self._last = now
        if self._emotion_until is not None and now >= self._emotion_until:
            self.set_emotion(self.resting, now)

        target = self._state_pose()
        a = 1 - math.exp(-dt / self.ease_s) if dt else 0.0
        for k in _POSE_KEYS:
            self._cur[k] += (getattr(target, k) - self._cur[k]) * a
        glow_target = self._ch.state_glow(self.state)
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
        """The emotion's pose as the state bends it (asleep, offline, listening...)."""
        return Pose(**self._ch.state_pose(self.state, self.emotion, asdict(self._target)))

    def _gesture(self, now: float) -> Offsets:
        if not self._clip:
            return Offsets()
        name, start = self._clip
        seconds = self._ch.gesture_seconds(name)
        t = (now - start) / seconds if seconds else 1.0
        if t >= 1:
            self._clip = None
            return Offsets()
        return Offsets(**self._ch.gesture_at(name, max(t, 0.0)))

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
