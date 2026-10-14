"""Dan's files: the folders he chooses (``files.roots``), walked, read and indexed
into the knowledge index as the ``files`` source, so recall and search find what's
inside a PDF, a Word file or a spreadsheet the way they find a note. Kit only reads
these folders. ``walk`` finds the files, ``extract`` turns each into text by page,
``fields`` picks out years, amounts and references, and ``index`` keeps the index
in step. See docs/2 How Kit Works/Your Files.md."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kit.settings import Settings
    from kit.settings_store import SettingsStore

FILES = "files"


@dataclass(frozen=True)
class Root:
    """One folder Kit indexes, by the short name Dan gave it."""

    name: str
    path: Path
    private: bool = False
    ocr: bool = False
    max_mb: int = 50


def roots_from(settings: Settings) -> list[Root]:
    return [
        Root(name, Path(r.path).expanduser(), r.private, r.ocr, r.max_mb)
        for name, r in settings.files.roots.items()
    ]


NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")


class RootError(ValueError):
    """A root that can't be added or changed, in words for Dan."""


def check_path(path: str) -> Path:
    """``path`` as a folder Kit can read, or RootError saying why not."""
    p = Path(path).expanduser()
    if not p.is_dir():
        raise RootError(f"{p} isn't a folder this machine can see")
    try:
        next(iter(os.scandir(p)), None)
    except OSError as e:
        raise RootError(f"{p} can't be read: {e.strerror or e}") from e
    return p


def _roots(store: SettingsStore) -> dict[str, dict]:
    return {n: r.model_dump(mode="json") for n, r in store.current().files.roots.items()}


def add_root(
    store: SettingsStore,
    name: str,
    path: str,
    private: bool = False,
    ocr: bool = False,
    changed_by: str = "cli",
) -> None:
    """Add a folder for Kit to index under the short ``name``."""
    if not NAME.match(name):
        raise RootError("a root's name is letters, digits, - and _ (e.g. finance)")
    roots = _roots(store)
    if name in roots:
        raise RootError(f"there's already a root called {name}")
    check_path(path)
    roots[name] = {"path": path, "private": private, "ocr": ocr}
    store.update({"files": {"roots": roots}}, changed_by)


def change_root(store: SettingsStore, name: str, changed_by: str = "cli", **change) -> None:
    """Change a root's ``private``, ``ocr`` or ``max_mb``."""
    roots = _roots(store)
    if name not in roots:
        raise RootError(f"no root called {name}")
    roots[name].update({k: v for k, v in change.items() if v is not None})
    store.update({"files": {"roots": roots}}, changed_by)


def remove_root(store: SettingsStore, name: str, changed_by: str = "cli") -> None:
    roots = _roots(store)
    if roots.pop(name, None) is None:
        raise RootError(f"no root called {name}")
    store.update({"files": {"roots": roots}}, changed_by)
