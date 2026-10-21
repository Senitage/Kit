"""Changing Dan's notes: adding under a heading, editing a line, ticking a task,
starting a note, and undoing the last change.

Every change is built first and shown (``preview``: a short diff), then applied
only after Dan's yes (kit.tools.confirm), except a note he plainly asked for.
Applying re-reads the note and refuses if it changed since the change was built
(edited in Obsidian meanwhile), so Kit never writes over Dan's own edit. The note
as it was goes into the undo folder first; ``undo`` puts the newest one back,
unless the note changed again since. Kit never renames, moves or deletes a note.
See docs/2 How Kit Works/Notes on the NAS.md#Changing a note."""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kit.notes import _HEADING, NoteError, file_name, notes_folder
from kit.notes_tasks import _TASK

if TYPE_CHECKING:
    from kit.notes import Notes
    from kit.settings import NasSettings

PREVIEW_LINES = 20


class NoteChanged(NoteError):
    """The note changed after the change was built: read it again first."""


@dataclass
class Applied:
    path: Path
    shown: str  # where it is in the vault
    undo_file: Path | None


@dataclass
class Change:
    """One change to one note, built against the note as it is now."""

    note: str  # how Dan named it
    path: Path = field(init=False)
    before: str = field(init=False, default="")
    mtime: float | None = field(init=False, default=None)  # None: a new note
    after: str = field(init=False, default="")
    what: str = field(init=False, default="")  # in words, for the ask and the undo log

    def build(self, notes: Notes, nas: NasSettings) -> Change:
        path = notes.find(nas, self.note)
        if path is None:
            raise NoteError(f"there's no note called {self.note.strip() or 'that'}")
        self.path = path
        try:
            self.before = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            self.mtime = path.stat().st_mtime
        except OSError as e:
            raise NoteError(f"couldn't open {path.name}: {e.strerror or e}") from e
        self.after = self.change(self.before)
        return self

    def change(self, text: str) -> str:
        raise NotImplementedError

    def preview(self) -> str:
        """A unified diff of the change, at most ``PREVIEW_LINES`` lines."""
        lines = list(
            difflib.unified_diff(
                self.before.splitlines(), self.after.splitlines(), lineterm="", n=1
            )
        )[2:]  # no ---/+++ header
        if len(lines) > PREVIEW_LINES:
            lines = lines[:PREVIEW_LINES] + [f"... ({len(lines) - PREVIEW_LINES} more lines)"]
        return "\n".join(lines)

    def apply(self, nas: NasSettings, undo_dir: Path, clock: Callable[[], datetime],
              keep: int = 50) -> Applied:  # fmt: skip
        vault = Path(nas.vault or "")
        shown = self.path.relative_to(vault).as_posix()
        undo_file = None
        try:
            if self.mtime is None:
                if self.path.exists():
                    raise NoteChanged(f"{shown} appeared since; look at it again first")
                self.path.parent.mkdir(parents=True, exist_ok=True)
            else:
                if not self.path.exists() or self.path.stat().st_mtime != self.mtime:
                    raise NoteChanged(
                        f"{shown} changed since I read it (edited in Obsidian?); "
                        "read it again before changing it"
                    )
                undo_file = save_undo(undo_dir, shown, self.before, self.what, clock, keep)
            self.path.write_text(self.after, encoding="utf-8", newline="\n")
            if undo_file is not None:  # what the note looks like after: undo checks it
                side = undo_file.with_suffix(".json")
                data = json.loads(side.read_text(encoding="utf-8"))
                data["after_mtime"] = self.path.stat().st_mtime
                side.write_text(json.dumps(data), encoding="utf-8")
        except NoteError:
            raise
        except OSError as e:
            raise NoteError(f"couldn't write {self.path.name}: {e.strerror or e}") from e
        return Applied(self.path, shown, undo_file)


def _ensure_newline(text: str) -> str:
    return text if not text or text.endswith("\n") else text + "\n"


