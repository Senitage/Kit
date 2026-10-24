"""The shape of every reply Kit gives, and how it's read while it streams.

The local model is forced to answer with JSON matching ``Reply``, so it picks
words, an emotion and named gestures but never invents a motion. The body (the
on-screen helper now, the arm later) turns those names into movement.

With the speaking pass on (``ollama.speak_pass``), the local model answers in
two steps instead: a quick ``Plan`` in JSON (emotion, gesture, action), then
his words in plain text, read as they stream by ``SpokenStream``. Both end up
as the same ``Reply``.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kit.memory import FACT_KINDS
from kit.things import SYSTEMS, THING_KINDS

EMOTIONS: dict[str, str] = {
    "neutral": "calm, nothing special",
    "happy": "pleased or glad",
    "curious": "interested, wants to know more",
    "thinking": "working something out",
    "surprised": "didn't expect that",
    "concerned": "worried or sympathetic",
    "playful": "joking or teasing",
    "tired": "low energy or bored",
    "proud": "something went well",
    "excited": "can't wait, really keen",
    "sad": "disappointed or sorry",
    "confused": "doesn't follow, puzzled",
    "shy": "flattered or a bit embarrassed",
    "grumpy": "annoyed or fed up, mildly",
    "focused": "concentrating on a task",
    "relieved": "a worry has gone away",
    "fond": "warm and affectionate",
}

GESTURES: dict[str, str] = {
    "none": "stay still",
    "nod": "yes, agreed, understood",
    "shake": "no, disagree",
    "tilt_head": "curious or confused",
    "perk_up": "interested or excited",
    "droop": "sad or tired",
    "look_away": "thinking it over",
    "shrug": "not sure, could go either way",
    "wave": "hello or goodbye",
    "bounce": "happy, celebrating",
    "lean_in": "listening closely, concerned",
    "wink": "a joke or a shared secret",
    "laugh": "something is funny",
    "sigh": "resigned, or letting go of a worry",
    "startle": "a sudden fright or shock",
    "yawn": "sleepy or bored",
    "double_take": "wait, what? surprised on second look",
    "wiggle": "a little happy dance",
    "peek": "sneaking a look, playful",
    "look_up": "trying to remember something",
}

# How Dan seems, read from his message by the model answering it (``life.read_mood``
# meaning): kit.life.feeling_from_read turns it into what Kit feels.
MOOD_FIELDS: dict[str, dict[str, str]] = {
    "dan_mood": {
        "fine": "nothing much either way",
        "happy": "in a good mood",
        "excited": "excited or keen",
        "proud": "pleased with something they did",
        "grateful": "thankful",
        "tired": "tired or worn out",
        "flat": "low or flat",
        "stressed": "stressed or under pressure",
        "worried": "worried about something",
        "sad": "sad, or had bad news",
        "angry": "annoyed or angry",
        "awful": "having a really bad time",
    },
    "about": {
        "kit": "you",
        "them": "themselves or their day",
        "someone": "someone else",
        "work": "work",
        "everyday": "everyday things",
        "nothing": "nothing in particular",
    },
    "for_whom": {
        "kit": "aimed at you (praise, thanks, a dig)",
        "them": "about how they feel themselves",
        "someone": "about someone else",
        "no_one": "not aimed at anyone",
    },
    "expected": {
        "better": "it went better than they hoped",
        "worse": "it went worse than they hoped",
        "as_hoped": "it went as they hoped",
        "not_said": "doesn't say",
    },
}
# What Dan's message is, as the model answering reads it (kit.brain.Reading): the
# words only guess at these; the model's reading wins where it gives one.
INTENTS: dict[str, str] = {
    "chat": "talk, a remark or a joke",
    "question": "wants an answer",
    "request": "wants you to do something: a note, a lookup, a reminder, a job",
    "goodbye": "only heading off, with nothing else asked",
    "news": "telling you something that happened, not asking",
}
READING_FIELDS = (
    "intent",
    "about_kit",
    "wants_pc_look",
    "wants_camera_look",
    "said_it",
    "crisis_candidate",
)
Intent = Literal[tuple(INTENTS)]  # type: ignore[valid-type]
DanMood = Literal[tuple(MOOD_FIELDS["dan_mood"])]  # type: ignore[valid-type]
About = Literal[tuple(MOOD_FIELDS["about"])]  # type: ignore[valid-type]
ForWhom = Literal[tuple(MOOD_FIELDS["for_whom"])]  # type: ignore[valid-type]
Expected = Literal[tuple(MOOD_FIELDS["expected"])]  # type: ignore[valid-type]

FactKind = Literal[tuple(FACT_KINDS)]  # type: ignore[valid-type]
Emotion = Literal[tuple(EMOTIONS)]  # type: ignore[valid-type]
Gesture = Literal[tuple(GESTURES)]  # type: ignore[valid-type]
ThingKind = Literal[tuple(THING_KINDS)]  # type: ignore[valid-type]
LinkSystem = Literal[("none", *SYSTEMS)]  # type: ignore[valid-type]


# A laugh written out as words ("Hehe!", "haha", "*laughs*"): a cloud model playing
# a cheeky character sprinkled them through his lines where nothing was funny, and his
# voice read them out. A laugh is fine when something is funny, so it stays only in a
# segment with the laugh gesture (``said_laughs``) and goes from the rest.
# "hee hee", "heehee" and "tee hee" too: Kit took to writing "hee hee" (2026-10-24),
# which a pattern of "he" and "ha" pairs let through.
_LAUGH = re.compile(
    r"(,\s*)?\b(?:h[ae]{1,3}(?:[\s-]?h[ae]{1,3})+h?|te{1,2}[\s-]?he{1,2}|heh|hah|lol)\b"
    r"([!~.,]*)",
    re.I,
)
_LAUGH_STAGE = re.compile(
    r"[*(]\s*(?:laugh|giggl|chuckl|snicker|snort|cackl)\w*[^*()\n]{0,30}[*)]", re.I
)
_GONE = "\x00"  # where a laugh was, until the words around it are tidied


def _laugh_gone(match: re.Match) -> str:
    if match[1]:  # "Good good, hehe." keeps its full stop
        return match[2].replace("~", "")
    before = match.string[: match.start()].rstrip()
    if not before or before[-1] in ".!?":  # it opened a sentence: so does the next word
        return _GONE
    return _GONE + match[2].replace("~", "")  # "Print good hehe." keeps its full stop


def without_laughs(text: str) -> str:
    """His words without a laugh written into them ("Hehe! Print good." is "Print
    good."); a sentence the laugh opened starts with a capital again."""
    out = _LAUGH.sub(_laugh_gone, _LAUGH_STAGE.sub(_GONE, text))
    if out == text:
        return text
    out = re.sub(rf"(^\s*|[.!?]\s+){_GONE}[\s{_GONE}]*([a-z])", lambda m: m[1] + m[2].upper(), out)
    out = re.sub(rf"\s*{_GONE}", "", out)
    out = re.sub(r"(?<=\S) {2,}", " ", out)
    return out.lstrip() if not text[:1].isspace() else out


def said_laughs(gesture: str, text: str) -> str:
    """A segment's words: a laugh stays where he laughs (the laugh gesture says he
    found it funny) and goes from everywhere else."""
    return text if gesture == "laugh" else without_laughs(text)


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gesture: Gesture = Field(description="The gesture that goes with it.")
    say: str = Field(description="One short sentence to say.")

    @model_validator(mode="after")
    def _laughs_only_when_funny(self) -> Segment:
        self.say = said_laughs(self.gesture, self.say)
        return self


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "none",
        "recall",
        "look_at_pc",
        "look_around",
        "remember",
        "note",
        "read_note",
        "offer_note",
        "thing",
        "weather",
        "ask_cloud",
        "ask_expert",
    ] = Field(
        description="recall searches memory before answering; look_at_pc checks what's "
        "open and in focus on Dan's PC and how it's running; look_around reads everything "
        "the camera sees right now (who's at the desk, what they're doing, what's about); "
        "remember saves a fact; "
        "note writes a note into Dan's notes; offer_note asks whether to; "
        "read_note opens one of his notes and reads it before answering; "
        "thing notes a named thing and where it lives; weather gets the forecast before "
        "answering; ask_cloud hands the question to the "
        "cloud model; ask_expert hands it to the strongest model; none does nothing."
    )
    text: str = Field(
        "",
        description="For recall: what to search for. For remember: the fact, as one "
        "sentence that makes sense on its own later. For note: the note itself, in "
        "markdown. For offer_note: what you'd write. For read_note: the note's name "
        "or path. For ask_cloud and ask_expert: the "
        "full question with the context it needs. For weather: the place, or empty for "
        "home.",
    )
    title: str = Field(
        "",
        description="For note: a short title for a new note, or the name of the note to add to.",
    )
    category: FactKind = Field("other", description="For remember: what kind of fact it is.")
    thing_kind: ThingKind = Field("other", description="For thing: what kind of thing it is.")
    link_system: LinkSystem = Field(
        "none", description="For thing: the system where it lives, if known."
    )
    link_target: str = Field(
        "", description="For thing: where in that system, e.g. a folder path or note name."
    )


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    segments: list[Segment] = Field(min_length=1, max_length=6)
    action: Action
    detail: str = Field(
        "",
        description="Longer written detail shown on screen but not spoken: code, steps, "
        "lists, numbers, sources. Usually empty.",
    )

    @property
    def text(self) -> str:
        return " ".join(s.say.strip() for s in self.segments if s.say.strip())

    @property
    def full_text(self) -> str:
        """What was said, then any written detail."""
        return f"{self.text}\n\n{self.detail.strip()}" if self.detail.strip() else self.text

    @classmethod
    def plain(cls, text: str, emotion: str = "neutral", gesture: str = "none") -> Reply:
        return cls(
            emotion=emotion,
            segments=[Segment(say=text, gesture=gesture)],
            action=Action(kind="none"),
        )


