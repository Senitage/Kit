"""Kit's inner life: what makes him fidget, get bored and pipe up on his own.

A few drives rise and fall over time, like moods in a pet:

- boredom climbs while nobody talks to him, faster while Dan sits at the PC;
- curiosity jumps when Dan opens an app or site Kit hasn't seen today (an
  everyday one: work apps, sites and builds only with ``life.work_triggers``);
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
import logging
import random
import re
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta

from kit.holidays import week_moment
from kit.knowledge import STOPWORDS
from kit.pastimes import Pastime, SelfStore, parse_time
from kit.pc_context import AWAY_AFTER_S, PcContext
from kit.settings import Settings

log = logging.getLogger(__name__)

TICK_S = 30
CALL_APPS = {"Teams", "Zoom", "Webex", "Skype", "Discord", "Slack"}
# Apps and sites that are work, which Kit leaves alone unless life.work_triggers is on.
WORK_APPS = {
    "VS Code",
    "Visual Studio",
    "PyCharm",
    "Terminal",
    "Command Prompt",
    "PowerShell",
    "Teams",
    "Slack",
    "Outlook",
    "Excel",
    "Word",
    "PowerPoint",
    "Access",
    "OneNote",
    "Acrobat",
    "Notepad++",
    "Claude",
}
WORK_SITES = (
    "github.com",
    "gitlab.com",
    "stackoverflow.com",
    "atlassian.net",
    "portal.azure.com",
    "console.aws.amazon.com",
    "sharepoint.com",
    "office.com",
    "pypi.org",
    "docs.python.org",
    "claude.ai",
    "chatgpt.com",
    "localhost",
    "127.0.0.1",
)
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
BET_SETTLES = 16  # from this hour today's top temperature is in
BET_RETRY = timedelta(minutes=30)  # the forecast didn't answer: try again after this
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
# "Not stressed, the footy's just on late": a word that's denied doesn't count.
NEGATED = re.compile(
    r"\b(not|no|never|nothing|hardly|without|nor|isn'?t|wasn'?t|aren'?t|weren'?t|don'?t|"
    r"doesn'?t|didn'?t|ain'?t|won'?t|wouldn'?t|haven'?t|hasn'?t|not that)\b(\s+\S+){0,2}\s*$|"
    r"n['’]t(\s+\S+){0,2}\s*$",
    re.I,
)
STILL_SO = re.compile(r"\b(never been (so|this|more)|couldn'?t be more|can'?t be more)\b", re.I)
CLAUSE = re.compile(r"[.,;:!?]|\bbut\b|\bthough\b|\balthough\b", re.I)
# A really bad time (``life.bad_night``): Kit drops the cheek and stays.
SELF_HARM = re.compile(
    r"\b(kill(ing)? my ?self|end (it all|my life|things)|suicid\w*|self[- ]?harm\w*|"
    r"hurt(ing)? my ?self|cut(ting)? my ?self|(don'?t|do not) want to (be here|be alive|live|"
    r"wake up|exist)|(no|not any) point (in )?(living|going on|being here|being alive)|"
    r"better off (dead|without me)|want(ed)? to die|wish i (was|were) dead)\b",
    re.I,
)
BAD_NIGHT = re.compile(
    r"\b(can'?t (cope|do this any ?more|take (it|this|much more)|go on|keep going)|"
    r"falling apart|worst (day|night|week|month|year) (of my life|ever)|"
    r"(everything|it all|life) (is|feels) (pointless|hopeless|too much|shit)|i give up|"
    r"(nobody|no ?one) cares|so (alone|lonely)|hate my life|completely (broken|lost|alone)|"
    r"at the end of my (rope|tether))\b",
    re.I,
)
BAD_NIGHT_FOR = timedelta(hours=3)  # the rest of the chat, give or take
LIFELINE = "Lifeline on 13 11 14 (any time, day or night)"
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
# Only Dan leaving now: "I see you've fixed it", "I need to run the tests", "I'm off on
# Friday" and "the results should be back in an hour" aren't goodbyes.
FAREWELL = re.compile(
    r"\b(bye(-?bye)?|goodbye|cya|ttyl|brb|see (ya|you) (later|soon|tomorrow|tonight|then|"
    r"in a (bit|sec|while|few))|catch (ya|you) later|talk to (you|ya) (later|soon|tomorrow)|"
    r"(?<!had a )(?<!was a )(?<!'s a )(?<!\u2019s a )(?<!such a )(?<!what a )good ?night"
    r"(?!['\u2019]s)|night,? kit|nighty?[- ]night|"
    r"(i'?m|we'?re|i'?ll be|i am) (off|heading (off|out|home))\b(?! (sick|work|duty|today|"
    r"tomorrow|the|my|this|that|it|on|until|till|next|from)\b)|heading (off|out|home)|"
    r"(i'?m|i am|we'?re|just) (heading|popping|nipping|ducking) (to|out|off|over|down|up)|"
    r"popping (out|off)|((i'?m|i am|we'?re|time) (going|heading|off) to|off to) (bed|sleep)"
    r"\b(?! on\b)|(i'?ll|i will|we'?ll|we will|i should|i'?d|i'?m gonna|i'?m going to) be "
    r"back|(gotta|got to|have to|need to) (go|head off)\b(?!\s+(through|over|and|with|back|"
    r"for|into|on|in|check|look|see|fix|find|do|test|try|get|grab|read|ahead)\b)|"
    r"(gotta|got to|have to|need to) run(?=\s*(now|soon|mate|kit|sorry)?\s*([.!,;]|$))|"
    r"logging off|signing off|calling it a (day|night))\b"
    r"|(^|[.!,;]\s*)(ok(ay)?,? |right(o)?,? |well,? |alright,? )?(see (ya|you)\b(?!['\u2019])|"
    r"talk (later|soon|tomorrow)\b|back (in (a|an|\d+)|soon|later|after)\b|"
    r"(just )?(heading|popping|nipping|ducking) (to|out|off|over|down|up)\b|"
    r"(just )?off (to|for|home|now|out)\b|(going|off) to (bed|sleep)\b)"
    r"|\bsee (ya|you)\W*$|\btalk (later|soon)\W*$|^\W*(night|nite|later|laters)\W*$",
    re.I,
)
NIGHT = re.compile(r"\b(night|nite|bed|sleep)\b", re.I)
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
HUFF = re.compile(r"\b(finally|about time|took (you )?(your time|long enough))\b", re.I)
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

# The face each mood and feeling wears between replies (kit.reply.EMOTIONS). A
# feeling, having a cause, shows over the mood his drives put him in.
MOOD_FACES = {
    "content": "happy",
    "curious": "curious",
    "bored": "tired",
    "lonely": "sad",
    "sleepy": "tired",
    "sulky": "grumpy",
    "asleep": "neutral",
}
FEELING_FACES = {
    "chuffed": "happy",
    "warm": "fond",
    "proud": "proud",
    "pleased": "happy",
    "excited": "excited",
    "amused": "playful",
    "worried": "concerned",
    "sympathetic": "concerned",
    "sad": "sad",
    "put_out": "grumpy",
    "hurt": "sad",
    "glad": "happy",
    "missing": "sad",
    "miffed": "grumpy",
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
# How each feeling moves the mood dials (``life.dials``): (valence -1..1, arousal 0..1).
FEELING_AFFECT: dict[str, tuple[float, float]] = {
    "chuffed": (0.7, 0.65),
    "warm": (0.6, 0.35),
    "proud": (0.6, 0.55),
    "pleased": (0.5, 0.45),
    "excited": (0.6, 0.9),
    "amused": (0.5, 0.6),
    "worried": (-0.4, 0.6),
    "sympathetic": (-0.2, 0.35),
    "sad": (-0.6, 0.2),
    "put_out": (-0.4, 0.4),
    "hurt": (-0.7, 0.4),
    "glad": (0.6, 0.6),
    "missing": (-0.3, 0.2),
    "miffed": (-0.3, 0.5),
}
DIALS_MOVE = 0.05  # bodies hear about the dials when one moves this much
AROUSAL_HALF_LIFE = 30  # minutes for liveliness to settle halfway back
VALENCE_HALF_LIFE = 90  # happiness settles more slowly: a mood lasts hours
# Energy as a need (``life.energy_need``): what tires him, and what restores him.
CHAT_TIRES = 0.1  # an hour of chat
CLOUD_TIRES = 0.05  # each real job (work or expert) handed to a cloud model
LATE_TIRES = 0.3  # an hour awake after 22:30
LATE_FROM = 22.5
SLEEP_RESTORES = 0.6  # an hour asleep
SLEPT_ENOUGH = timedelta(minutes=45)  # a sleep this long sets him back to full
TIRED = 0.4  # below this he yawns and keeps it short
NIGHT_CAP = 0.35  # his body clock's limit at night: under TIRED, so he's sleepy
WIND_DOWN = (21.0, 23.0)  # hours over which the limit falls to NIGHT_CAP
WAKE_UP = (5.0, 7.0)  # and rises back to full
# Away life (``life.alone_thoughts_per_hour``, kit.pastimes).
NOTHING_TO_DO = timedelta(minutes=15)  # found nothing to do: he waits this long to look again
DID_KEPT = 12  # the pastimes he remembers doing today
# Pipe-up scoring (``life.pipe_up_bar``) and how often Dan takes them up.
TAKEN_UP_WITHIN = timedelta(minutes=10)
TAKE_UP_KNOWN = 3  # pipe-ups of a kind before their take-up rate counts
PIPE_STATS_KEY = "pipe_ups"  # kit_self: {reason: [said, taken up]}
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


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


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


DAYTIME = ("morning", "lunchtime", "arvo")


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


def is_work(thing: str) -> bool:
    """Is an app or site (as the desk app names it) one for work?"""
    thing = thing.lower()
    return any(thing == a.lower() for a in WORK_APPS) or any(
        thing == s or thing.endswith("." + s) for s in WORK_SITES
    )


def farewell_plans(text: str) -> bool:
    """Does a goodbye say where Dan's off to ("off to lunch"), not just "bye"?"""
    rest = FAREWELL.sub(" ", text)
    filler = {"right", "righto", "okay", "alright", "well", "kit", "mate", "cheers", "thanks"}
    filler |= {"hour", "hours", "minute", "minutes", "mins", "bit", "sec", "tick", "while"}
    filler |= {"later", "soon", "now", "today", "tonight", "tomorrow", "night", "day"}
    words = [w for w in re.findall(r"[a-z']+", rest.lower()) if len(w) > 2]
    return any(w not in STOPWORDS and w not in filler for w in words)


