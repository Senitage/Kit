import random

import pytest

from kit.face import CLIPS, POSES, Face, plan_reply
from kit.reply import EMOTIONS, GESTURES

FPS = 60


def run(face, start, seconds):
    """Tick the face at 60 fps and return every frame."""
    return [face.tick(start + i / FPS) for i in range(int(seconds * FPS))]


def test_every_emotion_and_gesture_kit_can_pick_has_a_face_version():
    assert set(POSES) == set(EMOTIONS)
    assert set(CLIPS) == set(GESTURES)


def test_kit_blinks_on_its_own_and_the_eyes_fully_close():
    frames = run(Face(rng=random.Random(1)), 0, 8)
    shut = [f for f in frames if f.open_left < 0.1]
    assert shut, "no blink in 8 seconds"
    assert len(shut) < len(frames) * 0.1, "eyes should be open most of the time"


def test_eyes_dart_around_when_idle():
    frames = run(Face(rng=random.Random(2)), 0, 10)
    assert len({round(f.look_x, 2) for f in frames}) > 3


def test_emotion_eases_in_holds_then_returns_to_neutral():
    face = Face(rng=random.Random(3))
    face.tick(0)
    face.set_emotion("happy", 0, hold_s=2)
    first = face.tick(1 / FPS)
    settled = run(face, 1 / FPS, 1)[-1]
    assert first.squint < settled.squint, "the pose should ease in, not snap"
    assert settled.squint == pytest.approx(POSES["happy"].squint, abs=0.05)
    later = run(face, 2.5, 1)[-1]
    assert face.emotion == "neutral"
    assert later.squint < 0.1


@pytest.mark.parametrize("gesture", [g for g in GESTURES if g != "none"])
def test_each_gesture_moves_the_face_and_hands_back(gesture):
    face = Face(rng=random.Random(4))
    face.tick(0)
    face.play(gesture, 0)
    seconds = CLIPS[gesture].seconds
    frames = run(face, 0, seconds)
    moved = max(
        abs(f.dx)
        + abs(f.rot)
        + abs(f.sx - 1)
        + abs(f.sy - 1)
        + abs(f.scale - 1)
        + abs(f.look_x)
        + abs(f.squint)
        for f in frames
    )
    assert moved > 0.03, f"{gesture} barely moves"
    face.tick(seconds + 0.05)
    assert face.gesture is None


def test_unknown_names_are_rejected():
    face = Face()
    with pytest.raises(ValueError):
        face.set_emotion("furious", 0)
    with pytest.raises(ValueError):
        face.play("backflip", 0)
    with pytest.raises(ValueError):
        face.set_state("dancing")


def test_sleeping_closes_the_eyes_and_dims_and_waking_opens_them():
    face = Face(rng=random.Random(5))
    face.set_state("sleeping")
    asleep = run(face, 0, 3)[-1]
    assert asleep.open_left < 0.15 and asleep.glow < 0.6
    face.set_state("idle")
    awake = max(f.open_left for f in run(face, 3, 2))
    assert awake > 0.9


def test_offline_looks_dim_and_grey():
    face = Face(rng=random.Random(6))
    face.set_state("offline")
    f = run(face, 0, 3)[-1]
    assert f.offline and f.glow < 0.4


def test_speaking_pulses_and_other_states_do_not():
    face = Face(rng=random.Random(7))
    face.set_state("speaking")
    assert max(f.talk for f in run(face, 0, 1)) > 0.3
    face.set_state("idle")
    assert max(f.talk for f in run(face, 1, 1)) == 0


def test_eyes_follow_a_look_at_target_then_go_back_to_idle():
    face = Face(rng=random.Random(8))
    face.look_at(0.8, -0.5, 0)
    f = face.tick(0.1)
    assert (f.look_x, f.look_y) == pytest.approx((0.8, -0.5))
    face.look_at(5, 5, 0.2)
    assert face.tick(0.3).look_x == 1
    later = run(face, 3.5, 0.2)[-1]
    assert later.look_x != 1


def test_reply_plan_starts_each_gesture_before_its_words():
    reply = {
        "emotion": "happy",
        "segments": [
            {"say": "Oh, you're back.", "gesture": "perk_up"},
            {"say": "Did it work?", "gesture": "none"},
        ],
    }
    cues = plan_reply(reply)
    kinds = [(c.kind, c.value) for c in cues]
    assert kinds == [
        ("emotion", "happy"),
        ("gesture", "perk_up"),
        ("say", "Oh, you're back."),
        ("say", "Did it work?"),
        ("done", ""),
    ]
    gesture, first_say, second_say = cues[1], cues[2], cues[3]
    assert gesture.at < first_say.at
    assert second_say.at >= first_say.at + first_say.seconds
    assert [c.at for c in cues] == sorted(c.at for c in cues)
