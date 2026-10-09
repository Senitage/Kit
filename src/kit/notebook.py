"""Kit's notebook: what he thinks, wants and keeps for himself.

Facts in memory are about Dan. The notebook is Kit's own:

- thoughts he had in a quiet moment (kit.thinking), and opinions he's formed;
- wants: things he means to say or ask, until he does. They press harder the
  longer they wait, and his next pipe-up brings the most pressing one up. One
  for tomorrow ("ask me tomorrow how the shutdown went") waits till morning;
- moments worth keeping, and a journal entry for each day (kit.reflection);
- threads: things coming up in Dan's life that he named ("dentist Thursday arvo"),
  to ask how they went once they're over, once;
- bits: running jokes you two share, brought back now and then when something
  sets one off, and retired if they keep falling flat.

Entries live in the knowledge index as the ``self`` source, so recall finds
them like any memory ("what did you make of that?") and the memory page shows
them, with forget. Small thoughts fade after a couple of weeks (the journal
keeps their gist); opinions, moments and the journal stay until forgotten.

His self-sheet (who he thinks he is, in his own words), what's going on with Dan
lately (a short paragraph he writes each night) and the weekly reviews are kept
apart, as the ``self-sheet`` source: the sheet and the paragraph are always in his
prompt, so they're never recalled. Every version is kept, so Dan can go back to
one. His quirks live in ``kit_self``, with the ones he or Dan retired.
"""

from __future__ import annotations

import json
import random
import re
from datetime import date, datetime, time, timedelta

from kit.knowledge import STOPWORDS, Item
from kit.life import QUIRK_POOL, QUIRKS_KEY, WORK_QUIRKS, ago, my_quirks, parse_time, quoted
from kit.memory import SELF, SHEET, Memory
from kit.settings import PersonaSettings
from kit.when import When, asked_for, find_when, label, strip_when

KINDS = {
    "thought": "something he thought in a quiet moment",
    "opinion": "a view he's formed",
    "want": "something he means to say or ask",
    "moment": "something that happened that he wants to keep",
    "journal": "his diary entry for a day",
    "thread": "something coming up in Dan's life, to ask how it went",
    "bit": "a running joke you two share",
}
ASKING = ("want", "thread")  # kinds he means to bring up
WANT_STRENGTH = 0.7  # a new want; it presses a little harder each hour it waits
WANT_GROWS = 0.1
ASKED_STRENGTH = 1.0  # Dan asked to be asked: it comes up as soon as it's due
FRESH = timedelta(hours=3)  # an unsaid thought older than this is old news
LATELY = timedelta(hours=12)  # what counts as on his mind lately
THOUGHTS_KEEP = timedelta(days=14)
WANTS_KEEP = timedelta(days=7)  # said or not, by then it's moot
THREAD_STRENGTH = 0.8  # a thread due: he's wondering how it went
THREAD_KEEPS = timedelta(days=3)  # not asked by then, it's old news
THREADS_KEEP = timedelta(days=30)  # asked: kept a while for his reflection and recall
THREAD_AHEAD = timedelta(days=21)  # further out than this isn't worth following yet
BIT_REST = timedelta(hours=20)  # a running joke comes back once a day at most
BIT_FLOPS = 3  # brought back this often without a laugh, it's retired
# A want for later: it waits till the morning (the end of quiet hours).
FOR_LATER = re.compile(r"\b(tomorrow|in the morning|next morning|first thing)\b", re.I)
# Dan asking Kit to bring something up later: "Ask me tomorrow how the shutdown went",
# "check in after my 2 pm". The time must be in the same sentence (``asks_later``).
ASK_ME = re.compile(
    r"\b(ask|remind|check with|chase) me\b|\bcheck (in|back) (with|on) me\b"
    r"|(^|[.!?]\s*|\b(can|could|would|will) you |\bplease |\bkit,? )check (in|back)\b",
    re.I,
)
# Dan saying something's still to come, so it isn't how it went: "dentist in an hour".
STILL_TO_COME = re.compile(
    r"\b(in an? (hour|bit|minute|sec)|in \d+ (min|hour)|later on|soon|going to|gonna|"
    r"about to|wish me luck|heading|off to|on my way|on the way)\b",
    re.I,
)
# Words in a want that don't say what it's about ("ask Dan tomorrow about ...").
GENERIC = frozenset(
    "ask asked tell told say said bring mention tomorrow morning today later".split()
)
# Dan telling of something already over, or something for work: not a thread.
PAST = re.compile(
    r"\b(had|was|were|went|did|got back|came back|yesterday|ago|last (night|week|weekend|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.I,
)
WORKY = re.compile(
    r"\b(work|works|working|meetings?|shutdown|deadline|client|boss|report|presentation|"
    r"stand-?up|roster|shift|office|project|deploy|release|sprint|pull request|code|build|"
    r"tests? (run|suite)|review|audit|site visit|webinar|onboarding|payroll|invoice)\b",
    re.I,
)
# The weather and such: not something Dan does, so nothing to ask how it went.
NOT_EVENTS = re.compile(
    r"\b(hot|cold|warm|rain\w*|storm\w*|wind\w*|sunny|weather|forecast|nothing on|"
    r"nothing planned|no plans|free|tired|sick|crook)\b",
    re.I,
)
# "Remind me what we said": a question about the past, not something for later.
REMIND_WHAT = re.compile(r"\bremind me (what|who|when|where|how|why|which|if|whether)\b", re.I)
THREAD_SAME = timedelta(days=3)  # named again within this of the first: the same thing
# Words that don't say what a thread is about.
THREAD_FILLER = frozenset(
    """got get getting have having has going gonna heading head off booked booking need
    needs on for at in my the a an our we i im ive us this that some to with and of up
    out over about big busy long quiet good great fun huge massive coming come it its
    just so well oh then also really reckon think hope should might maybe probably
    nothing much anything everything plans plan""".split()
)
_ASKING_NICELY = re.compile(r"\b(can|could|would|will) you\b|\b(please|hey|kit)\b", re.I)
_FIRST_PERSON = re.compile(r"\b(i|me|my|mine|myself)\b|\bi['\u2019]", re.I)
AIMS = "ask|tell|remind|show|let|check in with|check with|chase"
RETIRED_KEY = "quirks_retired"
EVERYDAY_KEY = "quirks_everyday"  # the day his work quirks were swapped (once)
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


