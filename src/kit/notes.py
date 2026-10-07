"""Notes Dan asks Kit to take ("take a note: ...", "jot down ...").

Each note is a plain markdown file in the notes folder (``nas.notes_folder``)
inside the Obsidian vault (``nas.vault``), the only place on the NAS Kit may
write, so Obsidian shows it like any other note. The file is named after the
note's title; a note with the same title gets the new text added at the end
under the time, so "add milk to my shopping list" keeps one list.

Every note Kit takes also goes into the knowledge index (source ``notes``), so
"what did I note about the fridge?" finds it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kit.knowledge import Index
from kit.settings import NasSettings

NOTES = "notes"
NOTE = "note"  # the kind of item: a note Kit took
TITLE_MAX = 80
# Characters Windows, Obsidian links or the NAS won't take in a file name.
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10))}
_RESERVED |= {f"LPT{i}" for i in range(1, 10)}


class NoteError(Exception):
    """The note couldn't be saved; the message says why, in plain words."""


@dataclass
class Saved:
    path: Path
    shown: str  # where it went, relative to the vault, as Dan would see it in Obsidian
    added: bool  # True if the text went on the end of an existing note


def file_name(title: str, when: datetime) -> str:
    """A safe file name for a note titled ``title``."""
    name = _UNSAFE.sub(" ", title)
    name = re.sub(r"\s+", " ", name).strip(" .")[:TITLE_MAX].strip(" .")
    if not name:
        name = f"Note {when:%Y-%m-%d %H%M}"
    if name.upper() in _RESERVED:
        name += " note"
    return f"{name}.md"


def notes_folder(nas: NasSettings) -> Path:
    """The folder notes go in, checked to be inside the vault."""
    if not nas.vault:
        raise NoteError("no notes folder is set up yet (nas.vault in settings)")
    vault = Path(nas.vault)
    folder = vault / nas.notes_folder if nas.notes_folder else vault
    if not folder.resolve().is_relative_to(vault.resolve()):
        raise NoteError(f"the notes folder {nas.notes_folder} isn't inside the vault")
    return folder


class Notes:
    def __init__(self, index: Index, clock: Callable[[], datetime]) -> None:
        self.index = index
        self.clock = clock

    def take(self, nas: NasSettings, title: str, text: str) -> Saved:
        text = text.strip()
        if not text:
            raise NoteError("the note was empty")
        now = self.clock()
        folder = notes_folder(nas)
        if not folder.is_dir():
            if not Path(nas.vault).is_dir():
                raise NoteError(f"can't reach {nas.vault}; is the NAS mounted?")
            folder.mkdir(parents=True, exist_ok=True)
        path = folder / file_name(title, now)
        added = path.exists()
        try:
            if added:
                with path.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(f"\n\n**{now:%a %d %b %Y, %H:%M}**\n\n{text}\n")
            else:
                path.write_text(
                    f"---\ncreated: {now:%Y-%m-%dT%H:%M}\ntags: [kit]\n---\n\n{text}\n",
                    encoding="utf-8",
                    newline="\n",
                )
        except OSError as e:
            raise NoteError(f"couldn't write {path.name}: {e.strerror or e}") from e
        shown = path.relative_to(Path(nas.vault)).as_posix()
        self.index.add(NOTES, NOTE, text, title=path.stem, ref=shown)
        return Saved(path, shown, added)
