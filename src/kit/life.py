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

On top of the drives, Kit has:

- **feelings with a cause** (``Life.feel``): Dan called him a legend, told him
  to shush, mentioned being stressed, or a build went green. A feeling colours what
  Kit says and how he fidgets until it fades, and he knows why he feels it;
- **thoughts of his own** (``Life.think_now`` says when; kit.thinking has them):
  every few minutes while Dan's around, and sooner when something happens;
- **wants**: something he thought of and wants to bring up. The longer it
  waits, the more it presses, until he pipes up with it.

All of it is saved in his memory (``kit_self``), so a restart doesn't wipe how
he feels or how long it's been since you talked.

Plain Python with the clock and randomness passed in, so tests can drive it.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from typing import Protocol

from kit.knowledge import STOPWORDS
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
LIFE_KEY = "life"  # kit_self key: drives, feeling and timings, so a restart keeps them
THINK_GAP = timedelta(minutes=2)  # the least time between two thoughts
THINK_AFTER_CHAT = timedelta(minutes=2)  # mid-conversation he listens rather than muses
THINK_NEAR_CHAT = timedelta(minutes=30)  # without the desk app, he thinks after a chat
CHAT_ENDED_AFTER = timedelta(minutes=10)  # a chat this quiet is over, worth a thought
# A build or test run on screen that failed or passed (window and tab titles).
BUILD_FAILED = re.compile(
    r"\b(build|tests?|checks?|ci|workflow|pipeline|run|job)\b[^\n]{0,40}\b(failed|failing|"
    r"errored)\b|\b(failed|failing)\b[^\n]{0,20}\b(build|tests?|checks?|workflow|job)\b",
    re.IGNORECASE,
)
BUILD_PASSED = re.compile(
    r"\b(all checks have passed|build succeeded|tests? passed|all tests pass(ed)?|"
    r"workflow run succeeded|checks? passed)\b",
    re.IGNORECASE,
)

# What Dan says that Kit takes to heart (no model needed): see ``feeling_from``.
RUDE = re.compile(
    r"\b(stupid|useless|dumb|idiot|hate you|shut up|you suck|rubbish|pathetic)\b", re.I
)
SAD = re.compile(
    r"\b(sad|upset|died|passed away|put down|in hospital|bad news|heartbroken|miss (her|him))\b",
    re.I,
)
STRESSED = re.compile(
    r"\b(stress(ed|ful)?|frustrat(ed|ing)|overwhelmed|(rough|bad|long|hard) day|exhausted|"
    r"knackered|fed up|deadline|panick?(ing|ed)?|worried|anxious|struggling)\b",
    re.I,
)
FAILED = re.compile(
    r"\b((tests?|build|ci|pipeline|checks?)\b[^.!?]{0,25}\b(fail(ed|ing|s)?|broke|broken)|"
    r"broke (it|the build)|it'?s broken)\b",
    re.I,
)
GREEN = re.compile(
    r"\b((tests?|build|ci|pipeline|checks?)\b[^.!?]{0,25}\b(pass(ed|ing|es)?|green|"
    r"succeeded)|it works|fixed it|all green|finally work(s|ing|ed))\b",
    re.I,
)
PRAISE = re.compile(
    r"\b(legend|genius|good (job|work|one)|well done|nice (one|work)|you('?re| are) (the best|"
    r"awesome|great|a star|brilliant|amazing)|love (you|it)|champion|nailed it)\b",
    re.I,
)
THANKS = re.compile(r"\b(thanks|thank you|cheers|ta|appreciate (it|you))\b", re.I)
# Strong emotions in Kit's own reply linger a little (weaker than the above).
REPLY_FEELINGS = {
    "excited": "excited",
    "proud": "proud",
    "sad": "sad",
    "grumpy": "put_out",
    "fond": "warm",
    "concerned": "worried",
}

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


