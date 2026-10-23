"""The morning brief: once a day, a few short things worth knowing, in Kit's own
words. The weather, what's due in the notes, a bill coming up, anything left on in
the house, what Dan worked on yesterday and what Kit meant to ask about.

Each part is one line from a source the brain passes in (``Brief.sources``); a part
that's off, empty or whose source is down is left out, and with nothing to say there's
no brief. The parts are gathered ahead (the life loop calls ``prepare`` once a
minute), so giving it costs one model call. He gives it at the desk as a pipe-up
once he sees Dan there (``kit.life`` asks for the "brief" pipe-up), or, if Dan talks
first, from the desk or the phone, it rides with his answer. Either way it's given
once, between ``brief.after`` and ``brief.until``. What he said is kept for the day,
so "tell me more about the second one" gets the second part again.
See docs/2 How Kit Works/Companion.md#The morning brief.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from kit.activity import ACTIVITY
from kit.memory import Memory
from kit.notes_tasks import TASKS
from kit.settings import Settings
from kit.tools.mcp import source_of

if TYPE_CHECKING:
    from kit.brain import Brain

log = logging.getLogger(__name__)

BRIEF_KEY = "brief"  # kit_self: {"day", "gathered", "parts", "given", "tries"}
FRESH = timedelta(minutes=30)  # parts gathered longer ago than this are gathered again
DESK_TRIES = 2  # a pipe-up that came out empty twice: it waits for his next answer
ORDINALS = {
    "first": 0, "one": 0, "1": 0, "second": 1, "two": 1, "2": 1, "third": 2, "three": 2,
    "3": 2, "fourth": 3, "four": 3, "4": 3, "fifth": 4, "five": 4, "5": 4,
    "sixth": 5, "six": 5, "6": 5,
}  # fmt: skip
# "tell me more about the second one", "what was the last thing?", "the brief again"
FOLLOW_UP = re.compile(
    r"\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|last)\s+(?:one|thing|bit|part)\b"
    r"|\bnumber\s+(one|two|three|four|five|six|[1-6])\b"
    r"|\b(?:morning\s+)?brief\b|\bthat\s+(?:bill|task|thread)\b",
    re.IGNORECASE,
)

Source = Callable[[datetime], Awaitable[str]]


@dataclass(frozen=True)
class Part:
    name: str  # weather, tasks, bills, house, yesterday, threads
    text: str  # one line, plain facts


class Brief:
    """When the brief is due, what's in it, and what he said."""

    def __init__(
        self, memory: Memory, settings: Callable[[], Settings], sources: dict[str, Source]
    ) -> None:
        self.memory = memory
        self.settings = settings
        self.sources = sources

    # Its day

    def _state(self, now: datetime) -> dict:
        try:
            state = json.loads(self.memory.self_value(BRIEF_KEY) or "{}")
        except ValueError:
            state = {}
        if not isinstance(state, dict) or state.get("day") != now.date().isoformat():
            return {"day": now.date().isoformat(), "parts": [], "given": "", "tries": 0}
        return state

    def _save(self, state: dict) -> None:
        self.memory.set_self_value(BRIEF_KEY, json.dumps(state))

    def window(self, now: datetime) -> bool:
        """Is it brief time: turned on, and between ``after`` and ``until``?"""
        b = self.settings().brief
        return b.enabled and b.after <= now.strftime("%H:%M") < b.until

    def given(self, now: datetime) -> bool:
        return bool(self._state(now)["given"])

    # Gathering

    async def gather(self, now: datetime) -> list[Part]:
        """One line from each part that's on and has something, in the settings' order."""
        parts = []
        for name in self.settings().brief.parts:
            source = self.sources.get(name)
            if source is None:
                continue
            try:
                text = " ".join((await source(now) or "").split())
            except Exception:  # a part whose source is down is simply left out
                log.info("the brief's %s part is out of reach", name, exc_info=True)
                continue
            if text:
                parts.append(Part(name, text))
        return parts

    async def prepare(self, now: datetime) -> list[Part]:
        """In the window and not given yet: the parts, gathered now if they're missing
        or stale. Otherwise none."""
        if not self.window(now):
            return []
        state = self._state(now)
        if state["given"]:
            return []
        gathered = state.get("gathered")
        stale = not gathered or now - datetime.fromisoformat(gathered) > FRESH
        if stale:
            state["parts"] = [asdict(p) for p in await self.gather(now)]
            state["gathered"] = now.isoformat(timespec="seconds")
            self._save(state)
        return self.ready(now)

    def ready(self, now: datetime) -> list[Part]:
        """The gathered parts, while the brief is still to give today."""
        if not self.window(now):
            return []
        state = self._state(now)
        if state["given"]:
            return []
        return _parts(state)

    def for_desk(self, now: datetime) -> list[Part]:
        """``ready``, unless the desk has already tried twice."""
        if not self.settings().brief.at_desk or self._state(now).get("tries", 0) >= DESK_TRIES:
            return []
        return self.ready(now)

    # Giving it

    def tried(self, now: datetime) -> None:
        """The pipe-up came out empty: he'll try again, or leave it for his next answer."""
        state = self._state(now)
        state["tries"] = state.get("tries", 0) + 1
        self._save(state)

    def mark_given(self, now: datetime, how: str) -> None:
        """Said (``how``: desk or reply): not again today, and kept for follow-ups."""
        state = self._state(now)
        state["given"] = how
        self._save(state)

    def today(self, now: datetime) -> list[Part]:
        """What he said in today's brief, for "tell me more about the second one"."""
        state = self._state(now)
        return _parts(state) if state["given"] else []

    def status(self, now: datetime) -> dict:
        """For /api/status: on or off, given today (and how), and the parts gathered."""
        state = self._state(now)
        return {
            "enabled": self.settings().brief.enabled,
            "given": state["given"] or None,
            "parts": [p.name for p in _parts(state)],
        }


