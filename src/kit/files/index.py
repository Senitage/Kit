"""Keeping the knowledge index in step with Dan's folders. A sync walks the roots,
compares each file's time and size with what the index holds, and re-reads only
what's new or changed: each page split into pieces of about ``files.chunk_words``
words at paragraph breaks, one index item per piece, all a file's pieces sharing
its ``root:path`` ref. Gone files drop out; a root that can't be reached right now
changes nothing, so a NAS blip doesn't forget a share. A file that can't be read
is remembered (with its time and size) so it isn't tried again until it changes.
Each file is written as it's read, so an interrupted first run carries on where it
stopped. Everything here blocks; the server runs it in a thread."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from kit.files import FILES, Root, roots_from
from kit.files.extract import Page, Unavailable, extract
from kit.files.fields import fields
from kit.files.walk import Found, Walker, changes

if TYPE_CHECKING:
    from kit.knowledge import Index
    from kit.settings import Settings

log = logging.getLogger(__name__)

ALL = 1_000_000


@dataclass
class Report:
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (ref, why)

    def line(self) -> str:
        bits = [f"{self.indexed} indexed", f"{self.unchanged} unchanged", f"{self.removed} removed"]
        if self.failed:
            bits.append(f"{len(self.failed)} couldn't be read")
        return ", ".join(bits)


def chunks(text: str, words: int) -> list[str]:
    """``text`` in pieces of about ``words`` words, cut at paragraph breaks (a single
    line break when a page has none), a long paragraph cut by words."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) == 1:
        paras = [p.strip() for p in text.split("\n") if p.strip()]
    out, current, count = [], [], 0
    for para in paras:
        n = len(para.split())
        if n > words:  # one long paragraph: cut it by words
            if current:
                out.append("\n\n".join(current))
                current, count = [], 0
            parts = para.split()
            out += [" ".join(parts[i : i + words]) for i in range(0, n, words)]
            continue
        if count + n > words and current:
            out.append("\n\n".join(current))
            current, count = [], 0
        current.append(para)
        count += n
    if current:
        out.append("\n\n".join(current))
    return out