BROUGHT_UP = Field(
    default_factory=list,
    description="The numbers of the things on your mind lately that you bring up in this "
    "reply, if any. Usually empty.",
)

# The reading fields, shared by both plans. They come before the action, so stopping
# early at a "none" action keeps them, and each is None when the model left it out
# (then the words decide, kit.brain.Reading).
_INTENT = Field(None, description="What the message is.")
_ABOUT_KIT = Field(None, description="Is it about you yourself?")
_WANTS_PC_LOOK = Field(None, description="Does answering need a look at what's open on the PC?")
_WANTS_CAMERA_LOOK = Field(None, description="Does answering need a look through your eyes?")
_SAID_IT = Field(
    None,
    description="For remember or thing: did they actually say or name it, rather than you "
    "guessing or quoting yourself?",
)
_CRISIS_CANDIDATE = Field(
    None,
    description="True only when they're really in distress or may hurt themselves; false "
    "for a figure of speech.",
)


class _Reads:
    def reading(self) -> dict:
        """The reading fields the model gave (those not None)."""
        return {k: getattr(self, k) for k in READING_FIELDS if getattr(self, k) is not None}


class Plan(_Reads, BaseModel):
    """The quick first pass of a two-pass reply: how Kit feels, a gesture, his reading
    of the message (what it is, whether it's about him, whether a look is needed,
    whether Dan really said what's being kept, whether it's real distress), which of
    the things on his mind he's bringing up, and what to do. His words come next, in
    plain text."""

    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    gesture: Gesture = Field(description="The gesture that goes with what you'll say.")
    intent: Intent | None = _INTENT
    about_kit: bool | None = _ABOUT_KIT
    wants_pc_look: bool | None = _WANTS_PC_LOOK
    wants_camera_look: bool | None = _WANTS_CAMERA_LOOK
    said_it: bool | None = _SAID_IT
    crisis_candidate: bool | None = _CRISIS_CANDIDATE
    brought_up: list[int] = BROUGHT_UP
    action: Action

    @classmethod
    def default(cls) -> Plan:
        return cls(emotion="neutral", gesture="none", action=Action(kind="none"))