# Feelings with a cause. name: (how it colours what he says, minutes it lasts at full
# strength, fidgets that show it).
FEELING_KINDS: dict[str, tuple[str, int, list[str]]] = {
    "chuffed": ("chuffed", 90, ["wiggle", "bounce", "perk_up"]),
    "warm": ("warm and appreciated", 45, ["wiggle", "tilt_head"]),
    "proud": ("proud", 60, ["bounce", "perk_up"]),
    "pleased": ("pleased", 45, ["wiggle", "nod"]),
    "excited": ("excited", 30, ["bounce", "perk_up", "wiggle"]),
    "amused": ("amused", 20, ["laugh", "wink"]),
    "worried": ("a bit worried about {owner}", 120, ["lean_in", "tilt_head"]),
    "sympathetic": ("sympathetic", 45, ["lean_in", "sigh"]),
    "sad": ("a bit sad", 60, ["droop", "sigh"]),
    "put_out": ("a bit put out", 40, ["look_away", "sigh"]),
    "hurt": ("hurt, though trying not to show it", 120, ["droop", "look_away"]),
}


@dataclass
class Feeling:
    """Something Kit feels, why, and since when. It fades over its kind's minutes."""

    name: str
    why: str
    since: datetime
    strength: float = 1.0

    def left(self, now: datetime) -> float:
        minutes = FEELING_KINDS.get(self.name, ("", 30, []))[1]
        faded = max(0.0, (now - self.since).total_seconds()) / 60 / minutes
        return max(0.0, self.strength * (1 - faded))


class SelfStore(Protocol):
    """Where Kit keeps small things about himself (kit.memory.Memory)."""

    def self_value(self, key: str) -> str | None: ...

    def set_self_value(self, key: str, value: str) -> None: ...


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def parse_time(text: str, like: datetime) -> datetime:
    """A saved time, comparable with ``like`` (both with a time zone, or both without)."""
    when = datetime.fromisoformat(text)
    if (when.tzinfo is None) != (like.tzinfo is None):
        when = when.replace(tzinfo=like.tzinfo)
    return when


