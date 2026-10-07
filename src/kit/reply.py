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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

FactKind = Literal[tuple(FACT_KINDS)]  # type: ignore[valid-type]
Emotion = Literal[tuple(EMOTIONS)]  # type: ignore[valid-type]
Gesture = Literal[tuple(GESTURES)]  # type: ignore[valid-type]
ThingKind = Literal[tuple(THING_KINDS)]  # type: ignore[valid-type]
LinkSystem = Literal[("none", *SYSTEMS)]  # type: ignore[valid-type]


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gesture: Gesture = Field(description="The gesture that goes with it.")
    say: str = Field(description="One short sentence to say.")


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
        "thing",
        "weather",
        "ask_cloud",
        "ask_expert",
    ] = Field(
        description="recall searches memory before answering; look_at_pc checks what's "
        "open and in focus on Dan's PC and how it's running; look_around reads everything "
        "the camera sees right now (who's at the desk, what they're doing, what's about); "
        "remember saves a fact; "
        "note writes a note into Dan's notes; read_note opens one of his notes and reads "
        "it before answering; "
        "thing notes a named thing and where it lives; weather gets the forecast before "
        "answering; ask_cloud hands the question to the "
        "cloud model; ask_expert hands it to the strongest model; none does nothing."
    )
    text: str = Field(
        "",
        description="For recall: what to search for. For remember: the fact, as one "
        "sentence that makes sense on its own later. For note: the note itself, in "
        "markdown. For read_note: the note's name or path. For ask_cloud and ask_expert: the "
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


class Plan(BaseModel):
    """The quick first pass of a two-pass reply: how Kit feels, a gesture, and what
    to do. His words come next, in plain text."""

    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    gesture: Gesture = Field(description="The gesture that goes with what you'll say.")
    action: Action

    @classmethod
    def default(cls) -> Plan:
        return cls(emotion="neutral", gesture="none", action=Action(kind="none"))


def plan_schema() -> dict:
    return inline_refs(Plan.model_json_schema())


def parse_plan(text: str) -> Plan:
    try:
        return Plan.model_validate_json(text)
    except ValidationError as e:
        raise ReplyError(f"not a valid plan: {e.errors()[0]['msg']}: {text[:200]!r}") from e


_PLAN_FIELD = re.compile(r'"(emotion|gesture|kind)"\s*:\s*"([a-z_]+)"')


def early_plan(text: str) -> Plan | None:
    """The plan from the start of its JSON, once it's plain the action is "none": the
    rest of the action would only be empty fields, so Kit can start talking now."""
    found = dict(_PLAN_FIELD.findall(text))
    if found.get("kind") != "none" or "emotion" not in found or "gesture" not in found:
        return None
    try:
        return Plan(emotion=found["emotion"], gesture=found["gesture"], action=Action(kind="none"))
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
            elif ch == ":":
                self._expect_value = True
            elif ch in ",{}[]":
                self._expect_value = False
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

    def _spoken(self, final: bool) -> str:
        text = self._text()
        if self._prefix is not None:
            text = self._prefix.sub("", text, count=1)
        text = text.lstrip('"\u201c ').split("\n\n", 1)[0]
        text = _STAGE.sub("", text)
        if "*" in text:  # a stage direction still being written, or a stray star
            text = text.replace("*", "") if final else text[: text.index("*")]
        if "{" in text:  # JSON that's still being written, or broken: never words
            text = text[: text.index("{")]
        text = _cap(re.sub(r"\s+", " ", text))
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
    return json.dumps(plan.model_dump(mode="json"))