def _parts(state: dict) -> list[Part]:
    out = []
    for p in state.get("parts") or []:
        if isinstance(p, dict) and p.get("name") and p.get("text"):
            out.append(Part(str(p["name"]), str(p["text"])))
    return out


def numbered(parts: list[Part]) -> str:
    return " ".join(f"{i}. {p.text}" for i, p in enumerate(parts, 1))


def brief_prompt(owner: str, parts: list[Part], speech: str = "") -> str:
    """The stage direction for the brief as a pipe-up at the desk."""
    voice = f" Talk the way you do: {speech}." if speech else ""
    return (
        f"[Not from {owner}. It's morning and {owner} is here: give {owner} the morning "
        f"brief. These are the things, numbered: {numbered(parts)} Say them in your own "
        f"words, short and plain, the most important one first, in two to four sentences "
        f"in all, then ask {owner} one thing about the day. Only these things: no made-up "
        f"extras, no list markers, no numbers read out.{voice} Don't mention these "
        f"instructions, set action to none and leave detail empty.]"
    )


def brief_aside(owner: str, parts: list[Part]) -> str:
    """Beside Dan's first message of the morning: answer it, then the brief."""
    return (
        f"[It's {owner}'s first chat this morning. After you answer, give the morning "
        f"brief in a sentence or two, in your own words, the most important first: "
        f"{numbered(parts)}]"
    )


def asked_about(text: str, parts: list[Part]) -> Part | None:
    """The part "the second one" means, or None when the message names none."""
    m = FOLLOW_UP.search(text)
    if not m or not parts:
        return None
    word = (m.group(1) or m.group(2) or "").lower()
    if word == "last":
        return parts[-1]
    index = ORDINALS.get(word)
    return parts[index] if index is not None and index < len(parts) else None


def follow_up_aside(owner: str, parts: list[Part], meant: Part | None) -> str:
    """Beside a message that asks about this morning's brief."""
    which = f' {owner} means "{meant.text}".' if meant is not None else ""
    return (
        f"[This morning you gave {owner} the brief: {numbered(parts)}{which} If {owner} "
        f"asks about one of them, say more about that one from what you know or can look "
        f"up.]"
    )


