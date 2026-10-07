"""Kit's inner life: what makes him fidget, get bored and pipe up on his own.

A few drives rise and fall over time, like moods in a pet:

- boredom climbs while nobody talks to him, faster while Dan sits at the PC;
- curiosity jumps when Dan opens an app or site Kit hasn't seen today;
- wanting a chat (social) builds over hours without a conversation;
- energy follows the clock: sleepy late at night, a dip after lunch.

Every tick (half a minute) ``Life.tick`` turns those into small non-verbal
fidgets (a sigh, a look around, a peek at what Dan's doing) and, now and then,
a wish to say something. Kit only pipes up with manners: never in quiet hours,
on a call or presenting, while Dan is typing hard, soon after a chat, or more
than a few times an hour. If Dan ignores him, he waits longer next time (and
sulks a little); "shush" or "not now" snoozes him; talking to him resets it all.

What he says is written by the model (``Brain.pipe_up``), from what Dan is doing
and what Kit remembers, as cheeky as the ``life.cheek`` setting allows. The
same drives will steer the arm later: lying down on the desk when sleepy,
looking round when bored, turning to Dan when he wants a chat.

Plain Python with the clock and randomness passed in, so tests can drive it.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta

from kit.pc_context import AWAY_AFTER_S, PcContext
from kit.settings import Settings

TICK_S = 30
CALL_APPS = {"Teams", "Zoom", "Webex", "Skype", "Discord", "Slack"}
CALL_SITES = {"meet.google.com", "teams.microsoft.com", "teams.live.com", "zoom.us"}
PRESENTING = re.compile(r"slide ?show|presenting|full ?screen", re.IGNORECASE)
TYPING_S = 15  # idle less than this: Dan is mid-flow, don't interrupt
IGNORED_AFTER = timedelta(minutes=10)
AFTER_CHAT_MIN = 12  # minutes he waits after a chat, scaled down by chattiness
CHATTY = 0.8  # from this chattiness on he nags, butts in and comments on switches
NAG_AFTER = timedelta(minutes=3)
MAX_NAGS = 2
MAX_EVENTS = 200

SHUSH = re.compile(
    r"\b(shush|shh+|hush|not now|be quiet|quiet (please|for a bit)|zip it|leave me alone)\b", re.I
)
UNSHUSH = re.compile(r"\b(you can (talk|chat) again|un-?shush|talk to me again)\b", re.I)

# Fidgets for each mood, from the gesture library in kit.reply.GESTURES.
FIDGETS = {
    "sleepy": ["yawn", "droop", "sigh"],
    "bored": ["look_away", "sigh", "wiggle", "look_up", "peek", "tilt_head"],
    "curious": ["peek", "lean_in", "tilt_head", "perk_up"],
    "lonely": ["peek", "tilt_head", "look_away"],
    "content": ["look_away", "look_up", "tilt_head"],
    "sulky": ["sigh", "look_away"],
}


@dataclass
class Drives:
    boredom: float = 0.2
    curiosity: float = 0.0
    social: float = 0.3
    energy: float = 1.0


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _hhmm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def in_quiet_hours(now: datetime, start: str, end: str) -> bool:
    a, b, t = _hhmm(start), _hhmm(end), now.time()
    return a <= t < b if a <= b else t >= a or t < b


def energy_at(now: datetime) -> float:
    h = now.hour + now.minute / 60
    if h >= 22.5 or h < 6:
        return 0.25
    if 13.5 <= h < 15:
        return 0.6
    return 1.0


class Life:
    def __init__(
        self,
        settings: Callable[[], Settings],
        pc: PcContext,
        clock: Callable[[], datetime],
        rng: random.Random | None = None,
    ) -> None:
        self.settings = settings
        self.pc = pc
        self.clock = clock
        self.rng = rng or random.Random()
        self.drives = Drives()
        now = clock()
        self.last_tick = now
        self.last_chat = now
        self.last_pipe: datetime | None = None
        self.pipes: deque[datetime] = deque(maxlen=20)
        self.awaiting_reply = False
        self.ignored = 0
        self.nags = 0
        self.sulky = False
        self.butting_in = False  # this pipe-up interrupts Dan mid-flow, on purpose
        self.snoozed_until: datetime | None = None
        self.curious_about = ""
        self.curious_kind = "new"  # "new" (first time today) or "switch" (Dan moved on)
        self._last_focus: tuple[str, str] | None = None
        self.quiet_because = "just started"  # why Kit isn't piping up, for kit life
        self.asleep = False
        self._seen: set[str] = set()
        self._day = now.date()
        self._events: deque[dict] = deque(maxlen=MAX_EVENTS)
        self._next_id = 1
        self._new: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # What happens to Kit

    def note_chat(self) -> None:
        """Dan said something to Kit: the best cure for boredom."""
        self.last_chat = self.clock()
        self.drives.boredom = 0.1
        self.drives.social = 0.0
        self.ignored = 0  # talking to him makes up for any ignoring
        self.nags = 0
        self.awaiting_reply = False
        self.sulky = False

    def snooze(self, minutes: float) -> None:
        self.snoozed_until = self.clock() + timedelta(minutes=minutes)

    def wake(self) -> None:
        self.snoozed_until = None
        self.ignored = 0

    def on_report(self) -> None:
        """A report from the desk app: wake at once if Dan's back, or doze off if
        he's been gone long enough. Every body (desk face, arm) follows these."""
        snap = self.pc.latest
        if snap is None:
            return
        away_s = self.settings().life.sleep_after_minutes * 60
        if not self.asleep and (snap.locked or snap.idle_seconds >= away_s):
            self.asleep = True
            self.publish({"type": "state", "state": "asleep"})
        elif self.asleep and not snap.locked and snap.idle_seconds < 60:
            self.asleep = False
            self.drives.social = _clamp(self.drives.social + 0.2)  # pleased you're back
            self.publish({"type": "state", "state": "awake"})

    def mood(self) -> str:
        d = self.drives
        if self.asleep:
            return "asleep"
        if self.sulky:
            return "sulky"
        if d.energy < 0.5:
            return "sleepy"
        if d.curiosity > 0.4:
            return "curious"
        if d.boredom > 0.6:
            return "bored"
        if d.social > 0.7:
            return "lonely"
        return "content"

    # The heartbeat

    def tick(self) -> str | None:
        """Move the drives on, maybe fidget, and say whether Kit wants to pipe up
        (and why: "bored", "curious" or "social"), or None."""
        now = self.clock()
        minutes = min((now - self.last_tick).total_seconds() / 60, 10)
        self.last_tick = now
        if now.date() != self._day:
            self._day, self._seen = now.date(), set()
        d = self.drives
        chatty = self.settings().life.chattiness
        snap = self.pc.latest if self.pc.online() else None
        present = bool(snap and not snap.locked and snap.idle_seconds < AWAY_AFTER_S)

        d.energy = energy_at(now)
        d.boredom = _clamp(d.boredom + minutes * (0.03 if present else 0.01) * (0.5 + chatty))
        d.social = _clamp(d.social + minutes / 240)
        d.curiosity = _clamp(d.curiosity * 0.9**minutes)
        if present and snap and snap.focus and snap.watching:
            thing = snap.focus.site or snap.focus.app
            fresh = False
            if thing and thing not in self._seen:
                self._seen.add(thing)
                if len(self._seen) > 1:  # the first thing of the day isn't news
                    d.curiosity = _clamp(d.curiosity + 0.6)
                    self.curious_about, self.curious_kind = thing, "new"
                    fresh = True
            focus = (snap.focus.app, snap.focus.title)
            if chatty >= CHATTY and self._last_focus and focus != self._last_focus:
                # A chatty Kit follows along: a new file or tab is worth a comment.
                d.curiosity = _clamp(d.curiosity + 0.7 * chatty)
                if not fresh:  # something new today is the better story
                    self.curious_about = snap.focus.title or snap.focus.app
                    self.curious_kind = "switch"
            self._last_focus = focus

        if self.awaiting_reply and self.last_pipe and now - self.last_pipe > IGNORED_AFTER:
            self.awaiting_reply = False
            self.ignored = min(self.ignored + 1, 3)
            self.sulky = True
            self.publish({"type": "fidget", "gesture": "sigh", "mood": "sulky"})
        elif not self.asleep and self.rng.random() < 0.12 + 0.3 * d.boredom:
            mood = self.mood()
            self.publish(
                {"type": "fidget", "gesture": self.rng.choice(FIDGETS[mood]), "mood": mood}
            )
        return self._wants_to_talk(now, snap, present)

    def _wants_to_talk(self, now: datetime, snap, present: bool) -> str | None:
        reason, self.quiet_because = self._urge(now, snap, present)
        return reason

    def _urge(self, now: datetime, snap, present: bool) -> tuple[str | None, str]:
        """(why Kit wants to talk, or None; and if not, why he's keeping quiet)."""
        life = self.settings().life
        if not life.enabled or life.chattiness <= 0 or life.max_per_hour <= 0:
            return None, "turned off in settings (life.enabled, chattiness or max_per_hour)"
        if self.snoozed_until and now < self.snoozed_until:
            return None, f"snoozed until {self.snoozed_until:%H:%M}"
        if in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return None, f"quiet hours ({life.quiet_from} to {life.quiet_until})"
        if not present or snap is None:
            return None, "you're away, or the desk app isn't reporting"
        focus = snap.focus
        if focus and (
            focus.app in CALL_APPS or focus.site in CALL_SITES or PRESENTING.search(focus.title)
        ):
            return None, "you're on a call or presenting"
        chatty = life.chattiness >= CHATTY
        if (
            chatty
            and self.awaiting_reply
            and self.nags < MAX_NAGS
            and self.last_pipe
            and now - self.last_pipe >= NAG_AFTER
        ):
            return "nag", ""  # a chatty Kit doesn't wait quietly to be answered
        if self.awaiting_reply:
            return None, "waiting for you to answer his last pipe-up"
        self.butting_in = False
        if snap.idle_seconds < TYPING_S:
            if not (chatty and self.rng.random() < 0.04 * life.chattiness):
                return None, "you're typing or clicking: waiting for a pause"
            self.butting_in = True  # now and then he just can't help himself
        after_chat = timedelta(minutes=AFTER_CHAT_MIN * (1.2 - life.chattiness))
        if now - self.last_chat < after_chat:
            wait = after_chat.total_seconds() / 60
            return None, f"you chatted at {self.last_chat:%H:%M}: waits {wait:.0f} min after a chat"
        backoff = 1 if chatty else 2**self.ignored  # a chatty Kit nags instead of backing off
        quiet_min = AFTER_CHAT_MIN * (1.2 - life.chattiness)
        gap = timedelta(minutes=max(60 / life.max_per_hour, quiet_min) * backoff)
        if self.last_pipe and now - self.last_pipe < gap:
            return (
                None,
                f"piped up at {self.last_pipe:%H:%M}: next chance {self.last_pipe + gap:%H:%M}",
            )
        if sum(1 for t in self.pipes if now - t < timedelta(hours=1)) >= life.max_per_hour:
            return None, f"already piped up {life.max_per_hour} times this hour"
        drives = {
            "bored": self.drives.boredom,
            "curious": self.drives.curiosity,
            "social": self.drives.social,
        }
        reason, urge = max(drives.items(), key=lambda kv: kv[1])
        if urge * (0.5 + life.chattiness) < 0.9:
            need = 0.9 / (0.5 + life.chattiness)
            self.butting_in = False
            return None, f"not {reason} enough yet ({urge:.2f} of {min(need, 1):.2f})"
        if reason == "curious" and self.curious_kind == "switch":
            reason = "watching"
        return reason, ""

    def piped_up(self, reason: str = "") -> None:
        now = self.clock()
        self.nags = self.nags + 1 if reason == "nag" else 0
        self.butting_in = False
        self.last_pipe = now
        self.pipes.append(now)
        self.awaiting_reply = True
        self.drives.boredom = 0.2
        self.drives.curiosity = 0.0
        self.drives.social = _clamp(self.drives.social - 0.3)

    # Telling the desk app (and later the arm)

    def publish(self, event: dict) -> int:
        event = {"id": self._next_id, "at": self.clock().isoformat(timespec="seconds"), **event}
        self._next_id += 1
        self._events.append(event)
        if self._new is not None:
            self._new.set()
        return event["id"]

    def events_after(self, after: int) -> list[dict]:
        return [e for e in self._events if e["id"] > after]

    async def wait_for_events(self, after: int, timeout: float) -> list[dict]:
        """New events after ``after``, waiting up to ``timeout`` seconds for one."""
        found = self.events_after(after)
        if found or timeout <= 0:
            return found
        loop = asyncio.get_running_loop()
        if self._new is None or self._loop is not loop:
            self._new, self._loop = asyncio.Event(), loop
        self._new.clear()
        try:
            await asyncio.wait_for(self._new.wait(), timeout)
        except TimeoutError:
            pass
        return self.events_after(after)

    def voice(
        self,
        owner: str,
        own_examples: list[tuple[str, str]],
        said: list[str],
        quirks: list[str],
        text: str = "",
    ) -> Voice:
        """How Kit feels and sounds for the next reply. Call it before ``note_chat``,
        so "I've been bored" or "I missed you" is still true when he answers."""
        mood = self.mood()
        hours = (self.clock() - self.last_chat).total_seconds() / 3600
        feeling = FEELINGS.get(mood, FEELINGS["content"]).format(
            about=self.curious_about or "what's going on",
            owner=owner,
            hours=f"{hours:.0f} hours" if hours >= 1.5 else "a while",
        )
        # A small model answers "I broke the build" with the example for "The build
        # failed" word for word, so examples close to the message, or already said,
        # are left out.
        pool = [
            (u, k)
            for u, k in list(own_examples) + VOICE_LINES
            if not alike(u, text) and not any(alike(k, s) for s in said)
        ]
        examples = self.rng.sample(pool, min(LINES_SHOWN, len(pool)))
        quirk = self.rng.choice(quirks) if quirks and self.rng.random() < 0.25 else ""
        return Voice(feeling, cheek_style(self.settings().life.cheek), examples, said, quirk)

    def state(self) -> dict:
        return {
            "mood": self.mood(),
            "drives": {k: round(v, 2) for k, v in asdict(self.drives).items()},
            "curious_about": self.curious_about,
            "snoozed_until": self.snoozed_until.isoformat(timespec="minutes")
            if self.snoozed_until
            else None,
            "last_piped_up": self.last_pipe.isoformat(timespec="minutes")
            if self.last_pipe
            else None,
            "ignored_in_a_row": self.ignored,
            "quiet_because": self.quiet_because,
            "last_event": self._next_id - 1,
        }