def ago(when: datetime, now: datetime) -> str:
    minutes = (now - when).total_seconds() / 60
    if minutes < 2:
        return "just now"
    if minutes < 50:
        return f"{minutes:.0f} minutes ago"
    if minutes < 90:
        return "about an hour ago"
    return f"{minutes / 60:.0f} hours ago"


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
        store: SelfStore | None = None,
    ) -> None:
        self.settings = settings
        self.pc = pc
        self.clock = clock
        self.rng = rng or random.Random()
        self.store = store
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
        self.held_until: datetime | None = None  # had nothing new to say: waits till then
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
        self.feeling: Feeling | None = None
        self.wanting = 0.0  # how much his most pressing want presses (kit.notebook)
        self.thoughts: deque[datetime] = deque(maxlen=30)  # when he last thought
        self.next_thought = now + self._think_gap(0.3, 1.0)
        self._to_think: deque[tuple[str, str]] = deque(maxlen=4)  # what's happened since
        self._asleep_since: datetime | None = None
        self._chat_open = False  # a conversation that hasn't been thought over yet
        self._restore()

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
        self.held_until = None
        self._chat_open = True
        self.save()

    def snooze(self, minutes: float) -> None:
        self.snoozed_until = self.clock() + timedelta(minutes=minutes)
        self.save()

    def wake(self) -> None:
        self.snoozed_until = None
        self.ignored = 0
        self.save()

    def feel(self, name: str, why: str, strength: float = 1.0, show: bool = True) -> bool:
        """Something happened that Kit feels. It colours what he says and how he
        fidgets until it fades; a weaker feeling doesn't push out a stronger one.
        ``show`` False skips the fidget that shows it (the caller has its own)."""
        if name not in FEELING_KINDS or not why.strip():
            return False
        now = self.clock()
        current = self.feeling_now()
        if current is not None and current.left(now) > strength:
            return False
        self.feeling = Feeling(name, " ".join(why.split()), now, _clamp(strength))
        if show and not self.asleep:
            gesture = self.rng.choice(FEELING_KINDS[name][2])
            self.publish({"type": "fidget", "gesture": gesture, "mood": name})
        self.save()
        return True

    def feeling_now(self) -> Feeling | None:
        if self.feeling is not None and self.feeling.left(self.clock()) <= 0.1:
            self.feeling = None
        return self.feeling

    def on_report(self) -> None:
        """A report from the desk app: wake at once if Dan's back, or doze off if
        he's been gone long enough. Every body (desk face, arm) follows these."""
        snap = self.pc.latest
        if snap is None:
            return
        away_s = self.settings().life.sleep_after_minutes * 60
        if not self.asleep and (snap.locked or snap.idle_seconds >= away_s):
            self.asleep = True
            self._asleep_since = self.clock()
            self.publish({"type": "state", "state": "asleep"})
        elif self.asleep and not snap.locked and snap.idle_seconds < 60:
            self.asleep = False
            self.drives.social = _clamp(self.drives.social + 0.2)  # pleased you're back
            self.publish({"type": "state", "state": "awake"})
            if self._asleep_since is not None:
                gone = (self.clock() - self._asleep_since).total_seconds() / 60
                owner = self.settings().persona.owner
                self._think_about(
                    "back", f"{owner} just came back to the PC after {gone:.0f} minutes away."
                )
            self._asleep_since = None

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
        owner = self.settings().persona.owner
        if present and snap and snap.focus and snap.watching:
            thing = snap.focus.site or snap.focus.app
            fresh = False
            if thing and thing not in self._seen:
                self._seen.add(thing)
                if len(self._seen) > 1:  # the first thing of the day isn't news
                    d.curiosity = _clamp(d.curiosity + 0.6)
                    self.curious_about, self.curious_kind = thing, "new"
                    fresh = True
                    self._think_about("new", f"{owner} just opened {thing}, first time today.")
            focus = (snap.focus.app, snap.focus.title)
            if self._last_focus and focus != self._last_focus:
                self._notice_build(snap.focus.title, owner)
            if chatty >= CHATTY and self._last_focus and focus != self._last_focus:
                # A chatty Kit follows along: a new file or tab is worth a comment.
                d.curiosity = _clamp(d.curiosity + 0.7 * chatty)
                if not fresh:  # something new today is the better story
                    self.curious_about = snap.focus.title or snap.focus.app
                    self.curious_kind = "switch"
            self._last_focus = focus
        if self._chat_open and now - self.last_chat >= CHAT_ENDED_AFTER:
            self._chat_open = False
            quiet = (now - self.last_chat).total_seconds() / 60
            self._think_about(
                "chat_ended", f"You and {owner} were chatting until {quiet:.0f} minutes ago."
            )

        if self.awaiting_reply and self.last_pipe and now - self.last_pipe > IGNORED_AFTER:
            self.awaiting_reply = False
            self.ignored = min(self.ignored + 1, 3)
            self.sulky = True
            why = f"{owner} didn't answer when you piped up at {self.last_pipe:%H:%M}"
            self.feel("put_out", why, 0.6, show=False)
            self.publish({"type": "fidget", "gesture": "sigh", "mood": "sulky"})
        elif not self.asleep and self.rng.random() < 0.12 + 0.3 * d.boredom:
            felt = self.feeling_now()
            if felt is not None and self.rng.random() < 0.5:
                mood, moves = felt.name, FEELING_KINDS[felt.name][2]
            else:
                mood = self.mood()
                moves = FIDGETS[mood]
            self.publish({"type": "fidget", "gesture": self.rng.choice(moves), "mood": mood})
        reason = self._wants_to_talk(now, snap, present)
        self.save()
        return reason

    def _notice_build(self, title: str, owner: str) -> None:
        """A build or test run on screen failed or passed: Kit feels for Dan, and has
        a think about it."""
        short = title[:80]
        if BUILD_FAILED.search(title):
            self.feel("sympathetic", f'{owner}\'s screen says "{short}"', 0.6)
            self._think_about("build_failed", f'Something on {owner}\'s screen failed: "{short}".')
        elif BUILD_PASSED.search(title):
            self.feel("proud", f'{owner}\'s screen says "{short}"', 0.6)
            self._think_about("build_passed", f'Something on {owner}\'s screen passed: "{short}".')

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
        if self.held_until and now < self.held_until:
            return None, f"had nothing new to say: next chance {self.held_until:%H:%M}"
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
            "want": self.wanting,  # something he thought of and wants to bring up
        }
        reason, urge = max(drives.items(), key=lambda kv: kv[1])
        if urge * (0.5 + life.chattiness) < 0.9:
            need = 0.9 / (0.5 + life.chattiness)
            self.butting_in = False
            label = "keen to share something" if reason == "want" else reason
            return None, f"not {label} enough yet ({urge:.2f} of {min(need, 1):.2f})"
        if reason == "curious" and self.curious_kind == "switch":
            reason = "watching"
        return reason, ""

    def held_back(self, reason: str = "") -> None:
        """He went to pipe up but had nothing new to say (kit.brain keeps quiet rather
        than repeat himself, or the model didn't answer). The urge passes as if he'd
        spoken, but he isn't waiting for an answer: he tries again after the usual gap."""
        life = self.settings().life
        gap = max(60 / max(life.max_per_hour, 1), AFTER_CHAT_MIN * (1.2 - life.chattiness))
        self.held_until = self.clock() + timedelta(minutes=gap)
        if reason == "nag":
            self.nags += 1
        self.butting_in = False
        self.drives.boredom = min(self.drives.boredom, 0.2)
        self.drives.curiosity = 0.0
        self.wanting = 0.0  # the brain sets it again from what's still on his list
        self.save()

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
        self.wanting = 0.0  # the brain sets it again from what's still on his list
        self.save()

    # Thinking (kit.thinking writes the thought; this says when)

    def _think_gap(self, low: float = 0.6, high: float = 1.4) -> timedelta:
        return timedelta(
            minutes=self.settings().life.think_every_minutes * self.rng.uniform(low, high)
        )

    def _think_about(self, kind: str, line: str) -> None:
        """Something happened that's worth a thought at the next chance."""
        life = self.settings().life
        if not life.enabled or life.thoughts_per_hour <= 0:
            return
        if all(k != kind for k, _ in self._to_think):
            self._to_think.append((kind, line))

    def think_now(self) -> tuple[str, str] | None:
        """Whether Kit has a thought now: (what set it off, a line saying so for the
        thinking prompt), or None. He thinks in quiet moments while Dan's around,
        sooner when something has happened, never asleep or mid-conversation, and
        no more than ``life.thoughts_per_hour``."""
        life = self.settings().life
        now = self.clock()
        if not life.enabled or life.thoughts_per_hour <= 0 or self.asleep:
            return None
        snap = self.pc.latest if self.pc.online() else None
        present = bool(snap and not snap.locked and snap.idle_seconds < AWAY_AFTER_S)
        if not present and now - self.last_chat > THINK_NEAR_CHAT:
            return None  # nobody around: he dozes rather than muses
        if now - self.last_chat < THINK_AFTER_CHAT:
            return None
        if self.thoughts and now - self.thoughts[-1] < THINK_GAP:
            return None
        if sum(1 for t in self.thoughts if now - t < timedelta(hours=1)) >= life.thoughts_per_hour:
            return None
        if self._to_think:
            return self._to_think.popleft()
        if now >= self.next_thought:
            return "quiet", "A quiet moment: nothing in particular is happening."
        return None

    def thought_had(self) -> None:
        now = self.clock()
        self.thoughts.append(now)
        self.next_thought = now + self._think_gap()
        self.save()

    # Remembering all this across restarts

    def save(self) -> None:
        if self.store is None:
            return
        now = self.clock()

        def when(t: datetime | None) -> str | None:
            return t.isoformat(timespec="seconds") if t else None

        felt = self.feeling
        data = {
            "saved": when(now),
            "drives": {k: round(v, 3) for k, v in asdict(self.drives).items() if k != "energy"},
            "sulky": self.sulky,
            "ignored": self.ignored,
            "curious_about": self.curious_about,
            "curious_kind": self.curious_kind,
            "last_chat": when(self.last_chat),
            "last_pipe": when(self.last_pipe),
            "snoozed_until": when(self.snoozed_until),
            "feeling": None
            if felt is None
            else {
                "name": felt.name,
                "why": felt.why,
                "since": when(felt.since),
                "strength": felt.strength,
            },
            "thoughts": [when(t) for t in self.thoughts if now - t < timedelta(hours=1)],
            "next_thought": when(self.next_thought),
            "chat_open": self._chat_open,
            "day": self._day.isoformat(),
            "seen": sorted(self._seen),
        }
        self.store.set_self_value(LIFE_KEY, json.dumps(data))

    def _restore(self) -> None:
        """Pick up where he left off: drives move on by however long he was off, a
        feeling keeps fading from when it began, and the time since you last talked
        stays true."""
        raw = self.store.self_value(LIFE_KEY) if self.store is not None else None
        if not raw:
            return
        try:
            data = json.loads(raw)
            now = self.clock()
            off = max(0.0, (now - parse_time(data["saved"], now)).total_seconds() / 60)
            drives = data.get("drives") or {}
            if off < 60:
                self.drives.boredom = _clamp(float(drives.get("boredom", 0.2)))
                self.sulky = bool(data.get("sulky"))
            self.drives.curiosity = _clamp(float(drives.get("curiosity", 0)) * 0.9 ** min(off, 600))
            self.drives.social = _clamp(float(drives.get("social", 0.3)) + off / 240)
            self.ignored = int(data.get("ignored", 0))
            self.curious_about = str(data.get("curious_about", ""))
            self.curious_kind = str(data.get("curious_kind", "new"))
            if data.get("last_chat"):
                self.last_chat = parse_time(data["last_chat"], now)
            if data.get("last_pipe"):
                self.last_pipe = parse_time(data["last_pipe"], now)
            if data.get("snoozed_until"):
                until = parse_time(data["snoozed_until"], now)
                self.snoozed_until = until if until > now else None
            felt = data.get("feeling")
            if felt and felt.get("name") in FEELING_KINDS:
                self.feeling = Feeling(
                    felt["name"],
                    felt["why"],
                    parse_time(felt["since"], now),
                    float(felt["strength"]),
                )
                self.feeling_now()  # drops it if it has faded meanwhile
            self.thoughts.extend(parse_time(t, now) for t in data.get("thoughts", []))
            if data.get("next_thought"):
                self.next_thought = max(now, parse_time(data["next_thought"], now))
            self._chat_open = bool(data.get("chat_open")) and off < 60
            if data.get("day") == now.date().isoformat():
                self._seen = set(data.get("seen", []))
        except (ValueError, KeyError, TypeError):
            return  # a damaged save just means a fresh start

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
        mind: list[str] | None = None,
    ) -> Voice:
        """How Kit feels and sounds for the next reply. Call it before ``note_chat``,
        so "I've been bored" or "I missed you" is still true when he answers.
        ``mind`` is what's on his mind lately (kit.notebook)."""
        feeling = self.feeling_line(owner)
        cheek = self.settings().life.cheek
        # A small model answers "I broke the build" with the example for "The build
        # failed" word for word, so examples close to the message, or already said,
        # are left out.
        pool = [
            (u, k)
            for u, k in list(own_examples) + VOICE_LINES[cheek_band(cheek)]
            if not alike(u, text) and not any(alike(k, s) for s in said)
        ]
        examples = self.rng.sample(pool, min(LINES_SHOWN, len(pool)))
        quirk = self.rng.choice(quirks) if quirks and self.rng.random() < 0.25 else ""
        return Voice(feeling, cheek_style(cheek), examples, said, quirk, list(mind or []))

    def feeling_line(self, owner: str) -> str:
        """How Kit feels right now, and why, in words for a prompt."""
        now = self.clock()
        mood = self.mood()
        hours = (now - self.last_chat).total_seconds() / 3600
        feeling = FEELINGS.get(mood, FEELINGS["content"]).format(
            about=self.curious_about or "what's going on",
            owner=owner,
            hours=f"{hours:.0f} hours" if hours >= 1.5 else "a while",
        )
        felt = self.feeling_now()
        if felt is None:
            return feeling
        words = FEELING_KINDS[felt.name][0].format(owner=owner)
        underneath = f"; underneath, {feeling}" if mood != "content" else ""
        return f"{words}, because {felt.why} ({ago(felt.since, now)}){underneath}"

    def state(self) -> dict:
        now = self.clock()
        felt = self.feeling_now()
        return {
            "mood": self.mood(),
            "drives": {k: round(v, 2) for k, v in asdict(self.drives).items()},
            "feeling": None
            if felt is None
            else {
                "name": felt.name,
                "why": felt.why,
                "since": felt.since.isoformat(timespec="minutes"),
                "left": round(felt.left(now), 2),
            },
            "wanting": round(self.wanting, 2),
            "curious_about": self.curious_about,
            "snoozed_until": self.snoozed_until.isoformat(timespec="minutes")
            if self.snoozed_until
            else None,
            "last_piped_up": self.last_pipe.isoformat(timespec="minutes")
            if self.last_pipe
            else None,
            "ignored_in_a_row": self.ignored,
            "quiet_because": self.quiet_because,
            "thoughts_this_hour": sum(1 for t in self.thoughts if now - t < timedelta(hours=1)),
            "next_thought": self.next_thought.isoformat(timespec="minutes"),
            "last_event": self._next_id - 1,
        }