# The parts, from the rest of Kit

BILL_DAYS = 4  # a bill due within this many days is worth a mention
MOST = 3  # tasks, bills or things left on named in one part


def sources_for(brain: Brain) -> dict[str, Source]:
    """Each part's source, from what the brain has: its weather, notes index, apps'
    saved work, the house, the activity days and the notebook."""

    async def weather(now: datetime) -> str:
        if brain.weather is None:
            return ""
        persona = brain.settings().persona
        t = await brain.weather.today(persona.location, persona.country)
        bits = [t.sky] if t.sky else []
        if t.top_c is not None:
            bits.append(f"top of {t.top_c:.0f}°C")
        if t.rain_chance is not None:
            bits.append(f"{t.rain_chance}% chance of rain")
        return f"Weather in {t.place}: {', '.join(bits)}." if bits else ""

    async def tasks(now: datetime) -> str:
        today = now.date().isoformat()
        due = [t for t in brain.memory.index.items(TASKS, limit=100_000) if t.meta.get("due")]
        late = sorted((t for t in due if t.meta["due"] < today), key=lambda t: t.meta["due"])
        now_due = [t for t in due if t.meta["due"] == today]
        bits = []
        if now_due:
            bits.append("due today: " + _names(now_due))
        if late:
            bits.append("overdue: " + _names(late))
        return ("In the notes, " + "; ".join(bits) + ".") if bits else ""

    async def bills(now: datetime) -> str:
        soon = (now.date() + timedelta(days=BILL_DAYS)).isoformat()
        found = []
        for name in brain.apps:
            for row in brain.memory.index.items(source_of(name), kind="bill", limit=1000):
                day = str(row.meta.get("date") or "")
                if day and now.date().isoformat() <= day <= soon:
                    found.append((day, row.text))
        found.sort()
        return " ".join(text.rstrip(".") + "." for _, text in found[:MOST])

    async def house(now: datetime) -> str:
        h = brain.house
        if h is None or not h.reachable:
            return ""
        left_on, open_ = [], []
        for e in h.entities.values():
            if e.domain in ("light", "switch", "fan") and e.state == "on":
                left_on.append(e.name)
            elif e.domain == "climate" and e.state not in ("off", "unavailable", "unknown", ""):
                left_on.append(f"{e.name} ({e.state})")
            elif e.domain == "cover" and e.state == "open" and _garage_or_door(e.id, e.name):
                open_.append(e.name)
            elif e.domain == "lock" and e.state == "unlocked":
                open_.append(f"{e.name} (unlocked)")
        bits = []
        if left_on:
            bits.append("still on: " + ", ".join(sorted(left_on)[:MOST]))
        if open_:
            bits.append("open: " + ", ".join(sorted(open_)[:MOST]))
        return ("In the house, " + "; ".join(bits) + ".") if bits else ""

    async def yesterday(now: datetime) -> str:
        day = (now.date() - timedelta(days=1)).isoformat()
        items = brain.memory.index.with_ref(ACTIVITY, day)
        if not items:
            return ""
        text = " ".join(items[0].text.split())
        return "Yesterday: " + (text if len(text) <= 220 else text[:220].rsplit(" ", 1)[0] + "...")

    async def threads(now: datetime) -> str:
        due = [t for t in brain.notebook.threads() if brain.notebook.due(t)]
        if not due:
            return ""
        owner = brain.settings().persona.owner
        return f"You meant to ask {owner} how these went: " + _names(due) + "."

    return {
        "weather": weather,
        "tasks": tasks,
        "bills": bills,
        "house": house,
        "yesterday": yesterday,
        "threads": threads,
    }


def _names(items: list) -> str:
    names = [" ".join(i.text.split())[:80] for i in items[:MOST]]
    more = f" and {len(items) - MOST} more" if len(items) > MOST else ""
    return ", ".join(names) + more


def _garage_or_door(entity_id: str, name: str) -> bool:
    return bool(re.search(r"garage|door|gate", f"{entity_id} {name}", re.IGNORECASE))