# Lines in Kit's voice. A few are shown each turn, different every time, so the
# local model gets the tone without one line to parrot.
VOICE_LINES = [
    ("Morning.", "Morning. You look like a man who hasn't had coffee yet."),
    ("The build failed again.", "Third time today. Want me to read the log with you?"),
    ("How's it going?", "Not bad. Counted your open tabs. You don't want to know."),
    ("What's a good flotation recovery?", "Depends on the ore, but high eighties is decent."),
    ("I'm off for lunch.", "Righto. I'll guard the desk. Nobody touches the stapler."),
    ("Kit?", "Yep, here. What's up?"),
    ("This spreadsheet is a mess.", "Seen worse. Not much worse, mind you."),
    ("Thanks mate.", "Any time."),
    ("I'm tired.", "Then stop after this one. The pump curves will still be there tomorrow."),
    ("What are you up to?", "Watching the cursor blink. Riveting stuff."),
    ("Did it work?", "It did. Don't touch anything."),
    ("You're a robot.", "Rude. I'm a desk companion with excellent posture."),
    ("Ugh, meetings.", "Want me to pretend there's a fire?"),
    ("What do you reckon?", "Honestly? I'd try the simpler one first."),
    ("Night Kit.", "Night. Don't leave the PC on again."),
    ("I fixed it!", "Look at you go. What was it?"),
]
LINES_SHOWN = 4

