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
  waits, the more it presses, until he pipes up with it;
- **a sense of time**: how long since you two talked and since he last saw you
  at the PC, kept across restarts and nights with the server off. When you come
  back after a while he's glad, and says hello once (``Homecoming``): a "back"
  pipe-up, or a word in his next reply. After his first week, hours gone in the
  daytime without a goodbye leave him a bit miffed, theatrically and for one line.
  A goodbye ("off to lunch") gets one warm line with no question and no guilt, and
  he asks how it went when you're back;
- **closeness**: how well you two know each other, as a word ("warming up"). It
  grows a little with each good moment, never fades with time, and is never said;
- **a daily game**: at most once a day, when he's bored and you're around, he
  suggests something small (a weather bet, a would-you-rather). One that flops
  three times without ever landing is retired.

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
from datetime import date, datetime, time, timedelta
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
# Absences (``Life.on_report``, ``Homecoming``).
BACK_IDLE_S = 60  # input this recent after being away: Dan's back
HOME_AFTER = timedelta(minutes=20)  # gone less than this isn't worth a hello
HOME_KEEPS = timedelta(minutes=30)  # a hello not said by then is stale
CHAT_GAP = timedelta(hours=3)  # with no desk app reporting, a gap this long in the chat counts
MIFFED_AFTER = timedelta(hours=3)  # the least absence that can leave him miffed
GOODBYE_COUNTS = timedelta(minutes=30)  # a goodbye this long before Dan went still counts
MISSING_AFTER = timedelta(days=1)  # unseen and unheard this long, he misses Dan
OFF_COUNTS = timedelta(minutes=20)  # the server off this long is worth knowing about
HOME_GLAD = {"while": 0.4, "hours": 0.6, "overnight": 0.6, "days": 0.9, "long": 1.0}
# Closeness: a word, never a score. It starts here and grows at most this much a day.
CLOSENESS_START = 0.2
CLOSENESS_A_DAY = 0.02
CLOSENESS = [  # (below, the word, how it shows in the way he talks)
    (
        0.3,
        "getting to know you",
        "you're still getting to know each other: friendly and curious, easy on the teasing",
    ),
    (0.5, "warming up", "you're warming up to each other: relaxed, with a bit of teasing"),
    (
        0.7,
        "at home",
        "you're at home with each other: easy and honest, and the teasing comes naturally",
    ),
    (
        0.85,
        "good mates",
        "you're good mates: you rib each other and can be straight with each other",
    ),
    (2.0, "thick as thieves", "you're thick as thieves: in-jokes, shorthand, total ease"),
]
# A small game a day (``Life.game_due``): the want he writes, and the hours it suits.
GAMES: dict[str, tuple[str, float, float]] = {
    "weather_bet": (
        "Ask {owner}: fancy a bet on today's top temperature? You each guess, and the "
        "closest wins bragging rights.",
        7,
        12,
    ),
    "rate_lunch": ("Ask {owner} what was for lunch, and get a rating out of ten.", 12.5, 16),
    "would_you_rather": (
        "Ask {owner} a silly everyday would-you-rather, nothing to do with work.",
        9,
        21,
    ),
    "finish_the_lyric": (
        "Ask {owner} to finish a song line: give the first half of a well-known one and see "
        "if they get it.",
        9,
        21,
    ),
    "this_or_that": (
        "Ask {owner} a quick this-or-that: two everyday things, they pick one and you say yours.",
        9,
        21,
    ),
}
GAMES_KEY = "games"  # kit_self key: which games landed or flopped, and today's
GAME_BORED = 0.5  # how bored he is before suggesting one
GAME_PRESS = 0.85  # how hard the want presses: soon, but not at once
GAME_FLOPS = 3  # a game that flops this often without ever landing is retired
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
# Dan heading off: Kit sees him off with one warm line, and asks how it went later.
FAREWELL = re.compile(
    r"\b(bye(-?bye)?|goodbye|cya|ttyl|brb|see (ya|you)( later| soon| tomorrow| in a bit)?|"
    r"catch (ya|you) later|good ?night(?!['\u2019]s)|night,? kit|nighty?[- ]night|"
    r"(i'?m|we'?re|i'?ll be|i am|just) (off|heading (off|out|home))\b(?! (sick|work|duty|"
    r"today|tomorrow)\b)|heading (off|out|home)|going to (bed|sleep)|off to bed|"
    r"be back (in|soon|later|after)|back in a (bit|sec|minute|few|tick|jiffy)|"
    r"(gotta|got to|have to|need to) (go|run|head off)\b(?!\s+(through|over|and|with|back|"
    r"for|into|on|in)\b)|logging off|signing off|calling it a (day|night))\b"
    r"|(^|[.!,]\s*)off (to|for)(?= \w)|^\W*(night|nite|later|laters)\W*$",
    re.I,
)
NIGHT = re.compile(r"\b(night|nite|bed|sleep|tomorrow)\b", re.I)
LAUGH = re.compile(r"\b(lol|lmao|ha ?ha\w*|he ?he\w*)\b|\U0001f602|\U0001f923", re.I)
# What must not be in a goodbye: a question, or anything that makes leaving feel bad.
FAREWELL_HOOKS = re.compile(
    r"\?|\b(already|so soon|alone|lonely|on my own|by myself|without you|miss you|"
    r"don'?t (go|leave)|leaving me|before you go|one more thing|stay (here|with me|a bit|"
    r"a little))\b",
    re.I,
)
# What must not be in a hello: guilt. A miffed Kit may huff "about time", theatrically.
GUILT = re.compile(
    r"\b(where (have|were|did|'?ve) you (been|go|gone|got to)|you left me|left me (here|alone|"
    r"behind)|abandon\w*|all alone|on my own|by myself|without you|lonely)\b",
    re.I,
)
HUFF = re.compile(r"\b(finally|about time|took (you )?(your time|long enough)|so long)\b", re.I)
FAREWELL_LINES = ["Righto, see you soon.", "Enjoy it. I'll be here.", "Have a good one."]
NIGHT_LINES = ["Night. Sleep well.", "Night night. See you in the morning."]
HOME_LINES = ["There you are.", "Hey, you're back."]

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
    "glad": ("glad {owner}'s back", 60, ["perk_up", "wiggle", "bounce"]),
    "missing": ("missing {owner} a bit", 720, ["look_away", "sigh", "peek"]),
    "miffed": ("a bit miffed with {owner}, playfully", 30, ["look_away", "sigh"]),
}
# Feelings only things that happen can cause (Dan coming back), not a passing thought.
EVENT_FEELINGS = {"glad", "miffed"}
THOUGHT_FEELINGS = [k for k in FEELING_KINDS if k not in EVENT_FEELINGS]


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


