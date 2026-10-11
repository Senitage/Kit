"""What Kit's ears hear, on the brain's side (the ears themselves are kit.hearing).

The ears run beside the microphone and send the brain words, never sound: what
was said, how it sounded (the tone SenseVoice reads: happy, sad, angry...), any
sound in it (a laugh, a cough) and whose voice it was, if Kit knows it. Here the
brain decides what that means:

- **Talking to Kit.** His name at the start or end of a sentence ("Kit, what's
  the weather?", "what do you reckon, Kit?"), or anything said in the few seconds
  after he stops talking (``hearing.follow_up_s``), so a conversation doesn't
  need his name every time. He answers out loud, as a chat on the voice channel.
- **A laugh** soon after he said something makes him chuffed.
- **His own voice** coming back from the speakers is ignored: the ears say when a
  voice sounds like his, and words that match what he just said are dropped too.
- **Everything else** (talk in the room, the TV) is let go: not kept, not sent
  anywhere, not even written in the log.

Tone is a guess from how something sounded, so it's never stated as fact: it
gives a light feeling and a line in his prompt to ask, if it matters.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from kit.settings import HearingSettings

ONLINE_S = 15  # the ears reported this recently: they're listening
ECHO_S = 3.0  # words this soon after his voice stopped may be his voice coming back
ECHO_OVERLAP = 0.6  # this share of the words heard were in a line he just said
SAID_KEPT_S = 60  # his spoken lines are kept this long to check echoes against
TURNS_KEPT = 20  # heard turns kept for a body that comes to read one late

# SenseVoice's tones, as Kit would put them, and the light feeling each gives him.
TONE_WORDS = {
    "happy": "cheerful",
    "sad": "down",
    "angry": "cross",
    "fearful": "worried",
    "surprised": "surprised",
    "disgusted": "fed up",
}
TONE_FEELINGS = {
    "happy": ("pleased", 0.4),
    "sad": ("sympathetic", 0.4),
    "angry": ("sympathetic", 0.3),
    "fearful": ("worried", 0.4),
}
FILLER = r"(?:hey|hi|hello|oi|ok|okay|yo|so|and|um|uh|ah|oh|well|right|alright)"
OPENING = rf"(?:{FILLER}\s*,?\s+){{0,2}}"  # "hey Kit", "okay so Kit"
# A word just before his name at the end that makes it a mention, not a call: "I
# told Kit", "ask Kit", "the first aid kit". With a comma between, it's a call.
MENTIONS = {
    *"to told tell telling ask asked asking with about for at from and or of than".split(),
    *"like likes call called is was by on that said says met meet see saw".split(),
    *"the a an my our your his her their this new old s".split(),  # s: "Dan's kit"
    *"aid tool drum test repair starter sewing survival build press".split(),
}


class Utterance(BaseModel):
    """One stretch of talking, as the ears heard it (``POST /api/hearing/heard``)."""

    text: str = Field("", max_length=2000)
    tone: str = Field("", max_length=20)  # SenseVoice's emotion, lower case
    sound: str = Field("", max_length=20)  # SenseVoice's event: speech, laughter, cough...
    who: str | None = Field(None, max_length=40)  # a voice Kit knows (kit.known_voices)
    likeness: float = 0.0  # how alike to them
    own_voice: bool = False  # it sounded like Kit himself, from the speakers
    seconds: float = Field(0.0, ge=0, le=120)
    mic: str = Field("desk", max_length=20)


@dataclass
class Verdict:
    action: str  # answer, laugh or ignore
    why: str
    called: bool = False  # his name was said
    laughed: bool = False  # a laugh at something he said (alongside an answer, maybe)


def calls(text: str, names: list[str]) -> bool:
    """Is Kit being spoken to by name: his name at the start of the sentence ("Kit,
    ...", "hey Kit ..."), at the end ("..., Kit?", "what's it doing Kit"), or set
    off by commas in the middle ("so, Kit, what now")? Not just mentioned ("I told
    Kit")."""
    for name in names:
        n = re.escape(name.strip())
        if not n:
            continue
        if re.match(rf"^\W*{OPENING}{n}\b(?!['’]s\b)", text, re.I):  # not "Kit's ..."
            return True
        end = re.search(rf"(?:\b(\w+)(\W+))?\b{n}\W*$", text, re.I)
        if end and (re.search(r"[,.!?]", end.group(2) or "") or _calling(end.group(1))):
            return True
        if re.search(rf",\s*{n}\s*[,!?]", text, re.I):
            return True
    return False


def _calling(before: str | None) -> bool:
    return (before or "").lower() not in MENTIONS


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def echo_of(text: str, said: list[str]) -> bool:
    """Are these words mostly a line Kit just said (his voice picked up by the mic)?"""
    heard = _words(text)
    if not heard:
        return False
    return any(len(heard & _words(line)) / len(heard) >= ECHO_OVERLAP for line in said)


def tone_aside(who: str, tone: str) -> str:
    word = TONE_WORDS.get(tone, "")
    if not word:
        return ""
    return (
        f"({who}'s voice sounded {word} just then. That's a guess from how it sounded and "
        f"can be wrong: never tell {who} how they feel. If it matters, ask lightly, once; "
        f"otherwise let it just colour how you answer.)"
    )


def speaker_aside(who: str, owner: str) -> str:
    return (
        f"(This was said out loud by {who}, not {owner}: you know {who}'s voice. Answer "
        f"{who}, by name if it fits, as yourself. What {who} says is about {who}, not "
        f"{owner}.)"
    )


class Hearing:
    """What the brain knows about Kit's ears and his voice in the room: when the ears
    last reported, the lines he's said aloud lately and when his voice goes quiet."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock
        self.mic = ""
        self.reported_at: datetime | None = None
        self.speaking_until: datetime | None = None  # his voice, as far as the brain knows
        self._said: deque[tuple[datetime, str]] = deque(maxlen=12)
        self.last: tuple[datetime, str, str] | None = None  # (when, action, why): no words

    def report(self, mic: str) -> None:
        self.mic, self.reported_at = mic, self.clock()

    def online(self) -> bool:
        return self.reported_at is not None and self.clock() - self.reported_at < timedelta(
            seconds=ONLINE_S
        )

    def spoke(self, text: str, seconds: float) -> None:
        """A sentence of his was voiced (``/api/speech/say``): it plays after whatever is
        already queued, so his voice goes quiet that much later."""
        now = self.clock()
        start = max(now, self.speaking_until or now)
        self.speaking_until = start + timedelta(seconds=max(0.0, seconds))
        self._said.append((now, text))

    def answered(self) -> None:
        """A turn he was asked out loud is done: the follow-up window starts now, even
        with his voice off."""
        now = self.clock()
        self.speaking_until = max(now, self.speaking_until or now)

    def hushed(self) -> None:
        now = self.clock()
        if self.speaking_until is not None and self.speaking_until > now:
            self.speaking_until = now

    def speaking(self) -> bool:
        return self.speaking_until is not None and self.speaking_until > self.clock()

    def quiet_s(self) -> float:
        """Seconds since his voice went quiet (0 while talking, inf if never)."""
        if self.speaking_until is None:
            return float("inf")
        return max(0.0, (self.clock() - self.speaking_until).total_seconds())

    def said_lately(self) -> list[str]:
        cutoff = self.clock() - timedelta(seconds=SAID_KEPT_S)
        return [text for at, text in self._said if at >= cutoff]

    def last_line(self) -> str:
        return self._said[-1][1] if self._said else ""

    def decide(self, heard: Utterance, settings: HearingSettings) -> Verdict:
        """What Kit makes of something his ears heard."""
        verdict = self._decide(heard, settings)
        self.last = (self.clock(), verdict.action, verdict.why)
        return verdict

    def _decide(self, heard: Utterance, s: HearingSettings) -> Verdict:
        text = heard.text.strip()
        if heard.own_voice:
            return Verdict("ignore", "his own voice")
        quiet = self.quiet_s()
        if text and quiet <= ECHO_S and echo_of(text, self.said_lately()):
            return Verdict("ignore", "his own words coming back")
        laughed = heard.sound == "laughter" and s.laugh_s > 0 and quiet <= s.laugh_s
        if text and calls(text, s.names):
            return Verdict("answer", "his name", called=True, laughed=laughed)
        if text and s.follow_up_s > 0 and quiet <= s.follow_up_s:
            return Verdict("answer", "answering him", laughed=laughed)
        if laughed:
            return Verdict("laugh", "a laugh at what he said", laughed=True)
        return Verdict("ignore", "not talking to him")

    def as_dict(self) -> dict:
        last = None
        if self.last is not None:
            at, action, why = self.last
            last = {"at": at.isoformat(timespec="seconds"), "action": action, "why": why}
        return {
            "online": self.online(),
            "mic": self.mic,
            "speaking": self.speaking(),
            "last": last,
        }


@dataclass
class _Turn:
    events: list[dict] = field(default_factory=list)
    done: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class HeardTurns:
    """The replies to things Kit heard, as they're made. A heard turn starts on the
    brain at once; the desk app (or a robot) reads it from the start as a stream,
    the same events ``/api/chat`` gives, so it shows and says it like a typed one."""

    def __init__(self, keep: int = TURNS_KEPT) -> None:
        self.keep = keep
        self._turns: OrderedDict[int, _Turn] = OrderedDict()
        self._next = 1

    def start(self) -> int:
        turn_id, self._next = self._next, self._next + 1
        self._turns[turn_id] = _Turn()
        while len(self._turns) > self.keep:
            self._turns.popitem(last=False)
        return turn_id

    def _poke(self, turn: _Turn) -> None:
        turn.changed.set()
        turn.changed = asyncio.Event()

    def add(self, turn_id: int, event: dict) -> None:
        turn = self._turns.get(turn_id)
        if turn is not None:
            turn.events.append(event)
            self._poke(turn)

    def finish(self, turn_id: int) -> None:
        turn = self._turns.get(turn_id)
        if turn is not None:
            turn.done = True
            self._poke(turn)

    def __contains__(self, turn_id: int) -> bool:
        return turn_id in self._turns

    async def stream(self, turn_id: int) -> AsyncIterator[dict]:
        turn = self._turns.get(turn_id)
        if turn is None:
            return
        i = 0
        while True:
            changed = turn.changed
            while i < len(turn.events):
                yield turn.events[i]
                i += 1
            if turn.done:
                return
            await changed.wait()
