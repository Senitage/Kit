"""Who's who: telling the people Kit has been introduced to apart by their faces.

Nothing is trained. A ready-made face model (SFace, from the OpenCV Zoo, Apache
2.0) turns a straightened face into 128 numbers, an "embedding", so that two
pictures of the same person give numbers that point the same way. Introducing
someone (``kit eyes enrol NAME``) keeps a few dozen of their embeddings, in
Kit's data folder on the brain; recognising them is comparing a face in view
with those. No picture is ever kept, only the numbers, and forgetting someone
(``kit eyes forget NAME``) deletes them.

One look can be wrong (a blink, a hand in the way), so a person's name is only
agreed when several looks in a row say the same; someone checked many times
who matches nobody is "someone Kit doesn't know".

``Gallery`` and ``Recogniser`` are plain Python and the tests drive them with
made-up numbers; only ``SFaceEmbedder`` needs OpenCV.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from kit.eyes.body import Fetcher, fetch, model_path

EMBEDDING_SIZE = 128

LOOK_EVERY_S = 0.3  # someone not yet known: look again this often
RECHECK_EVERY_S = 10.0  # someone known: check now and then that it's still them
VOTES = 5  # the last few looks at each person...
AGREE = 3  # ...of which this many must name the same person
UNKNOWN_AFTER = 8  # this many looks matching nobody: someone Kit doesn't know

Vector = list[float]
Embed = Callable[[object, object], Vector | None]  # (frame, Face) -> embedding


def normalise(v: Iterable[float]) -> Vector:
    v = [float(x) for x in v]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two normalised embeddings: 1 the same, 0 unrelated."""
    return sum(x * y for x, y in zip(a, b, strict=True))


class Gallery:
    """The people Kit has been introduced to: a few embeddings each."""

    def __init__(self, people: dict[str, list[Vector]] | None = None, threshold: float = 0.4):
        self.people = {
            name: [normalise(v) for v in vectors if len(v) == EMBEDDING_SIZE]
            for name, vectors in (people or {}).items()
        }
        self.people = {name: vs for name, vs in self.people.items() if vs}
        self.threshold = threshold

    def __bool__(self) -> bool:
        return bool(self.people)

    def match(self, v: Vector) -> tuple[str | None, float]:
        """The best-matching name and how close it is, or None when nobody is close
        enough. Each person's closest embedding counts, so a few side-on shots
        don't drag down a good front-on match."""
        best, score = None, -1.0
        for name, vectors in self.people.items():
            s = max(similarity(v, known) for known in vectors)
            if s > score:
                best, score = name, s
        return (best, score) if score >= self.threshold else (None, max(score, 0.0))


@dataclass
class _Looks:
    last: float = -1e9
    checks: int = 0
    votes: deque = field(default_factory=lambda: deque(maxlen=VOTES))


class Recogniser:
    """Puts names to the people in a ``Scene``, from a few agreeing looks each."""

    def __init__(self, embed: Embed, gallery: Gallery | None = None) -> None:
        self.embed = embed
        self.gallery = gallery or Gallery()
        self._looks: dict[int, _Looks] = {}

    def update(self, frame, scene, now: float) -> None:
        """Look at the faces in this frame (the one ``scene`` was just updated from)."""
        self._looks = {k: v for k, v in self._looks.items() if k in scene.people}
        if not self.gallery:
            return  # nobody to know: don't spend the time
        for pid, info in scene.people.items():
            face = info.get("face")
            if face is None or face.align_points is None or not face.facing_camera:
                continue
            looks = self._looks.setdefault(pid, _Looks())
            wait = RECHECK_EVERY_S if scene.names.get(pid) else LOOK_EVERY_S
            if now - looks.last < wait:
                continue
            looks.last = now
            v = self.embed(frame, face)
            if v is None:
                continue
            name, score = self.gallery.match(v)
            face.name, face.similarity, face.checked = name, score, True
            looks.checks += 1
            looks.votes.append(name)
            named = Counter(n for n in looks.votes if n)
            agreed = next((n for n, c in named.most_common(1) if c >= AGREE), None)
            if agreed is not None:
                if agreed != scene.names.get(pid):
                    scene.recognise(pid, agreed)
            elif looks.checks >= UNKNOWN_AFTER and not named and not scene.names.get(pid):
                scene.unknown.add(pid)


class SFaceEmbedder:
    """OpenCV's SFace: a face (straightened by its five key points) to 128 numbers.
    Each face is read as it is and flipped, and the two added, so a mirrored
    webcam and an ordinary photo give the same numbers."""

    def __init__(self, folder: Path, fetcher: Fetcher = fetch) -> None:
        import cv2

        self.model = cv2.FaceRecognizerSF.create(str(model_path("sface", folder, fetcher)), "")

    def embed(self, frame, face) -> Vector | None:
        import numpy as np

        if face.align_points is None:
            return None
        x1, y1, x2, y2 = face.box
        row = np.array([[x1, y1, x2 - x1, y2 - y1, *face.align_points, 1.0]], dtype=np.float32)
        crop = self.model.alignCrop(frame, row)
        a = self.model.feature(crop)
        b = self.model.feature(np.ascontiguousarray(crop[:, ::-1]))
        return normalise((a + b).ravel().tolist())