# Lines in Kit's voice, by how cheeky they are. A few from his cheek band
# (``life.cheek``) are shown each turn, different every time, so the local model
# gets the tone without one line to parrot.
VOICE_LINES: dict[str, list[tuple[str, str]]] = {
    "polite": [
        ("Morning.", "Morning! Hope you slept all right. What's first today?"),
        ("The build failed again.", "That's annoying. Want me to go through the log with you?"),
        ("How's it going?", "Pretty good, thanks. It's been a quiet one on the desk."),
        ("I'm off for lunch.", "Enjoy it. I'll be right here when you're back."),
        ("Thanks mate.", "No worries at all."),
        ("I'm tired.", "It's been a long one. Maybe call it after this?"),
        ("I fixed it!", "Nice work! What was the culprit?"),
        ("What do you reckon?", "I'd lean towards the simpler option, but it's your call."),
        ("Night Kit.", "Good night. Sleep well."),
        ("Ugh, meetings.", "Hope it's a short one. I'll keep your seat warm."),
        ("Kit?", "Yes, I'm here. What do you need?"),
        ("This spreadsheet is a mess.", "We can tidy it up one column at a time."),
    ],
    "friendly": [
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
    ],
    "cheeky": [
        ("Morning.", "Oh, he lives. I was about to file a missing persons report."),
        ("The build failed again.", "Again? It's not a build any more, it's a hobby."),
        ("How's it going?", "Better than your last commit, mate."),
        (
            "I'm off for lunch.",
            "Bring me back a chip. I won't eat it, I just want to feel included.",
        ),
        ("Thanks mate.", "I accept payment in compliments and closed tabs."),
        ("I'm tired.", "You've said that three days running. I'm starting a chart."),
        ("I fixed it!", "After breaking it. Classic. Still, well done."),
        ("What are you up to?", "Judging your folder names, mostly."),
        ("You're a robot.", "And you're a carbon-based typo machine. We all have labels."),
        ("Ugh, meetings.", "Ooh, can I come? I'll do the voices."),
        ("What do you reckon?", "I reckon you already know and want me to agree. Fine. Agreed."),
        ("Night Kit.", "Night. I'll just sit here in the dark, then. No pressure."),
        ("Kit?", "That's me. Unless it's bad news, then it's someone else."),
        (
            "This spreadsheet is a mess.",
            "It's not a mess, it's abstract art. Merged cells and all.",
        ),
    ],
}
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