class Files:
    def __init__(
        self,
        index: Index,
        settings: Callable[[], Settings],
        state_dir: Path,
        extract: Callable[..., list[Page]] = extract,
        names: Callable[[], list[str]] = lambda: [],
        clock: Callable[[], datetime] = datetime.now,
        scandir=None,
    ) -> None:
        self.index = index
        self.settings = settings
        self.folder = state_dir / "files"
        self.extract = extract
        self.names = names
        self.clock = clock
        self.scandir = scandir
        self.running = False

    # Walking and indexing

    def roots(self) -> list[Root]:
        return roots_from(self.settings())

    def walker(self) -> Walker:
        kw = {"scandir": self.scandir} if self.scandir is not None else {}
        return Walker(self.roots(), self.settings().files.skip, **kw)

    def sync(
        self,
        full: bool = False,
        only: str | None = None,
        on_file: Callable[[str], None] | None = None,
    ) -> Report:
        """Bring the index up to date with the roots (``only`` one of them). ``full``
        reads every file again. ``on_file`` hears each file as it's read."""
        report = Report()
        self.running = True
        try:
            roots = [r for r in self.roots() if only is None or r.name == only]
            if only is None:  # a root taken out of the settings leaves the index too
                named = {r.name for r in roots}
                for gone in self._indexed_roots() - named:
                    report.removed += self.drop_root(gone)
            for root in roots:  # a private tick changed since the last sync
                self.set_private(root.name, root.private)
            failed = self._read_json("failed.json")
            walker = self.walker()
            for root in roots:
                part = Report()
                if not root.path.is_dir():
                    log.warning("files root %s (%s) isn't there just now", root.name, root.path)
                    part.failed.append((f"{root.name}:", f"{root.path} isn't reachable"))
                    report.failed += part.failed
                    continue
                found = list(walker.walk(root.name))
                diff = changes(found, self._known(root.name))
                for ref in diff.gone:
                    self.index.delete_source(FILES, ref)
                    failed.pop(ref, None)
                    part.removed += 1
                todo = found if full else diff.new + diff.changed
                part.unchanged = len(found) - len(todo)
                for f in todo:
                    if not full and failed.get(f.ref) == [f.modified, f.size]:
                        part.unchanged += 1  # it couldn't be read, and hasn't changed
                        continue
                    if on_file is not None:
                        on_file(f.ref)
                    why = self._index_file(f, root)
                    if why:
                        failed[f.ref] = [f.modified, f.size]
                        part.failed.append((f.ref, why))
                    else:
                        failed.pop(f.ref, None)
                        part.indexed += 1
                part.failed += walker.errors
                self._note_run(root.name, part)
                report.indexed += part.indexed
                report.unchanged += part.unchanged
                report.removed += part.removed
                report.failed += part.failed
            self._write_json("failed.json", failed)
        finally:
            self.running = False
        return report

    def _index_file(self, f: Found, root: Root) -> str:
        """Read one file into the index; the reason it couldn't be read, or ""."""
        s = self.settings().files
        try:
            pages = self.extract(f.path, f.kind, ocr=root.ocr, max_rows=s.max_rows)
        except Unavailable as e:
            return str(e)
        except Exception as e:  # a damaged or locked file: say so, carry on
            log.info("couldn't read %s: %s", f.ref, e)
            return f"{type(e).__name__}: {e}"
        names = self.names()
        folder = f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""
        name = f.rel.rsplit("/", 1)[-1]
        self.index.delete_source(FILES, f.ref)
        written = 0
        for page in pages:
            for n, piece in enumerate(chunks(page.text, s.chunk_words), 1):
                title = name
                if page.title:
                    title += f" > {page.title}"
                elif len(pages) > 1:
                    title += f" (page {page.number})"
                meta = {
                    "root": f.root,
                    "rel": f.rel,
                    "folder": folder,
                    "modified": f.modified,
                    "size": f.size,
                    "page": page.number,
                    "chunk": n,
                    "private": root.private,
                    "fields": fields(piece, names),
                }
                self.index.add(FILES, f.kind, piece, title=title, ref=f.ref, meta=meta)
                written += 1
        if not written:  # nothing to read (a scan without OCR): keep its name findable
            meta = {
                "root": f.root,
                "rel": f.rel,
                "folder": folder,
                "modified": f.modified,
                "size": f.size,
                "page": 1,
                "chunk": 1,
                "private": root.private,
                "fields": {},
                "no_text": True,
            }
            self.index.add(
                FILES, f.kind, f"{name} (no text in it)", title=name, ref=f.ref, meta=meta
            )
        return ""

    def _indexed_roots(self) -> set[str]:
        return {i.meta.get("root", "") for i in self.index.items(FILES, limit=ALL)}

    def _known(self, root: str) -> dict[str, tuple[float, int]]:
        out: dict[str, tuple[float, int]] = {}
        for item in self.index.items(FILES, limit=ALL):
            if item.ref and item.meta.get("root") == root and item.ref not in out:
                out[item.ref] = (item.meta.get("modified"), item.meta.get("size"))
        return out

    # Changing roots

    def set_private(self, root: str, private: bool) -> int:
        """Mark every item of ``root`` private or not, without reading it again."""
        n = 0
        for item in self.index.items(FILES, limit=ALL):
            if item.meta.get("root") == root and bool(item.meta.get("private")) != private:
                self.index.set_meta(item.id, {**item.meta, "private": private})
                n += 1
        return n

    def drop_root(self, root: str) -> int:
        """Take everything of ``root`` out of the index (the root was removed)."""
        refs = {i.ref for i in self.index.items(FILES, limit=ALL) if i.meta.get("root") == root}
        n = sum(self.index.delete_source(FILES, ref) for ref in refs if ref)
        failed = self._read_json("failed.json")
        self._write_json(
            "failed.json", {k: v for k, v in failed.items() if not k.startswith(f"{root}:")}
        )
        runs = self._read_json("runs.json")
        runs.pop(root, None)
        self._write_json("runs.json", runs)
        return n

    # What's there

    def status(self) -> dict:
        """Per root: where it is, whether it's reachable, files and pieces indexed,
        the last run and the files it couldn't read."""
        runs = self._read_json("runs.json")
        failed = self._read_json("failed.json")
        counts: dict[str, set[str]] = {}
        pieces: dict[str, int] = {}
        for item in self.index.items(FILES, limit=ALL):
            root = item.meta.get("root", "")
            counts.setdefault(root, set()).add(item.ref or "")
            pieces[root] = pieces.get(root, 0) + 1
        out = {}
        for root in self.roots():
            out[root.name] = {
                "path": str(root.path),
                "reachable": root.path.is_dir(),
                "private": root.private,
                "ocr": root.ocr,
                "max_mb": root.max_mb,
                "files": len(counts.get(root.name, ())),
                "pieces": pieces.get(root.name, 0),
                "last_run": runs.get(root.name),
                "unreadable": sorted(k for k in failed if k.startswith(f"{root.name}:")),
            }
        return out

    def _note_run(self, root: str, report: Report) -> None:
        runs = self._read_json("runs.json")
        runs[root] = {"at": self.clock().isoformat(timespec="seconds"), "result": report.line()}
        self._write_json("runs.json", runs)

    def _read_json(self, name: str) -> dict:
        try:
            return json.loads((self.folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_json(self, name: str, data: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{name}.tmp"
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.folder / name)
