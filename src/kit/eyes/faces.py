"""Faces: where someone is looking and their expression (and, from stage 2,
who they are).

MediaPipe's Face Landmarker gives 478 points per face, 52 "blendshape" scores
that measure facial movements (smile, jaw open, brows raised...) and the
head's 3D rotation. ``Face``, ``read_expressions`` and ``head_direction`` are
plain Python; only ``FaceAnalyzer`` needs MediaPipe.

Nothing here stores an image. Recognition (stage 2) keeps embeddings only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from kit.eyes.body import Fetcher, fetch, model_path

Box = tuple[int, int, int, int]

# Only recognise faces turned less than this many degrees from the camera:
# side-on faces give poor embeddings.
MAX_TURN_FOR_RECOGNITION = 30


@dataclass
class Face:
    box: Box  # x1, y1, x2, y2 in pixels
    yaw: float = 0.0  # degrees; + = turned to their right (mirrored view)
    pitch: float = 0.0  # degrees; + = looking up
    scores: dict[str, float] = field(default_factory=dict)  # the 52 blendshapes, 0-1
    expressions: list[str] = field(default_factory=list)
    name: str | None = None  # set by recognition (stage 2)
    similarity: float = 0.0
    checked: bool = False  # True once recognition has been run on it
    align_points: object = None  # the 5 key points recognition straightens by

    @property
    def jaw(self) -> float | None:
        return self.scores.get("jawOpen")

    @property
    def facing_camera(self) -> bool:
        turn = MAX_TURN_FOR_RECOGNITION
        return abs(self.yaw) < turn and abs(self.pitch) < turn + 10

    @property
    def looking(self) -> str:
        return head_direction(self.yaw, self.pitch)


def read_expressions(s: dict[str, float]) -> list[str]:
    """Turn blendshape scores into expression words.

    Blendshapes measure muscle movements, not feelings: "smiling" is reliable,
    "happy" would be a guess. Thresholds were tuned on a live webcam.
    """

    def both(name: str) -> float:  # average of the left and right versions
        return (s.get(name + "Left", 0.0) + s.get(name + "Right", 0.0)) / 2

    jaw, brow_in = s.get("jawOpen", 0.0), s.get("browInnerUp", 0.0)
    found = []
    if both("mouthSmile") > 0.5:
        found.append("smiling")
    if both("mouthFrown") > 0.3 or both("browDown") > 0.45:
        found.append("frowning")
    if jaw > 0.35 and brow_in > 0.4:
        found.append("surprised")
    elif jaw > 0.35:
        found.append("mouth open")
    if both("eyeBlink") > 0.6:
        found.append("eyes closed")
    elif "surprised" not in found and (brow_in > 0.5 or both("browOuterUp") > 0.5):
        found.append("eyebrows raised")
    return found


def head_direction(yaw: float, pitch: float) -> str:
    """Describe head rotation in words, from the person's own point of view."""
    parts = []
    if pitch > 35:
        parts.append("up")
    elif pitch < -20:
        parts.append("down")
    if yaw > 25:
        parts.append("to their right")
    elif yaw < -25:
        parts.append("to their left")
    return "looking " + " and ".join(parts) if parts else "facing the camera"


# Landmark numbers in MediaPipe's 478-point face mesh.
IRIS_A, IRIS_B, NOSE_TIP, MOUTH_A, MOUTH_B = 468, 473, 1, 61, 291


class FaceAnalyzer:
    """MediaPipe's Face Landmarker in VIDEO mode: boxes, head angles and
    expressions for up to ``num_faces`` faces a frame."""

    def __init__(self, folder: Path, num_faces: int = 2, fetcher: Fetcher = fetch) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        self.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model_path("face", folder, fetcher))),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=num_faces,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
        )
        self._last_ts = -1

    def detect(self, image, frame_size: tuple[int, int], timestamp_ms: int) -> list[Face]:
        """The faces in one frame (``image`` from ``kit.eyes.body.mp_image``)."""
        timestamp_ms = self._last_ts = max(timestamp_ms, self._last_ts + 1)
        result = self.landmarker.detect_for_video(image, timestamp_ms)
        return read_faces(result, frame_size)

    def close(self) -> None:
        self.landmarker.close()


def read_faces(result, frame_size: tuple[int, int]) -> list[Face]:
    """``Face``s from a MediaPipe face landmarker result."""
    w, h = frame_size
    faces = []
    for points, blendshapes, matrix in zip(
        result.face_landmarks,
        result.face_blendshapes,
        result.facial_transformation_matrixes,
        strict=True,
    ):
        xs = [p.x * w for p in points]
        ys = [p.y * h for p in points]
        box = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
        # The matrix rotates a standard face model into the camera's view. Its third
        # column is the direction the face points; turn that into angles.
        fx, fy, fz = (float(row[2]) for row in list(matrix)[:3])
        yaw, pitch = math.degrees(math.atan2(fx, fz)), math.degrees(math.atan2(fy, fz))
        scores = {b.category_name: float(b.score) for b in blendshapes}

        face = Face(box, yaw, pitch, scores, read_expressions(scores))
        face.align_points = _align_points(points, w, h)
        faces.append(face)
    return faces


def _align_points(points, w: int, h: int) -> list[float]:
    """The 5 points recognition straightens a face by (both eyes, nose tip, both
    mouth corners), each pair ordered left to right in the image, in pixels."""

    def px(i: int) -> tuple[float, float]:
        return (points[i].x * w, points[i].y * h)

    eyes = sorted([px(IRIS_A), px(IRIS_B)])
    mouth = sorted([px(MOUTH_A), px(MOUTH_B)])
    return [*eyes[0], *eyes[1], *px(NOSE_TIP), *mouth[0], *mouth[1]]
