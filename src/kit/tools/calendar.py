"""The ``calendar`` pack: what's on in Dan's Google calendars (kit.google.calendar),
adding an event and moving one, each after his yes (``google.calendar_write`` turns
both off). He never deletes an event. See docs/2 How Kit Works/Mail and Calendar.md."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from kit.google.calendar import WhenError, read_when
from kit.google.client import GoogleError
from kit.tools import EvalCase, Pack, Tool, ToolResult

if TYPE_CHECKING:
    from kit.brain import Brain

DEFAULT_DAYS = 7
MOST_DAYS = 90
MOST_SHOWN = 40


def calendar_pack(brain: Brain) -> Pack:
    def cals():
        return brain.calendars

    def settings():
        return brain.settings()

    def tz():
        return brain.google_tz()

    def tz_name() -> str:
        return settings().persona.timezone

    def now() -> datetime:
        t = brain.memory.clock()
        return t.astimezone(tz()) if t.tzinfo else t.replace(tzinfo=tz())

    def private() -> bool:
        return settings().google.private

    def failed(e: Exception) -> ToolResult:
        return ToolResult(str(e), ok=False)

    async def calendar_events(args: dict) -> ToolResult:
        today = now()
        try:
            start = read_when(args["from"], tz())[0] if args.get("from") else today
            if args.get("to"):
                end, all_day = read_when(args["to"], tz())
                if all_day:
                    end += timedelta(days=1)
            else:
                days = max(1, min(int(args.get("days") or DEFAULT_DAYS), MOST_DAYS))
                end = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                    days=days
                )
            found = await cals().events_between(start, end, str(args.get("query", "")))
        except (WhenError, ValueError) as e:
            return failed(e)
        except GoogleError as e:
            return failed(e)
        span = (
            f"{start.strftime('%a %d %b')} to {(end - timedelta(minutes=1)).strftime('%a %d %b')}"
        )
        if not found:
            which = f" matching '{args['query']}'" if args.get("query") else ""
            return ToolResult(f"Nothing on{which} from {span}.", step="checked the calendar")
        lines = "\n".join(f"- {e.line(today.date())}" for e in found[:MOST_SHOWN])
        more = f"\n(and {len(found) - MOST_SHOWN} more)" if len(found) > MOST_SHOWN else ""
        names = ", ".join(c.name for c in cals().calendars)
        return ToolResult(
            f"On the calendar ({names}), {span}:\n{lines}{more}",
            step="checked the calendar",
            private=private(),
        )

    async def calendar_add(args: dict) -> ToolResult:
        try:
            start, all_day = read_when(args.get("start", ""), tz())
            end = None
            if args.get("end"):
                end, _ = read_when(args["end"], tz())
                if all_day:
                    end += timedelta(days=1)
            if not cals().calendars:
                await cals().list_calendars()
            ev = await cals().add(
                str(args.get("title", "")).strip() or "(no title)",
                start,
                end,
                all_day,
                str(args.get("where", "")),
                str(args.get("notes", "")),
                str(args.get("calendar", "")),
                tz_name(),
            )
        except (WhenError, GoogleError) as e:
            return failed(e)
        done = f"added '{ev.title}' to the {ev.calendar_name} calendar, {ev.when(now().date())}"
        return ToolResult(f"Done: {done}.", step=done)

    async def calendar_move(args: dict) -> ToolResult:
        try:
            if cals().refreshed is None:
                await cals().refresh()
            found = cals().find(str(args.get("event", "")))
            if not found:
                return ToolResult(
                    f"No coming event matches '{args.get('event', '')}': use calendar_events "
                    "to find it and give its id.",
                    ok=False,
                )
            if len(found) > 1:
                listed = "; ".join(e.line(now().date()) for e in found[:6])
                return ToolResult(f"That could be several: {listed}. Ask which.", ok=False)
            start, _ = read_when(args.get("start", ""), tz())
            end = read_when(args["end"], tz())[0] if args.get("end") else None
            ev = await cals().move(found[0], start, end, tz_name())
        except (WhenError, GoogleError) as e:
            return failed(e)
        done = f"moved '{ev.title}' to {ev.when(now().date())}"
        return ToolResult(f"Done: {done}.", step=done)

    def add_preview(args: dict) -> str:
        start, all_day = read_when(args.get("start", ""), tz())
        when = start.strftime("%a %d %b") if all_day else start.strftime("%a %d %b %I:%M %p")
        if args.get("end") and not all_day:
            when += " to " + read_when(args["end"], tz())[0].strftime("%I:%M %p")
        where = f", at {args['where']}" if args.get("where") else ""
        which = f" ({args['calendar']} calendar)" if args.get("calendar") else ""
        return f"{args.get('title', '')}: {when}{where}{which}"

    def move_preview(args: dict) -> str:
        found = cals().find(str(args.get("event", "")))
        start, _ = read_when(args.get("start", ""), tz())
        what = found[0].line(now().date()) if len(found) == 1 else str(args.get("event", ""))
        return f"{what}\nto {start.strftime('%a %d %b %I:%M %p')}"

    def configured() -> bool:
        return brain.calendars is not None and settings().google.calendar

    def may_write() -> bool:
        return configured() and settings().google.calendar_write

    when_help = (
        "ISO 8601 in the owner's time zone, like 2026-10-24T14:00, or a date alone for all day."
    )
    return Pack(
        "calendar",
        "the owner's Google Calendar: what's on; adding or moving an event after a yes",
        words=[
            "calendar",
            "appointment",
            "appointments",
            "meeting",
            "meetings",
            "what's on",
            "whats on",
            "on today",
            "on tomorrow",
            "on this week",
            "schedule",
            "booked",
            "am i free",
            "free on",
            "diary",
            "put it in",
            "book it",
        ],  # fmt: skip
        questions=[
            "What's on today?",
            "Am I free Thursday afternoon?",
            "When's the dentist?",
            "What have I got on this week?",
            "Put the dentist in for Thursday at 2",
            "Move my 3 pm to 4",
            "Add Sam's birthday on the 12th",
        ],
        cases=[
            EvalCase("What's on today?", "calendar_events"),
            EvalCase("When's the dentist?", "calendar_events", {"query": "dentist"}),
            EvalCase("Put the dentist in for Thursday at 2", "calendar_add", {"title": "dentist"}),
            EvalCase("Turn the lamp off", None),
        ],
        context=lambda: [
            "Calendar: times are in the owner's zone; work out dates from today's date in "
            "the prompt and give them as ISO 8601. Adding or moving an event always asks "
            "the owner first.",
        ],
        tools=[
            Tool(
                "calendar_events",
                "What's on the owner's calendars between two times (default: the next week "
                "from now), optionally only events matching some words. Returns each "
                "event's id, when, title, place and calendar.",
                calendar_events,
                {
                    "from": {
                        "type": "string",
                        "description": "Start. " + when_help + " Default: now.",
                    },
                    "to": {"type": "string", "description": "End. " + when_help},
                    "days": {
                        "type": "integer",
                        "description": "Instead of 'to': how many days from the start (1 to 90).",
                    },
                    "query": {"type": "string", "description": "Only events with these words."},
                },
                offered=configured,
                examples=[{"days": 1}, {"query": "dentist", "days": 60}],
                speak="checking the calendar",
            ),
            Tool(
                "calendar_add",
                "Add an event to the owner's calendar. It always asks the owner first.",
                calendar_add,
                {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": when_help},
                    "end": {
                        "type": "string",
                        "description": "Same form. Default: an hour after the start (all day "
                        "events: that day).",
                    },
                    "where": {"type": "string"},
                    "notes": {"type": "string"},
                    "calendar": {
                        "type": "string",
                        "description": "Which calendar, by name. Default: the main one.",
                    },
                },
                ["title", "start"],
                effect="change",
                offered=may_write,
                ask="add '{title}' to the calendar for {start}",
                preview=add_preview,
                examples=[
                    {"title": "Dentist", "start": "2026-10-30T14:00", "end": "2026-10-30T15:00"}
                ],
                speak="putting it in",
            ),
            Tool(
                "calendar_move",
                "Move a coming event to another time (its id from calendar_events, or words "
                "from its title). It always asks the owner first.",
                calendar_move,
                {
                    "event": {"type": "string", "description": "The event's id or title words."},
                    "start": {"type": "string", "description": "The new start. " + when_help},
                    "end": {"type": "string", "description": "The new end. Default: same length."},
                },
                ["event", "start"],
                effect="change",
                offered=may_write,
                ask="move '{event}' to {start}",
                preview=move_preview,
                examples=[{"event": "dentist", "start": "2026-10-30T16:00"}],
                speak="moving it",
            ),
        ],
    )