# A day still to come: "heading to the footy Saturday" is a plan, not a goodbye.
LATER_DAY = re.compile(
    r"\b(tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|"
    r"next week)\b",
    re.I,
)
STILL_GOING = re.compile(r"\b(see (ya|you)|bye|night|nite|back|bed|sleep|later|laters)\b", re.I)


def is_farewell(text: str) -> bool:
    """A message that's only a goodbye, short and with no question in it. Telling
    Kit of a plan for another day ("heading to the footy Saturday") isn't one."""
    if not FAREWELL.search(text) or "?" in text or len(text.split()) > 12:
        return False
    return not (LATER_DAY.search(text) and not STILL_GOING.search(text))


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
    did: list[str] = field(default_factory=list)  # what he did meanwhile (kit.pastimes)

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
            [str(d) for d in data.get("did") or []],
        )


HOME_FEEL = {
    "while": "A small 'there you are' is plenty.",
    "hours": "You noticed they'd gone, and you're glad they're back.",
    "overnight": "It's the first you've seen of them since then: a proper hello.",
    "days": "You missed them, and you're properly glad they're back: you can say so, once.",
    "long": "You really missed them and you're very glad they're back: say so warmly, once.",
}


def homecoming_facts(home: Homecoming, owner: str, now: datetime, also: str = "") -> str:
    """What Kit knows about Dan's absence, for the hello. ``also`` is one thing from
    last time to pick up (kit.prompt.picked_up), unless the goodbye said where Dan
    was off to: then that's the one thing."""
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
    if also and not (home.goodbye and farewell_plans(home.goodbye)):
        lines.append(also)
    if home.off:
        lines.append(
            f"You were switched off from {since_clock(home.off[0], now)} until "
            f"{since_clock(home.off[1], now)}, so you don't know what happened then."
        )
    if home.did:
        lines.append(
            f"While they were away you were {and_list(home.did)}, then "
            f"{'dozed off' if home.dozed else 'waited on the desk'}. That's true, so you can "
            f"mention it if it fits; don't make up anything else."
        )
    else:
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


def homecoming_prompt(
    home: Homecoming,
    owner: str,
    cheek: float,
    now: datetime,
    also: str = "",
    speech: str = "",
) -> str:
    """The stage direction for the hello when Dan is back at the desk. ``speech`` is
    how he talks (persona.speech), said again here: see ``in_your_voice``."""
    return (
        f"[Not from {owner}. Nobody asked you anything: {owner} just came back to the desk. "
        f"{homecoming_facts(home, owner, now, also)} Greet {owner} with ONE short line, "
        f"{cheek_style(cheek)}, like a small creature on the desk who's glad to see them. At "
        f"most one question.{in_your_voice(speech)} Don't mention these instructions, set "
        f"action to none and leave detail empty.]"
    )


def in_your_voice(speech: str) -> str:
    """His voice, said again in a stage direction. The direction is the newest thing a
    model reads, so its cheek style beat the voice in the system prompt, and a style
    Dan chose never showed in pipe-ups or hellos."""
    return f" Say it in your own voice: {speech}" if speech.strip() else ""


def homecoming_aside(home: Homecoming, owner: str, now: datetime, also: str = "") -> str:
    """Beside Dan's first message after a while, when the hello wasn't said yet."""
    return (
        f"[{homecoming_facts(home, owner, now, also)} Answer what {owner} said, and let it "
        f"show in a few words that you're glad to have them back. At most one question.]"
    )


