"""Finding the files under each root: depth first, skipping the folders and names in
``files.skip``, files over the root's size cap, symlinks and types Kit can't read.
A folder that can't be read is logged and skipped, never fatal."""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from kit.files import Root

log = logging.getLogger(__name__)

KINDS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pptx": "pptx",
    ".txt": "txt",
    ".md": "md",
    ".csv": "csv",
}


@dataclass(frozen=True)
class Found:
    """A file Kit can read. ``ref`` is ``root:relative/path`` with forward slashes,
    never an absolute path, so the index survives a mount moving."""

    root: str
    path: Path
    rel: str
    size: int
    modified: float
    kind: str

    @property
    def ref(self) -> str:
        return f"{self.root}:{self.rel}"


@dataclass
class Changes:
    new: list[Found] = field(default_factory=list)
    changed: list[Found] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)  # refs


def skipped(name: str, skip: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in skip)


class Walker:
    def __init__(
        self,
        roots: list[Root],
        skip: list[str],
        scandir: Callable[[Path], object] = os.scandir,
    ) -> None:
        self.roots = roots
        self.skip = skip
        self.scandir = scandir
        self.errors: list[tuple[str, str]] = []  # (where, why) from the last walk

    def walk(self, only: str | None = None) -> Iterator[Found]:
        self.errors = []
        for root in self.roots:
            if only is None or root.name == only:
                yield from self._walk(root, root.path, "")

    def _walk(self, root: Root, folder: Path, rel: str) -> Iterator[Found]:
        try:
            with self.scandir(folder) as entries:
                listed = sorted(entries, key=lambda e: e.name)
        except OSError as e:
            log.warning("couldn't read %s: %s", folder, e)
            self.errors.append((f"{root.name}:{rel or '.'}", str(e)))
            return
        cap = root.max_mb * 1024 * 1024
        for entry in listed:
            if skipped(entry.name, self.skip):
                continue
            child = f"{rel}/{entry.name}" if rel else entry.name
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    yield from self._walk(root, Path(entry.path), child)
                    continue
                kind = KINDS.get(Path(entry.name).suffix.lower())
                if kind is None:
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError as e:
                self.errors.append((f"{root.name}:{child}", str(e)))
                continue
            if st.st_size > cap:
                continue
            yield Found(root.name, Path(entry.path), child, st.st_size, st.st_mtime, kind)


def changes(found: list[Found], known: dict[str, tuple[float, int]]) -> Changes:
    """What's new, changed (time or size) and gone, against what the index holds
    (``ref -> (modified, size)``)."""
    out = Changes()
    seen = set()
    for f in found:
        seen.add(f.ref)
        before = known.get(f.ref)
        if before is None:
            out.new.append(f)
        elif before != (f.modified, f.size):
            out.changed.append(f)
    out.gone = [ref for ref in known if ref not in seen]
    return out
