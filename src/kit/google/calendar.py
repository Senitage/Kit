"""Google Calendar, as far as Kit may go: what's on, across the calendars Dan
chose; adding an event and moving one, each after his yes; nothing deleted.
Coming events are kept in the knowledge index (source ``calendar``) so recall and
the morning brief find them, and one starting soon becomes a want in his notebook,
so he mentions it the way he brings anything up (``google.remind_minutes``)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kit.google import CALENDAR
from kit.google.client import Google

if TYPE_CHECKING:
    from kit.knowledge import Index
    from kit.notebook import Notebook

log = logging.getLogger(__name__)

API = "/calendar/v3"
AHEAD = timedelta(days=60)  # how far ahead events are kept in memory
BEHIND = timedelta(days=7)
MOST = 250


class WhenError(ValueError):
    """A time the tools couldn't read."""


@dataclass(frozen=True)
class Calendar:
    id: str
    name: str
    primary: bool = False
    writable: bool = False

    def line(self) -> str:
        bits = [self.name]
        if self.primary:
            bits.append("primary")
        bits.append("can add to it" if self.writable else "read only")
        return f"{self.id}: " + ", ".join(bits)


@dataclass(frozen=True)
class Event:
    id: str
    calendar: str  # the calendar's id
    calendar_name: str
    title: str
    start: datetime  # zone-aware; all-day events start at midnight
    end: datetime
    all_day: bool = False
    where: str = ""
    notes: str = ""
    link: str = ""

    @property
    def ref(self) -> str:
        return f"{self.calendar}:{self.id}"

    def when(self, today: date | None = None) -> str:
        """ "Thu 24 Oct 2:00 pm to 3:00 pm", "today all day", "Fri 25 Oct to Sun 27 Oct"."""
        day = _day_words(self.start.date(), today)
        if self.all_day:
            last = (self.end - timedelta(days=1)).date()
            if last <= self.start.date():
                return f"{day} all day"
            return f"{day} to {_day_words(last, today)}"
        if self.end.date() == self.start.date():
            return f"{day} {clock_words(self.start)} to {clock_words(self.end)}"
        end_day = _day_words(self.end.date(), today)
        return f"{day} {clock_words(self.start)} to {end_day} {clock_words(self.end)}"

    def line(self, today: date | None = None) -> str:
        where = f", at {self.where}" if self.where else ""
        return f"[{self.ref}] {self.when(today)}: {self.title}{where} ({self.calendar_name})"


def clock_words(t: datetime) -> str:
    """ "2 pm", "9:10 am"."""
    return t.strftime("%I:%M %p").lstrip("0").lower().replace(":00", "")


def _day_words(day: date, today: date | None) -> str:
    if today is not None:
        if day == today:
            return "today"
        if day == today + timedelta(days=1):
            return "tomorrow"
    return day.strftime("%a %d %b").replace(" 0", " ")