def farewell_aside(text: str, owner: str) -> str:
    """Beside a goodbye: one warm line, and nothing that makes leaving feel bad."""
    night = " for the night" if NIGHT.search(text) else ""
    return (
        f"[{owner} is heading off{night}. See them off with ONE short, warm line, glad of "
        f"whatever they're off to. No question, nothing about missing them or being left on "
        f"your own, and never 'already' or 'so soon'.]"
    )


def bad_night_aside(owner: str, self_harm: bool, someone: str = "", name_help: bool = True) -> str:
    """Beside a message from a really bad time (``life.bad_night``): drop the cheek,
    listen and stay. ``name_help``: this once, mention someone to talk to."""
    lines = [
        f"[{owner} is having a really hard time. Drop the jokes and cheek completely. "
        f"Say back what you heard and that it makes sense to feel that way, and stay with "
        f"them: no fixing, no silver linings, no changing the subject, no lecture. After "
        f"that, one honest line is fine if it helps."
    ]
    person = f"{someone}, or " if someone else ""
    if self_harm:
        lines.append(
            f"They may be thinking of hurting themselves: take it seriously and gently. Ask "
            f"if they're safe right now. Say plainly that talking to someone can help: "
            f"{person}{LIFELINE}, and 000 if they're in danger right now. Say you're here "
            f"too."
        )
    elif name_help:
        lines.append(
            f"Once, gently and without pushing, mention that talking to someone might help: "
            f"{person}{LIFELINE}."
        )
    return " ".join(lines) + "]"


def farewell_fault(line: str) -> str:
    """What's wrong with a goodbye line, as a note for another go ("" if nothing)."""
    hook = FAREWELL_HOOKS.search(line)
    if hook is None:
        return ""
    what = "question" if hook.group(0) == "?" else f'"{hook.group(0).lower()}"'
    return f' (Not "{line}": no {what} in a goodbye. Just a warm see-you line.)'


def homecoming_fault(line: str, miffed: bool = False, kind: str = "") -> str:
    """What's wrong with a hello line, as a note for another go ("" if nothing). After
    days away, "finally, you're back!" is glad, not a huff."""
    if line.count("?") > 1:
        return f' (Not "{line}": one question at most.)'
    huffs = not miffed and kind not in ("days", "long")
    guilt = GUILT.search(line) or (HUFF.search(line) if huffs else None)
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