class ReadingPlan(_Reads, BaseModel):
    """A plan that also reads how Dan seems (``life.read_mood`` meaning). The reading
    comes before the action, so stopping early at a "none" action keeps it."""

    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    gesture: Gesture = Field(description="The gesture that goes with what you'll say.")
    dan_mood: DanMood
    about: About
    for_whom: ForWhom
    expected: Expected
    intent: Intent | None = _INTENT
    about_kit: bool | None = _ABOUT_KIT
    wants_pc_look: bool | None = _WANTS_PC_LOOK
    wants_camera_look: bool | None = _WANTS_CAMERA_LOOK
    said_it: bool | None = _SAID_IT
    crisis_candidate: bool | None = _CRISIS_CANDIDATE
    brought_up: list[int] = BROUGHT_UP
    action: Action


def plan_schema(read: bool = False) -> dict:
    return inline_refs((ReadingPlan if read else Plan).model_json_schema())


def parse_plan(text: str) -> Plan:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in MOOD_FIELDS}
        return Plan.model_validate(data)
    except (ValueError, ValidationError) as e:
        raise ReplyError(f"not a valid plan: {text[:200]!r}") from e


def mood_read(text: str) -> dict[str, str] | None:
    """How Dan seems, from a plan or a cloud reply's JSON: its dan_mood, about,
    for_whom and expected, or None if there's no reading in it."""
    found = {k: v for k, v in _MOOD_FIELD.findall(text) if v in MOOD_FIELDS[k]}
    return found if "dan_mood" in found else None