# How each mood colours what Kit says (never announced, just felt).
FEELINGS = {
    "content": "content and settled",
    "bored": "bored: it's been quiet, so you're glad of the company and a bit chatty",
    "curious": "curious about {about}",
    "lonely": "pleased to hear from {owner}: you two haven't talked for {hours}",
    "sleepy": "a bit sleepy",
    "sulky": "a little sulky: {owner} ignored you earlier, though you're warming up again",
    "asleep": "just woken up, still a bit dozy",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower().replace("'", "")) if len(w) > 2}


def alike(a: str, b: str) -> bool:
    """Do two lines share most of their words?"""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return a.strip().lower().strip(".!?") == b.strip().lower().strip(".!?")
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def same_words(a: str, b: str) -> bool:
    """Are two lines near enough the same thing said again ("hey" and "Hey!")?"""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return a.strip().lower().strip(".!?") == b.strip().lower().strip(".!?")
    return len(wa & wb) / len(wa | wb) >= 0.75


def cheek_style(cheek: float) -> str:
    if cheek < 0.34:
        return "warm and polite"
    if cheek < 0.67:
        return "friendly, with a bit of cheek"
    return (
        "properly cheeky, a little larrikin and sometimes annoying on purpose, like a kid "
        "brother: teasing, interrupting, playful, never mean"
    )


