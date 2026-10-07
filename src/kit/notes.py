"""Dan's notes: the Obsidian vault on the NAS (``nas.vault``).

Kit reads the whole vault and takes notes in it when asked.

- Reading: every markdown note in the vault goes into the knowledge index
  (source ``notes``), split at its headings, so recall and memory search find
  it. ``sync`` brings the index up to date with the files (new, changed and
  deleted notes) and runs at start-up, every upkeep round, and after Kit writes
  a note. Folders starting with a dot (``.obsidian``, ``.trash``, Synology's own)
  and Synology's ``@eaDir`` and ``#recycle`` are skipped. ``read`` gives a whole
  note by name, for the ``read_note`` action.
- Writing: a note Dan asks for ("take a note: ...") is a plain markdown file.
  If a note with that title already exists anywhere in the vault, the text is
  added at the end under the time, so "add milk to my shopping list" keeps one
  list. Otherwise it's a new note in ``nas.notes_folder`` (or wherever the
  title's folder says, e.g. "Projects/Kit ideas").

The vault is the only place on the NAS Kit may write.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from kit.knowledge import Index
from kit.settings import NasSettings

NOTES = "notes"
NOTE = "note"  # the kind of item: part of a note in the vault
CHUNK_CHARS = 1500  # a section longer than this is split at paragraphs
READ_CHARS = 8000  # how much of one note Kit reads at once
ALL = 1_000_000  # every item of the source
SKIP_DIRS = {"@eaDir", "#recycle", "#snapshot"}
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n?", re.S)
_ASKED = re.compile(
    r"^\W*(?:(?:can|could|would) you\s+|please\s+)*(?:(?:take|make|write|jot)\s+(?:down\s+)?"
    r"(?:a\s+)?(?:quick\s+)?(?:note|memo)?|note\b)\s*(?:down\s+)?(?:for me\s*)?"
    r"(?:(?:stating|saying|says|that|about|of|on)\b\s*)*[:,-]?\s*",
    re.IGNORECASE,
)
TITLE_MAX = 80
TITLE_WORDS = 6  # a note Kit names himself is called after its first few words
CLOSE_ENOUGH = 0.82  # how alike a note's name and Dan's words must be ("holday planner")
# Plainly asking for a note to be written: "take a note", "jot this down", "note that".
_WRITE = re.compile(
    r"\b(?:take|make|jot|write)\b(?:\W+\w+){0,3}?\W+(?:note|memo|down)\b|"
    r"^\W*note(?:\s+(?:that|this|down)\b|\s*:)",
    re.IGNORECASE,
)
# Dan's message is about his notes at all: only then may the model write one.
_ABOUT_NOTES = re.compile(
    r"\b(?:notes?|jot|memo|write\s+(?:\w+\s+)?down|list|planner)\b", re.IGNORECASE
)
# "add book the car to my holiday planner", "put milk on the shopping list".
_ADD_TO = re.compile(
    r"^\W*(?:(?:can|could|would) you\s+|please\s+)*(?:add|put|append|stick|pop)\s+"
    r"(?P<what>.+?)\s+(?:to|in|into|on|onto)\s+(?:my|the|our)\s+(?P<note>[^.?!,]+?)"
    r"(?:\s+(?:note|notes|file|page))?\s*(?:please)?\W*$",
    re.IGNORECASE,
)
# Asking about a note: "what's in my holiday planner?", "read me my shopping list".
_READ = re.compile(
    r"\b(?:what'?s|whats|what is|what have i got|what do i have|read|open|show|check|"
    r"look at|go through|go over|summari[sz]e|tell me)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[\w']+")
_NOTEISH = {"note", "notes", "list", "file", "page", "planner", "plan", "log", "journal"}
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


def asked_text(message: str) -> str:
    """What Dan wants noted, from his whole message, when the model left the note
    empty: "take a note for me stating that the tap leaks" gives "the tap leaks"."""
    text = _ASKED.sub("", message.strip(), count=1).strip()
    return text[:1].upper() + text[1:] if text else ""


@dataclass
class Request:
    """A plain request about Dan's notes, spotted in his own words so Kit doesn't
    depend on a small model choosing the right action."""

    kind: str  # "take" (a new note), "add" (to an existing note) or "read"
    note: str  # the note's name ("" for a new note Kit names)
    text: str = ""  # what to write


def mentioned(message: str, names: Iterable[str]) -> str | None:
    """The note ``message`` talks about, by name, forgiving a typo ("holday
    planner"). A one-word name only counts as "my <name>" or "<name> note", so
    "what's up, Kit?" doesn't open the note called Kit."""
    words = [w.lower() for w in _WORD.findall(message)]
    best, best_score = None, 0.0
    for name in names:
        stem = name.rsplit("/", 1)[-1].lower()
        size = len(_WORD.findall(stem))
        if not size:
            continue
        for i in range(len(words) - size + 1):
            window = " ".join(words[i : i + size])
            score = SequenceMatcher(None, window, stem).ratio()
            if score < CLOSE_ENOUGH or score <= best_score:
                continue
            before = words[i - 1] if i else ""
            after = words[i + size] if i + size < len(words) else ""
            if size == 1 and before not in {"my", "the", "our"} and after not in _NOTEISH:
                continue
            best, best_score = name, score
    return best


def request(message: str, names: Iterable[str]) -> Request | None:
    """What Dan is plainly asking of his notes, or None to leave it to the model."""
    names = list(names)
    added = _ADD_TO.match(message.strip())
    if added:
        note = mentioned(added.group("note"), names) or (
            added.group("note").strip()
            if added.group("note").split()[-1].lower() in _NOTEISH
            else None
        )
        if note:
            return Request("add", note, added.group("what").strip(" '\""))
    if _WRITE.search(message):
        text = asked_text(message)
        return Request("take", "", text) if text else None
    if _READ.search(message):
        note = mentioned(message, names)
        if note:
            return Request("read", note)
    return None


def asks_for_note(message: str) -> bool:
    """Dan's message asks for something to be written in his notes. Kit never takes
    a note on his own: without this he offers instead ("want me to note that?")."""
    return bool(_ABOUT_NOTES.search(message))


def title_for(text: str) -> str:
    """A name for a new note from what it says: its first few words."""
    words = _WORD.findall(text.split("\n", 1)[0])[:TITLE_WORDS]
    title = " ".join(words)
    return title[:1].upper() + title[1:]


def skipped(rel: Path) -> bool:
    """Folders Kit doesn't read: Obsidian's settings, the trash, the NAS's own."""
    return any(p.startswith(".") or p in SKIP_DIRS for p in rel.parts[:-1])


def sections(name: str, text: str) -> list[tuple[str, str]]:
    """A note as (title, text) pieces, split at headings and long sections at
    paragraphs, so a search finds the part that matters."""
    text = _FRONTMATTER.sub("", text.replace("\r\n", "\n"))
    parts: list[tuple[str, list[str]]] = [(name, [])]
    for line in text.split("\n"):
        heading = _HEADING.match(line)
        if heading:
            parts.append((f"{name} > {heading.group(1)}", [line]))
        else:
            parts[-1][1].append(line)
    out = []
    for title, lines in parts:
        body = "\n".join(lines).strip()
        while len(body) > CHUNK_CHARS:
            cut = body.rfind("\n\n", 0, CHUNK_CHARS)
            cut = cut if cut > CHUNK_CHARS // 3 else CHUNK_CHARS
            out.append((title, body[:cut].strip()))
            body = body[cut:].strip()
        if body:
            out.append((title, body))
    return out


class Notes:
    def __init__(self, index: Index, clock: Callable[[], datetime]) -> None:
        self.index = index
        self.clock = clock

    # Reading

    def sync(self, nas: NasSettings) -> tuple[int, int]:
        """Bring the index up to date with the vault. Returns (notes indexed, notes
        removed). An unreachable vault changes nothing, so a NAS blip doesn't make
        Kit forget every note."""
        if not nas.vault or not Path(nas.vault).is_dir():
            return 0, 0
        vault = Path(nas.vault)
        known = self._known()
        seen, indexed = set(), 0
        for path in vault.rglob("*.md"):
            rel = path.relative_to(vault)
            if skipped(rel):
                continue
            ref = rel.as_posix()
            seen.add(ref)
            try:
                mtime = path.stat().st_mtime
                if known.get(ref) == mtime:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            self._index_note(ref, path.stem, text, mtime)
            indexed += 1
        gone = [ref for ref in known if ref not in seen]
        for ref in gone:
            self.index.delete_source(NOTES, ref)
        return indexed, len(gone)

    def _known(self) -> dict[str, float]:
        return {
            item.ref: item.meta.get("mtime")
            for item in self.index.items(NOTES, limit=ALL)
            if item.ref is not None
        }

    def _index_note(self, ref: str, name: str, text: str, mtime: float) -> None:
        self.index.delete_source(NOTES, ref)
        for title, body in sections(name, text) or [(name, name)]:
            self.index.add(NOTES, NOTE, body, title=title, ref=ref, meta={"mtime": mtime})

    def names(self, limit: int = 40) -> list[str]:
        """The vault's notes (path without .md), most recently changed first."""
        newest: dict[str, float] = {}
        for item in self.index.items(NOTES, limit=ALL):
            if item.ref:
                newest[item.ref] = item.meta.get("mtime") or 0
        refs = sorted(newest, key=lambda r: newest[r], reverse=True)[:limit]
        return [r.removesuffix(".md") for r in refs]

    def find(self, nas: NasSettings, name: str) -> Path | None:
        """The note called ``name``: a path in the vault ("Projects/Kit"), or a
        title anywhere in it, ignoring case and ".md". None if there isn't one."""
        if not nas.vault:
            return None
        vault = Path(nas.vault)
        wanted = name.strip().strip("[]").removesuffix(".md").strip().strip("/")
        if not wanted:
            return None
        refs = {
            item.ref
            for item in self.index.items(NOTES, limit=ALL)
            if item.ref and (vault / item.ref).exists()
        }
        lower = wanted.lower()
        for ref in sorted(refs):
            if ref.removesuffix(".md").lower() == lower:
                return vault / ref
        stem = lower.rsplit("/", 1)[-1]
        matches = sorted(r for r in refs if Path(r).stem.lower() == stem)
        return vault / matches[0] if matches else None

    def read(self, nas: NasSettings, name: str) -> tuple[str, str]:
        """(where it is in the vault, its text) for the note called ``name``."""
        path = self.find(nas, name)
        if path is None:
            raise NoteError(f"there's no note called {name.strip() or 'that'}")
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise NoteError(f"couldn't open {path.name}: {e.strerror or e}") from e
        text = _FRONTMATTER.sub("", text).strip()
        if len(text) > READ_CHARS:
            text = text[:READ_CHARS] + "\n[... the rest of the note is longer than this]"
        return path.relative_to(Path(nas.vault)).as_posix(), text

    # Writing

    def take(self, nas: NasSettings, title: str, text: str) -> Saved:
        text = text.strip()
        if not text:
            raise NoteError("the note was empty")
        now = self.clock()
        folder = notes_folder(nas)
        vault = Path(nas.vault)
        if not vault.is_dir():
            raise NoteError(f"can't reach {nas.vault}; is the NAS mounted?")
        path = self.find(nas, title) if title.strip() else None
        if path is None:
            *where, name = title.replace("\\", "/").split("/")
            if where:  # "Projects/Kit ideas": a folder of its own in the vault
                parts = [_UNSAFE.sub(" ", w).strip(" .") for w in where]
                if any(parts):
                    folder = vault.joinpath(*(p for p in parts if p))
            path = folder / file_name(name, now)
        path.parent.mkdir(parents=True, exist_ok=True)
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
        shown = path.relative_to(vault).as_posix()
        try:
            self._index_note(
                shown, path.stem, path.read_text(encoding="utf-8"), path.stat().st_mtime
            )
        except OSError:
            pass  # saved; the next sync indexes it
        return Saved(path, shown, added)
