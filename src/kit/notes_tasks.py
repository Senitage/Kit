"""The tasks in Dan's notes: every ``- [ ]`` line in the vault.

Open tasks go into the knowledge index as the ``tasks`` source, one item each,
whenever their note is read (kit.notes.Notes.sync), so "what's on my list?" and
"anything due this week?" are a look-up, not a read of every note. A ticked or
deleted task drops out. A due date is read from the Tasks plugin's ``📅
2026-10-20``, a ``due:2026-10-20``, or a ``(due 20 Oct)``. See
docs/2 How Kit Works/Notes on the NAS.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

TASKS = "tasks"
TASK = "task"  # the kind of item: one open task in a note

_TASK = re.compile(r"^\s*[-*+]\s+\[(?P<mark>[ xX])\]\s+(?P<text>.+?)\s*$")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_ISO_DUE = re.compile(r"(?:📅\s*|\bdue:\s*)(\d{4}-\d{2}-\d{2})")
_WORD_DUE = re.compile(r"\(due\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?(?:\s+(\d{4}))?\)", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
)}  # fmt: skip


@dataclass(frozen=True)
class Task:
    note: str  # the note's path in the vault, without .md
    heading: str  # the heading it's under ("" at the top)
    text: str  # the task's words, as written
    done: bool
    due: date | None
    line_no: int  # 1-based, in the file as read

    def line(self) -> str:
        due = f", due {self.due:%a %d %b}" if self.due else ""
        under = f", under {self.heading}" if self.heading else ""
        return f"{self.text} (in {self.note}{under}{due})"


def due_of(text: str, today: date) -> date | None:
    """The due date written in a task, if any. "(due 20 Oct)" with no year is the
    next 20 October from ``today``, or this year's if it's under a month past."""
    m = _ISO_DUE.search(text)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    m = _WORD_DUE.search(text)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month is None:
            return None
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            when = date(year, month, int(m.group(1)))
        except ValueError:
            return None
        if not m.group(3) and when < today - timedelta(days=31):
            when = when.replace(year=year + 1)
        return when
    return None


def tasks_in(note: str, text: str, today: date) -> list[Task]:
    """Every task line in a note, with the heading it's under."""
    out, heading, fence = [], "", False
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        h = _HEADING.match(line)
        if h:
            heading = h.group(1)
            continue
        t = _TASK.match(line)
        if t:
            words = t.group("text")
            out.append(Task(note, heading, words, t.group("mark") != " ", due_of(words, today), n))
    return out


def due_window(words: str, now: datetime) -> tuple[date | None, date | None]:
    """The dates "today", "tomorrow", "this week", "overdue" or "next week" cover,
    as (from, to), either open. ("", None) means no limit."""
    today = now.date()
    w = words.strip().lower()
    if not w or w in {"any", "all", "anytime"}:
        return None, None
    if w in {"today", "now"}:
        return None, today
    if w == "tomorrow":
        return None, today + timedelta(days=1)
    if w in {"overdue", "late"}:
        return None, today - timedelta(days=1)
    if w in {"week", "this week"}:
        return None, today + timedelta(days=6 - today.weekday())
    if w == "next week":
        start = today + timedelta(days=7 - today.weekday())
        return start, start + timedelta(days=6)
    if w in {"month", "this month"}:
        nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        return None, nxt - timedelta(days=1)
    return None, None
