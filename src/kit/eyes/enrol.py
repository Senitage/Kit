"""Introducing someone to Kit's eyes (``kit eyes enrol NAME``).

From the camera: the person sits in front of it and turns their head a little
while the eyes take a couple of dozen looks (faces found by MediaPipe, as when
the eyes run). From photos: every picture in a folder with exactly one face in
it (a group photo can't say which face is whose), found by OpenCV's YuNet,
which spots the smaller faces in photos that MediaPipe's webcam model misses.
Either way only the face numbers (kit.eyes.recognise) go to the brain; no
frame or photo is kept or sent.

``from_camera`` and ``from_photos`` take the camera, the face finder and the
embedder as plain callables, so the tests run them with fakes;
``build_enroller`` makes the real ones.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from kit.eyes.recognise import Vector, similarity

PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MAX_PHOTOS = 500
SHOT_GAP_S = 0.25  # between looks from the camera, so they differ a little
SAME_LOOK = 0.97  # a look this like the last one adds nothing


Look = Callable[[object], list]  # frame (BGR) -> faces in it (kit.eyes.faces.Face)
Embed = Callable[[object, object], Vector | None]


@dataclass
class Enroller:
    look: Look
    embed: Embed
    read_photo: Callable[[Path], object | None] = lambda path: None


def _one_face(faces: list, front_only: bool):
    if len(faces) != 1:
        return None
    face = faces[0]
    if face.align_points is None or (front_only and not face.facing_camera):
        return None
    return face


def yunet_faces(rows) -> list:
    """``Face``s from YuNet's rows: box, the five key points SFace straightens by
    (already in the order it wants), and a rough "facing the camera" from where
    the nose sits between the eyes."""
    from kit.eyes.faces import Face

    faces = []
    for row in [] if rows is None else rows:
        x, y, w, h = (float(v) for v in row[:4])
        points = [float(v) for v in row[4:14]]
        ex1, ex2, nose = points[0], points[2], points[4]
        span = abs(ex2 - ex1) or 1.0
        off = (nose - min(ex1, ex2)) / span  # 0.5: square on
        face = Face((int(x), int(y), int(x + w), int(y + h)), yaw=(off - 0.5) * 120)
        face.align_points = points
        faces.append(face)
    return faces


def from_camera(
    enroller: Enroller,
    read_frame: Callable[[], object | None],
    shots: int = 24,
    timeout_s: float = 90.0,
    say: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> list[Vector]:
    """Looks at the one person in front of the camera, ``shots`` times."""
    got: list[Vector] = []
    start = last = clock()
    last_said = ""
    while len(got) < shots and clock() - start < timeout_s:
        frame = read_frame()
        if frame is None:
            break
        faces = enroller.look(frame)
        hint = (
            "Kit can't see a face yet"
            if not faces
            else "more than one face in view: just the one person, please"
            if len(faces) > 1
            else ""
        )
        if hint and hint != last_said:
            say(hint)
            last_said = hint
        face = _one_face(faces, front_only=False)
        now = clock()
        if face is None or now - last < SHOT_GAP_S:
            continue
        v = enroller.embed(frame, face)
        if v is None or (got and similarity(v, got[-1]) >= SAME_LOOK):
            continue
        got.append(v)
        last, last_said = now, ""
        if len(got) % 6 == 0 and len(got) < shots:
            say(f"{len(got)} of {shots}: now turn your head a little the other way")
    return got


def photos_in(folder: Path) -> list[Path]:
    found = sorted(p for p in folder.rglob("*") if p.suffix.lower() in PHOTO_TYPES)
    return found[:MAX_PHOTOS]


def from_photos(
    enroller: Enroller, photos: Iterable[Path], say: Callable[[str], None] = print
) -> list[Vector]:
    """A look from each photo with exactly one clear face in it."""
    got: list[Vector] = []
    skipped = 0
    for path in photos:
        image = enroller.read_photo(path)
        face = _one_face(enroller.look(image), front_only=True) if image is not None else None
        v = enroller.embed(image, face) if face is not None else None
        if v is None:
            skipped += 1
            continue
        got.append(v)
    if skipped:
        say(
            f"skipped {skipped} photo(s): no face, more than one face, a face turned "
            "away, or a file Kit can't open"
        )
    return got


def build_enroller(models: Path, photos: bool) -> Enroller:
    """The real parts: a face finder (YuNet for ``photos``, else MediaPipe's, as the
    running eyes use) and SFace."""
    import cv2
    import numpy as np

    from kit.eyes.body import model_path
    from kit.eyes.recognise import SFaceEmbedder

    embedder = SFaceEmbedder(models)
    if photos:
        yunet = cv2.FaceDetectorYN.create(str(model_path("yunet", models)), "", (320, 320), 0.8)

        def look(frame) -> list:
            h, w = frame.shape[:2]
            yunet.setInputSize((w, h))
            return yunet_faces(yunet.detect(frame)[1])

    else:
        from kit.eyes.body import mp_image
        from kit.eyes.faces import FaceAnalyzer
        from kit.eyes.run import quiet_native_logs

        with quiet_native_logs():
            finder = FaceAnalyzer(models, num_faces=2)
        started = time.monotonic()

        def look(frame) -> list:
            h, w = frame.shape[:2]
            rgb = np.ascontiguousarray(frame[:, :, ::-1])
            ts = int((time.monotonic() - started) * 1000)
            return finder.detect(mp_image(rgb), (w, h), ts)

    def read_photo(path: Path):
        data = np.fromfile(str(path), dtype=np.uint8)  # imread can't open every Windows path
        image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        if image is None:
            return None
        h, w = image.shape[:2]
        if max(h, w) > 1600:  # big camera photos: faces are still plenty big
            scale = 1600 / max(h, w)
            image = cv2.resize(image, (int(w * scale), int(h * scale)))
        return image

    return Enroller(look, embedder.embed, read_photo)