_PLAN_FIELD = re.compile(r'"(emotion|gesture|kind)"\s*:\s*"([a-z_]+)"')
_BROUGHT_UP = re.compile(r'"brought_up"\s*:\s*\[([0-9,\s]*)\]')


def brought_up_in(text: str) -> list[int]:
    """The numbers in a plan's ``brought_up``, from its JSON so far."""
    found = _BROUGHT_UP.search(text)
    return [int(n) for n in found.group(1).split(",") if n.strip()] if found else []


_MOOD_FIELD = re.compile(r'"(dan_mood|about|for_whom|expected)"\s*:\s*"([a-z_]+)"')
_READING_FIELD = re.compile(
    r'"(intent)"\s*:\s*"([a-z_]+)"|'
    r'"(about_kit|wants_pc_look|wants_camera_look|said_it|crisis_candidate)"\s*:\s*(true|false)'
)


def reading_read(text: str) -> dict:
    """The reading fields (``MessageReading``) in a plan's or a cloud reply's JSON, as
    far as it's written: the intent if it's a known one, and the yes-or-no fields."""
    found: dict = {}
    for word, intent, flag, value in _READING_FIELD.findall(text):
        if word and intent in INTENTS:
            found[word] = intent
        elif flag:
            found[flag] = value == "true"
    return found


def early_plan(text: str, read: bool = False) -> Plan | None:
    """The plan from the start of its JSON, once it's plain the action is "none": the
    rest of the action would only be empty fields, so Kit can start talking now.
    With ``read``, the reading of Dan comes first, so it's in by then."""
    found = dict(_PLAN_FIELD.findall(text))
    if found.get("kind") != "none" or "emotion" not in found or "gesture" not in found:
        return None
    if read and mood_read(text) is None:
        return None
    try:
        return Plan(
            emotion=found["emotion"],
            gesture=found["gesture"],
            brought_up=brought_up_in(text),
            action=Action(kind="none"),
            **reading_read(text),
        )
    except ValidationError:
        return None


def inline_refs(schema: dict) -> dict:
    """The schema with every "$ref" replaced by its definition.

    Ollama's schema-to-grammar step is happiest with one self-contained schema.
    """
    defs = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def reply_schema() -> dict:
    """JSON schema handed to the local model to force its output format."""
    return inline_refs(Reply.model_json_schema())


class ReplyError(ValueError):
    """The model's output isn't a valid reply."""


def parse_reply(text: str) -> Reply:
    try:
        return Reply.model_validate_json(text)
    except ValidationError as e:
        raise ReplyError(f"not a valid reply: {e.errors()[0]['msg']}: {text[:200]!r}") from e


SPOKEN_LIMIT = 300


def parse_cloud_reply(text: str) -> Reply:
    """A cloud model's reply. Cloud models are asked for the same JSON as the local
    one but not forced into it, so this is forgiving: JSON wrapped in prose or a
    code fence, a half-written attempt before the real one (a web search can split
    the answer), or a made-up emotion or gesture still give a proper reply. Plain
    text becomes a reply too: a short answer is said, a long one is shown."""
    text = text.strip()
    for data in reversed(_json_objects(text)):
        reply = _lenient_reply(data)
        if reply is not None:
            return reply
    if len(text) <= SPOKEN_LIMIT:
        return Reply.plain(text)
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:SPOKEN_LIMIT]
    reply = Reply.plain(first)
    reply.detail = text
    return reply


_DECODER = json.JSONDecoder(strict=False)  # allow raw newlines inside strings


def _json_objects(text: str) -> list[dict]:
    """Every complete JSON object in ``text`` that looks like a reply, in order."""
    found, i = [], text.find("{")
    while i != -1:
        try:
            data, end = _DECODER.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(data, dict) and "segments" in data:
            found.append(data)
            i = text.find("{", end)
        else:
            i = text.find("{", i + 1)
    return found


def _lenient_reply(data: dict) -> Reply | None:
    """A reply from JSON that's nearly right, with unknown values set to defaults."""
    segments = []
    for seg in data.get("segments") or []:
        if isinstance(seg, dict) and str(seg.get("say", "")).strip():
            gesture = seg.get("gesture")
            segments.append(
                {"say": str(seg["say"]), "gesture": gesture if gesture in GESTURES else "none"}
            )
    if not segments:
        return None
    raw = data.get("action") if isinstance(data.get("action"), dict) else {}
    action = Action(kind="none").model_dump()
    for name in Action.model_fields:
        if name in raw:
            try:
                Action(**{**action, name: raw[name]})
            except ValidationError:
                continue
            action[name] = raw[name]
    emotion = data.get("emotion")
    detail = data.get("detail")
    try:
        return Reply(
            emotion=emotion if emotion in EMOTIONS else "neutral",
            segments=[Segment(**seg) for seg in segments[:6]],
            action=Action(**action),
            detail=detail if isinstance(detail, str) else "",
        )
    except ValidationError:
        return None


