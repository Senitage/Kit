"""The shape of every reply Kit gives, and how it's read while it streams.

The local model is forced to answer with JSON matching ``Reply``, so it picks
words, an emotion and named gestures but never invents a motion. The body (the
on-screen helper now, the arm later) turns those names into movement.
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
    kind: Literal["none", "recall", "remember", "thing", "ask_cloud", "ask_expert"] = Field(
        description="recall searches memory before answering; remember saves a fact; "
        "thing notes a named thing and where it lives; ask_cloud hands the question to the "
        "cloud model; ask_expert hands it to the strongest model; none does nothing."
    )
    text: str = Field(
        "",
        description="For recall: what to search for. For remember: the fact, as one "
        "sentence that makes sense on its own later. For ask_cloud and ask_expert: the "
        "full question with the context it needs.",
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


FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
SPOKEN_LIMIT = 300


def parse_cloud_reply(text: str) -> Reply:
    """A cloud model's reply. Cloud models are asked for the same JSON as the local
    one but not forced into it, so plain text (or JSON wrapped in prose or a code
    fence) still becomes a reply: a short answer is said, a long one is shown."""
    text = text.strip()
    candidates = [FENCE.sub("", text).strip()]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return parse_reply(candidate)
        except ReplyError:
            continue
    if len(text) <= SPOKEN_LIMIT:
        return Reply.plain(text)
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:SPOKEN_LIMIT]
    reply = Reply.plain(first)
    reply.detail = text
    return reply


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