def zone_for(name: str) -> tzinfo:
    """The owner's time zone (``persona.timezone``), else this machine's."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("persona.timezone %r isn't a known zone", name)
    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def read_when(text: str, tz: tzinfo) -> tuple[datetime, bool]:
    """A time the model wrote: ISO like "2026-10-24T14:00" or "2026-10-24 2pm"
    (in the owner's zone unless it says one), or a date alone (all day).
    Returns (when, all_day)."""
    text = str(text or "").strip()
    if not text:
        raise WhenError("no time given")
    try:
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, tzinfo=tz), True
    except ValueError:
        pass
    try:
        t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise WhenError(
            f"can't read the time '{text}': use ISO 8601, like 2026-10-24T14:00, "
            "or a date alone for all day"
        ) from e
    t = t.replace(tzinfo=tz) if t.tzinfo is None else t.astimezone(tz)
    return t, False


def _api_time(t: datetime, all_day: bool, tz_name: str) -> dict:
    if all_day:
        return {"date": t.date().isoformat()}
    out = {"dateTime": t.isoformat(timespec="seconds")}
    if tz_name:
        out["timeZone"] = tz_name
    return out


def _event(data: dict, cal: Calendar, tz: tzinfo) -> Event | None:
    start, end = data.get("start") or {}, data.get("end") or {}
    all_day = "date" in start
    try:
        if all_day:
            s = datetime.combine(date.fromisoformat(start["date"]), datetime.min.time(), tz)
            e_day = date.fromisoformat(end.get("date") or start["date"])
            e = datetime.combine(e_day, datetime.min.time(), tz)
        else:
            s = datetime.fromisoformat(str(start.get("dateTime", "")).replace("Z", "+00:00"))
            e = datetime.fromisoformat(str(end.get("dateTime", "")).replace("Z", "+00:00"))
            s, e = s.astimezone(tz), e.astimezone(tz)
    except (ValueError, KeyError, TypeError):
        return None
    return Event(
        str(data.get("id", "")),
        cal.id,
        cal.name,
        str(data.get("summary") or "(no title)"),
        s,
        e,
        all_day,
        str(data.get("location") or ""),
        str(data.get("description") or ""),
        str(data.get("htmlLink") or ""),
    )


class Calendars:
    """Dan's calendars and what's on them. ``chosen`` names the calendars to use
    (ids or names, ``google.calendars``); empty means the ones he shows in Google
    Calendar. ``refresh`` keeps a cache for the brief and reminders."""

    def __init__(
        self,
        google: Google,
        clock: Callable[[], datetime],
        tz: Callable[[], tzinfo],
        chosen: Callable[[], list[str]],
    ) -> None:
        self.google = google
        self.clock = clock
        self.tz = tz
        self.chosen = chosen
        self.calendars: list[Calendar] = []
        self.events: list[Event] = []  # from the last refresh, BEHIND to AHEAD
        self.refreshed: datetime | None = None

    async def list_calendars(self) -> list[Calendar]:
        data = await self.google.get(f"{API}/users/me/calendarList", maxResults=MOST)
        found = []
        for item in data.get("items") or []:
            role = str(item.get("accessRole", ""))
            cal = Calendar(
                str(item.get("id", "")),
                str(item.get("summaryOverride") or item.get("summary") or item.get("id", "")),
                bool(item.get("primary")),
                role in ("owner", "writer"),
            )
            wanted = self.chosen()
            if wanted:
                if cal.id in wanted or cal.name.lower() in {w.lower() for w in wanted}:
                    found.append(cal)
            elif item.get("selected", True):
                found.append(cal)
        self.calendars = found
        return found

    def calendar(self, name: str = "") -> Calendar | None:
        """One calendar by id or name; the primary (else the first writable) if none."""
        if name:
            low = name.strip().lower()
            for c in self.calendars:
                if c.id.lower() == low or c.name.lower() == low:
                    return c
            return None
        for c in self.calendars:
            if c.primary:
                return c
        return next((c for c in self.calendars if c.writable), None)

    async def events_between(
        self, start: datetime, end: datetime, query: str = "", limit: int = MOST
    ) -> list[Event]:
        """What's on from ``start`` to ``end`` across the chosen calendars, in order."""
        if not self.calendars:
            await self.list_calendars()
        tz = self.tz()
        found: list[Event] = []
        for cal in self.calendars:
            data = await self.google.get(
                f"{API}/calendars/{cal.id}/events",
                timeMin=start.isoformat(timespec="seconds"),
                timeMax=end.isoformat(timespec="seconds"),
                singleEvents="true",
                orderBy="startTime",
                q=query.strip() or None,
                maxResults=min(limit, MOST),
            )
            for item in data.get("items") or []:
                if item.get("status") == "cancelled":
                    continue
                ev = _event(item, cal, tz)
                if ev is not None:
                    found.append(ev)
        found.sort(key=lambda e: (e.start, e.title))
        return found[:limit]

    def now(self) -> datetime:
        """The clock, zone-aware (a naive clock is read as the owner's zone)."""
        t = self.clock()
        return t if t.tzinfo else t.replace(tzinfo=self.tz())

    async def refresh(self) -> list[Event]:
        """The cache: everything from a week ago to two months ahead."""
        now = self.now()
        await self.list_calendars()
        self.events = await self.events_between(now - BEHIND, now + AHEAD)
        self.refreshed = now
        return self.events

    def today(self, now: datetime | None = None) -> list[Event]:
        now = now or self.now()
        day = now.astimezone(self.tz()).date() if now.tzinfo else now.date()
        return [
            e
            for e in self.events
            if e.start.date() <= day < max(e.end.date(), e.start.date() + timedelta(days=1))
        ]

    def find(self, text: str) -> list[Event]:
        """Cached events by ref, id or words of the title."""
        text = text.strip()
        exact = [e for e in self.events if e.ref == text or e.id == text]
        if exact:
            return exact
        words = {w for w in text.lower().split() if len(w) > 2}
        if not words:
            return []
        return [e for e in self.events if words <= set(e.title.lower().split())] or [
            e for e in self.events if words & set(e.title.lower().split())
        ]

    async def add(
        self,
        title: str,
        start: datetime,
        end: datetime | None,
        all_day: bool,
        where: str = "",
        notes: str = "",
        calendar: str = "",
        tz_name: str = "",
    ) -> Event:
        cal = self.calendar(calendar)
        if cal is None:
            raise WhenError(f"no calendar called '{calendar}'" if calendar else "no calendar")
        if not cal.writable:
            raise WhenError(f"the {cal.name} calendar is read only")
        if end is None:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
        body = {
            "summary": title.strip(),
            "start": _api_time(start, all_day, tz_name),
            "end": _api_time(end, all_day, tz_name),
        }
        if where.strip():
            body["location"] = where.strip()
        if notes.strip():
            body["description"] = notes.strip()
        data = await self.google.post(f"{API}/calendars/{cal.id}/events", json=body)
        ev = _event(data, cal, self.tz())
        if ev is None:
            raise WhenError("Google added it but sent it back in a shape Kit can't read")
        if self.refreshed is not None:
            self.events = sorted([*self.events, ev], key=lambda e: (e.start, e.title))
        return ev

    async def move(
        self, event: Event, start: datetime, end: datetime | None, tz_name: str = ""
    ) -> Event:
        cal = next((c for c in self.calendars if c.id == event.calendar), None)
        if cal is None or not cal.writable:
            raise WhenError(f"the {event.calendar_name} calendar is read only")
        if end is None:
            end = start + (event.end - event.start)
        body = {
            "start": _api_time(start, event.all_day, tz_name),
            "end": _api_time(end, event.all_day, tz_name),
        }
        data = await self.google.patch(f"{API}/calendars/{cal.id}/events/{event.id}", json=body)
        moved = _event(data, cal, self.tz())
        if moved is None:
            raise WhenError("Google moved it but sent it back in a shape Kit can't read")
        self.events = sorted(
            [e for e in self.events if e.ref != event.ref] + [moved],
            key=lambda e: (e.start, e.title),
        )
        return moved


# In his memory, and on his mind


def write_contents(index: Index, events: list[Event]) -> int:
    """Replace the ``calendar`` items with the coming events; how many were written."""
    index.delete_source(CALENDAR)
    n = 0
    for e in events:
        where = f" at {e.where}" if e.where else ""
        text = f"{e.title}, {e.when()}{where} ({e.calendar_name} calendar)."
        meta = {
            "start": e.start.isoformat(timespec="minutes"),
            "end": e.end.isoformat(timespec="minutes"),
            "all_day": e.all_day,
            "calendar": e.calendar_name,
            "where": e.where,
            "day": e.start.date().isoformat(),
        }
        index.add(CALENDAR, "event", text, title=e.title, ref=e.ref, meta=meta)
        n += 1
    return n


def plant_reminders(
    notebook: Notebook, events: list[Event], now: datetime, minutes: int, owner: str
) -> int:
    """A want for each timed event starting within ``minutes``, once per event, so
    Kit brings it up ("your dentist's at 2") the way he brings anything up. The want
    is only worth saying till the event starts."""
    if minutes <= 0:
        return 0
    planted = {str(w.meta.get("event")) for w in notebook.entries("want", 200)}
    n = 0
    for e in events:
        if e.all_day or e.ref in planted:
            continue
        start = e.start if now.tzinfo else e.start.replace(tzinfo=None)
        gap = start - now
        if timedelta(0) < gap <= timedelta(minutes=minutes):
            where = f" at {e.where}" if e.where else ""
            text = (
                f"Remind {owner}: {e.title} starts at {clock_words(e.start)}{where}, "
                f"in about {max(1, round(gap.total_seconds() / 60))} minutes."
            )
            if notebook.write(
                "want",
                text,
                event=e.ref,
                strength=1.0,
                until=start.isoformat(timespec="seconds"),
            ):
                n += 1
    return n
