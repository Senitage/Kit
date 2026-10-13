"""``kit docs check``: the note that goes stale when nobody tells it a pull request
landed. Reads "docs/1 Meet Kit/Where Kit Is Up To.md" and reports the rows that look
out of date, with no network: the file is all it has, so it goes by what the note
says about itself.

The rules, in plain words (also in docs/5 Reference/Commands.md):

- A part marked "Open, pull request #N" whose #N is also in the "How we got here"
  table has landed: the row is **stale**.
- A part marked open with a number lower than the newest landed pull request is
  **worth a look**: a later one merged, so this one may have too (or it may still be
  open; GitHub knows, this check doesn't).
- A part marked "Open, pull request (number to come)" **needs its number**.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

STATUS_NOTE = Path("1 Meet Kit") / "Where Kit Is Up To.md"

OPEN_ROW = re.compile(r"^\|(?P<part>[^|\n]+)\|\s*Open, pull request #(?P<n>\d+)\s*\|", re.M)
UNNUMBERED_ROW = re.compile(
    r"^\|(?P<part>[^|\n]+)\|\s*Open, pull request \(number to come\)\s*\|", re.M
)
PR_NUMBER = re.compile(r"#(\d+)")
LANDED_TABLE = re.compile(r"^## How we got here\n(?P<table>.*?)(?=^## |\Z)", re.M | re.S)
TABLE_ROW = re.compile(r"^\|(?P<when>[^|\n]+)\|(?P<what>[^|\n]+)\|(?P<prs>[^|\n]+)\|$", re.M)


@dataclass(frozen=True)
class Finding:
    kind: str  # "stale", "worth a look" or "needs its number"
    part: str
    why: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.part} ({self.why})"


def landed(text: str) -> set[int]:
    """The pull request numbers in the "How we got here" table."""
    table = LANDED_TABLE.search(text)
    if not table:
        return set()
    numbers: set[int] = set()
    for row in TABLE_ROW.finditer(table.group("table")):
        numbers.update(int(n) for n in PR_NUMBER.findall(row.group("prs")))
    return numbers


def findings(text: str) -> list[Finding]:
    """What looks stale in the status note's text."""
    done = landed(text)
    newest = max(done, default=0)
    out = []
    for row in OPEN_ROW.finditer(text):
        part, n = row.group("part").strip(), int(row.group("n"))
        if n in done:
            out.append(Finding("stale", part, f"#{n} is in the history table: it landed"))
        elif n < newest:
            out.append(Finding("worth a look", part, f"#{n} is open but #{newest} landed after it"))
    for row in UNNUMBERED_ROW.finditer(text):
        out.append(
            Finding("needs its number", row.group("part").strip(), "the pull request is open")
        )
    return out


def repo_docs() -> Path:
    """The vault in the checkout Kit runs from (the docs aren't installed with him)."""
    return Path(__file__).resolve().parents[2] / "docs"


def check(vault: Path, out=print) -> int:
    """Print the findings; 1 if a row is stale, 0 otherwise (looks and numbers are
    advice, not failures)."""
    note = vault / STATUS_NOTE
    if not note.is_file():
        out(f"no status note at {note}; point --vault at the docs folder")
        return 2
    found = findings(note.read_text(encoding="utf-8"))
    for f in found:
        out(str(f))
    stale = [f for f in found if f.kind == "stale"]
    if stale:
        out(f"{len(stale)} row(s) say open for a pull request that landed: move them to Done")
        return 1
    out("nothing stale" if not found else f"nothing stale; {len(found)} to look at")
    return 0