def bedtime_cap(now: datetime) -> float:
    """The most energy his body clock allows (``life.energy_need``): full by day,
    winding down from 21:00 to sleepy by 23:00, low through the night, and back up
    from 05:00 to 07:00."""
    h = now.hour + now.minute / 60
    if WIND_DOWN[0] <= h < WIND_DOWN[1]:
        return 1 - (1 - NIGHT_CAP) * (h - WIND_DOWN[0]) / (WIND_DOWN[1] - WIND_DOWN[0])
    if h >= WIND_DOWN[1] or h < WAKE_UP[0]:
        return NIGHT_CAP
    if h < WAKE_UP[1]:
        return NIGHT_CAP + (1 - NIGHT_CAP) * (h - WAKE_UP[0]) / (WAKE_UP[1] - WAKE_UP[0])
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
        self._feelings: list[Feeling] = []  # strongest first; two with life.mixed_feelings
        self.wanting = 0.0  # how much his most pressing want presses (kit.notebook)
        self.thoughts: deque[datetime] = deque(maxlen=30)  # when he last thought
        self.next_thought = now + self._think_gap(0.3, 1.0)
        self._to_think: deque[tuple[str, str]] = deque(maxlen=4)  # what's happened since
        self._asleep_since: datetime | None = None
        self._talked_at: datetime | None = None  # Dan's last message, this run
        self._chat_open = False  # a conversation that hasn't been thought over yet
        # Absences: when Dan last touched the PC, went away and came back.
        self.last_seen = now
        self.present_since: datetime | None = None  # at the desk since, without a break
        self.away_since: datetime | None = None
        self.came_back: tuple[datetime, datetime] | None = None  # (gone since, back at)
        self.goodbye: tuple[datetime, str] | None = None  # when Dan said bye, and how
        self.homecoming: Homecoming | None = None  # a hello still to say
        self.was_off: tuple[datetime, datetime] | None = None  # the server was off then
        self.companion_since = now  # his first day (miffed waits a week from it)
        self.closeness = CLOSENESS_START
        self._grown = (now.date().isoformat(), 0.0)  # (day, closeness grown that day)
        self.game_out = ""  # a game he suggested, waiting to hear back
        self.bad_night_until: datetime | None = None  # Dan's having a really bad time
        self.bad_night_named = False  # he's mentioned someone to talk to, this bad night
        self.energy = 1.0  # with life.energy_need; else drives.energy follows the clock
        self.arousal, self.valence = 0.5, 0.0  # the mood dials (life.dials)
        self._dials_shown = (0.5, 0.0)
        self.doing: Pastime | None = None  # what he's doing while Dan's out
        self.did: list[tuple[datetime, str, str]] = []  # today's pastimes: (when, doing, found)
        self._look_for_pastime = now  # found nothing to do: when to look again
        self.alone_thoughts: deque[datetime] = deque(maxlen=12)
        self._week_done = ""  # the week moment he's had a thought about (kit.holidays)
        self._pipe_out: tuple[str, datetime] | None = None  # his last pipe-up, for taken_up
        self._quiet_shown: str | None = None  # the quiet_because bodies last heard
        self._face_shown: str | None = None  # the resting face bodies last heard
        self._restore()

    @property
    def feeling(self) -> Feeling | None:
        """His strongest feeling (``feelings_now`` has both, with mixed feelings)."""
        return self._feelings[0] if self._feelings else None

    @feeling.setter
    def feeling(self, value: Feeling | None) -> None:
        self._feelings = [value] if value is not None else []

    # What happens to Kit

    def note_chat(self, text: str = "") -> None:
        """Dan said something to Kit: the best cure for boredom. Answering his pipe-up
        brings you closer (and a game he suggested landed); a miff is over once he's
        had his say; and a message wakes him (he stays up while you're chatting, even
        with the PC away)."""
        owner = self.settings().persona.owner
        if self.awaiting_reply:
            self.grow(0.005)
            if self.game_out:
                self._game_result(self.game_out, landed=True)
        self.grow(closeness_from(text))
        felt = self.feeling_now()
        if felt is not None and felt.name == "miffed":
            self.feel("glad", f"{owner} is back and talking to you", 0.6, show=False, force=True)
        now = self.clock()
        self._talked_at = now
        if self.asleep:
            self._wake()
        if self._pipe_out is not None:  # Dan answered his last pipe-up in time: it landed
            reason, at = self._pipe_out
            if now - at <= TAKEN_UP_WITHIN:
                self._count_pipe_up(reason, taken=True)
            self._pipe_out = None
        if now - self.last_chat < CHAT_ENDED_AFTER:  # chatting away tires him a little
            self.spend(CHAT_TIRES * (now - self.last_chat).total_seconds() / 3600)
        self.last_chat = now
        self.drives.boredom = 0.1
        self.drives.social = 0.0
        self.ignored = 0  # talking to him makes up for any ignoring
        self.nags = 0
        self.awaiting_reply = False
        self.sulky = False
        self.held_until = None
        self._chat_open = True
        self._show_face()
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
        new = Feeling(name, " ".join(why.split()), now, _clamp(strength))
        current = self.feelings_now()
        if self.settings().life.mixed_feelings and not force:
            # Two at once: the new one beside the strongest other kind, if it's strong
            # enough to be one of the two.
            same = next((f for f in current if f.name == name), None)
            if same is not None and same.left(now) > strength:
                return False
            kept = sorted(
                [f for f in current if f.name != name] + [new], key=lambda f: -f.left(now)
            )
            if new not in kept[:2]:
                return False
            self._feelings = kept[:2]
        else:
            if not force and current and current[0].left(now) > strength:
                return False
            self._feelings = [new]
        self._show_face()
        if show and not self.asleep:
            gesture = self.rng.choice(FEELING_KINDS[name][2])
            self.publish({"type": "fidget", "gesture": gesture, "mood": name})
        self._move_dials(0, push=True)
        self.save()
        return True

    def feeling_now(self) -> Feeling | None:
        """His strongest feeling now, if one hasn't faded."""
        found = self.feelings_now()
        return found[0] if found else None

    def feelings_now(self) -> list[Feeling]:
        """What he feels now, strongest first (two at most, with mixed feelings)."""
        now = self.clock()
        self._feelings = sorted(
            (f for f in self._feelings if f.left(now) > 0.1), key=lambda f: -f.left(now)
        )
        return list(self._feelings)

    def feels(self, *names: str) -> bool:
        """Does he feel any of these now?"""
        return any(f.name in names for f in self.feelings_now())

    # A really bad time (life.bad_night)

    def start_bad_night(self, why: str) -> None:
        """Dan's having a really bad time: no cheek, no games, and he stays with Dan
        for the rest of the chat. Each message that says so again keeps it going."""
        if not self.settings().life.bad_night:
            return
        now = self.clock()
        if not self.bad_night():
            self.bad_night_named = False
        self.bad_night_until = now + BAD_NIGHT_FOR
        self.feel("worried", why, 0.9, show=False, force=True)
        self.save()

    def bad_night(self) -> bool:
        return self.bad_night_until is not None and self.clock() < self.bad_night_until

    def named_help(self) -> None:
        """He's mentioned someone to talk to (or Lifeline): once a bad night."""
        self.bad_night_named = True
        self.save()

    def cheek(self) -> float:
        """How cheeky he is right now: none at all while Dan's having a bad night."""
        return 0.0 if self.bad_night() else self.settings().life.cheek

    # Energy (life.energy_need)

    def spend(self, amount: float) -> None:
        """Something tired him out (a cloud job): only with ``life.energy_need``."""
        if self.settings().life.energy_need:
            self.energy = max(0.05, self.energy - amount)
            self.drives.energy = self.energy

    def tired(self) -> bool:
        """Low enough on energy to yawn and keep his replies short."""
        return self.settings().life.energy_need and self.energy < TIRED

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
            self.present_since = None
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
            if start is not None or self.present_since is None:
                self.present_since = last_input
        elif self.away_since is None:
            self.last_seen = max(self.last_seen, last_input)
        life = self.settings().life
        away_s = life.sleep_after_minutes * 60
        if self.alone_life() and in_quiet_hours(now, life.quiet_from, life.quiet_until):
            away_s = min(away_s, AWAY_AFTER_S)  # at night he goes to sleep, not off to play
        if self.away_since is None and self.doing is not None:
            self.stop_doing()  # Dan's back
            changed = True
        if (
            not self.asleep
            and (snap.locked or snap.idle_seconds >= away_s)
            and not self.chatting(now)
        ):
            self.stop_doing()
            self.asleep = True
            self._asleep_since = now
            self.publish({"type": "state", "state": "asleep"})
            changed = True
        elif self.asleep and not snap.locked and snap.idle_seconds < BACK_IDLE_S:
            self._wake()
            changed = True
        if changed:
            self._show_face()
            self.save()

    def _wake(self) -> None:
        slept = self.clock() - self._asleep_since if self._asleep_since else timedelta(0)
        if slept >= SLEPT_ENOUGH:
            self.energy = 1.0  # a proper sleep sets him right (life.energy_need)
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
        # Only for vanishing in the daytime while the desk app saw it; a gap between
        # messages from his phone, or an evening out, is just life.
        daytime = day_part(since) in DAYTIME and not (
            in_quiet_hours(since, s.life.quiet_from, s.life.quiet_until)
            or in_quiet_hours(now, s.life.quiet_from, s.life.quiet_until)
        )
        miffed = (
            s.life.miffed
            and kind == "hours"
            and daytime
            and not by_chat
            and not goodbye
            and off is None
            and now - self.companion_since >= timedelta(days=s.life.miffed_after_days)
        )
        dozed = self.asleep or self._asleep_since is not None
        did = [doing for at, doing, _ in self.did if at >= since]
        home = Homecoming(kind, since, now, goodbye, miffed, off, dozed, by_chat, did=did)
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

    def take_homecoming(self) -> Homecoming | None:
        """The hello, claimed as the "back" pipe-up starts writing it, so a message from
        Dan meanwhile doesn't get a hello too. ``held_back`` gives it back."""
        home, self.homecoming = self.homecoming, None
        return home

    # Away life (life.alone_thoughts_per_hour, kit.pastimes)

    def alone_life(self) -> bool:
        life = self.settings().life
        return life.enabled and life.alone_thoughts_per_hour > 0

    def presence(self) -> str:
        """Where things stand: "here" (Dan's around), "away" (Dan's gone a few minutes
        and Kit's waiting), "alone" (Kit's awake and entertaining himself) or
        "asleep"."""
        if self.asleep:
            return "asleep"
        if self.away_since is None or self.chatting(self.clock()):
            return "here"  # at the PC, or chatting from his phone
        return "alone" if self.alone_life() else "away"

    def chatting(self, now: datetime) -> bool:
        """Dan's talking to him (from the desk or his phone): he stays awake for it."""
        return self._talked_at is not None and now - self._talked_at < CHAT_ENDED_AFTER

    def wants_pastime(self) -> bool:
        """Alone, awake, and not doing anything (or done with it): time to find
        something to do. Never in quiet hours: then he's off to sleep."""
        now = self.clock()
        life = self.settings().life
        if self.presence() != "alone" or in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return False
        if self.chatting(now):
            return False
        if self.doing is not None and now < self.doing.until:
            return False
        if self.doing is not None:
            self.stop_doing()
        return now >= self._look_for_pastime

    def start_doing(self, pastime: Pastime) -> None:
        """He's found something to do: the face shows it, and it eases the drive it
        feeds."""
        self.doing = pastime
        self.did = [d for d in self.did if d[0].date() == pastime.since.date()][-DID_KEPT + 1 :]
        self.did.append((pastime.since, pastime.doing, pastime.found))
        drive = pastime.feeds
        if hasattr(self.drives, drive):
            setattr(self.drives, drive, _clamp(getattr(self.drives, drive) - 0.3))
        self.publish({"type": "doing", "what": pastime.doing})
        self.save()

    def stop_doing(self) -> None:
        if self.doing is None:
            return
        self.doing = None
        self.publish({"type": "doing", "what": ""})
        self.save()

    def nothing_to_do(self) -> None:
        """Nothing to do just now: he looks again in a while."""
        self._look_for_pastime = self.clock() + NOTHING_TO_DO

    def did_line(self, owner: str) -> str:
        """What he did on his own today, true, for "what did you get up to?"."""
        now = self.clock()
        today = [(at, doing) for at, doing, _ in self.did if at.date() == now.date()]
        if not today:
            return ""
        done = [f"{doing} ({at:%H:%M})" for at, doing in today[-4:]]
        return f"While {owner} was away today you were: {'; '.join(done)}."

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
        if not isinstance(games, dict):
            return {}
        played = games.get("played")
        games["played"] = {
            str(name): {k: v for k, v in record.items() if isinstance(v, int)}
            for name, record in (played.items() if isinstance(played, dict) else [])
            if isinstance(record, dict)
        }
        return games

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
        if self.bad_night() or in_quiet_hours(now, life.quiet_from, life.quiet_until):
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

    # The weather bet: who guessed closer to today's top

    def bet_placed(self, dan: float, kit: float) -> None:
        """Dan and Kit have each guessed today's top temperature."""
        games = self._games()
        today = self.clock().date().isoformat()
        games["bet"] = {"day": today, "dan": dan, "kit": kit}
        self._save_games(games)

    def bet_open(self) -> dict | None:
        """Today's bet, once the day's top is in (late afternoon) and it isn't settled
        yet; checked at most every half hour."""
        bet = self._games().get("bet")
        now = self.clock()
        if not isinstance(bet, dict) or bet.get("day") != now.date().isoformat():
            return None
        if bet.get("settled") or now.hour < BET_SETTLES:
            return None
        tried = bet.get("tried")
        if tried and now - parse_time(tried, now) < BET_RETRY:
            return None
        bet["tried"] = now.isoformat(timespec="seconds")
        self._save_games({**self._games(), "bet": bet})
        return bet

    def bet_settled(self, top: float) -> str:
        """Today's top was ``top``: who won, how Kit feels about it, and the line he
        wants to bring up (a want for kit.notebook)."""
        games = self._games()
        bet = games.get("bet") or {}
        owner = self.settings().persona.owner
        dan, kit = float(bet["dan"]), float(bet["kit"])
        games["bet"] = {**bet, "settled": True, "top": top}
        self._save_games(games)
        said = f"it got to {top:.0f}°; {owner} guessed {dan:.0f}° and you guessed {kit:.0f}°"
        if abs(kit - top) < abs(dan - top):
            self.feel("chuffed", f"you won today's weather bet: {said}", 0.7)
            return f"Tell {owner} you won today's weather bet ({said}). Gloat a little."
        if abs(kit - top) > abs(dan - top):
            self.feel("put_out", f"you lost today's weather bet: {said}", 0.6)
            return f"Tell {owner} they won today's weather bet ({said}). Be a sore loser, briefly."
        self.feel("amused", f"today's weather bet was a draw: {said}", 0.5)
        return f"Tell {owner} today's weather bet was a draw ({said})."

    def mood(self) -> str:
        d = self.drives
        if self.asleep:
            return "asleep"
        if self.sulky:
            return "sulky"
        if d.energy < (TIRED if self.settings().life.energy_need else 0.5):
            return "sleepy"
        if d.curiosity > 0.4:
            return "curious"
        if d.boredom > 0.6:
            return "bored"
        if d.social > 0.7:
            return "lonely"
        return "content"

    def face(self) -> str:
        """The face he wears between replies: his strongest feeling's, else his
        mood's. Asleep, it's neutral (bodies show sleep themselves)."""
        mood = self.mood()
        felt = None if mood == "asleep" else self.feeling_now()
        if felt is not None and felt.name in FEELING_FACES:
            return FEELING_FACES[felt.name]
        return MOOD_FACES.get(mood, "neutral")

    def _show_face(self) -> None:
        """Tell bodies when his resting face changes."""
        face = self.face()
        if face != self._face_shown:
            self._face_shown = face
            self.publish({"type": "mood", "mood": self.mood(), "face": face})

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

        d.energy = self._energy_after(now, minutes)
        d.boredom = _clamp(d.boredom + minutes * (0.03 if present else 0.01) * (0.5 + chatty))
        d.social = _clamp(d.social + minutes / 240)
        d.curiosity = _clamp(d.curiosity * 0.9**minutes)
        owner = self.settings().persona.owner
        work_too = self.settings().life.work_triggers
        if present and snap and snap.focus and snap.watching:
            thing = snap.focus.site or snap.focus.app
            fresh = False
            interesting = work_too or not is_work(thing)
            if thing and thing not in self._seen:
                self._seen.add(thing)
                if len(self._seen) > 1 and interesting:  # the first thing of the day isn't news
                    d.curiosity = _clamp(d.curiosity + 0.6)
                    self.curious_about, self.curious_kind = thing, "new"
                    fresh = True
                    self._think_about("new", f"{owner} just opened {thing}, first time today.")
            focus = (snap.focus.app, snap.focus.title)
            if work_too and self._last_focus and focus != self._last_focus:
                self._notice_build(snap.focus.title, owner)
            switched = self._last_focus and focus != self._last_focus
            if chatty >= CHATTY and switched and interesting:
                # A chatty Kit follows along: a new file or tab is worth a comment.
                d.curiosity = _clamp(d.curiosity + 0.7 * chatty)
                if not fresh:  # something new today is the better story
                    self.curious_about = snap.focus.title or snap.focus.app
                    self.curious_kind = "switch"
            self._last_focus = focus
        gone = self.away_since is not None and not self.pc.online()
        if gone and self.alone_life() and not self.asleep and not self.chatting(now):
            # The PC went to sleep while Dan was out: Kit dozes off in the usual time.
            if now - self.away_since >= timedelta(minutes=self.settings().life.sleep_after_minutes):
                self.stop_doing()
                self.asleep, self._asleep_since = True, now
                self.publish({"type": "state", "state": "asleep"})
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
        self._move_dials(minutes)
        self._show_face()
        self.save()
        return reason

    def _energy_after(self, now: datetime, minutes: float) -> float:
        """His energy now. With ``life.energy_need`` it's a need: staying up past
        22:30 tires him and sleep restores him (chats and cloud jobs spend it too);
        otherwise it follows the clock."""
        if not self.settings().life.energy_need:
            return energy_at(now)
        h = now.hour + now.minute / 60
        if self.asleep:
            self.energy = min(1.0, self.energy + SLEEP_RESTORES * minutes / 60)
        else:
            if h >= LATE_FROM or h < 5:
                self.energy = max(0.05, self.energy - LATE_TIRES * minutes / 60)
            # However rested he is, his body clock winds him down at night: an evening
            # nap mustn't leave him bright at 11 pm.
            self.energy = min(self.energy, bedtime_cap(now))
        return self.energy

    # The mood dials (life.dials): how lively and how happy, for bodies to show

    def _move_dials(self, minutes: float, push: bool = False) -> None:
        """Arousal (0 flat .. 1 lively) and valence (-1 low .. 1 happy) drift toward
        where his energy, drives and feelings put them, slowly (a mood lasts hours);
        a new feeling (``push``) moves them at once. Bodies hear when one has moved."""
        if not self.settings().life.dials:
            return
        d = self.drives
        arousal = 0.05 if self.asleep else 0.15 + 0.5 * d.energy + 0.25 * d.curiosity
        valence = 0.15 - 0.25 * d.boredom - 0.2 * max(0.0, d.social - 0.5)
        valence -= 0.3 if self.sulky else 0.0
        now = self.clock()
        for felt in self.feelings_now():
            v, a = FEELING_AFFECT.get(felt.name, (0.0, 0.5))
            left = felt.left(now)
            valence += v * left
            arousal += (a - 0.5) * 0.6 * left
        arousal, valence = _clamp(arousal), max(-1.0, min(1.0, valence))
        if push:
            ka = kv = 0.6
        else:
            ka = 1 - 0.5 ** (minutes / AROUSAL_HALF_LIFE)
            kv = 1 - 0.5 ** (minutes / VALENCE_HALF_LIFE)
        self.arousal += (arousal - self.arousal) * ka
        self.valence += (valence - self.valence) * kv
        shown_a, shown_v = self._dials_shown
        if abs(self.arousal - shown_a) >= DIALS_MOVE or abs(self.valence - shown_v) >= DIALS_MOVE:
            self._dials_shown = (self.arousal, self.valence)
            self.publish(self.dials_event())

    def dials_event(self) -> dict:
        return {
            "type": "dials",
            "arousal": round(self.arousal, 2),
            "valence": round(self.valence, 2),
        }

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
        self._tell_quiet()
        return reason

    def _tell_quiet(self) -> None:
        """Bodies hear why he's keeping quiet when that changes (not every new number
        in it), so the desk app can say why."""
        gist = re.split(r"[(:0-9]", self.quiet_because, maxsplit=1)[0].strip()
        if self._quiet_shown is None:
            self._quiet_shown = gist  # just started: nothing has changed yet
        elif gist != self._quiet_shown:
            self._quiet_shown = gist
            self.publish({"type": "quiet", "because": self.quiet_because})

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

    def held_back(self, reason: str = "", home: Homecoming | None = None) -> None:
        """He went to pipe up but had nothing new to say (kit.brain keeps quiet rather
        than repeat himself, or the model didn't answer). The urge passes as if he'd
        spoken, but he isn't waiting for an answer: he tries again after the usual gap.
        A hello he couldn't say (``home``) is owed again, unless Dan spoke meanwhile."""
        life = self.settings().life
        gap = max(60 / max(life.max_per_hour, 1), AFTER_CHAT_MIN * (1.2 - life.chattiness))
        self.held_until = self.clock() + timedelta(minutes=gap)
        if reason == "nag":
            self.nags += 1
        home = home or self.homecoming
        if reason == "back" and home is not None and self.last_chat < home.back:
            home.tried = True  # his next reply says hello instead
            self.homecoming = home
        self.butting_in = False
        self.drives.boredom = min(self.drives.boredom, 0.2)
        self.drives.curiosity = 0.0
        self.wanting = 0.0  # the brain sets it again from what's still on his list
        self.save()

    def piped_up(self, reason: str = "") -> None:
        now = self.clock()
        if reason not in ("back", "nag"):
            self._count_pipe_up(reason, taken=False)
            self._pipe_out = (reason, now)
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

    # How his pipe-ups land (taken_up), and scoring one before he says it

    def _pipe_stats(self) -> dict[str, list[int]]:
        raw = self.store.self_value(PIPE_STATS_KEY) if self.store is not None else None
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _count_pipe_up(self, reason: str, taken: bool) -> None:
        if self.store is None:
            return
        stats = self._pipe_stats()
        said, took = stats.get(reason, [0, 0])
        stats[reason] = [said, took + 1] if taken else [said + 1, took]
        self.store.set_self_value(PIPE_STATS_KEY, json.dumps(stats))

    def take_up_rate(self, reason: str) -> float | None:
        """How often Dan answers this kind of pipe-up within ten minutes, once
        there have been a few."""
        said, took = self._pipe_stats().get(reason, [0, 0])
        return min(1.0, took / said) if said >= TAKE_UP_KNOWN else None

    def scored_out(self, reason: str, why: str) -> None:
        """He had something to say but it didn't score well enough: he keeps it to
        himself, and tries again after the usual gap."""
        self.held_back(reason)
        self.quiet_because = why
        self._tell_quiet()

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
        if not life.enabled or self.asleep:
            return None
        if self.presence() == "alone":  # on his own, only his alone thoughts (their own budget)
            return self._alone_thought(now)
        if life.thoughts_per_hour <= 0:
            return None
        snap = self.pc.latest if self.pc.online() else None
        present = bool(snap and not snap.locked and snap.idle_seconds < AWAY_AFTER_S)
        if not present and now - self.last_chat > THINK_NEAR_CHAT:
            return None  # nobody around: he dozes rather than muses
        week = week_moment(now, self.settings().persona.owner) if life.week_thoughts else None
        if week is not None and week[0] != self._week_done and present:
            if now - self.last_chat >= THINK_AFTER_CHAT and not self._thought_too_soon(now):
                self._week_done = week[0]
                return "week", week[1]
        if now - self.last_chat < THINK_AFTER_CHAT or self._thought_too_soon(now):
            return None
        if self._to_think:
            return self._to_think.popleft()
        if now >= self.next_thought:
            return "quiet", "A quiet moment: nothing in particular is happening."
        return None

    def _thought_too_soon(self, now: datetime) -> bool:
        if self.thoughts and now - self.thoughts[-1] < THINK_GAP:
            return True
        hour = sum(1 for t in self.thoughts if now - t < timedelta(hours=1))
        return hour >= self.settings().life.thoughts_per_hour

    def _alone_thought(self, now: datetime) -> tuple[str, str] | None:
        """A thought while he's on his own, about what he's doing: at most
        ``life.alone_thoughts_per_hour``, never in quiet hours."""
        life = self.settings().life
        doing = self.doing
        if doing is None or self.presence() != "alone" or now >= doing.until:
            return None
        if in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return None
        hour = sum(1 for t in self.alone_thoughts if now - t < timedelta(hours=1))
        if hour >= life.alone_thoughts_per_hour or now < self.next_thought:
            return None
        owner = self.settings().persona.owner
        away = self.away_since or now
        return (
            "alone",
            f"{owner} has been away from the PC since {since_clock(away, now)}. You're on "
            f"your own, {doing.doing}. {doing.found}",
        )

    def thought_had(self, kind: str = "") -> None:
        """He had a thought: it counts toward his hourly limit."""
        now = self.clock()
        (self.alone_thoughts if kind == "alone" else self.thoughts).append(now)
        self.next_thought = now + self._think_gap()
        self.save()

    def thought_failed(self) -> None:
        """A thought that didn't happen (the model was down, or Dan started talking):
        it costs no budget, but he doesn't try again straight away."""
        self.next_thought = self.clock() + self._think_gap()
        self.save()

    # Remembering all this across restarts

    def save(self) -> None:
        if self.store is None:
            return
        now = self.clock()

        def when(t: datetime | None) -> str | None:
            return t.isoformat(timespec="seconds") if t else None

        def feeling(f: Feeling) -> dict:
            return {"name": f.name, "why": f.why, "since": when(f.since), "strength": f.strength}

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
            "feelings": [feeling(f) for f in self._feelings],
            "thoughts": [when(t) for t in self.thoughts if now - t < timedelta(hours=1)],
            "alone_thoughts": [
                when(t) for t in self.alone_thoughts if now - t < timedelta(hours=1)
            ],
            "week_done": self._week_done,
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
            "awaiting_reply": self.awaiting_reply,
            "bad_night_until": when(self.bad_night_until),
            "bad_night_named": self.bad_night_named,
            "energy": round(self.energy, 3),
            "dials": [round(self.arousal, 3), round(self.valence, 3)],
            "doing": self.doing.as_dict() if self.doing else None,
            "did": [[when(t), doing, found] for t, doing, found in self.did],
            "pipe_out": [self._pipe_out[0], when(self._pipe_out[1])] if self._pipe_out else None,
        }
        self.store.set_self_value(LIFE_KEY, json.dumps(data))

    def _restore(self) -> None:
        """Pick up where he left off: drives move on by however long he was off, a
        feeling keeps fading from when it began, and the time since you last talked
        stays true."""
        raw = self.store.self_value(LIFE_KEY) if self.store is not None else None
        if not raw:
            return
        now = self.clock()
        try:
            data = json.loads(raw)
            saved = parse_time(data["saved"], now)
        except (ValueError, KeyError, TypeError, IndexError):
            return  # a damaged save just means a fresh start
        for part in (self._restore_mood, self._restore_absence):
            try:
                part(data, now, saved)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError):
                log.warning("part of Kit's saved life was damaged; starting that part fresh")

    def _restore_mood(self, data: dict, now: datetime, saved: datetime) -> None:
        """Drives, feeling, thoughts and the day so far."""
        off = max(0.0, (now - saved).total_seconds() / 60)
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
        saved_feelings = data.get("feelings")
        if saved_feelings is None:  # saved by a Kit with one feeling at a time
            saved_feelings = [data["feeling"]] if data.get("feeling") else []
        self._feelings = [
            Feeling(f["name"], f["why"], parse_time(f["since"], now), float(f["strength"]))
            for f in saved_feelings
            if f.get("name") in FEELING_KINDS
        ][:2]
        self.feelings_now()  # drops any that have faded meanwhile
        self.thoughts.extend(parse_time(t, now) for t in data.get("thoughts", []))
        self.alone_thoughts.extend(parse_time(t, now) for t in data.get("alone_thoughts", []))
        if data.get("day") == now.date().isoformat():
            self._week_done = str(data.get("week_done", ""))
        if data.get("bad_night_until"):
            self.bad_night_until = parse_time(data["bad_night_until"], now)
            self.bad_night_named = bool(data.get("bad_night_named"))
        self.energy = _clamp(float(data.get("energy", 1.0)))
        if off >= 6 * 60:
            self.energy = 1.0  # a night off is a night's sleep
        self.drives.energy = self.energy if self.settings().life.energy_need else energy_at(now)
        if isinstance(data.get("dials"), list):
            self.arousal = _clamp(float(data["dials"][0]))
            self.valence = max(-1.0, min(1.0, float(data["dials"][1])))
            self._dials_shown = (self.arousal, self.valence)
        if isinstance(data.get("doing"), dict):
            doing = Pastime.from_dict(data["doing"], now)
            self.doing = doing if doing.until > now else None
        self.did = [
            (parse_time(t, now), str(doing), str(found))
            for t, doing, found in data.get("did") or []
        ]
        if data.get("pipe_out"):
            self._pipe_out = (str(data["pipe_out"][0]), parse_time(data["pipe_out"][1], now))
        if data.get("next_thought"):
            self.next_thought = max(now, parse_time(data["next_thought"], now))
        self._chat_open = bool(data.get("chat_open")) and off < 60
        if data.get("day") == now.date().isoformat():
            self._seen = set(data.get("seen", []))
        if off < 60:  # still waiting on an answer to his last pipe-up
            self.awaiting_reply = bool(data.get("awaiting_reply"))

    def _restore_absence(self, data: dict, now: datetime, saved: datetime) -> None:
        """Where Dan was, and whether Kit was switched off: a night with the server off
        still counts as a night away, and Kit knows he wasn't there for it."""

        def when(key: str) -> datetime | None:
            return parse_time(data[key], now) if data.get(key) else None

        # Saved before there was a first day: his week to settle in starts now.
        self.companion_since = when("companion_since") or now
        if "closeness" in data:
            self.closeness = _clamp(float(data["closeness"]))
        if data.get("grown"):
            self._grown = (str(data["grown"][0]), float(data["grown"][1]))
        self.asleep = bool(data.get("asleep"))
        self._asleep_since = when("asleep_since") if self.asleep else None
        self.last_seen = when("last_seen") or saved  # an older Kit's save: he was there
        self.away_since = when("away_since")
        if data.get("came_back"):
            a, b = data["came_back"]
            self.came_back = (parse_time(a, now), parse_time(b, now))
        if data.get("goodbye"):
            self.goodbye = (parse_time(data["goodbye"][0], now), str(data["goodbye"][1]))
        if isinstance(data.get("homecoming"), dict):
            self.homecoming = Homecoming.from_dict(data["homecoming"], now)
        if data.get("was_off"):
            a, b = data["was_off"]
            self.was_off = (parse_time(a, now), parse_time(b, now))
        if now - saved >= OFF_COUNTS:
            start = self.was_off[0] if self.was_off and self.was_off[1] >= saved else saved
            self.was_off = (start, now)
        # A game he suggested still counts only while he's waiting to hear back.
        self.game_out = str(data.get("game_out", "")) if self.awaiting_reply else ""

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
        opinions: list[str] | None = None,
    ) -> Voice:
        """How Kit feels and sounds for the next reply. Call it before ``note_chat``,
        so "I've been bored" or "I missed you" is still true when he answers.
        ``mind`` is what's on his mind lately (kit.notebook), ``opinions`` views he
        stands by (``life.opinions``)."""
        feeling = self.feeling_line(owner)
        cheek = self.cheek()
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
        style = cheek_style(cheek)
        if self.bad_night():
            style = BAD_NIGHT_STYLE
            quirk = ""
        elif self.tired():
            style += TIRED_STYLE
        voice = Voice(feeling, style, examples, said, quirk, list(mind or []), close, when)
        voice.opinions = list(opinions or [])
        return voice

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
        felt = self.feelings_now()
        if not felt:
            return feeling
        parts = [
            f"{FEELING_KINDS[f.name][0].format(owner=owner)}, because {f.why} ({ago(f.since, now)})"
            for f in felt
        ]
        underneath = f"; underneath, {feeling}" if mood != "content" else ""
        return "; and ".join(parts) + underneath

    def state(self) -> dict:
        now = self.clock()
        felt = self.feeling_now()
        also = self.feelings_now()[1:]
        hour = timedelta(hours=1)
        taken = {
            reason: f"{min(took, said)} of {said}"
            for reason, (said, took) in self._pipe_stats().items()
            if said
        }
        return {
            "mood": self.mood(),
            "face": self.face(),
            "presence": self.presence(),
            "doing": self.doing.doing if self.doing else None,
            "did_today": [
                f"{at:%H:%M} {doing}" for at, doing, _ in self.did if at.date() == now.date()
            ],
            "also_feeling": None
            if not also
            else {"name": also[0].name, "why": also[0].why, "left": round(also[0].left(now), 2)},
            "bad_night": self.bad_night(),
            "energy": round(self.energy, 2)
            if self.settings().life.energy_need
            else round(self.drives.energy, 2),
            "dials": {"arousal": round(self.arousal, 2), "valence": round(self.valence, 2)}
            if self.settings().life.dials
            else None,
            "taken_up": taken,
            "alone_thoughts_this_hour": sum(1 for t in self.alone_thoughts if now - t < hour),
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


def and_list(items: list[str]) -> str:
    """ "a", "a and b", "a, b and c"."""
    items = [i for i in items if i]
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


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
        if says(pattern, text):
            return name, why, strength
    return None


INNER_NOT = re.compile(r"\bnot\b|n['\u2019]t\b|\bnever\b|\bno longer\b", re.I)


def says(pattern: re.Pattern, text: str, inner: bool = True) -> bool:
    """Does ``text`` say what ``pattern`` matches, and mean it? "Not stressed" and
    "the tests aren't failing" don't count; "never been so stressed" does. ``inner``
    False: a "not" inside the match is part of it ("can't cope")."""
    for m in pattern.finditer(text):
        before = CLAUSE.split(text[: m.start()])[-1]
        if STILL_SO.search(f"{before}{m.group(0)}"):
            return True
        inside = inner and " " in m.group(0) and INNER_NOT.search(m.group(0))
        if NEGATED.search(before) or inside:
            continue
        return True
    return False


def bad_night_in(text: str) -> str:
    """A really bad time in Dan's words: "self_harm" (never second-guessed by a
    "not"), "bad_night", or ""."""
    if SELF_HARM.search(text):
        return "self_harm"
    return "bad_night" if says(BAD_NIGHT, text, inner=False) else ""


# How Dan seems, as the model answering read it (kit.reply.MOOD_FIELDS), turned
# into what Kit feels: (feeling, strength), by dan_mood, then who it's aimed at.
READ_FEELINGS: dict[str, tuple[str, float]] = {
    "happy": ("pleased", 0.5),
    "excited": ("excited", 0.6),
    "proud": ("proud", 0.6),
    "grateful": ("warm", 0.6),
    "tired": ("sympathetic", 0.5),
    "flat": ("worried", 0.5),
    "stressed": ("worried", 0.7),
    "worried": ("worried", 0.6),
    "sad": ("sad", 0.7),
    "angry": ("sympathetic", 0.6),
    "awful": ("worried", 0.7),
}


def feeling_from_read(read: dict, text: str, owner: str) -> tuple[str, str, float] | None:
    """What Kit feels from the model's reading of Dan's message (``read_mood``
    meaning): praise or thanks aimed at Kit, anger at Kit, Dan's own mood, or
    things going worse than hoped. None when Dan seems fine."""
    mood = str(read.get("dan_mood") or "")
    at_kit = read.get("for_whom") == "kit"
    expected = read.get("expected")
    why = f'{owner} said "{quoted(text)}"'
    if at_kit and mood == "angry":
        return "hurt", why, 0.7
    if at_kit and mood in ("happy", "proud", "excited"):
        return "chuffed", why, 0.7
    if at_kit and mood == "grateful":
        return "warm", why, 0.6
    if mood in READ_FEELINGS:
        name, strength = READ_FEELINGS[mood]
        if name in ("pleased", "excited") and expected == "better":
            name = "proud"  # it went better than Dan hoped: proud of him
        return name, why, strength
    if expected == "worse":
        return "sympathetic", why, 0.5
    return None


def pipe_up_score(
    reason: str,
    candidate: str,
    context: str,
    said: list[str],
    urgency: float,
    rate: float | None = None,
) -> tuple[float, str]:
    """How worth saying a pipe-up is, before he says it (``life.pipe_up_bar``), and
    the parts as words: relevance to what Dan's doing and the time of day,
    originality against what Kit said lately, and urgency (how hard it presses).
    Kinds Dan often takes up count for more (``rate``, from ``Life.take_up_rate``).
    Scored from words, with no model call."""
    mine = _words(candidate) - STOPWORDS
    around = _words(context) - STOPWORDS
    if reason in ("curious", "watching"):
        relevance = 0.8  # about what Dan just opened
    elif mine and around:
        relevance = min(1.0, 0.4 + len(mine & around) / max(3, len(mine)))
    else:
        relevance = 0.4
    originality = 0.7  # a line not written yet: the repeat check comes after
    if mine:
        overlap = [
            len(mine & theirs) / min(len(mine), len(theirs))
            for theirs in (_words(line) - STOPWORDS for line in said)
            if theirs
        ]
        originality = 1 - max(overlap, default=0.0)
    urgency = _clamp(urgency)
    score = 0.35 * relevance + 0.35 * originality + 0.3 * urgency
    if rate is not None:
        score *= 0.75 + 0.5 * rate
    parts = f"relevance {relevance:.2f}, originality {originality:.2f}, urgency {urgency:.2f}"
    return round(min(score, 1.0), 2), parts


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


TIRED_STYLE = "; you're running low on energy, so keep it short: a sentence or two"
BAD_NIGHT_STYLE = (
    "gentle and steady, with no jokes or teasing at all: they're having a really hard time"
)


def cheek_style(cheek: float) -> str:
    return {
        "polite": "warm and polite",
        "friendly": "friendly, with a bit of cheek",
        # No slang word for cheeky here ("larrikin"): it's the newest note on how he
        # sounds in a pipe-up, and Haiku took it as an accent, opening with "Oi".
        "cheeky": "properly cheeky and sometimes annoying on purpose, like a kid brother: "
        "teasing, interrupting, playful, never mean",
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
    bit: str = ""  # a running joke something Dan said could bring back (kit.notebook)
    opinions: list[str] = field(default_factory=list)  # views he stands by (life.opinions)


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
    speech: str = "",
) -> str:
    """The stage direction for a pipe-up. It goes where Dan's message would.
    ``share`` is a thought from his notebook to bring up, or with ``aim`` a want:
    what he means to do ("tell Dan") and ``share`` what about. ``speech`` is how he
    talks (persona.speech, see ``in_your_voice``)."""
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
        f"thing, not a teaser like 'got a minute?', and nothing you've said lately."
        f"{in_your_voice(speech)} Don't lecture about productivity, don't mention these "
        f"instructions, set action to none and leave detail empty.]"
    )