def without_plans(text: str) -> str:
    """``text`` without any whole JSON object in it that isn't a reply. Asked for his
    words, a small model sometimes writes its plan again first ({"emotion": ...,
    "gesture": ...}), and once one is in the chat it copies it every time."""
    kept, start, at = [], 0, text.find("{")
    while at != -1:
        try:
            data, end = _DECODER.raw_decode(text, at)
        except ValueError:
            at = text.find("{", at + 1)
            continue
        if isinstance(data, dict) and "segments" not in data:
            kept.append(text[start:at])
            start = end
        at = text.find("{", end)
    kept.append(text[start:])
    return _EMPTY_FENCE.sub("", "".join(kept)).strip()


_EMPTY_FENCE = re.compile(r"```(?:json)?\s*```")
_JSON_START = re.compile(r"(```\w*\s*)?\{")


_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class SayExtractor:
    """Pulls the text of every "say" field out of JSON as it streams in.

    Feed it chunks of the model's output; it returns any new spoken text, so
    the chat page can show (and later the voice can speak) the first words
    before the whole reply has arrived. Sentences from separate segments are
    joined with a space.

    ``segments`` lists the gesture of each segment whose words have begun, and
    ``words_done`` turns true once the words are over (a field after the segments,
    such as the action, has begun), so his voice needn't wait for written detail.
    """

    def __init__(self) -> None:
        self._in_string = False
        self._escape = ""
        self._string = ""
        self._last_key = ""
        self._capturing = False
        self._expect_value = False
        self._said_any = False
        self._pending_space = False
        self._high_surrogate = ""
        self._gesture = ""  # the gesture of the segment being read, once it's written
        self.segments: list[str] = []
        self.words_done = False

    @property
    def in_words(self) -> bool:
        """Is it partway through a segment's words (a "say" still being written)?"""
        return self._in_string and self._capturing

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if self._in_string:
                self._string_char(ch, out)
            elif ch == '"':
                self._in_string = True
                self._string = ""
                self._capturing = self._expect_value and self._last_key == "say"
                self._pending_space = self._capturing and self._said_any
                if self._capturing:
                    self.segments.append(self._gesture)
            elif ch == ":":
                self._expect_value = True
            elif ch in ",{}[]":
                self._expect_value = False
                if ch == "{":
                    self._gesture = ""  # a new segment: no gesture till it says one
        return "".join(out)

    def _string_char(self, ch: str, out: list[str]) -> None:
        if self._escape:
            self._escape += ch
            if self._escape[1] == "u":
                if len(self._escape) < 6:
                    return
                decoded = self._unicode(self._escape[2:])
            else:
                decoded = _ESCAPES.get(ch, ch)
            self._escape = ""
            if decoded:
                self._emit(decoded, out)
        elif ch == "\\":
            self._escape = ch
        elif ch == '"':
            self._in_string = False
            if self._capturing:
                self._capturing = False
            elif not self._expect_value:
                self._last_key = self._string
                if self._said_any and self._string not in ("say", "gesture"):
                    self.words_done = True
            elif self._last_key == "gesture":
                self._gesture = self._string
            self._expect_value = False
        else:
            self._emit(ch, out)

    def _unicode(self, hex4: str) -> str:
        """Decode one \\uXXXX escape; a surrogate pair waits for its second half.
        Malformed escapes are dropped rather than crashing the stream."""
        try:
            code = int(hex4, 16)
        except ValueError:
            self._high_surrogate = ""
            return ""
        if 0xD800 <= code <= 0xDBFF:
            self._high_surrogate = hex4
            return ""
        if 0xDC00 <= code <= 0xDFFF:
            high, self._high_surrogate = self._high_surrogate, ""
            if not high:
                return ""
            return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + (code - 0xDC00))
        self._high_surrogate = ""
        return chr(code)

    def _emit(self, ch: str, out: list[str]) -> None:
        if self._capturing:
            if self._pending_space:
                out.append(" ")
                self._pending_space = False
            out.append(ch)
            self._said_any = True
        else:
            self._string += ch