def asks_later(text: str, now: datetime, wake: str) -> datetime | None:
    """When Dan asked to be asked about something, if he did: "ask me this arvo how
    it went" is 1:30 pm, "check in after my 2 pm" about 2:30, "ask me tomorrow" the
    morning. The ask and the time must be in one sentence."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if ASK_ME.search(sentence) and not REMIND_WHAT.search(sentence):
            w = find_when(sentence, now, wake)
            if w is not None and not (w.past(now) and w.span not in ("clock", "part")):
                return asked_for(w, now, wake)
    return None


def thread_in(text: str, now: datetime, wake: str) -> tuple[str, When] | None:
    """Something coming up in Dan's life that he just named, worth asking about once
    it's over: "dentist Thursday arvo" is ("dentist", Thursday afternoon). Only one a
    message, and never for a question, something already started or past, work, the
    weather, or something more than three weeks out. Judged a sentence at a time, so
    "Got the dentist this arvo. Reckon the Eagles will win?" is still the dentist."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if "?" in sentence or PAST.search(sentence) or WORKY.search(sentence):
            continue
        if NOT_EVENTS.search(sentence):
            continue
        w = find_when(sentence, now, wake)
        if w is None or w.start <= now or w.start - now > THREAD_AHEAD:
            continue  # only what's still to come: "hot today" and "this morning" aren't
        first = w.words.split()[0]
        clause = next((c for c in re.split(r"[,;.!]", sentence) if first in c), sentence)
        about = _about(clause) or _about(sentence)
        if about:
            return about, w
    return None


def _about(text: str) -> str:
    """The words that say what something is, in order: "Got the dentist Thursday arvo"
    is "dentist"."""
    words = re.findall(r"[A-Za-z][A-Za-z'\u2019]*", strip_when(text))
    keep = [
        w
        for w in words
        if len(w) > 1 and _plain(w) not in THREAD_FILLER and _plain(w) not in STOPWORDS
    ]
    return " ".join(keep[:5])


def _plain(word: str) -> str:
    return word.lower().replace("\u2019", "'").removesuffix("'s").replace("'", "")


