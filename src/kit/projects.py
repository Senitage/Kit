"""Dan's code projects: each folder under ``projects.roots`` with a ``.git`` or a
README is one. Once a day each goes into the knowledge index as a ``projects``
item (its name, what the README says it's for, the branch and the last commit),
so recall and the PC pack find "the Pod firmware" or "that pump app" by meaning,
and opening one knows where it lives. Git is asked through ``run``, so tests use
a fake; a folder that isn't a repo just has no commit line.
See docs/2 How Kit Works/Desk App.md."""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kit.knowledge import Index
    from kit.things import Register

log = logging.getLogger(__name__)

PROJECTS = "projects"
PURPOSE_CHARS = 300
READMES = ("README.md", "README.rst", "README.txt", "README", "readme.md")


@dataclass(frozen=True)
class Project:
    name: str
    path: Path
    purpose: str = ""
    branch: str = ""
    last_commit: str = ""  # "2026-10-13T09:12:00+10:00 Fix the neck"

    def text(self) -> str:
        bits = [f"Code project {self.name}"]
        if self.purpose:
            bits.append(self.purpose)
        if self.branch:
            bits.append(f"On branch {self.branch}.")
        if self.last_commit:
            bits.append(f"Last commit {self.last_commit}.")
        return " ".join(bits)


def _purpose(folder: Path) -> str:
    """The README's first real paragraph (not a heading, badge or blank)."""
    for name in READMES:
        path = folder / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:5000]
        except OSError:
            return ""
        for para in re.split(r"\n\s*\n", text):
            line = " ".join(para.split())
            if line and not line.startswith(("#", "[!", "![", "<", "=", "-")):
                return line[:PURPOSE_CHARS]
    return ""


class Projects:
    def __init__(
        self,
        roots: Callable[[], list[str]],
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.roots = roots
        self.run = run
        self.refreshed: date | None = None

    def _git(self, folder: Path, *args: str) -> str:
        try:
            out = self.run(
                ["git", "-C", str(folder), *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as e:
            log.info("git in %s: %s", folder, e)
            return ""
        return out.stdout.strip() if out.returncode == 0 else ""

    def find(self) -> list[Project]:
        found = []
        for root in self.roots():
            base = Path(root).expanduser()
            try:
                children = sorted(p for p in base.iterdir() if p.is_dir())
            except OSError as e:
                log.warning("can't read projects folder %s: %s", base, e)
                continue
            for folder in children:
                if folder.name.startswith("."):
                    continue
                is_repo = (folder / ".git").exists()
                if not is_repo and not any((folder / r).is_file() for r in READMES):
                    continue
                found.append(
                    Project(
                        folder.name,
                        folder,
                        _purpose(folder),
                        self._git(folder, "rev-parse", "--abbrev-ref", "HEAD") if is_repo else "",
                        self._git(folder, "log", "-1", "--format=%cI %s") if is_repo else "",
                    )
                )
        return found

    def refresh(self, index: Index, register: Register | None = None) -> int:
        """Put every project into the index (replacing the old items); how many."""
        projects = self.find()
        index.delete_source(PROJECTS)
        for p in projects:
            thing = register.named(p.name) if register is not None else None
            meta = {
                "path": str(p.path),
                "branch": p.branch,
                "last_commit": p.last_commit,
                "thing": thing.name if thing else "",
            }
            index.add(PROJECTS, "project", p.text(), title=p.name, ref=str(p.path), meta=meta)
        return len(projects)


def pc_path(path: str, mapping: dict[str, str]) -> str:
    """``path`` (as the server sees it) as Dan's PC sees it, through the first
    ``server folder = PC folder`` pair it falls under; unchanged when none does."""
    norm = path.replace("\\", "/")
    for here, there in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        base = here.replace("\\", "/").rstrip("/")
        if norm == base or norm.startswith(base + "/"):
            rest = norm[len(base) :].lstrip("/")
            sep = "\\" if ("\\" in there or re.match(r"^[A-Za-z]:", there)) else "/"
            joined = there.rstrip("/\\") + (sep + rest.replace("/", sep) if rest else "")
            return joined
    return path
