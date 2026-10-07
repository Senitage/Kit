"""Kit's notebook: what he thinks, wants and keeps for himself.

Facts in memory are about Dan. The notebook is Kit's own:

- thoughts he had in a quiet moment (kit.thinking), and opinions he's formed;
- wants: things he means to say or ask, until he does. They press harder the
  longer they wait, and his next pipe-up brings the most pressing one up. One
  for tomorrow ("ask me tomorrow how the shutdown went") waits till morning;
- moments worth keeping, and a journal entry for each day (kit.reflection).

Entries live in the knowledge index as the ``self`` source, so recall finds
them like any memory ("what did you make of that?") and the memory page shows
them, with forget. Small thoughts fade after a couple of weeks (the journal
keeps their gist); opinions, moments and the journal stay until forgotten.

His self-sheet (who he thinks he is, in his own words) and the weekly reviews
of it are kept apart, as the ``self-sheet`` source: the sheet is always in his
prompt, so it's never recalled. Every version is kept, so Dan can go back to
one. His quirks live in ``kit_self``, with the ones he or Dan retired.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta

from kit.knowledge import STOPWORDS, Item
from kit.life import QUIRKS_KEY, ago, my_quirks, parse_time
from kit.memory import SELF, SHEET, Memory

KINDS = {
    "thought": "something he thought in a quiet moment",
    "opinion": "a view he's formed",
    "want": "something he means to say or ask",
    "moment": "something that happened that he wants to keep",
    "journal": "his diary entry for a day",
}
WANT_STRENGTH = 0.7  # a new want; it presses a little harder each hour it waits
WANT_GROWS = 0.1
FRESH = timedelta(hours=3)  # an unsaid thought older than this is old news
LATELY = timedelta(hours=12)  # what counts as on his mind lately
THOUGHTS_KEEP = timedelta(days=14)
WANTS_KEEP = timedelta(days=7)  # said or not, by then it's moot
# A want for later: it waits till the morning (the end of quiet hours).
FOR_LATER = re.compile(r"\b(tomorrow|in the morning|next morning|first thing)\b", re.I)
# Dan asking Kit to bring something up tomorrow: "Ask me tomorrow how the shutdown went."
ASK_LATER = re.compile(
    r"\b(ask|remind|check with|chase) me\b[^.!?]*\b(tomorrow|in the morning|first thing)\b"
    r"|\b(tomorrow|in the morning|first thing)\b[^.!?]*\b(ask|remind|check with|chase) me\b",
    re.I,
)
# Words in a want that don't say what it's about ("ask Dan tomorrow about ...").
GENERIC = frozenset(
    "ask asked tell told say said bring mention tomorrow morning today later".split()
)
RETIRED_KEY = "quirks_retired"
VETOES_KEY = "vetoes"  # what Dan undid, so the next reflection doesn't do it again
MAX_VETOES = 10


def _meaning(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower().replace("'", "")) if len(w) > 2}


def same_entry(a: str, b: str) -> bool:
    """Is ``a`` near enough ``b`` written again? Judged on the words that carry
    meaning, so "Ask Dan about the pump test" and "Ask Dan about the thickener" stay
    two wants."""
    wa, wb = _meaning(a) - STOPWORDS, _meaning(b) - STOPWORDS
    if not wa or not wb:
        return a.strip().lower().strip(".!?") == b.strip().lower().strip(".!?")
    return len(wa & wb) / len(wa | wb) >= 0.6


def morning(day: date, wake: str) -> str:
    """When quiet hours end (``life.quiet_until``) on ``day``: when a want for that
    day is due."""
    h, m = (int(x) for x in wake.split(":"))
    return datetime.combine(day, time(h, m)).isoformat(timespec="seconds")


def tomorrow_morning(now: datetime, wake: str) -> str:
    """When something for "tomorrow" is due. Said after midnight, before quiet hours
    end, tomorrow means this morning."""
    today = morning(now.date(), wake)
    if now.replace(tzinfo=None) < datetime.fromisoformat(today):
        return today
    return morning(now.date() + timedelta(days=1), wake)


def _later(when: datetime, now: datetime) -> str:
    days = (when.date() - now.date()).days
    part = "morning" if when.hour < 12 else "afternoon" if when.hour < 17 else "evening"
    if days <= 0:
        return f"this {part}"
    return f"tomorrow {part}" if days == 1 else f"on {when:%A}"


def basis(traits: list[str]) -> str:
    """What a self-sheet was written from. When the persona's traits change, his
    prompt shows them again beside the sheet until he next reflects."""
    return "; ".join(traits)


class Notebook:
    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        self.index = memory.index

    def _now(self) -> datetime:
        return self.memory.clock()

    def _age(self, item: Item) -> timedelta:
        now = self._now()
        return now - parse_time(item.created, now)

    # His entries

    def write(self, kind: str, text: str, **meta) -> int | None:
        """Add an entry, unless it's empty or nearly the same as a recent one of its
        kind. Returns its id, or None if it wasn't added."""
        text = " ".join(text.split())
        kind = kind if kind in KINDS else "thought"
        if not text or any(same_entry(text, e.text) for e in self.entries(kind, 30)):
            return None
        if kind == "want":
            meta.setdefault("strength", WANT_STRENGTH)
        return self.index.add(SELF, kind, text, meta=meta)

    def entries(self, kind: str | None = None, limit: int = 50) -> list[Item]:
        """Current entries (of one kind, if given), newest first."""
        return list(reversed(self.index.items(SELF, kind=kind, limit=limit)))

    def on(self, day: str) -> list[Item]:
        """What he noted on ``day``, journal aside, oldest first."""
        return [
            e for e in reversed(self.entries(limit=400)) if e.day == day and e.kind != "journal"
        ]

    def forget(self, item_id: int) -> bool:
        item = self.index.get(item_id)
        if item is None or item.source != SELF:
            return False
        return self.index.delete(item_id)

    def tidy(self) -> int:
        """Small thoughts fade after a couple of weeks (the journal keeps their gist),
        and a week-old want is moot, said or not. Opinions, moments and the journal
        stay. Returns how many entries went."""
        gone = 0
        for kind, keep in (("thought", THOUGHTS_KEEP), ("want", WANTS_KEEP)):
            for e in self.entries(kind, 5000):
                if self._age(e) > keep:
                    gone += self.index.delete(e.id)
        return gone

    # Wants and what's on his mind

    def _after(self, want: Item) -> datetime | None:
        """When a want for later is due, or None if it's due now."""
        after = want.meta.get("after")
        if not after:
            return None
        try:
            return parse_time(str(after), self._now())
        except ValueError:
            return None

    def due(self, want: Item) -> bool:
        """Is it time to bring ``want`` up? One for tomorrow waits till morning."""
        after = self._after(want)
        return after is None or self._now() >= after

    def pressure(self, want: Item) -> float:
        """How hard a want presses: from 0.7 when written, a little more each hour,
        and 0 while it waits for later."""
        if not self.due(want):
            return 0.0
        hours = self._age(want).total_seconds() / 3600
        return min(1.0, float(want.meta.get("strength", WANT_STRENGTH)) + WANT_GROWS * hours)

    def unsaid_wants(self) -> list[Item]:
        """Wants he hasn't said yet, ones waiting for later included (last), most
        pressing first."""
        wants = [w for w in self.entries("want", 100) if not w.meta.get("said")]
        return sorted(wants, key=self.pressure, reverse=True)

    def open_wants(self) -> list[Item]:
        """Wants he hasn't said yet and it's time for, most pressing first."""
        return [w for w in self.unsaid_wants() if self.due(w)]

    def said_in(self, text: str, owner: str) -> list[int]:
        """He just said ``text``: wants it brought up are said, so he doesn't ask
        again. A want counts when at least half the words saying what it's about
        are there ("How did the shutdown go?" for "Ask Dan how the shutdown went")."""
        words = _meaning(text)
        done = []
        for want in self.open_wants():
            about = _meaning(want.text) - STOPWORDS - GENERIC - {owner.lower()}
            if about and 2 * len(about & words) >= len(about):
                self.mark_said(want.id)
                done.append(want.id)
        return done

    def pressing(self) -> float:
        """How hard his most pressing want presses (0 with none), for kit.life."""
        wants = self.open_wants()
        return self.pressure(wants[0]) if wants else 0.0

    def to_share(self) -> Item | None:
        """What he'd bring up given the chance: his most pressing want, else his
        newest thought he hasn't said that isn't old news."""
        wants = self.open_wants()
        if wants:
            return wants[0]
        for t in self.entries("thought", 10):
            if not t.meta.get("said") and self._age(t) < FRESH:
                return t
        return None

    def mark_said(self, item_id: int) -> None:
        item = self.index.get(item_id)
        if item is not None and item.source == SELF:
            said = self._now().isoformat(timespec="seconds")
            self.index.set_meta(item_id, {**item.meta, "said": said})

    def latest_thought(self) -> Item | None:
        for e in self.entries(limit=20):
            if e.kind in ("thought", "opinion") and self._age(e) < LATELY:
                return e
        return None

    def on_mind(self, limit: int = 3) -> list[Item]:
        """What's on his mind lately: what he wants to bring up (two at most, ones
        for later last), then his newest thoughts and opinions."""
        items = self.unsaid_wants()[:2]
        for e in self.entries(limit=20):
            if len(items) >= limit:
                break
            if e.kind in ("thought", "opinion") and self._age(e) < LATELY:
                items.append(e)
        return items

    def mind(self, limit: int = 3) -> list[str]:
        """What's on his mind lately, as lines for his prompt, with how long ago."""
        now = self._now()

        def line(e: Item) -> str:
            if e.kind != "want":
                return f"({ago(parse_time(e.created, now), now)}) {e.text}"
            after = self._after(e)
            if after is None or now >= after:
                return f"(you want to bring this up) {e.text}"
            return f"(to bring up {_later(after, now)}, not before) {e.text}"

        return [line(e) for e in self.on_mind(limit)]

    # His journal

    def journal(self, day: str) -> Item | None:
        return next((e for e in self.entries("journal", 60) if e.ref == day), None)

    def write_journal(self, day: str, text: str) -> int:
        """His diary entry for ``day``. Writing the same day again replaces it (the
        earlier entry stays in its history)."""
        old = self.journal(day)
        new_id = self.index.add(
            SELF,
            "journal",
            text.strip(),
            title=f"My journal, {day}",
            ref=day,
            created=f"{day}T23:59:59",
        )
        if old is not None:
            self.index.supersede(old.id, new_id)
        return new_id

    # Who he thinks he is

    def sheet(self) -> Item | None:
        found = self.index.items(SHEET, kind="sheet", limit=1)
        return found[-1] if found else None

    def set_sheet(self, text: str, basis: str = "", note: str = "") -> int:
        """A new version of his self-sheet; the old one stays in its history.
        ``basis`` records the persona traits it was written from."""
        old = self.sheet()
        new_id = self.index.add(
            SHEET, "sheet", text.strip(), title="Who I am", meta={"basis": basis, "note": note}
        )
        if old is not None:
            self.index.supersede(old.id, new_id)
        return new_id

    def sheet_history(self) -> list[Item]:
        """Every version of his self-sheet, newest first."""
        current = self.sheet()
        return self.index.history(current.id) if current else []

    def restore_sheet(self, item_id: int, owner: str) -> int | None:
        """Go back to an earlier version of his self-sheet (the owner's veto). It comes
        back as a new version, so the one it replaces is kept too."""
        old = self.index.get(item_id)
        current = self.sheet()
        if old is None or old.source != SHEET or old.kind != "sheet" or current is None:
            return None
        if old.id == current.id:
            return current.id
        note = f"{owner} went back to the version from {old.day}"
        new_id = self.set_sheet(old.text, old.meta.get("basis", ""), note)
        self.add_veto(
            f"{owner} undid a change to your self-sheet, going back to the version from "
            f"{old.day}. Don't make that change again."
        )
        return new_id

    def add_review(self, text: str, **meta) -> int:
        return self.index.add(SHEET, "review", text.strip(), title="Weekly review", meta=meta)

    def reviews(self, limit: int = 5) -> list[Item]:
        """The weekly reviews of how he's changing, newest first."""
        return list(reversed(self.index.items(SHEET, kind="review", limit=limit)))

    # Quirks

    def quirks(self) -> list[str]:
        return my_quirks(self.memory)

    def retired_quirks(self) -> list[dict]:
        """Quirks he dropped or the owner took away: {quirk, by ("kit" or "owner"), day}."""
        try:
            return json.loads(self.memory.self_value(RETIRED_KEY) or "[]")
        except ValueError:
            return []

    def set_quirks(self, quirks: list[str], retired_by: str = "kit") -> None:
        """His quirks from now on. Any he no longer has go on the retired list."""
        try:
            before = json.loads(self.memory.self_value(QUIRKS_KEY) or "[]")
        except ValueError:
            before = []
        self.memory.set_self_value(QUIRKS_KEY, json.dumps(quirks))
        today = self._now().date().isoformat()
        retired = [r for r in self.retired_quirks() if r.get("quirk") not in quirks]
        retired += [{"quirk": q, "by": retired_by, "day": today} for q in before if q not in quirks]
        self.memory.set_self_value(RETIRED_KEY, json.dumps(retired[-20:]))

    def retire_quirk(self, quirk: str, owner: str) -> bool:
        """The owner's veto: take a quirk away. He won't pick it up again."""
        current = self.quirks()
        if quirk not in current:
            return False
        self.set_quirks([q for q in current if q != quirk], retired_by="owner")
        self.add_veto(f"{owner} took away your quirk '{quirk}'. Don't bring it back.")
        return True

    def restore_quirk(self, quirk: str, owner: str) -> bool:
        current = self.quirks()
        if quirk in current or quirk not in {r.get("quirk") for r in self.retired_quirks()}:
            return False
        self.set_quirks([*current, quirk])
        self.add_veto(f"{owner} brought back your quirk '{quirk}'.")
        return True

    def banned_quirks(self) -> set[str]:
        """Quirks the owner took away."""
        return {r["quirk"] for r in self.retired_quirks() if r.get("by") == "owner"}

    # What the owner undid

    def vetoes(self) -> list[str]:
        try:
            return json.loads(self.memory.self_value(VETOES_KEY) or "[]")
        except ValueError:
            return []

    def add_veto(self, line: str) -> None:
        self.memory.set_self_value(VETOES_KEY, json.dumps([*self.vetoes(), line][-MAX_VETOES:]))
