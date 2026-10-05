"""The shape of every reply Kit gives, and how it's read while it streams.

The local model is forced to answer with JSON matching ``Reply``, so it picks
words, an emotion and named gestures but never invents a motion. The body (the
on-screen helper now, the arm later) turns those names into movement.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
}

Emotion = Literal[tuple(EMOTIONS)]  # type: ignore[valid-type]
Gesture = Literal[tuple(GESTURES)]  # type: ignore[valid-type]


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    say: str = Field(description="One short sentence to say.")
    gesture: Gesture = Field(description="The gesture that goes with it.")


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["none", "ask_claude", "remember"] = Field(
        description="ask_claude hands a question to Claude; remember saves a fact about the "
        "owner for later; none does nothing."
    )
    text: str = Field(
        "",
        description="For ask_claude: the full question with the context Claude needs. "
        "For remember: the fact, as one short sentence.",
    )


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emotion: Emotion
    segments: list[Segment] = Field(min_length=1, max_length=6)
    action: Action

    @property
    def text(self) -> str:
        return " ".join(s.say.strip() for s in self.segments if s.say.strip())

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

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if self._in_string:
                self._string_char(ch, out)
            elif ch == '"':
                self._in_string = True
                self._string = ""
                self._capturing = self._expect_value and self._last_key == "say"
                if self._capturing and self._said_any:
                    out.append(" ")
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
                decoded = chr(int(self._escape[2:], 16))
            else:
                decoded = _ESCAPES.get(ch, ch)
            self._escape = ""
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

    def _emit(self, ch: str, out: list[str]) -> None:
        if self._capturing:
            out.append(ch)
            self._said_any = True
        else:
            self._string += ch


def reply_json(reply: Reply) -> str:
    return json.dumps(reply.model_dump(mode="json"))
