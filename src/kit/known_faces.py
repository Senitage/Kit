"""The people Kit has been introduced to, as his eyes know them (kit.eyes.recognise).

Each person is a name and a few dozen embeddings: 128 numbers worked out from a
face, from which no picture can be rebuilt. They're kept in one file in Kit's
data folder (``state/faces.json``), so moving Kit moves them and deleting
someone is deleting their entry. The eyes fetch them from the brain and do the
matching beside the camera; ``version`` goes up with every change, so running
eyes know to fetch them again.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from pydantic import BaseModel, Field

FACES_FILE = "faces.json"  # in the data folder's state folder
EMBEDDING_SIZE = 128
KEEP_PER_PERSON = 60  # newest kept: enough angles and lighting, small enough to send
NAME = re.compile(r"^[^\W\d_][\w .'-]{0,39}$")


class Enrolment(BaseModel):
    """Some new looks at someone, from ``kit eyes enrol``."""

    name: str = Field(min_length=1, max_length=40)
    embeddings: list[list[float]] = Field(min_length=1, max_length=200)


def clean_name(name: str) -> str:
    """A tidy name ("sam " -> "Sam"), or ValueError if it isn't one."""
    name = " ".join(name.split())
    if not NAME.match(name):
        raise ValueError(f"{name!r} isn't a name Kit can use: letters, spaces, ' . or -")
    return name[0].upper() + name[1:]


class KnownFaces:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.version = 0
        self.people: dict[str, list[list[float]]] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None:  # kept in memory only (tests)
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.version = int(data.get("version", 0))
        self.people = {
            str(name): [list(map(float, v)) for v in vectors if len(v) == EMBEDDING_SIZE]
            for name, vectors in data.get("people", {}).items()
        }

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"version": self.version, "people": self.people}), encoding="utf-8"
        )
        os.replace(tmp, self.path)

    def _find(self, name: str) -> str | None:
        return next((n for n in self.people if n.casefold() == name.casefold()), None)

    def add(self, name: str, embeddings: list[list[float]]) -> tuple[str, int]:
        """Keep more looks at someone (new or known). Returns their name as kept and
        how many looks Kit has of them now."""
        name = clean_name(name)
        good = [[round(float(x), 5) for x in v] for v in embeddings if len(v) == EMBEDDING_SIZE]
        if not good:
            raise ValueError(f"no usable face numbers (each must be {EMBEDDING_SIZE} long)")
        with self._lock:
            name = self._find(name) or name
            kept = (self.people.get(name, []) + good)[-KEEP_PER_PERSON:]
            self.people[name] = kept
            self.version += 1
            self._save()
            return name, len(kept)

    def forget(self, name: str) -> str | None:
        """Delete everything kept about someone's face. Returns the name forgotten."""
        with self._lock:
            found = self._find(name)
            if found is None:
                return None
            del self.people[found]
            self.version += 1
            self._save()
            return found

    def names(self) -> dict[str, int]:
        return {name: len(v) for name, v in sorted(self.people.items())}

    def as_dict(self) -> dict:
        return {"version": self.version, "people": self.people, "names": self.names()}