def _words(text: str) -> set[str]:
    """The words that carry meaning, "Milo's" as "milo"."""
    found = {_plain(w) for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\u2019]*", text)}
    return {w for w in found if len(w) > 2} - STOPWORDS


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


def later_want(text: str, owner: str) -> str:
    """What the owner asked to be asked later, as a want of Kit's own: "Ask me
    tomorrow how the shutdown went." is "Ask Dan how the shutdown went." When the ask
    leans on what came before it ("..., ask me tomorrow how it went") or speaks for
    the owner ("remind me that I need to call Bob"), their words are kept as said."""
    ask = re.search(r"\b(ask|remind|check with|chase) me\b", text, re.I)
    if ask is not None:
        before = _ASKING_NICELY.sub(" ", strip_when(text[: ask.start()]))
        rest = strip_when(text[ask.end() :])
        rest = rest.strip(" ,;:-").rstrip(".!?").strip()
        if not re.search(r"\w", before) and len(rest.split()) >= 2:
            if not _FIRST_PERSON.search(rest):
                return f"{ask.group(1).capitalize()} {owner} {rest}."
    elif re.search(r"\bcheck (in|back)\b", text, re.I):
        return f'Check in with {owner}, as {owner} asked: "{quoted(text, 200)}"'
    return f'{owner} asked you: "{quoted(text, 200)}"'


def as_aim(text: str, owner: str) -> tuple[str, str]:
    """A want as what he means to do and what about: "Tell Dan I counted 41 tabs."
    is ("tell Dan", "I counted 41 tabs."). Put to a small model as a note, it read it
    out ("Tell Dan I counted..."). A want put any other way is ("bring this up", the
    want)."""
    aim = re.match(
        rf"\W*(?:(?:tomorrow|later|next time)\W+)?({AIMS}) {re.escape(owner)}\b"
        rf"(?!['\u2019]s\b)\W*",
        text,
        re.I,
    )
    if aim is None or not text[aim.end() :].strip():
        return "bring this up", text
    return f"{aim.group(1).lower()} {owner}", text[aim.end() :]


def thread_when(item: Item, like: datetime) -> When | None:
    """When a thread's thing is, from what was kept with it."""
    meta = item.meta
    if not meta.get("start") or not meta.get("end") or not meta.get("span"):
        return None
    try:
        start, end = parse_time(str(meta["start"]), like), parse_time(str(meta["end"]), like)
    except ValueError:
        return None
    return When(start, end, "", str(meta["span"]), part=str(meta.get("part", "")))


def aim_of(item: Item, owner: str, now: datetime | None = None) -> tuple[str, str]:
    """What he means to do with a want or a thread, and what about (``as_aim``). A
    thread is asking how it went, with when as of ``now`` ("this afternoon") and what
    Dan said about it."""
    if item.kind != "thread":
        return as_aim(item.text, owner)
    w = thread_when(item, now) if now is not None else None
    text = f"{item.meta['about']}, {w.shown(now)}" if w is not None else item.text
    heard = item.meta.get("heard")
    said = f" {owner} said on {item.meta.get('heard_on', item.day)}: '{heard}'" if heard else ""
    return f"ask {owner} how it went", f"{text}.{said}"