# Sounds his voice can make inside his words (``speech.sounds``), for the gestures
# that come with one: a chuckle on the punchline, a sigh, a gasp. Chatterbox Turbo
# makes them; other engines leave them out.
GESTURE_SOUNDS: dict[str, str] = {
    "laugh": "chuckle",
    "sigh": "sigh",
    "startle": "gasp",
    "double_take": "gasp",
}
_EMOTION = re.compile(r'"emotion"\s*:\s*"([a-z_]+)"')


class Sounds:
    """Which segments get a sound in his voice: one whose gesture comes with a sound,
    at most every other sentence (so no two in a row)."""

    def __init__(self, on: bool) -> None:
        self.on = on
        self._last = -2  # the segment that last had one

    def at(self, n: int, gesture: str) -> str:
        """The sound for segment ``n`` (from 0), or ""."""
        sound = GESTURE_SOUNDS.get(gesture, "") if self.on else ""
        if not sound or n - self._last < 2:
            return ""
        self._last = n
        return sound


class StreamedReply:
    """A reply in JSON (a cloud model's) read as it streams in, as chat events: how he
    feels as soon as it's written (so his voice speaks in that mood), his words as they
    come with a sound before a segment whose gesture has one (``sounds``), and
    ``spoken`` once the words are over, ahead of any written detail. A segment's
    gesture comes before its words (as the schema and prompt have it); one written
    after them is too late for a sound."""

    def __init__(self, source: str = "", sounds: bool = False) -> None:
        self.source = source
        self.raw = ""
        self.said = ""
        self.mood = ""
        self._extractor = SayExtractor()
        self._sounds = Sounds(sounds)
        self._segments = 0
        self._spoken = False
        self._words: list[list[str]] = []  # [gesture, words as written] per segment

    def feed(self, piece: str) -> list[dict]:
        self.raw += piece
        events: list[dict] = []
        if not self.mood and (found := _EMOTION.search(self.raw)) and found[1] in EMOTIONS:
            self.mood = found[1]
            if not self.said:  # his voice takes the mood before his first word
                events.append({"type": "mood", "emotion": self.mood})
        extractor = self._extractor
        for ch in piece:  # a character at a time, so a sound lands right before its words
            text = extractor.feed(ch)
            while self._segments < len(extractor.segments):
                sound = self._sounds.at(self._segments, extractor.segments[self._segments])
                self._segments += 1
                self._words.append([extractor.segments[-1], ""])
                if sound:
                    events.append({"type": "sound", "sound": sound})
            if text:
                self._words[-1][1] += text
            if text := self._release(final=not extractor.in_words):
                self.said += text
                if events and events[-1]["type"] == "say":
                    events[-1]["text"] += text
                else:
                    events.append(self._say(text))
        if extractor.words_done and self.said and not self._spoken:
            self._spoken = True
            events.append({"type": "spoken"})
        return events

    def _release(self, final: bool) -> str:
        """Words ready to hand out, with laughs only where he laughs
        (``said_laughs``). Partway through a segment the last word and what's before
        it (", hehe") wait, as does a stage direction still open ("*laugh"), until
        it's clear what they are. A segment that was only a laugh says nothing."""
        parts = []
        for n, (gesture, words) in enumerate(self._words):
            if n == len(self._words) - 1 and not final:
                cut = _LAST_WORD.search(words).start()
                ready = words[:cut]
                opener = max(ready.rfind("*") if ready.count("*") % 2 else -1, ready.rfind("("))
                if opener > ready.rfind(")") and len(words) - opener < STAGE_HELD:
                    cut = len(ready[:opener].rstrip())
                parts.append(said_laughs(gesture, words[:cut]))
            elif said := said_laughs(gesture, words).strip():
                parts.append((" " if parts else "") + said)
        clean = "".join(parts)
        if not clean.startswith(self.said):
            return ""  # tidying changed words already out; the rest waits for the reply
        return clean[len(self.said) :]

    def _say(self, text: str) -> dict:
        return {"type": "say", "text": text, **({"source": self.source} if self.source else {})}


_LAST_WORD = re.compile(r"[\s,]*\S*$")  # the word still being written, and its comma
STAGE_HELD = 40  # characters: a "(" or "*" open this long isn't a stage direction


def reply_events(reply: Reply, source: str = "", sounds: bool = False) -> list[dict]:
    """A whole reply as the chat events a streamed one gives: his mood, then each
    segment's words, with a sound before a segment whose gesture has one."""
    events: list[dict] = [{"type": "mood", "emotion": reply.emotion}]
    chosen = Sounds(sounds)
    said = [seg for seg in reply.segments if seg.say.strip()]
    for n, seg in enumerate(said):
        if sound := chosen.at(n, seg.gesture):
            events.append({"type": "sound", "sound": sound})
        text = (" " if n else "") + seg.say.strip()
        if events[-1]["type"] == "say":
            events[-1]["text"] += text
        else:
            events.append({"type": "say", "text": text, **({"source": source} if source else {})})
    return events


