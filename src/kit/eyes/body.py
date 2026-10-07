"""Hands and body pose with MediaPipe, and the plain-Python reading of them.

MediaPipe runs small, fast models on the CPU. Each task loads its own model
file, downloaded into the eyes' models folder the first time:
  - Gesture recognizer: 21 points per hand plus a named gesture (thumbs up, fist...)
  - Pose landmarker:    33 body points (shoulders, elbows, wrists, hips...)
  - Face landmarker:    used by ``kit.eyes.faces``

``Point``, ``Hand``, ``describe_pose`` and ``read_hands`` are plain Python, so
the scene and the tests never need MediaPipe; only ``BodyReader`` does.
"""

from __future__ import annotations

import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

MEDIAPIPE_MODELS = "https://storage.googleapis.com/mediapipe-models"
MODEL_URLS = {
    "gesture": f"{MEDIAPIPE_MODELS}/gesture_recognizer/gesture_recognizer/float16/latest/"
    "gesture_recognizer.task",
    "pose": f"{MEDIAPIPE_MODELS}/pose_landmarker/pose_landmarker_lite/float16/latest/"
    "pose_landmarker_lite.task",
    "face": f"{MEDIAPIPE_MODELS}/face_landmarker/face_landmarker/float16/latest/"
    "face_landmarker.task",
}

# The recognizer's built-in gestures, with friendlier names.
GESTURE_NAMES = {
    "Thumb_Up": "thumbs up",
    "Thumb_Down": "thumbs down",
    "Open_Palm": "open palm",
    "Closed_Fist": "fist",
    "Pointing_Up": "pointing up",
    "Victory": "victory",
    "ILoveYou": "I love you",
}

# Pose landmark numbers (33 points, 0 = nose).
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_ELBOW, RIGHT_ELBOW = 13, 14
LEFT_WRIST, RIGHT_WRIST = 15, 16

Fetcher = Callable[[str, Path], None]


@dataclass(frozen=True)
class Point:
    """A landmark as a fraction of the frame (0 to 1 each way, y downwards)."""

    x: float
    y: float
    visibility: float = 1.0


@dataclass
class Hand:
    side: str  # "left" or "right", the person's own
    gesture: str | None  # a GESTURE_NAMES value, or None
    points: list[Point]  # 21 landmarks, 0 = wrist


def fetch(url: str, path: Path) -> None:
    urllib.request.urlretrieve(url, path)


def model_path(name: str, folder: Path, fetcher: Fetcher = fetch) -> Path:
    """The local file for one of MODEL_URLS, downloaded the first time."""
    url = MODEL_URLS[name]
    path = folder / url.rsplit("/", 1)[1]
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        log.info("downloading %s", path.name)
        fetcher(url, path)
    return path


def describe_pose(points: list[Point]) -> list[str]:
    """Turn raw body points into simple facts, e.g. ["left hand raised"].
    y grows downwards in images, so "above" means a smaller y."""
    facts = []
    sides = (("left", LEFT_WRIST, LEFT_SHOULDER), ("right", RIGHT_WRIST, RIGHT_SHOULDER))
    for side, wrist, shoulder in sides:
        w, s = points[wrist], points[shoulder]
        if w.visibility > 0.5 and s.visibility > 0.5 and w.y < s.y:
            facts.append(f"{side} hand raised")
    return facts


def _points(landmarks) -> list[Point]:
    return [
        Point(lm.x, lm.y, lm.visibility if lm.visibility is not None else 1.0) for lm in landmarks
    ]


def read_hands(result, min_wrist_gap: float = 0.05) -> list[Hand]:
    """The hands in a MediaPipe gesture result, as ``Hand``s.

    MediaPipe sometimes reports the same hand twice (once as left, once as
    right). If two wrists are closer than ``min_wrist_gap`` (a fraction of the
    frame), they are the same hand, so only the more confident one is kept.
    """
    candidates = sorted(
        zip(result.handedness, result.gestures, result.hand_landmarks, strict=True),
        key=lambda h: h[0][0].score,
        reverse=True,
    )
    found: list[Hand] = []
    for handedness, gestures, landmarks in candidates:
        wrist = landmarks[0]
        if any(
            abs(wrist.x - other.points[0].x) < min_wrist_gap
            and abs(wrist.y - other.points[0].y) < min_wrist_gap
            for other in found
        ):
            continue
        side = handedness[0].category_name.lower()
        name = GESTURE_NAMES.get(gestures[0].category_name) if gestures else None
        found.append(Hand(side, name, _points(landmarks)))
    return found


def read_poses(result) -> list[list[Point]]:
    return [_points(landmarks) for landmarks in result.pose_landmarks]


def mp_image(rgb):
    """Wrap an RGB frame for MediaPipe (imported here, so only the eyes need it)."""
    import mediapipe as mp

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


class BodyReader:
    """MediaPipe's gesture recognizer and pose landmarker, in VIDEO mode (frames
    are a sequence, so it follows a hand from the last frame instead of searching
    from scratch)."""

    def __init__(
        self, folder: Path, hands: bool = True, poses: int = 1, fetcher: Fetcher = fetch
    ) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        video = vision.RunningMode.VIDEO
        self.gesture = None
        self.pose = None
        if hands:
            self.gesture = vision.GestureRecognizer.create_from_options(
                vision.GestureRecognizerOptions(
                    base_options=BaseOptions(
                        model_asset_path=str(model_path("gesture", folder, fetcher))
                    ),
                    running_mode=video,
                    num_hands=2,
                )
            )
        if poses > 0:
            self.pose = vision.PoseLandmarker.create_from_options(
                vision.PoseLandmarkerOptions(
                    base_options=BaseOptions(
                        model_asset_path=str(model_path("pose", folder, fetcher))
                    ),
                    running_mode=video,
                    num_poses=poses,
                )
            )
        self._last_ts = -1

    def read(self, image, timestamp_ms: int) -> tuple[list[Hand], list[list[Point]]]:
        """Hands and poses in one frame (``image`` from ``mp_image``)."""
        # VIDEO mode rejects timestamps that don't increase.
        timestamp_ms = self._last_ts = max(timestamp_ms, self._last_ts + 1)
        hands = (
            read_hands(self.gesture.recognize_for_video(image, timestamp_ms))
            if self.gesture
            else []
        )
        poses = read_poses(self.pose.detect_for_video(image, timestamp_ms)) if self.pose else []
        return hands, poses

    def close(self) -> None:
        for task in (self.gesture, self.pose):
            if task is not None:
                task.close()
