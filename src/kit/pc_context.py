"""What Dan is doing on his PC, as reported by the desk app.

The desk app (Windows) sends a snapshot every few seconds: which window has
focus, what else is open, how long since he touched the keyboard or mouse, and
the PC's health. With Kit's Chrome extension installed it also carries the
browser's tabs, and the focused browser window names the site Dan is on. No
screenshots, only window titles, app names and tab addresses; titles from
hidden apps or with hidden words are blanked on the PC before they're sent.

Kit sees a one-line "right now" in every prompt, and the ``look_at_pc`` action
gives him the full picture: every open window, what has had focus over the
last hour and today, and how the PC is coping. Activity is kept in memory for
the day only; nothing here is written to disk.

This module is plain Python so the brain stays cross-platform. The Windows
code that reads windows lives in ``kit.desk``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

STALE_AFTER = timedelta(minutes=3)  # the desk app reports every few seconds
AWAY_AFTER_S = 300  # no keyboard or mouse for this long counts as away
KEEP_FOR = timedelta(hours=16)
MAX_WINDOWS = 40
MAX_TABS = 40
MAX_SITES = 10


class Window(BaseModel):
    app: str = Field(max_length=200)
    title: str = Field("", max_length=500)
    minimised: bool = False
    site: str = Field("", max_length=200)  # for a browser: the active tab's site


class Tab(BaseModel):
    title: str = Field("", max_length=500)
    url: str = Field("", max_length=1000)  # without the query string or #fragment
    site: str = Field("", max_length=200)
    active: bool = False  # the tab showing in its window
    audible: bool = False


class Browser(BaseModel):
    """What the Chrome extension sees: every tab in normal (not incognito) windows."""

    name: str = Field("Chrome", max_length=50)
    tabs: list[Tab] = Field(default_factory=list, max_length=300)


class Disk(BaseModel):
    name: str = Field(max_length=100)
    free_gb: float
    total_gb: float


class Battery(BaseModel):
    percent: float
    plugged_in: bool


class BusyApp(BaseModel):
    app: str = Field(max_length=200)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0


class System(BaseModel):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_gb: float | None = None
    memory_total_gb: float | None = None
    disks: list[Disk] = Field(default_factory=list, max_length=26)
    battery: Battery | None = None
    uptime_hours: float | None = None
    online: bool | None = None
    busiest: list[BusyApp] = Field(default_factory=list, max_length=10)


class Snapshot(BaseModel):
    """One report from the desk app."""

    host: str = Field("", max_length=100)
    watching: bool = True  # False while Dan has paused watching from the tray
    focus: Window | None = None
    idle_seconds: float = 0.0
    locked: bool = False
    windows: list[Window] = Field(default_factory=list, max_length=200)
    system: System | None = None
    browser: Browser | None = None


@dataclass
class Span:
    """A stretch of time with one window in focus (or Dan away)."""

    app: str
    title: str
    start: datetime
    end: datetime
    site: str = ""

    @property
    def away(self) -> bool:
        return self.app == ""

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def _mins(minutes: float) -> str:
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return f"{round(minutes)} min"
    return f"{minutes / 60:.1f} h"


def _title(w: Window) -> str:
    text = f'{w.app}: "{w.title}"' if w.title else w.app
    return f"{text} ({w.site})" if w.site else text


def _tab(t: Tab) -> str:
    text = f'"{t.title}"' if t.title else "(title hidden)"
    where = t.url or t.site
    return f"{text} {where}".strip() + (" (playing sound)" if t.audible else "")


def health_line(s: System, apps: bool = True) -> str:
    """CPU, memory, disks and so on. ``apps`` False leaves out the busiest apps'
    names (while watching is paused)."""
    parts = []
    if s.cpu_percent is not None:
        parts.append(f"CPU {s.cpu_percent:.0f}%")
    if s.memory_percent is not None:
        used = (
            f" ({s.memory_used_gb:.1f} of {s.memory_total_gb:.0f} GB)"
            if s.memory_used_gb is not None and s.memory_total_gb
            else ""
        )
        parts.append(f"memory {s.memory_percent:.0f}%{used}")
    for d in s.disks:
        parts.append(f"{d.name} {d.free_gb:.0f} GB free of {d.total_gb:.0f}")
    if s.battery:
        plug = "charging" if s.battery.plugged_in else "on battery"
        parts.append(f"battery {s.battery.percent:.0f}% {plug}")
    if s.uptime_hours is not None:
        up = s.uptime_hours
        parts.append(f"up {up / 24:.1f} days" if up >= 48 else f"up {up:.0f} h")
    if s.online is False:
        parts.append("no network")
    line = ", ".join(parts)
    if s.busiest and apps:
        busy = "; ".join(
            f"{b.app} {b.cpu_percent:.0f}% CPU {b.memory_mb / 1024:.1f} GB" for b in s.busiest[:3]
        )
        line += f". Busiest: {busy}"
    return line


class PcContext:
    """The latest snapshot from Dan's PC, and today's focus history built from them."""

    def __init__(self, clock: Callable[[], datetime] = datetime.now) -> None:
        self.clock = clock
        self.latest: Snapshot | None = None
        self.seen: datetime | None = None
        self.spans: list[Span] = []

    def update(self, snap: Snapshot) -> None:
        now = self.clock()
        self.latest, self.seen = snap, now
        away = snap.locked or snap.idle_seconds >= AWAY_AFTER_S or not snap.watching
        f = None if away else snap.focus
        app, title, site = (f.app, f.title, f.site) if f else ("", "", "")
        last = self.spans[-1] if self.spans else None
        if last and now - last.end > STALE_AFTER:
            # The app was off for a while: the gap is unknown, not time in one window.
            last = None
        if last and (last.app, last.title, last.site) == (app, title, site):
            last.end = now
        else:
            if last:
                last.end = now
            self.spans.append(Span(app, title, now, now, site))
        cutoff = now - KEEP_FOR
        self.spans = [s for s in self.spans if s.end >= cutoff]

    def online(self) -> bool:
        return self.seen is not None and self.clock() - self.seen <= STALE_AFTER

    def now_line(self, owner: str) -> str:
        """One line for every prompt; empty if the desk app has never reported."""
        snap = self.latest
        if snap is None or self.seen is None:
            return ""
        if not self.online():
            seen = f"{self.seen:%I:%M %p}"
            return f"{owner}'s PC was last seen at {seen}; the desk app isn't running."
        if not snap.watching:
            return f"{owner} has paused PC watching, so you can't see what's on screen."
        if snap.locked:
            return f"{owner}'s PC is locked."
        line = f"On {owner}'s PC right now: "
        if snap.focus:
            line += _title(snap.focus)
            span = self.spans[-1] if self.spans else None
            if span and not span.away and span.minutes >= 1:
                line += f", for {_mins(span.minutes)}"
        else:
            line += "the desktop"
        line += "."
        if snap.idle_seconds >= 60:
            line += f" No keyboard or mouse for {_mins(snap.idle_seconds / 60)}."
        focus_app = snap.focus.app if snap.focus else None
        others = list(dict.fromkeys(w.app for w in snap.windows if w.app != focus_app))
        if others:
            more = f" and {len(others) - 6} more" if len(others) > 6 else ""
            line += f" Also open: {', '.join(others[:6])}{more}."
        return line

    def detail(self, owner: str) -> str:
        """The full picture, for the look_at_pc action."""
        snap = self.latest
        if snap is None or self.seen is None:
            return f"The desk app isn't running on {owner}'s PC, so you can't see it."
        now = self.clock()
        host = f" ({snap.host})" if snap.host else ""
        lines = [f"{owner}'s PC{host}, as of {self.seen:%I:%M %p}:"]
        if not self.online():
            lines.append("The desk app has stopped reporting, so this is out of date.")
        if not snap.watching:
            lines.append(
                f"{owner} has paused watching: you can't see their windows, tabs or what "
                f"they've been doing. Only the PC's health is shared."
            )
        elif snap.locked:
            lines.append("The PC is locked.")
        else:
            lines.append(f"In focus: {_title(snap.focus) if snap.focus else 'the desktop'}.")
            if snap.idle_seconds >= 60:
                lines.append(f"No keyboard or mouse for {_mins(snap.idle_seconds / 60)}.")
            if snap.windows:
                lines.append(f"Open windows ({len(snap.windows)}):")
                for w in snap.windows[:MAX_WINDOWS]:
                    lines.append(f"- {_title(w)}{' (minimised)' if w.minimised else ''}")
            if snap.browser and snap.browser.tabs:
                tabs = snap.browser.tabs
                lines.append(f"{snap.browser.name} tabs ({len(tabs)}, showing ones marked *):")
                for t in tabs[:MAX_TABS]:
                    lines.append(f"- {'* ' if t.active else ''}{_tab(t)}")
                if len(tabs) > MAX_TABS:
                    lines.append(f"- and {len(tabs) - MAX_TABS} more")
        if snap.watching:
            # While paused, what came before stays private too, not just the screen.
            hour = self._summary(now - timedelta(hours=1), now, titles=True)
            if hour:
                lines += ["In focus over the last hour:", *hour]
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            today = self._summary(start_of_day, now, titles=False)
            if today:
                lines += ["Today so far, by app:", *today]
            sites = self._sites(start_of_day, now)
            if sites:
                lines += ["Websites today:", *sites]
        if snap.system:
            health = health_line(snap.system, apps=snap.watching)
            lines.append(f"PC health: {health}.")
        return "\n".join(lines)

    def _summary(self, since: datetime, until: datetime, titles: bool) -> list[str]:
        """Minutes per app (and its busiest titles) in focus between two times."""
        per_app: dict[str, float] = defaultdict(float)
        per_title: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        away = 0.0
        for s in self.spans:
            start, end = max(s.start, since), min(s.end, until)
            if end <= start:
                continue
            m = (end - start).total_seconds() / 60
            if s.away:
                away += m
                continue
            per_app[s.app] += m
            per_title[s.app][s.title] += m
        lines = []
        for app, m in sorted(per_app.items(), key=lambda x: -x[1]):
            if m < 0.5:
                continue
            line = f"- {app}: {_mins(m)}"
            if titles:
                top = sorted(per_title[app].items(), key=lambda x: -x[1])[:3]
                named = [f'"{t}" ({_mins(tm)})' for t, tm in top if t and tm >= 0.5]
                if named:
                    line += ", on " + ", ".join(named)
            lines.append(line)
        if away >= 1:
            lines.append(f"- away or paused: {_mins(away)}")
        return lines

    def _sites(self, since: datetime, until: datetime) -> list[str]:
        per_site: dict[str, float] = defaultdict(float)
        for s in self.spans:
            start, end = max(s.start, since), min(s.end, until)
            if s.site and end > start:
                per_site[s.site] += (end - start).total_seconds() / 60
        top = sorted(per_site.items(), key=lambda x: -x[1])[:MAX_SITES]
        return [f"- {site}: {_mins(m)}" for site, m in top if m >= 0.5]

    def as_dict(self, owner: str) -> dict:
        return {
            "seen": self.seen.isoformat() if self.seen else None,
            "online": self.online(),
            "snapshot": self.latest.model_dump() if self.latest else None,
            "line": self.now_line(owner),
            "detail": self.detail(owner),
        }