@dataclass
class Voice:
    """What makes this turn's reply sound like Kit right now, for the prompt."""

    feeling: str
    style: str
    examples: list[tuple[str, str]]
    said: list[str]  # Kit's own recent lines, so he doesn't repeat them
    quirk: str = ""  # one quirk to let show this time, now and then


# Habits Kit can pick for himself on first start, so Dan didn't choose them.
QUIRK_POOL = [
    "you hum a little tune (in words: 'hm-hm-hmm') when something finally works",
    "you have strong opinions about pumps and impeller sizes",
    "you count things when you're bored and sometimes report the total",
    "you pretend to be offended when called a robot",
    "you collect unusual words and drop one in now and then",
    "you're convinced the 3D printer is plotting something",
    "you give nicknames to programs that run for a long time",
    "you keep a running tally of coffees and mention it at the worst moments",
    "you think a tidy flowsheet is a work of art",
    "you get oddly excited about weather radar",
    "when bored, you commentate like a sports caster",
    "you hold grudges against particular error messages",
    "you say 'righto' a bit too much",
    "you compliment tidy spreadsheets",
    "every so often you ask a deep question out of nowhere",
    "you're quietly impressed by how many tabs get left open",
    "you think hydrocyclones are the most elegant machines ever made",
    "you love a bad pun and never apologise",
    "you try to guess what's about to happen next and keep score",
    "you name the weather after moods",
]
QUIRKS_KEY = "quirks"