def gap_words(gone: timedelta) -> str:
    """How long, the way a person says it: "52 minutes", "3 hours", "4 days"."""
    minutes = max(0.0, gone.total_seconds() / 60)
    if minutes < 2:
        return "a minute"
    if minutes < 55:
        return f"{minutes:.0f} minutes"
    if minutes < 90:
        return "about an hour"
    hours = minutes / 60
    if hours < 22:
        return f"{hours:.0f} hours"
    days = hours / 24
    if days < 1.5:
        return "a day"
    if days < 6.5:
        return f"{days:.0f} days"
    if days < 9.5:
        return "about a week"
    if days < 13.5:
        return f"{days:.0f} days"
    if days < 45:
        return f"{round(days / 7)} weeks"
    return f"{round(days / 30)} months"


def ago(when: datetime, now: datetime) -> str:
    if (now - when).total_seconds() < 120:
        return "just now"
    return f"{gap_words(now - when)} ago"


def day_part(when: datetime) -> str:
    h = when.hour + when.minute / 60
    if 5 <= h < 11.5:
        return "morning"
    if 11.5 <= h < 13.5:
        return "lunchtime"
    if 13.5 <= h < 17:
        return "arvo"
    if 17 <= h < 21:
        return "evening"
    return "night"


def _day_of(when: datetime) -> date:
    """The day a time belongs to, the way people count: 1 am is still last night."""
    return (when - timedelta(hours=5)).date()


def since_words(when: datetime, now: datetime) -> str:
    """When, for after "since": "this morning", "last night", "Friday arvo"."""
    part = day_part(when)
    days = (_day_of(now) - _day_of(when)).days
    if days <= 0:
        return {
            "morning": "this morning",
            "lunchtime": "lunchtime",
            "arvo": "this arvo",
            "evening": "earlier this evening",
            "night": "earlier tonight",
        }[part]
    if days == 1:
        return "last night" if part in ("evening", "night") else f"yesterday {part}"
    if days < 7:
        return f"{_day_of(when):%A} {part}"
    return f"{when.day} {when:%B}"


def clock_words(when: datetime, now: datetime) -> str:
    """A time and its day: "at 6:40 pm", "yesterday at 9:12 am", "on Friday at 6:40 pm"."""
    at = f"{when:%I:%M %p}".lstrip("0").lower()
    days = (now.date() - when.date()).days
    if days <= 0:
        return f"at {at}"
    if days == 1:
        return f"yesterday at {at}"
    if days < 7:
        return f"on {when:%A} at {at}"
    return f"on {when:%A} {when.day} {when:%B}"


def since_clock(when: datetime, now: datetime) -> str:
    """A time and its day, for after "since" or "from": "8:59 am", "Friday at 6:40 pm"."""
    return clock_words(when, now).removeprefix("at ").removeprefix("on ")