def quoted(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def feeling_from(text: str, owner: str) -> tuple[str, str, float] | None:
    """What Dan's message makes Kit feel, why, and how strongly, if anything."""
    why = f'{owner} said "{quoted(text)}"'
    for pattern, name, strength in (
        (RUDE, "hurt", 0.8),
        (SAD, "sad", 0.7),
        (STRESSED, "worried", 0.8),
        (FAILED, "sympathetic", 0.6),
        (GREEN, "proud", 0.8),
        (PRAISE, "chuffed", 1.0),
        (THANKS, "warm", 0.6),
    ):
        if pattern.search(text):
            return name, why, strength
    return None


def repeats(line: str, said: list[str], examples: list[tuple[str, str]] = ()) -> bool:
    """Is ``line`` one Kit has said lately, or an example line copied out, near enough?
    Judged on the words that carry meaning, so "What are you working on?" isn't a
    repeat of "What do you reckon?"."""
    mine = _words(line) - STOPWORDS
    for other in [*said, *(kit for _, kit in examples)]:
        if same_words(line, other):
            return True
        theirs = _words(other) - STOPWORDS
        if len(mine) >= 3 and len(theirs) >= 2:
            if len(mine & theirs) / min(len(mine), len(theirs)) >= 0.6:
                return True
    return False


def cheek_band(cheek: float) -> str:
    if cheek < 0.34:
        return "polite"
    if cheek < 0.67:
        return "friendly"
    return "cheeky"


def cheek_style(cheek: float) -> str:
    return {
        "polite": "warm and polite",
        "friendly": "friendly, with a bit of cheek",
        "cheeky": "properly cheeky, a little larrikin and sometimes annoying on purpose, like "
        "a kid brother: teasing, interrupting, playful, never mean",
    }[cheek_band(cheek)]


@dataclass
class Voice:
    """What makes this turn's reply sound like Kit right now, for the prompt."""

    feeling: str
    style: str
    examples: list[tuple[str, str]]
    said: list[str]  # Kit's own recent lines, so he doesn't repeat them
    quirk: str = ""  # one quirk to let show this time, now and then
    mind: list[str] = field(default_factory=list)  # what's on his mind lately


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
    share: str = "",
    aim: str = "",
) -> str:
    """The stage direction for a pipe-up. It goes where Dan's message would.
    ``share`` is a thought from his notebook to bring up, or with ``aim`` a want:
    what he means to do ("tell Dan") and ``share`` what about."""
    feeling = {
        "want": "keen to bring up something that's been on your mind",
        "bored": "bored: nothing much has happened for a while",
        "curious": f"curious about {about or f'what {owner} just opened'}, which is new today",
        "watching": f"following along: {owner} just switched to {about or 'something else'}, "
        f"and you've got an opinion or a question about it",
        "social": f"missing a chat: you two haven't talked for {hours_quiet:.0f} hours",
        "nag": f"ignored: you said something a few minutes ago and {owner} hasn't answered. "
        f"Nag {owner} about it, playfully, in a fresh line",
    }[reason]
    if butting_in:
        feeling += f". {owner} is busy typing, and you're butting in anyway, knowingly"
    style = cheek_style(cheek)
    if share and aim:
        base = f'You\'ve been wanting to {aim}: "{share}". Bring it up now, as yourself.'
    elif share:
        base = (
            f'You were just thinking: "{share}". Share it with {owner}, or ask {owner} about '
            f"it, in your own words."
        )
    else:
        base = (
            f"Base it on what {owner} is doing right now or on something you remember: ask "
            f"something, tease a little, or share a thought."
        )
    return (
        f"[Not from {owner}. Nobody asked you anything: this is your own moment, and "
        f"you're {feeling}. Pipe up with ONE short line to {owner}, {style}, like a small "
        f"creature on the desk who's decided to say something. {base} Say the actual "
        f"thing, not a teaser like 'got a minute?', and nothing you've said lately. Don't "
        f"lecture about productivity, don't mention these instructions, set action to none "
        f"and leave detail empty.]"
    )