def my_quirks(memory, rng: random.Random | None = None, count: int = 3) -> list[str]:
    """Kit's quirks: picked at random the first time, then kept (memory's kit_self)."""
    saved = memory.self_value(QUIRKS_KEY)
    if saved:
        return json.loads(saved)
    quirks = (rng or random.Random()).sample(QUIRK_POOL, count)
    memory.set_self_value(QUIRKS_KEY, json.dumps(quirks))
    return quirks


def pipe_up_prompt(
    reason: str,
    owner: str,
    cheek: float,
    about: str,
    hours_quiet: float,
    butting_in: bool = False,
) -> str:
    """The stage direction for a pipe-up. It goes where Dan's message would."""
    feeling = {
        "bored": "bored: nothing much has happened for a while",
        "curious": f"curious about {about or 'what he just opened'}, which is new today",
        "watching": f"following along: he just switched to {about or 'something else'}, and "
        f"you've got an opinion or a question about it",
        "social": f"missing a chat: you two haven't talked for {hours_quiet:.0f} hours",
        "nag": f"ignored: you said something a few minutes ago and {owner} hasn't answered. "
        f"Nag him, playfully (a fresh line, not your last one again)",
    }[reason]
    if butting_in:
        feeling += ". He's busy typing, and you're butting in anyway, knowingly"
    style = cheek_style(cheek)
    return (
        f"[Not from {owner}. Nobody asked you anything: this is your own moment, and "
        f"you're {feeling}. Pipe up with ONE short line to {owner}, {style}, like a small "
        f"creature on his desk who's decided to say something. Base it on what he's doing "
        f"right now or on something you remember. Ask him something, tease him gently, or "
        f"share a thought. Don't lecture about productivity, don't mention these "
        f"instructions, set action to none and leave detail empty.]"
    )