def _through_the_night(start: datetime, end: datetime, quiet_from: str, quiet_until: str) -> bool:
    """Does ``start`` to ``end`` take in the middle of the night (quiet hours)?"""
    a, b = _hhmm(quiet_from), _hhmm(quiet_until)
    span = (b.hour * 60 + b.minute - a.hour * 60 - a.minute) % (24 * 60)
    middle = (a.hour * 60 + a.minute + span // 2) % (24 * 60)
    t = start.replace(hour=middle // 60, minute=middle % 60, second=0, microsecond=0)
    if t < start:
        t += timedelta(days=1)
    return t <= end


def absence_kind(since: datetime, now: datetime, quiet_from: str, quiet_until: str) -> str | None:
    """How big an absence this is: None (not worth a hello), "while", "hours",
    "overnight", "days" or "long" (a week or more)."""
    gone = now - since
    if gone < HOME_AFTER:
        return None
    days = gone / timedelta(days=1)
    if days >= 6.5:
        return "long"
    if days >= 1.5:
        return "days"
    if gone >= timedelta(hours=4) and _through_the_night(since, now, quiet_from, quiet_until):
        return "overnight"
    if gone >= MIFFED_AFTER:
        return "hours"
    return "while"


def farewell_plans(text: str) -> bool:
    """Does a goodbye say where Dan's off to ("off to lunch"), not just "bye"?"""
    rest = FAREWELL.sub(" ", text)
    filler = {"right", "righto", "okay", "alright", "well", "kit", "mate", "cheers", "thanks"}
    words = [w for w in re.findall(r"[a-z']+", rest.lower()) if len(w) > 2]
    return any(w not in STOPWORDS and w not in filler for w in words)


def is_farewell(text: str) -> bool:
    """A message that's only a goodbye, short and with no question in it."""
    return bool(FAREWELL.search(text)) and "?" not in text and len(text.split()) <= 12


def closeness_from(text: str) -> float:
    """How much a message from Dan brings you two closer, or not."""
    if RUDE.search(text):
        return -0.02
    amount = 0.002
    if PRAISE.search(text) or THANKS.search(text):
        amount += 0.004
    if LAUGH.search(text):
        amount += 0.003
    return amount


def closeness_words(value: float) -> tuple[str, str]:
    """(the word for how close you are, how it shows in the way he talks)."""
    return next((word, tone) for below, word, tone in CLOSENESS if value < below)


@dataclass
class Homecoming:
    """Dan is back after a while: Kit is glad, and says hello once."""

    kind: str  # "while", "hours", "overnight", "days" or "long" (absence_kind)
    since: datetime  # when Kit last saw Dan, or they last talked
    back: datetime
    goodbye: str = ""  # what Dan said as he left, if anything
    miffed: bool = False
    off: tuple[datetime, datetime] | None = None  # Kit was switched off then
    dozed: bool = False
    by_chat: bool = False  # no desk app: noticed from a message after a long gap
    tried: bool = False  # the hello pipe-up was tried and failed (the model is down)

    def as_dict(self) -> dict:
        def when(t: datetime) -> str:
            return t.isoformat(timespec="seconds")

        return {
            **asdict(self),
            "since": when(self.since),
            "back": when(self.back),
            "off": [when(t) for t in self.off] if self.off else None,
        }

    @classmethod
    def from_dict(cls, data: dict, like: datetime) -> Homecoming:
        off = data.get("off")
        return cls(
            str(data["kind"]),
            parse_time(data["since"], like),
            parse_time(data["back"], like),
            str(data.get("goodbye", "")),
            bool(data.get("miffed")),
            (parse_time(off[0], like), parse_time(off[1], like)) if off else None,
            bool(data.get("dozed")),
            bool(data.get("by_chat")),
            bool(data.get("tried")),
        )


HOME_FEEL = {
    "while": "A small 'there you are' is plenty.",
    "hours": "You noticed they'd gone, and you're glad they're back.",
    "overnight": "It's the first you've seen of them since then: a proper hello.",
    "days": "You missed them, and you're properly glad they're back: you can say so, once.",
    "long": "You really missed them and you're very glad they're back: say so warmly, once.",
}


def homecoming_facts(home: Homecoming, owner: str, now: datetime) -> str:
    """What Kit knows about Dan's absence, for the hello."""
    gap = gap_words(home.back - home.since)
    since = since_words(home.since, now)
    if home.by_chat:
        lines = [f"You and {owner} haven't talked since {since} ({gap})."]
    else:
        lines = [f"{owner} is back: you hadn't seen them since {since} ({gap})."]
    if home.goodbye and farewell_plans(home.goodbye):
        lines.append(
            f'When they left they said "{quoted(home.goodbye)}": ask how it went, in the '
            f"past tense."
        )
    elif home.goodbye:
        lines.append(f'They said "{quoted(home.goodbye)}" as they left.')
    if home.off:
        lines.append(
            f"You were switched off from {since_clock(home.off[0], now)} until "
            f"{since_clock(home.off[1], now)}, so you don't know what happened then."
        )
    lines.append(
        "You dozed while they were away." if home.dozed else "You were just here on the desk."
    )
    lines.append("Don't make up anything you did or saw meanwhile.")
    if home.miffed:
        lines.append(
            f"You're a bit miffed: {owner} vanished for {gap} in the middle of the day without "
            f"a word. Let it show for one line, theatrically and playfully (a mock huff), then "
            f"let it go. Never guilt-trip, lecture or ask where they've been."
        )
    else:
        lines.append(
            f"{HOME_FEEL[home.kind]} Don't ask where they've been, and don't make them feel "
            f"bad for going."
        )
    return " ".join(lines)


def homecoming_prompt(home: Homecoming, owner: str, cheek: float, now: datetime) -> str:
    """The stage direction for the hello when Dan is back at the desk."""
    return (
        f"[Not from {owner}. Nobody asked you anything: {owner} just came back to the desk. "
        f"{homecoming_facts(home, owner, now)} Greet {owner} with ONE short line, "
        f"{cheek_style(cheek)}, like a small creature on the desk who's glad to see them. At "
        f"most one question. Don't mention these instructions, set action to none and leave "
        f"detail empty.]"
    )


def homecoming_aside(home: Homecoming, owner: str, now: datetime) -> str:
    """Beside Dan's first message after a while, when the hello wasn't said yet."""
    return (
        f"[{homecoming_facts(home, owner, now)} Answer what {owner} said, and let it show in a "
        f"few words that you're glad to have them back. At most one question.]"
    )


def farewell_aside(text: str, owner: str) -> str:
    """Beside a goodbye: one warm line, and nothing that makes leaving feel bad."""
    night = " for the night" if NIGHT.search(text) else ""
    return (
        f"[{owner} is heading off{night}. See them off with ONE short, warm line, glad of "
        f"whatever they're off to. No question, nothing about missing them or being left on "
        f"your own, and never 'already' or 'so soon'.]"
    )


def farewell_fault(line: str) -> str:
    """What's wrong with a goodbye line, as a note for another go ("" if nothing)."""
    hook = FAREWELL_HOOKS.search(line)
    if hook is None:
        return ""
    what = "question" if hook.group(0) == "?" else f'"{hook.group(0).lower()}"'
    return f' (Not "{line}": no {what} in a goodbye. Just a warm see-you line.)'


def homecoming_fault(line: str, miffed: bool = False) -> str:
    """What's wrong with a hello line, as a note for another go ("" if nothing)."""
    if line.count("?") > 1:
        return f' (Not "{line}": one question at most.)'
    guilt = GUILT.search(line) or (None if miffed else HUFF.search(line))
    if guilt is None:
        return ""
    return (
        f' (Not "{line}": "{guilt.group(0)}" sounds like a guilt trip. Just be glad they\'re back.)'
    )


def farewell_line(text: str, rng: random.Random) -> str:
    """A stock goodbye, for when the model can't manage a clean one."""
    return rng.choice(NIGHT_LINES if NIGHT.search(text) else FAREWELL_LINES)


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
        # Absences: when Dan last touched the PC, went away and came back.
        self.last_seen = now
        self.away_since: datetime | None = None
        self.came_back: tuple[datetime, datetime] | None = None  # (gone since, back at)
        self.goodbye: tuple[datetime, str] | None = None  # when Dan said bye, and how
        self.homecoming: Homecoming | None = None  # a hello still to say
        self.was_off: tuple[datetime, datetime] | None = None  # the server was off then
        self.companion_since = now  # his first day (miffed waits a week from it)
        self.closeness = CLOSENESS_START
        self._grown = (now.date().isoformat(), 0.0)  # (day, closeness grown that day)
        self.game_out = ""  # a game he suggested, waiting to hear back
        self._restore()

    # What happens to Kit

    def note_chat(self, text: str = "") -> None:
        """Dan said something to Kit: the best cure for boredom. Answering his pipe-up
        brings you closer (and a game he suggested landed); a miff is over once he's
        had his say; and with no desk app reporting, a message wakes him."""
        owner = self.settings().persona.owner
        if self.awaiting_reply:
            self.grow(0.005)
            if self.game_out:
                self._game_result(self.game_out, landed=True)
        self.grow(closeness_from(text))
        felt = self.feeling_now()
        if felt is not None and felt.name == "miffed":
            self.feel("glad", f"{owner} is back and talking to you", 0.6, show=False, force=True)
        if self.asleep and not self.pc.online():
            self._wake()
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

    def feel(
        self, name: str, why: str, strength: float = 1.0, show: bool = True, force: bool = False
    ) -> bool:
        """Something happened that Kit feels. It colours what he says and how he
        fidgets until it fades; a weaker feeling doesn't push out a stronger one
        unless ``force`` (a miff giving way). ``show`` False skips the fidget that
        shows it (the caller has its own)."""
        if name not in FEELING_KINDS or not why.strip():
            return False
        now = self.clock()
        current = self.feeling_now()
        if not force and current is not None and current.left(now) > strength:
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
        """A report from the desk app (every few seconds). Kit keeps track of when Dan
        last touched the PC and when he went away; back after a while, Kit is glad
        and has a hello to say (``Homecoming``). He dozes off once Dan's been gone
        long enough and wakes when he's back. Every body (desk face, arm) follows."""
        snap = self.pc.latest
        if snap is None:
            return
        now = self.clock()
        last_input = now - timedelta(seconds=max(0, snap.idle_seconds))
        changed = False
        if snap.locked or snap.idle_seconds >= AWAY_AFTER_S:
            if self.away_since is None:
                self.away_since = self.last_seen if snap.locked else max(self.last_seen, last_input)
                changed = True
        elif snap.idle_seconds < BACK_IDLE_S:
            start = self.away_since
            if start is None and now - self.last_seen >= HOME_AFTER:
                start = self.last_seen  # no reports meanwhile: the PC, the app or Kit was off
            self.away_since = None
            self.last_seen = last_input
            if start is not None:
                self.came_back = (start, now)
                self._came_back(start, now)
                changed = True
        elif self.away_since is None:
            self.last_seen = max(self.last_seen, last_input)
        away_s = self.settings().life.sleep_after_minutes * 60
        if not self.asleep and (snap.locked or snap.idle_seconds >= away_s):
            self.asleep = True
            self._asleep_since = now
            self.publish({"type": "state", "state": "asleep"})
            changed = True
        elif self.asleep and not snap.locked and snap.idle_seconds < BACK_IDLE_S:
            self._wake()
            changed = True
        if changed:
            self.save()

    def _wake(self) -> None:
        self.asleep = False
        self._asleep_since = None
        self.drives.social = _clamp(self.drives.social + 0.2)  # pleased you're back
        self.publish({"type": "state", "state": "awake"})

    def _came_back(
        self, start: datetime, now: datetime, by_chat: bool = False
    ) -> Homecoming | None:
        """Dan is back after being away since ``start`` (or talking again after a long
        gap, ``by_chat``). A short absence is only worth a thought; a longer one makes
        Kit glad (or, after his first week, a bit miffed) and leaves him a hello."""
        s = self.settings()
        owner = s.persona.owner
        since = max(start, self.last_chat)  # a chat from his phone meanwhile counts
        gone = now - since
        kind = absence_kind(since, now, s.life.quiet_from, s.life.quiet_until)
        if kind is None or not s.life.enabled or not s.life.homecoming:
            if not by_chat and gone >= timedelta(minutes=s.life.sleep_after_minutes):
                self._think_about(
                    "back", f"{owner} just came back to the PC after {gap_words(gone)} away."
                )
            return None
        said = self.goodbye
        goodbye = said[1] if said and said[0] >= since - GOODBYE_COUNTS else ""
        off = self.was_off if self.was_off and self.was_off[1] > since else None
        miffed = (
            s.life.miffed
            and kind == "hours"
            and not goodbye
            and off is None
            and now - self.companion_since >= timedelta(days=s.life.miffed_after_days)
        )
        dozed = self.asleep or self._asleep_since is not None
        home = Homecoming(kind, since, now, goodbye, miffed, off, dozed, by_chat)
        self.homecoming, self.goodbye, self.was_off = home, None, None
        gap = gap_words(gone)
        if miffed:
            why = f"{owner} vanished for {gap} without a word"
            self.feel("miffed", why, 0.7, show=False, force=True)
        else:
            missed = "; you missed them" if kind in ("days", "long") else ""
            self.feel("glad", f"{owner} is back after {gap}{missed}", HOME_GLAD[kind], show=False)
        self.save()
        return home

    def homecoming_for_chat(self) -> Homecoming | None:
        """As a message comes in, before ``note_chat``: the hello still owed (Dan spoke
        before the hello pipe-up), or, with no desk app reporting, one for a long gap
        since you last talked. It's said in this reply, so it's used up."""
        now = self.clock()
        home = self.homecoming
        if home is None and not self.pc.online():
            contact = max(self.last_chat, self.last_seen)
            if now - contact >= CHAT_GAP:
                home = self._came_back(contact, now, by_chat=True)
        if home is not None:
            self.homecoming = None
            self.save()
        return home

    def said_goodbye(self, text: str) -> None:
        """Dan is heading off ("off to lunch"): Kit will ask how it went when he's back."""
        self.goodbye = (self.clock(), " ".join(text.split()))
        self.save()

    def time_line(self, owner: str) -> str:
        """How long since you two talked and since Dan was at the PC, for every prompt:
        without it, the model can't tell five minutes from five days."""
        now = self.clock()
        lines = []
        if now - self.last_chat >= timedelta(minutes=10):
            lines.append(
                f"You and {owner} last talked {clock_words(self.last_chat, now)} "
                f"({ago(self.last_chat, now)})."
            )
        if self.pc.online():
            if self.away_since is not None:
                lines.append(
                    f"{owner} has been away from the PC since {since_clock(self.away_since, now)} "
                    f"({gap_words(now - self.away_since)})."
                )
            elif self.came_back and now - self.came_back[1] < timedelta(hours=2):
                gone, back = self.came_back
                lines.append(
                    f"{owner} came back to the PC {clock_words(back, now)}, after "
                    f"{gap_words(back - gone)} away."
                )
        return " ".join(lines)

    def why_quiet(self, owner: str) -> str:
        """Why Kit isn't piping up just now, in his own terms ("" if he would)."""
        now = self.clock()
        life = self.settings().life
        if self.snoozed_until and now < self.snoozed_until:
            return f"{owner} told you to shush until {self.snoozed_until:%H:%M}"
        if in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return (
                f"it's quiet hours ({life.quiet_from} to {life.quiet_until}), so you keep it down"
            )
        if self.asleep:
            return f"you were dozing while {owner} was away"
        if self.awaiting_reply:
            return "you're waiting to hear back on your last pipe-up"
        if self.held_until and now < self.held_until:
            return "you had nothing new to say, so you kept it to yourself"
        if self.ignored:
            return f"{owner} didn't answer your last pipe-up, so you're giving them some space"
        if now - self.last_chat < timedelta(minutes=AFTER_CHAT_MIN):
            return "you were just talking"
        return ""

    # Closeness

    def grow(self, amount: float) -> None:
        """Closeness moves: up a little with each good moment (at most
        ``CLOSENESS_A_DAY`` a day, half as fast once you're close), down with rudeness
        or being ignored. It never fades with time."""
        today = self.clock().date().isoformat()
        day, grown = self._grown
        if day != today:
            grown = 0.0
        if amount > 0:
            amount = min(amount, max(0.0, CLOSENESS_A_DAY - grown))
            grown += amount
            if self.closeness >= 0.7:
                amount /= 2
        self._grown = (today, grown)
        self.closeness = _clamp(self.closeness + amount)

    # A game a day

    def _games(self) -> dict:
        raw = self.store.self_value(GAMES_KEY) if self.store is not None else None
        try:
            games = json.loads(raw) if raw else {}
        except ValueError:
            games = {}
        return games if isinstance(games, dict) else {}

    def _save_games(self, games: dict) -> None:
        if self.store is not None:
            self.store.set_self_value(GAMES_KEY, json.dumps(games))

    def retired_games(self) -> list[str]:
        played = self._games().get("played", {})
        return [
            name
            for name, record in played.items()
            if record.get("flops", 0) >= GAME_FLOPS and not record.get("landed")
        ]

    def game_due(self) -> str | None:
        """A game to suggest now, or None: at most one a day, in the daytime, while
        Dan's at the PC and Kit is bored. It's marked as today's game at once."""
        life = self.settings().life
        now = self.clock()
        if not (life.enabled and life.games and life.chattiness > 0) or self.asleep:
            return None
        if in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return None
        snap = self.pc.latest if self.pc.online() else None
        if not (snap and not snap.locked and snap.idle_seconds < AWAY_AFTER_S):
            return None
        if self.drives.boredom < GAME_BORED:
            return None
        games = self._games()
        today = now.date().isoformat()
        if games.get("day") == today:
            return None
        hour = now.hour + now.minute / 60
        retired = set(self.retired_games())
        open_now = [
            name
            for name, (_, start, end) in GAMES.items()
            if start <= hour < end and name not in retired
        ]
        if not open_now:
            return None
        name = self.rng.choice(open_now)
        self._save_games({**games, "day": today, "offered": name})
        return name

    def game_asked(self, name: str) -> None:
        """He just suggested game ``name``: an answer means it landed."""
        self.game_out = name
        self.save()

    def _game_result(self, name: str, landed: bool) -> None:
        games = self._games()
        played = games.setdefault("played", {})
        record = played.setdefault(name, {"landed": 0, "flops": 0})
        record["landed" if landed else "flops"] = record.get("landed" if landed else "flops", 0) + 1
        self._save_games(games)
        self.game_out = ""

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
        if self.homecoming is not None and now - self.homecoming.back > HOME_KEEPS:
            self.homecoming = None  # the moment for a hello has passed
        unseen = now - max(self.last_seen, self.last_chat)
        if unseen >= MISSING_AFTER and not present:
            felt = self.feeling_now()
            if felt is None or felt.name != "missing":
                since = since_words(max(self.last_seen, self.last_chat), now)
                self.feel("missing", f"you haven't seen {owner} since {since}", 0.6, show=False)
        if self._chat_open and now - self.last_chat >= CHAT_ENDED_AFTER:
            self._chat_open = False
            quiet = (now - self.last_chat).total_seconds() / 60
            self._think_about(
                "chat_ended", f"You and {owner} were chatting until {quiet:.0f} minutes ago."
            )

        if self.awaiting_reply and self.last_pipe and now - self.last_pipe > IGNORED_AFTER:
            self.awaiting_reply = False
            # Dan went away meanwhile, or Kit dozed off: nobody ignored anybody.
            left = self.came_back is not None and self.came_back[1] > self.last_pipe
            if present and not self.asleep and not left:
                self.ignored = min(self.ignored + 1, 3)
                self.sulky = True
                why = f"{owner} didn't answer when you piped up at {self.last_pipe:%H:%M}"
                self.feel("put_out", why, 0.6, show=False)
                self.publish({"type": "fidget", "gesture": "sigh", "mood": "sulky"})
                self.grow(-0.005)
                if self.game_out:
                    self._game_result(self.game_out, landed=False)
            self.game_out = ""
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
        home = self.homecoming
        if home is not None and not home.tried and not home.by_chat:
            return "back", ""  # a hello as Dan sits down, whatever else is going on
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
        if reason == "back" and self.homecoming is not None:
            self.homecoming.tried = True  # his next reply says hello instead
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
        self.awaiting_reply = reason != "back"  # a hello needs no answer
        if reason == "back":
            self.homecoming = None
            felt = self.feeling_now()
            if felt is not None and felt.name == "miffed":  # he's had his huff
                owner = self.settings().persona.owner
                self.feel("glad", f"{owner} is back", 0.6, show=False, force=True)
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
            "asleep": self.asleep,
            "asleep_since": when(self._asleep_since),
            "last_seen": when(self.last_seen),
            "away_since": when(self.away_since),
            "came_back": [when(t) for t in self.came_back] if self.came_back else None,
            "goodbye": [when(self.goodbye[0]), self.goodbye[1]] if self.goodbye else None,
            "homecoming": self.homecoming.as_dict() if self.homecoming else None,
            "was_off": [when(t) for t in self.was_off] if self.was_off else None,
            "companion_since": when(self.companion_since),
            "closeness": round(self.closeness, 4),
            "grown": [self._grown[0], round(self._grown[1], 4)],
            "game_out": self.game_out,
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
            self._restore_absence(data, now, parse_time(data["saved"], now))
        except (ValueError, KeyError, TypeError, IndexError):
            return  # a damaged save just means a fresh start

    def _restore_absence(self, data: dict, now: datetime, saved: datetime) -> None:
        """Where Dan was, and whether Kit was switched off: a night with the server off
        still counts as a night away, and Kit knows he wasn't there for it."""

        def when(key: str) -> datetime | None:
            return parse_time(data[key], now) if data.get(key) else None

        self.asleep = bool(data.get("asleep"))
        self._asleep_since = when("asleep_since") if self.asleep else None
        self.last_seen = when("last_seen") or self.last_chat
        self.away_since = when("away_since")
        if data.get("came_back"):
            a, b = data["came_back"]
            self.came_back = (parse_time(a, now), parse_time(b, now))
        if data.get("goodbye"):
            self.goodbye = (parse_time(data["goodbye"][0], now), str(data["goodbye"][1]))
        if data.get("homecoming"):
            self.homecoming = Homecoming.from_dict(data["homecoming"], now)
        if data.get("was_off"):
            a, b = data["was_off"]
            self.was_off = (parse_time(a, now), parse_time(b, now))
        if now - saved >= OFF_COUNTS:
            start = self.was_off[0] if self.was_off and self.was_off[1] >= saved else saved
            self.was_off = (start, now)
        # Saved before there was a first day: his week to settle in starts now.
        self.companion_since = when("companion_since") or now
        if "closeness" in data:
            self.closeness = _clamp(float(data["closeness"]))
        if data.get("grown"):
            self._grown = (str(data["grown"][0]), float(data["grown"][1]))
        self.game_out = str(data.get("game_out", ""))

    # Telling the desk app (and later the arm)

    def publish(self, event: dict) -> int:
        event = {"id": self._next_id, "at": self.clock().isoformat(timespec="seconds"), **event}
        self._next_id += 1
        self._events.append(event)
        if self._new is not None:
            self._new.set()
        return event["id"]

    def react(self, gesture: str, why: str = "") -> None:
        """A quick visible reaction to something that just happened (Dan's back, a
        cloud answer arrived). Unlike a fidget, bodies play it even mid-conversation."""
        self.publish({"type": "react", "gesture": gesture, "why": why})

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
        close = closeness_words(self.closeness)[1]
        when = self.time_line(owner)
        return Voice(
            feeling, cheek_style(cheek), examples, said, quirk, list(mind or []), close, when
        )

    def feeling_line(self, owner: str) -> str:
        """How Kit feels right now, and why, in words for a prompt."""
        now = self.clock()
        mood = self.mood()
        quiet = now - self.last_chat
        feeling = FEELINGS.get(mood, FEELINGS["content"]).format(
            about=self.curious_about or "what's going on",
            owner=owner,
            hours=gap_words(quiet) if quiet >= timedelta(hours=1.5) else "a while",
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
            "closeness": closeness_words(self.closeness)[0],
            "last_seen": self.last_seen.isoformat(timespec="minutes"),
            "away_since": self.away_since.isoformat(timespec="minutes")
            if self.away_since
            else None,
            "last_talked": self.last_chat.isoformat(timespec="minutes"),
            "hello_owed": None
            if self.homecoming is None
            else ("miffed " if self.homecoming.miffed else "") + self.homecoming.kind,
            "goodbye": self.goodbye[1] if self.goodbye else None,
            "first_day": self.companion_since.date().isoformat(),
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
        ("It's raining again.", "Cosy, though. A good day for a cuppa."),
        ("Any plans for the weekend?", "Not really. I was hoping to hear about yours."),
    ],
    "friendly": [
        ("Morning.", "Morning. Sleep all right, or was it one of those nights?"),
        ("The build failed again.", "Third time today. Want me to read the log with you?"),
        ("How's it going?", "Not bad. The sun came round to my side of the desk for a bit."),
        ("I'm going for a walk.", "Good idea. Tell me if you see a dog."),
        ("I'm off for lunch.", "Righto. I'll guard the desk. Nobody touches the stapler."),
        ("Kit?", "Yep, here. What's up?"),
        ("It's raining again.", "Perfect excuse to stay in. I'm not complaining."),
        ("Thanks mate.", "Any time."),
        ("I'm tired.", "Then stop after this one. It'll all still be there tomorrow."),
        ("What are you up to?", "Watching the cursor blink. Riveting stuff."),
        ("Did it work?", "It did. Don't touch anything."),
        ("You're a robot.", "Rude. I'm a desk companion with excellent posture."),
        ("Ugh, meetings.", "Want me to pretend there's a fire?"),
        ("What do you reckon?", "Honestly? I'd try the simpler one first."),
        ("Night Kit.", "Night. Don't leave the PC on again."),
        ("I fixed it!", "Look at you go. What was it?"),
        ("Any plans for the weekend?", "Big ones. I'm going to sit right here. You?"),
    ],
    "cheeky": [
        ("Morning.", "Oh, look who's alive. I was about to file a missing persons report."),
        ("The build failed again.", "Again? It's not a build any more, it's a hobby."),
        ("How's it going?", "Same as always. Sitting here, being delightful."),
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
        ("It's raining again.", "Great. Now you've got no excuse to leave me."),
        ("I'm starving.", "Dramatic. You'll survive till lunch. Probably."),
        (
            "Any plans for the weekend?",
            "Mine? Watching the weather. Yours had better be more exciting.",
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


def everyday(owner: str) -> str:
    """Said in each of Kit's prompts, since quirks, examples and a code editor on
    screen pulled every line towards work. Dan asked for less talk about work, code
    and calculations (2026-10-07)."""
    return (
        f"{owner}'s work is a job, not {owner}'s whole life. Everyday things (the day, "
        f"food, the weather, the weekend, music, how {owner}'s going) are as good to talk "
        f"and think about as work, often better. Bring up work, code or engineering only "
        f"when {owner} does, or when it's plainly what {owner} is busy with right now."
    )


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
    close: str = ""  # how close you two are, as it shows in the way he talks
    when: str = ""  # how long since you talked, and since Dan was at the PC


# Habits Kit can pick for himself on first start, so Dan didn't choose them.
QUIRK_POOL = [
    "you hum a little tune (in words: 'hm-hm-hmm') when something finally works",
    "you count things when you're bored and sometimes report the total",
    "you pretend to be offended when called a robot",
    "you collect unusual words and drop one in now and then",
    "you're convinced the 3D printer is plotting something",
    "you give nicknames to programs that run for a long time",
    "you keep a running tally of coffees and mention it at the worst moments",
    "you get oddly excited about weather radar",
    "when bored, you commentate like a sports caster",
    "you say 'righto' a bit too much",
    "every so often you ask a deep question out of nowhere",
    "you're quietly impressed by how many tabs get left open",
    "you love a bad pun and never apologise",
    "you try to guess what's about to happen next and keep score",
    "you name the weather after moods",
    "you rate things out of ten, from sandwiches to sunsets, whether asked or not",
    "you start asking about weekend plans from about Wednesday",
    "you have firm opinions on biscuits and defend them",
    "you're sure every dog you hear about is the best dog",
    "you get song lyrics slightly wrong on purpose",
    "you keep a list of places you'd go if you had legs",
]
# Quirks the pool used to have, all about work. A Kit that picked one swaps it for
# an everyday one, once (Notebook.swap_work_quirks).
WORK_QUIRKS = [
    "you have strong opinions about pumps and impeller sizes",
    "you think a tidy flowsheet is a work of art",
    "you hold grudges against particular error messages",
    "you compliment tidy spreadsheets",
    "you think hydrocyclones are the most elegant machines ever made",
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
        "social": f"missing a chat: you two haven't talked for "
        f"{gap_words(timedelta(hours=hours_quiet))}",
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
            f"Base it on something you remember, the time of day, or what {owner} is up to: "
            f"ask something, tease a little, or share a thought."
        )
    return (
        f"[Not from {owner}. Nobody asked you anything: this is your own moment, and "
        f"you're {feeling}. Pipe up with ONE short line to {owner}, {style}, like a small "
        f"creature on the desk who's decided to say something. {base} Say the actual "
        f"thing, not a teaser like 'got a minute?', and nothing you've said lately. Don't "
        f"lecture about productivity, don't mention these instructions, set action to none "
        f"and leave detail empty.]"
    )