def voiced(reply: Reply, sounds: bool = False) -> str:
    """A reply's words as his voice says them, with any sounds in place
    ("[chuckle] Told you."), for a line said whole (a pipe-up)."""
    chosen = Sounds(sounds)
    parts = []
    for n, seg in enumerate(s for s in reply.segments if s.say.strip()):
        sound = chosen.at(n, seg.gesture)
        parts.append(f"[{sound}] {seg.say.strip()}" if sound else seg.say.strip())
    return " ".join(parts)


def reply_json(reply: Reply) -> str:
    return json.dumps(reply.model_dump(mode="json"))


_THINKING = re.compile(r"^\s*<think>.*?(</think>|$)", re.DOTALL)
_STAGE = re.compile(r"\*[^*\n]{1,80}\*")  # *grins*
_SENTENCE_END = re.compile(r"[.!?\u2026](?=\s)")
_BETWEEN_SENTENCES = re.compile(r"(?<=[.!?\u2026])\s+(?=\S)")
FIRST_LINE_MAX = 160  # a first "sentence" longer than this is let through as it is
# The opening held back to be judged is at least this many words: "You got a minute?"
# alone can't be told apart from a line he's said before.
JUDGED_WORDS = 6
MAX_SENTENCES = 3  # what's said: he talks in short bursts, and a small model rambles
MAX_WORDS = 30  # no new sentence is started after this many words
LONG_DETAIL = 40  # words: written detail this long is an explanation, worth showing
# Written detail worth showing: code, a list or steps, a table, a link or a path.
_WRITTEN = re.compile(
    r"```|`[^`\n]+`|https?://|^\s*(?:[-*\u2022]\s|\d+[.)]\s|step \d)|\|.*\||\w[\\/]\w",
    re.IGNORECASE | re.MULTILINE,
)


def _cap(text: str) -> str:
    """At most ``MAX_SENTENCES`` sentences, and none started after ``MAX_WORDS``
    words. A sentence is kept or dropped on what came before it, so as more streams
    in the cut only grows and the words handed out stay the start of the reply."""
    kept: list[str] = []
    words = 0
    for n, part in enumerate(_BETWEEN_SENTENCES.split(text)):
        if n >= MAX_SENTENCES or (n and words >= MAX_WORDS):
            break
        kept.append(part)
        words += len(part.split())
    return " ".join(kept)


def written(text: str) -> bool:
    """Is ``text`` something to read (code, a list or steps, a table, a link or path,
    several lines, or a proper explanation) rather than more talk? After a blank line
    a small model sometimes adds another line or two of chat, often an old one, which
    on screen looked like Kit answering himself."""
    text = text.strip()
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(text) and (
        len(lines) > 1 or len(text.split()) >= LONG_DETAIL or bool(_WRITTEN.search(text))
    )


