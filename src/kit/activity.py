"""What Dan worked on, day by day, so "what was I doing yesterday?" has an answer.
The desk app's reports (kit.pc_context) keep only the last 16 hours of focus; once
an hour the brain folds each day still in them into one ``activity`` item in the
knowledge index: the apps and how long, the files and sites, and the projects
they belong to (matched through the register's names and its code and NAS links).
A day's item is replaced as the day goes on, so the last one written holds the
whole day. Only the summary is kept, never a window-by-window log, and
``pc.keep_activity`` off keeps nothing. See docs/2 How Kit Works/Desk App.md."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from kit.when import find_when, how_long

if TYPE_CHECKING:
    from kit.knowledge import Index
    from kit.pc_context import Span
    from kit.things import Register

ACTIVITY = "activity"
MIN_MINUTES = 2  # an app or title used less than this in a day isn't worth a mention
TOP_TITLES = 3
MAX_SITES = 8
# "riverbend-costs.xlsx - Excel", "Kit - Visual Studio Code": the file or folder part.
_TITLE_SPLIT = re.compile(r"\s+[-–—|]\s+")


def _work_of(title: str) -> str:
    """The file or folder a window title names (its first part), or the title."""
    return _TITLE_SPLIT.split(title.strip())[0].strip(" *●") if title else ""


def _projects(texts: list[str], register: Register | None) -> list[str]:
    if register is None:
        return []
    found = []
    joined = "\n".join(texts)
    for thing in register.all():
        targets = [
            link.target.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
            for link in thing.links
            if link.system in ("code", "nas") and link.target
        ]
        names = [n for n in [*thing.names, *targets] if len(n) >= 3]
        if thing.kind == "project" or targets:
            lower = joined.lower()
            if any(re.search(rf"\b{re.escape(n.lower())}\b", lower) for n in names):
                found.append(thing.name)
    return found


def activity_item(
    day: date,
    spans: list[Span],
    recent: list[dict] | None = None,
    register: Register | None = None,
) -> tuple[str, dict] | None:
    """One day on the PC as a paragraph and its meta, or None when nothing of
    note happened. ``recent`` are the desk's recent files (``name``, ``path``,
    ``when`` as ISO time); only that day's are used."""
    tz = spans[0].start.tzinfo if spans else None  # the spans' own zone (aware in production)
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    per_app: dict[str, float] = defaultdict(float)
    per_work: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    per_site: dict[str, float] = defaultdict(float)
    titles: set[str] = set()  # whole titles: "pump.py - Pod - VS Code" names the project
    for s in spans:
        a, b = max(s.start, start), min(s.end, end)
        if b <= a or s.away:
            continue
        m = (b - a).total_seconds() / 60
        per_app[s.app] += m
        titles.add(s.title)
        work = _work_of(s.title)
        if work and work.lower() != s.app.lower():
            per_work[s.app][work] += m
        if s.site:
            per_site[s.site] += m
    files = [
        f["name"]
        for f in recent or []
        if str(f.get("when", ""))[:10] == day.isoformat() and f.get("name")
    ]
    apps = {app: round(m) for app, m in per_app.items() if m >= MIN_MINUTES}
    if not apps and not files:
        return None
    parts = []
    for app, m in sorted(per_app.items(), key=lambda x: -x[1]):
        if m < MIN_MINUTES:
            continue
        top = sorted(per_work[app].items(), key=lambda x: -x[1])[:TOP_TITLES]
        named = [w for w, wm in top if wm >= MIN_MINUTES]
        parts.append(f"{app} {how_long(m)}" + (f" ({', '.join(named)})" if named else ""))
    sites = [s for s, m in sorted(per_site.items(), key=lambda x: -x[1]) if m >= 1][:MAX_SITES]
    projects = _projects(sorted(titles) + files + sites, register)
    text = f"{day:%A} {day.day} {day:%b %Y} on the PC: " + "; ".join(parts or ["little"]) + "."
    if sites:
        text += f" Sites: {', '.join(sites)}."
    if files:
        text += f" Files opened: {', '.join(dict.fromkeys(files))}."
    if projects:
        text += f" Projects: {', '.join(projects)}."
    meta = {
        "day": day.isoformat(),
        "apps": apps,
        "files": list(dict.fromkeys(files)),
        "sites": sites,
        "projects": projects,
    }
    return text, meta


def write_days(
    index: Index,
    spans: list[Span],
    recent: list[dict] | None,
    register: Register | None,
    days: list[date],
) -> int:
    """Write (or replace) the activity item of each of ``days``; how many were written."""
    n = 0
    for day in days:
        made = activity_item(day, spans, recent, register)
        if made is None:
            continue
        text, meta = made
        index.delete_source(ACTIVITY, day.isoformat())
        index.add(ACTIVITY, "day", text, title=f"{day:%A %d %B}", ref=day.isoformat(), meta=meta)
        n += 1
    return n


def days_meant(words: str, now: datetime) -> list[date]:
    """The days "yesterday", "last Tuesday", "last week", "this week" mean, looking
    back (a bare weekday is the last one, not the coming one)."""
    text = (words or "").strip().lower()
    today = now.date()
    if not text or text in ("today", "so far today"):
        return [today]
    if "last week" in text:
        monday = today - timedelta(days=today.weekday() + 7)
        return [monday + timedelta(days=i) for i in range(7)]
    if "this week" in text:
        monday = today - timedelta(days=today.weekday())
        return [monday + timedelta(days=i) for i in range((today - monday).days + 1)]
    m = re.search(r"\blast (\d+) days\b", text)
    if m:
        return [today - timedelta(days=i) for i in range(int(m.group(1)), 0, -1)]
    when = find_when(text, now)
    if when is None:
        return [today - timedelta(days=1)] if "yesterday" in text else []
    first, last = when.start.date(), (when.end - timedelta(seconds=1)).date()
    while first > today:  # "Tuesday" asked about the past: the last one
        first, last = first - timedelta(days=7), last - timedelta(days=7)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def recent_work(index: Index, words: str, now: datetime) -> str:
    """The activity items for the days ``words`` means, as lines for a model."""
    days = days_meant(words, now)
    if not days:
        return f"I couldn't tell which day '{words}' means; ask for a day or a week."
    found = []
    for day in days:
        found += index.with_ref(ACTIVITY, day.isoformat())
    if not found:
        shown = days[0].strftime("%A %d %B") if len(days) == 1 else "those days"
        return f"There's nothing kept about {shown} on the PC."
    return "\n".join(f"- {item.text}" for item in found)