def basis(persona: PersonaSettings) -> str:
    """What a self-sheet was written from: the persona's backstory and traits. When
    they change, his prompt shows the traits again beside the sheet, and his next
    reflection brings the sheet in line with them."""
    return f"{persona.backstory} | {'; '.join(persona.traits)}"


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

    def write(self, kind: str, text: str, again: bool = False, **meta) -> int | None:
        """Add an entry, unless it's empty or nearly the same as a recent one of its
        kind (``again`` allows that: a game he suggests now and then). Returns its id,
        or None if it wasn't added."""
        text = " ".join(text.split())
        kind = kind if kind in KINDS else "thought"
        if not text:
            return None
        if not again and any(same_entry(text, e.text) for e in self.entries(kind, 30)):
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
        """Forget one of his entries, or what he wrote about what's going on with Dan."""
        item = self.index.get(item_id)
        if item is None or not (item.source == SELF or (item.source, item.kind) == (SHEET, "dan")):
            return False
        return self.index.delete(item_id)

    def tidy(self) -> int:
        """Small thoughts fade after a couple of weeks (the journal keeps their gist),
        and a week-old want is moot, said or not. A thread not asked about within
        three days of being due is old news; one asked about stays a month. A running
        joke that keeps falling flat is retired. Opinions, moments and the journal
        stay. Returns how many entries went."""
        gone = 0
        now = self._now()
        for kind, keep in (("thought", THOUGHTS_KEEP), ("want", WANTS_KEEP)):
            for e in self.entries(kind, 5000):
                if self._age(e) > keep or (not e.meta.get("said") and self.expired(e)):
                    gone += self.index.delete(e.id)
        for e in self.entries("thread", 5000):
            after = self._after(e)
            stale = after is not None and now - after > THREAD_KEEPS
            if (e.meta.get("said") and self._age(e) > THREADS_KEEP) or (
                not e.meta.get("said") and stale
            ):
                gone += self.index.delete(e.id)
        for e in self.entries("bit", 500):
            if int(e.meta.get("uses", 0)) >= BIT_FLOPS and not int(e.meta.get("landed", 0)):
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

    def expired(self, want: Item) -> bool:
        """A want that's only worth saying till a time ("get to bed" till 4 am) and
        wasn't said by then."""
        until = want.meta.get("until")
        if not until:
            return False
        try:
            return self._now() >= parse_time(str(until), self._now())
        except ValueError:
            return False

    def due(self, want: Item) -> bool:
        """Is it time to bring ``want`` up? One for tomorrow waits till morning; one
        whose moment has passed never is."""
        after = self._after(want)
        return (after is None or self._now() >= after) and not self.expired(want)

    def pressure(self, want: Item) -> float:
        """How hard a want presses: from 0.7 when written, a little more each hour,
        and 0 while it waits for later. A thread presses from when it's due."""
        if not self.due(want):
            return 0.0
        since = self._age(want)
        if want.kind == "thread" and (after := self._after(want)) is not None:
            since = self._now() - after
        hours = since.total_seconds() / 3600
        start = WANT_STRENGTH if want.kind == "want" else THREAD_STRENGTH
        return min(1.0, float(want.meta.get("strength", start)) + WANT_GROWS * hours)

    def unsaid_wants(self) -> list[Item]:
        """Wants and threads he hasn't brought up yet, ones waiting for later included
        (last), most pressing first. A thread that's due comes before any want: how
        the dentist went matters more than what he's been meaning to say."""
        wants = [
            w
            for k in ASKING
            for w in self.entries(k, 100)
            if not w.meta.get("said") and not self.expired(w)
        ]
        return sorted(
            wants,
            key=lambda w: (w.kind == "thread" and self.due(w), self.pressure(w)),
            reverse=True,
        )

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
            about = _meaning(str(want.meta.get("about") or want.text))
            about = about - STOPWORDS - GENERIC - {owner.lower()}
            if about and 2 * len(about & words) >= len(about):
                self.mark_said(want.id)
                done.append(want.id)
        return done

    def pressing(self) -> float:
        """How hard his most pressing want presses (0 with none), for kit.life."""
        return max((self.pressure(w) for w in self.open_wants()), default=0.0)

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

    def on_mind(self, limit: int = 3, shared: bool = False) -> list[Item]:
        """What's on his mind lately: what he wants to bring up (two at most, ones
        for later last), then his newest thoughts and opinions. ``shared``: only what
        may go to a cloud model (nothing from what Dan kept local)."""
        # A thread waits till it's over: knowing it's coming, a small model asked early.
        wants = [w for w in self.unsaid_wants() if w.kind != "thread" or self.due(w)]
        items = [w for w in wants if not (shared and w.meta.get("private"))][:2]
        for e in self.entries(limit=20):
            if len(items) >= limit:
                break
            if shared and e.meta.get("private"):
                continue
            if e.kind in ("thought", "opinion") and self._age(e) < LATELY:
                items.append(e)
        return items

    def mind(self, owner: str, limit: int = 3, shared: bool = False) -> list[str]:
        """What's on his mind lately, as lines for his prompt: thoughts with how long
        ago, wants as what he means to do (``as_aim``) and when."""
        now = self._now()

        def line(e: Item) -> str:
            if e.kind not in ASKING:
                return f"({ago(parse_time(e.created, now), now)}) {e.text}"
            aim, about = aim_of(e, owner, now)
            after = self._after(e)
            if after is None or now >= after:
                return f"(you want to {aim}) {about}"
            return f"(you want to {aim} {_later(after, now)}, not before) {about}"

        return [line(e) for e in self.on_mind(limit, shared)]

    # Threads: what's coming up in Dan's life

    def write_thread(
        self, about: str, w: When, after: datetime, heard: str = "", by: str = "chat"
    ) -> int | None:
        """Follow something coming up in Dan's life: ask how it went from ``after``,
        once. Named again ("the dentist's moved to Friday"), the same thread moves;
        one already asked about isn't started again."""
        about = " ".join(about.split())
        if not about:
            return None
        meta = {
            "about": about,
            "start": w.start.isoformat(timespec="minutes"),
            "end": w.end.isoformat(timespec="minutes"),
            "after": after.isoformat(timespec="seconds"),
            "span": w.span,
            "part": w.part,
            "by": by,
        }
        if heard:
            meta |= {"heard": quoted(heard, 160), "heard_on": f"{self._now():%A}"}
        shown = label(w)
        text = shown if about.lower() in shown.lower() else f"{about}, {shown}"
        for t in self.entries("thread", 60):
            if not same_entry(about, str(t.meta.get("about", ""))):
                continue
            old = thread_when(t, w.start)
            if old is not None and abs(old.start - w.start) > THREAD_SAME and t.meta.get("said"):
                continue  # last week's footy: this week's is another
            if t.meta.get("said"):
                return None  # asked already
            self.index.update(t.id, text=text)
            self.index.set_meta(t.id, {**t.meta, **meta})
            return t.id
        return self.index.add(SELF, "thread", text, meta=meta)

    def threads(self) -> list[Item]:
        """Threads not asked about yet, soonest due first."""
        found = [t for t in self.entries("thread", 100) if not t.meta.get("said")]
        return sorted(found, key=lambda t: str(t.meta.get("after", "")))

    def followed(self, days: int = 7) -> list[Item]:
        """Threads asked about in the last ``days``, newest first, with what Dan said."""
        since = self._now() - timedelta(days=days)
        return [
            t
            for t in self.entries("thread", 100)
            if t.meta.get("said") and parse_time(str(t.meta["said"]), since) > since
        ]

    def heard_about(self, text: str) -> list[int]:
        """Dan told Kit how something went before Kit asked ("dentist was fine"): the
        thread is done, with what he said, so Kit never asks what he already knows.
        Not when it's still to come ("dentist in an hour, wish me luck"), and not
        before it starts."""
        if "?" in text or STILL_TO_COME.search(text):
            return []
        now, words, done = self._now(), _meaning(text), []
        for t in self.threads():
            about = _meaning(str(t.meta.get("about", ""))) - STOPWORDS
            start = t.meta.get("start")
            if not about or not start or parse_time(str(start), now) > now:
                continue
            if 2 * len(about & words) >= len(about):
                said = now.isoformat(timespec="seconds")
                self.index.set_meta(t.id, {**t.meta, "said": said, "outcome": quoted(text, 300)})
                done.append(t.id)
        return done

    def thread_outcome(self, item_id: int, text: str) -> None:
        """What Dan said when Kit asked how it went."""
        item = self.index.get(item_id)
        if item is not None and item.kind == "thread" and not item.meta.get("outcome"):
            self.index.set_meta(item_id, {**item.meta, "outcome": quoted(text, 300)})

    # Running jokes

    def write_bit(self, line: str, trigger: str, by: str = "") -> int | None:
        """A running joke, and the words that bring it back."""
        trigger = " ".join(trigger.split())
        if not _words(trigger):
            return None
        if any(same_entry(line, b.text) for b in self.entries("bit", 200)):
            return None
        return self.write("bit", line, trigger=trigger, uses=0, landed=0, by=by)

    def bit_for(self, text: str) -> Item | None:
        """A running joke something Dan said sets off, unless it came up today."""
        words, now = _words(text), self._now()
        for b in self.entries("bit", 200):
            trigger = _words(str(b.meta.get("trigger", "")))
            used = b.meta.get("used")
            rested = not used or now - parse_time(str(used), now) >= BIT_REST
            if trigger and trigger & words and rested:
                return b
        return None

    def bit_said(self, bit: Item, text: str) -> bool:
        """Did he bring the running joke back in ``text``? Two of its words will do
        (or all of them, if it has fewer), one of them not a word that sets it off,
        since those were in what Dan just said."""
        words, said = _words(bit.text), _words(text)
        own = words - _words(str(bit.meta.get("trigger", "")))
        return bool(own & said) and len(words & said) >= min(2, len(words))

    def bit_used(self, item_id: int, landed: bool | None = None) -> None:
        """He brought a running joke back (``landed`` None), or it got a laugh (True)."""
        item = self.index.get(item_id)
        if item is None or item.kind != "bit":
            return
        meta = dict(item.meta)
        if landed:
            meta["landed"] = int(meta.get("landed", 0)) + 1
        else:
            meta["uses"] = int(meta.get("uses", 0)) + 1
            meta["used"] = self._now().isoformat(timespec="seconds")
        self.index.set_meta(item_id, meta)

    # What's going on with Dan (he writes it each night)

    def dan(self) -> Item | None:
        found = self.index.items(SHEET, kind="dan", limit=1)
        return found[-1] if found else None

    def set_dan(self, text: str, note: str = "", private: bool = False) -> int:
        """A new version of what's going on with Dan; the old one stays in its history.
        ``private``: written from something Dan said to keep local, so it never goes
        in a cloud model's prompt."""
        old = self.dan()
        meta = {"note": note, "private": private}
        new_id = self.index.add(
            SHEET, "dan", text.strip(), title="What's going on with Dan", meta=meta
        )
        if old is not None:
            self.index.supersede(old.id, new_id)
        return new_id

    def dan_history(self) -> list[Item]:
        """Every version of what's going on with Dan, newest first."""
        current = self.dan()
        return self.index.history(current.id) if current else []

    # His journal

    def journal(self, day: str) -> Item | None:
        return next((e for e in self.entries("journal", 60) if e.ref == day), None)

    def write_journal(self, day: str, text: str, private: bool = False) -> int:
        """His diary entry for ``day``. Writing the same day again replaces it (the
        earlier entry stays in its history). A ``private`` one was written at home
        from what Dan kept local, and never goes to a cloud model."""
        old = self.journal(day)
        new_id = self.index.add(
            SELF,
            "journal",
            text.strip(),
            title=f"My journal, {day}",
            ref=day,
            created=f"{day}T23:59:59",
            meta={"private": True} if private else None,
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

    def swap_work_quirks(self, owner: str, rng: random.Random | None = None) -> list[str]:
        """Once: quirks he picked from the old pool that were all about work (pumps,
        flowsheets, spreadsheets) each go for an everyday one, as the owner's choice,
        so his reflection won't pick them up again. Returns the ones that went."""
        if self.memory.self_value(EVERYDAY_KEY) is not None:
            return []
        try:
            current = json.loads(self.memory.self_value(QUIRKS_KEY) or "[]")
        except ValueError:
            return []
        if not current:
            return []  # none picked yet: he'll pick from today's pool
        gone = [q for q in current if q in WORK_QUIRKS]
        if gone:
            held = set(current) | self.banned_quirks()
            choices = [q for q in QUIRK_POOL if q not in held]
            fresh = iter((rng or random.Random()).sample(choices, min(len(gone), len(choices))))
            kept = [q if q not in WORK_QUIRKS else next(fresh, "") for q in current]
            self.set_quirks([q for q in kept if q], retired_by="owner")
            self.add_veto(
                f"{owner} asked for less talk about work, code and calculations, so your "
                f"quirks about work were swapped for everyday ones. Don't pick up work "
                f"quirks again."
            )
        self.memory.set_self_value(EVERYDAY_KEY, self._now().date().isoformat())
        return gone

    # What the owner undid

    def vetoes(self) -> list[str]:
        try:
            return json.loads(self.memory.self_value(VETOES_KEY) or "[]")
        except ValueError:
            return []

    def add_veto(self, line: str) -> None:
        self.memory.set_self_value(VETOES_KEY, json.dumps([*self.vetoes(), line][-MAX_VETOES:]))