class SpokenStream:
    """Kit's plain-text words as they stream in from the speaking pass.

    The opening is held back until it's whole sentences of at least
    ``JUDGED_WORDS`` words, so the brain can catch a line he's said before and ask
    again, and so a "Kit:" in front can be dropped. After that, words come out as
    they arrive, minus *stage directions*, up to three sentences. A blank line ends
    what's said: anything after it is written detail, shown but not spoken, if it's
    something to read (``written``); more chat after it is dropped. If the model
    answers in JSON anyway, nothing comes out until the end, when the words are read
    from it; JSON with no words in it (his plan again) is dropped, never said.
    """

    def __init__(self, name: str = "") -> None:
        self.raw = ""
        self.released = False
        self._given = ""  # spoken text already handed out
        self._prefix = (
            re.compile(rf"^\**\s*{re.escape(name)}\s*\**\s*:\s*\**\s*", re.I) if name else None
        )

    def feed(self, chunk: str) -> None:
        self.raw += chunk

    def _text(self) -> str:
        """What he wrote, without any thinking or a plan he wrote again."""
        return without_plans(_THINKING.sub("", self.raw))

    def in_json(self) -> bool:
        """Is he answering in JSON (or still writing a plan he wasn't asked for)?"""
        return bool(_JSON_START.match(self._text()))

    def wrote_json(self) -> bool:
        """Did any JSON turn up where his words should be?"""
        return "{" in _THINKING.sub("", self.raw)

    def _body(self) -> str:
        """What he wrote, without a "Kit:" or an opening quote in front."""
        text = self._text()
        if self._prefix is not None:
            text = self._prefix.sub("", text, count=1)
        return text.lstrip('"\u201c ')

    def _said(self) -> str:
        """What he wrote before any blank line (which ends what's said)."""
        return self._body().split("\n\n", 1)[0]

    def _spoken(self, final: bool, cap: bool = True) -> str:
        text = without_laughs(_STAGE.sub("", self._said()))
        if "*" in text:  # a stage direction still being written, or a stray star
            text = text.replace("*", "") if final else text[: text.index("*")]
        if "{" in text:  # JSON that's still being written, or broken: never words
            text = text[: text.index("{")]
        text = re.sub(r"\s+", " ", text)
        if cap:
            text = _cap(text)
        if final:
            return text.strip().rstrip('"\u201d').strip()
        text = text.rstrip()  # a space or newline may yet turn out to end what's said
        return text[:-1] if text.endswith(('"', "\u201d")) else text

    def first(self) -> str | None:
        """The opening once it's long enough to judge: whole sentences, at least
        ``JUDGED_WORDS`` words of them (None until then, and in JSON)."""
        if self.in_json():
            return None
        text = self._spoken(final=False)
        for end in _SENTENCE_END.finditer(text):
            opening = text[: end.end()].strip()
            if len(opening.split()) >= JUDGED_WORDS:
                return opening
        if len(text) > FIRST_LINE_MAX or "\n\n" in self.raw:
            return text.strip()
        return None

    def release(self) -> None:
        self.released = True

    def finished(self) -> bool:
        """Is what he says complete, while the model is still writing? A blank line
        ends it (what follows is written detail, or dropped), and so does the limit on
        how much he says. His voice can then say the last sentence straight away
        rather than wait for the rest, which took a couple of seconds."""
        if self.in_json():
            return False
        if "\n\n" in self._body():
            return bool(self._spoken(final=True))
        whole = self._spoken(final=False, cap=False)
        return _cap(whole) != whole

    def take(self) -> str:
        """Spoken text that's ready and hasn't been handed out yet."""
        if not self.released or self.in_json():
            return ""
        return self._hand_out(self._spoken(final=False))

    def end(self) -> str:
        """Whatever's left to hand out, now the stream has finished."""
        self.released = True
        return self._hand_out(self.result()[0])

    def _hand_out(self, spoken: str) -> str:
        if not spoken.startswith(self._given):
            return ""  # the cleaned text changed under us; the final reply has it all
        new, self._given = spoken[len(self._given) :], spoken
        return new

    def result(self) -> tuple[str, str]:
        """(what was said, written detail)."""
        if self.in_json():
            # Words in reply JSON count. Any other JSON is nothing said: read out as
            # text, it showed in the chat as {"emotion": ...}.
            for data in reversed(_json_objects(self._text())):
                reply = _lenient_reply(data)
                if reply is not None:
                    return _cap(reply.text), reply.detail if written(reply.detail) else ""
            return "", ""
        spoken = self._spoken(final=True)
        rest = self._text().split("\n\n", 1)
        detail = rest[1].strip() if len(rest) > 1 else ""
        if not spoken and detail:
            first, _, more = detail.partition("\n")
            spoken, detail = first.strip(), more.strip()
        return spoken, detail if written(detail) else ""


MAX_SEGMENTS = 6


def sentences(text: str) -> list[str]:
    """``text`` as sentences, at most ``MAX_SEGMENTS`` (the rest join the last)."""
    parts = [p for p in _BETWEEN_SENTENCES.split(text.strip()) if p]
    if len(parts) > MAX_SEGMENTS:
        parts = [*parts[: MAX_SEGMENTS - 1], " ".join(parts[MAX_SEGMENTS - 1 :])]
    return parts or [text.strip()]


def spoken_reply(plan: Plan, spoken: str, detail: str = "") -> Reply:
    """The reply a two-pass answer adds up to: a segment per sentence, the planned
    gesture with the first."""
    return Reply(
        emotion=plan.emotion,
        segments=[
            Segment(say=line, gesture=plan.gesture if n == 0 else "none")
            for n, line in enumerate(sentences(spoken))
        ],
        action=plan.action,
        detail=detail,
    )


def plan_json(plan: Plan) -> str:
    """The plan as the model wrote it, shown back to it before the speaking step: the
    reading fields it left out stay out."""
    return json.dumps(plan.model_dump(mode="json", exclude_none=True))