@dataclass
class Append(Change):
    """Add ``text`` at the end of a section (``section``: its heading), else the note."""

    text: str = ""
    section: str = ""

    def change(self, text: str) -> str:
        add = self.text.strip("\n")
        if not add.strip():
            raise NoteError("there was nothing to add")
        self.what = f"added to {self.note}" + (f" under {self.section}" if self.section else "")
        lines = text.split("\n")
        if not self.section.strip():
            body = text.rstrip("\n")
            return f"{body}\n{add}\n" if body else f"{add}\n"
        start, level = _find_heading(lines, self.section)
        if start is None:
            names = [h for _, h, _ in _headings(lines)]
            listed = ", ".join(names[:12]) or "none"
            raise NoteError(f"{self.note} has no heading '{self.section}' (its headings: {listed})")
        end = len(lines)
        for i in range(start + 1, len(lines)):
            h = _HEADING.match(lines[i])
            if h and _level(lines[i]) <= level:
                end = i
                break
        # After the section's last line that isn't blank.
        last = end
        while last > start + 1 and not lines[last - 1].strip():
            last -= 1
        new = lines[:last] + add.split("\n") + lines[last:]
        if end < len(lines) and last == end:
            new.insert(last + len(add.split("\n")), "")
        return _ensure_newline("\n".join(new))


@dataclass
class Edit(Change):
    """Replace the one place ``find`` appears with ``replace``."""

    find: str = ""
    replace: str = ""

    def change(self, text: str) -> str:
        if not self.find:
            raise NoteError("say what to change")
        count = text.count(self.find)
        if count != 1:
            where = "isn't in" if count == 0 else f"is in {count} places in"
            raise NoteError(f"'{self.find}' {where} {self.note}; it has to be in exactly one")
        self.what = f"changed '{_short(self.find)}' in {self.note}"
        return text.replace(self.find, self.replace, 1)


@dataclass
class Tick(Change):
    """Tick the one open task whose words contain ``task`` (any case)."""

    task: str = ""

    def change(self, text: str) -> str:
        want = self.task.strip().lower()
        if not want:
            raise NoteError("say which task to tick")
        lines = text.split("\n")
        hits = []
        for i, line in enumerate(lines):
            m = _TASK.match(line)
            if m and m.group("mark") == " " and want in m.group("text").lower():
                hits.append(i)
        if not hits:
            raise NoteError(f"there's no open task like '{self.task}' in {self.note}")
        if len(hits) > 1:
            shown = "; ".join(_TASK.match(lines[i]).group("text") for i in hits[:6])
            raise NoteError(f"'{self.task}' could be several tasks: {shown}. Which one?")
        i = hits[0]
        lines[i] = lines[i].replace("[ ]", "[x]", 1)
        self.what = f"ticked '{_short(_TASK.match(lines[i]).group('text'))}' in {self.note}"
        return "\n".join(lines)


@dataclass
class New(Change):
    """A new note called ``title``, in ``folder`` (else the notes folder), from a
    template (a note in the templates folder) when one is named."""

    title: str = ""
    folder: str = ""
    template: str = ""
    text: str = ""
    templates_folder: str = ""

    def build(self, notes: Notes, nas: NasSettings) -> Change:
        title = self.title.strip() or self.note.strip()
        if not title:
            raise NoteError("a new note needs a name")
        if notes.find(nas, title) is not None:
            raise NoteError(f"there's already a note called {title}; add to it instead")
        vault = Path(nas.vault or "")
        folder = notes_folder(nas)
        if self.folder.strip():
            folder = vault / self.folder.strip().strip("/\\")
            if not folder.resolve().is_relative_to(vault.resolve()):
                raise NoteError(f"{self.folder} isn't inside the vault")
        now = notes.clock()
        self.path = folder / file_name(title, now)
        if self.path.exists():  # made since the last sync
            raise NoteError(f"there's already a note called {title}; add to it instead")
        self.mtime = None
        body = ""
        if self.template.strip():
            body = self._template(notes, nas, title, now)
        text = self.text.strip()
        if body and text:
            body = body.rstrip("\n") + "\n\n" + text + "\n"
        elif text:
            body = f"---\ncreated: {now:%Y-%m-%dT%H:%M}\ntags: [kit]\n---\n\n{text}\n"
        elif not body:
            body = f"---\ncreated: {now:%Y-%m-%dT%H:%M}\ntags: [kit]\n---\n\n"
        self.after = body
        self.what = f"started {self.path.relative_to(vault).as_posix()}"
        return self

    def _template(self, notes: Notes, nas: NasSettings, title: str, now: datetime) -> str:
        wanted = self.template.strip()
        if self.templates_folder and "/" not in wanted:
            wanted = f"{self.templates_folder.strip('/')}/{wanted}"
        path = notes.find(nas, wanted) or notes.find(nas, self.template)
        if path is None:
            raise NoteError(f"there's no template called {self.template}")
        try:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except OSError as e:
            raise NoteError(f"couldn't open the template: {e.strerror or e}") from e
        for key, value in {
            "title": title,
            "date": f"{now:%Y-%m-%d}",
            "time": f"{now:%H:%M}",
        }.items():
            text = re.sub(r"\{\{\s*" + key + r"(?::[^}]*)?\s*\}\}", value, text)
        return text


def _short(text: str, n: int = 40) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _level(line: str) -> int:
    return len(line) - len(line.lstrip("#"))


def _headings(lines: list[str]) -> list[tuple[int, str, int]]:
    out = []
    fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence and (h := _HEADING.match(line)):
            out.append((i, h.group(1), _level(line)))
    return out


def _find_heading(lines: list[str], name: str) -> tuple[int | None, int]:
    """The heading called ``name`` (any case, a leading '#' ignored), else one that
    starts with it."""
    want = name.strip().lstrip("#").strip().lower()
    heads = _headings(lines)
    for i, h, level in heads:
        if h.strip().lower() == want:
            return i, level
    starts = [(i, level) for i, h, level in heads if h.strip().lower().startswith(want)]
    if len(starts) == 1:
        return starts[0]
    return None, 0


# Undo


def save_undo(undo_dir: Path, shown: str, before: str, what: str,
              clock: Callable[[], datetime], keep: int) -> Path:  # fmt: skip
    """The note as it was, with a small JSON beside it; keeps the newest ``keep``."""
    undo_dir.mkdir(parents=True, exist_ok=True)
    now = clock()
    stem = f"{now:%Y%m%d-%H%M%S-%f}-{file_name(shown.replace('/', ' '), now)[:-3]}"
    path = undo_dir / f"{stem}.md"
    path.write_text(before, encoding="utf-8", newline="\n")
    side = {"note": shown, "applied_at": now.isoformat(timespec="seconds"), "change": what}
    path.with_suffix(".json").write_text(json.dumps(side), encoding="utf-8")
    old = sorted(undo_dir.glob("*.md"))
    for extra in old[: max(0, len(old) - keep)]:
        extra.unlink(missing_ok=True)
        extra.with_suffix(".json").unlink(missing_ok=True)
    return path


def last_undo(undo_dir: Path) -> tuple[Path, dict] | None:
    """The newest undo file and what it says, or None."""
    files = sorted(undo_dir.glob("*.md")) if undo_dir.is_dir() else []
    for path in reversed(files):
        try:
            side = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return path, side
    return None


def undo(nas: NasSettings, undo_dir: Path) -> str:
    """Put back the note the last change was made to. Refuses if the note changed
    again since (someone else's edit would be lost). Says what it did."""
    found = last_undo(undo_dir)
    if found is None:
        raise NoteError("there's nothing of mine to undo")
    path, side = found
    note = Path(nas.vault or "") / side["note"]
    try:
        changed = note.stat().st_mtime
    except OSError as e:
        raise NoteError(f"{side['note']} isn't there any more") from e
    if side.get("after_mtime") is not None and changed != side["after_mtime"]:
        # Written after Kit's change: undoing would lose that edit.
        stamp = datetime.fromtimestamp(changed)
        raise NoteError(
            f"{side['note']} was changed again at {stamp:%H:%M} after mine; "
            "undoing now would lose that edit"
        )
    try:
        note.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    except OSError as e:
        raise NoteError(f"couldn't write {note.name}: {e.strerror or e}") from e
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)
    return f"put {side['note']} back as it was before I {side['change']}"
