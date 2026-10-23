"""Tools: the things Kit can do mid-answer, and the packs they come in.

A **tool** is one thing a model can ask for while it answers: search memory, look
at the PC, fetch the forecast, read a note. It has a name, a description (the whole
instruction the model gets for it), a JSON schema for its arguments, an **effect**
(``read`` looks and changes nothing; ``act`` does something; ``change`` alters
something of Dan's and always asks first) and the coroutine that runs it. A
**pack** groups the tools for one part of Kit's world (``core``, later ``files``,
``house``) with a one-line card. The **registry** holds the packs and runs a call.

The brain offers a cloud model the tools as the provider's native tool calls
(kit.cloud) and runs what it asks for in a loop (``tools.hops`` at most), handing
each result back until the model answers in words. Only the packs a message needs
are loaded (kit.tools.match), a ``change`` waits for Dan's yes (kit.tools.confirm)
and a private result reaches a cloud model only as a local summary
(kit.tools.private). The local model keeps its one
``action`` in the reply JSON (kit.reply); the brain turns a look-up action into the
same tool call, so one loop serves both. Tool definitions never go in the system
prompt: they ride in the request's tools field, and the prompt carries one line
per pack. See docs/2 How Kit Works/Tools and Packs.md.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from kit.settings import Settings

log = logging.getLogger(__name__)

Effect = Literal["read", "act", "change"]
EFFECTS: dict[str, str] = {
    "read": "looks something up; changes nothing",
    "act": "does something that's easily undone",
    "change": "alters something of the owner's, so it asks first",
}


@dataclass
class Context:
    """What there is to look at this turn, and what's been looked at already, so a
    tool is offered only where it has somewhere to look (kit.tools.core)."""

    pc: bool = False  # the desk app has reported
    pc_detail: bool = False  # the full PC picture is already in the prompt
    scene: bool = False  # his eyes have reported
    scene_detail: bool = False
    weather: bool = False  # there's a forecast source
    forecast: bool = False  # the forecast is already in the prompt
    notes: bool = False  # there's a notes vault
    note_done: bool = False  # a note request was carried out this turn already
    files: bool = False  # there's a folder of Dan's in the files index (kit.files)
    desk: bool = False  # a desk app is online to take commands (kit.desk_commands)
    activity: bool = False  # there are PC days or code projects kept (kit.activity)
    projects: bool = False  # there are code project folders (kit.projects)

    def looked(self, tool: str) -> None:
        """A look was taken this turn, so it isn't offered again."""
        if tool == "look_at_pc":
            self.pc_detail = True
        elif tool == "look_around":
            self.scene_detail = True
        elif tool == "weather":
            self.forecast = True
        elif tool == "read_note":
            self.note_done = True


@dataclass
class ToolResult:
    """What a tool gives back: ``text`` is what the model reads next; ``event`` goes
    to the chat (the desk shows it under his words, like ``recalled`` today);
    ``step`` is a line for a job's progress; ``private`` marks text that must not
    reach a cloud model whole."""

    text: str
    event: dict | None = None
    step: str = ""
    private: bool = False
    ok: bool = True


@dataclass
class ToolCall:
    """A model asking for a tool. ``id`` is the provider's call id, used to hand the
    result back to the right call; a legacy ``action`` call gets the tool's name."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def line(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items() if v not in ("", None))
        return f"{self.name}({args})"


Runner = Callable[[dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class Tool:
    """One tool. ``description`` and ``examples`` are the whole instruction the model
    gets, so they matter more than the code. ``offered`` decides per turn whether the
    model sees it (no camera, no look_around); None means always."""

    name: str
    description: str
    run: Runner
    parameters: dict[str, Any] = field(default_factory=dict)  # JSON schema properties
    required: list[str] = field(default_factory=list)
    effect: Effect = "read"
    examples: list[dict[str, Any]] = field(default_factory=list)
    offered: Callable[[], bool] | None = None
    # What to say while it runs, for the local model's speaking pass (kit.prompt).
    speak: str = ""
    # For a tool that asks first: what it will do, filled from the call's arguments,
    # as the end of "Ask whether to ..." ("tick '{item}' in {note}").
    ask: str = ""
    # For a tool that asks only sometimes (the garage, not the blinds; the aircon
    # once a day): whether this call asks, from its arguments.
    confirm_if: Callable[[dict[str, Any], Settings], bool] | None = None
    # For a tool that asks first: the change itself, shown with the question (a
    # note's diff). It may raise; the question is then asked without it.
    preview: Callable[[dict[str, Any]], str] | None = None
    # Shared parts of the schema its properties point to (``$ref``), as an app's MCP
    # server gives them (kit.tools.mcp).
    defs: dict[str, Any] = field(default_factory=dict)

    def asking(self, call: ToolCall) -> str:
        """What the tool will do, in words, for the question Kit asks first."""
        if self.ask:
            try:
                return self.ask.format(**call.arguments)
            except (KeyError, IndexError, ValueError):
                pass
        return call.line()

    def schema(self) -> dict[str, Any]:
        schema = {
            "type": "object",
            "properties": dict(self.parameters),
            "required": list(self.required),
            "additionalProperties": False,
        }
        if self.defs:
            schema["$defs"] = dict(self.defs)
        return schema

    def definition(self) -> dict[str, Any]:
        """The provider-neutral definition; each provider in kit.cloud reshapes it.
        Examples go into the description, which every provider reads."""
        text = self.description.strip()
        if self.examples:
            shown = "; ".join(json.dumps(e, ensure_ascii=False) for e in self.examples[:3])
            text += f" Example arguments: {shown}."
        return {"name": self.name, "description": text, "input_schema": self.schema()}


@dataclass
class EvalCase:
    """One question for ``kit eval tools``: the tool a good answer calls first (None:
    none at all) and the arguments it should carry. An argument matches when the
    call has it and its value contains the case's, ignoring case."""

    question: str
    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    pack: str = ""
    note: str = ""

    def matches(self, name: str | None, arguments: dict[str, Any]) -> bool:
        if name != self.tool:
            return False
        return all(
            key in arguments and str(want).lower() in str(arguments[key]).lower()
            for key, want in self.arguments.items()
        )


@dataclass
class Pack:
    """The tools for one part of Kit's world, and the one line the prompt gets. How a
    message loads it (kit.tools.match): ``always``, a whole word from ``words``, a
    register thing linked into one of ``systems``, or meaning close to one of
    ``questions``. ``confirm`` names tools that ask first though they only ``act``;
    ``cases`` are its questions for ``kit eval tools``; ``context`` gives a few lines
    about its corner of the world (how the notes vault is laid out), in the prompt
    only while the pack is loaded."""

    name: str
    card: str
    tools: list[Tool] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    always: bool = False
    confirm: list[str] = field(default_factory=list)
    cases: list[EvalCase] = field(default_factory=list)
    context: Callable[[], list[str]] | None = None

    def offered(self) -> list[Tool]:
        return [t for t in self.tools if t.offered is None or t.offered()]


class Registry:
    """Every pack Kit has, and how a call is run."""

    def __init__(self) -> None:
        self.packs: dict[str, Pack] = {}

    def add(self, pack: Pack) -> Pack:
        self.packs[pack.name] = pack
        return pack

    def names(self) -> list[str]:
        return list(self.packs)

    def tool_names(self, packs: list[str] | None = None) -> set[str]:
        """Every tool in ``packs`` (all packs when None), offered this turn or not."""
        chosen = (
            self.packs.values()
            if packs is None
            else [self.packs[p] for p in packs if p in self.packs]
        )
        return {tool.name for pack in chosen for tool in pack.tools}

    def get(self, name: str) -> Tool | None:
        for pack in self.packs.values():
            for tool in pack.tools:
                if tool.name == name:
                    return tool
        return None

    def pack_of(self, name: str) -> str:
        for pack in self.packs.values():
            if any(t.name == name for t in pack.tools):
                return pack.name
        return ""

    def offered(self, packs: list[str] | None = None) -> list[Tool]:
        """The tools to offer this turn, from ``packs`` (all packs when None)."""
        chosen = (
            self.packs.values()
            if packs is None
            else [self.packs[p] for p in packs if p in self.packs]
        )
        return [tool for pack in chosen for tool in pack.offered()]

    def cards(self, packs: list[str] | None = None) -> list[str]:
        chosen = (
            self.packs.values()
            if packs is None
            else [self.packs[p] for p in packs if p in self.packs]
        )
        return [f"{pack.name}: {pack.card}" for pack in chosen if pack.offered()]

    def context(self, packs: list[str] | None = None) -> list[str]:
        """The loaded packs' own lines for the prompt (``Pack.context``)."""
        chosen = (
            self.packs.values()
            if packs is None
            else [self.packs[p] for p in packs if p in self.packs]
        )
        lines: list[str] = []
        for pack in chosen:
            if pack.context is None or not pack.offered():
                continue
            try:
                lines += pack.context()
            except Exception:  # a pack's own lines never stop a turn
                log.exception("the %s pack's context failed", pack.name)
        return lines

    async def run(self, call: ToolCall) -> ToolResult:
        """Run one call. A tool that fails, or one Kit doesn't have, becomes a result
        the model can read and say sorry about, never an exception up the chat."""
        tool = self.get(call.name)
        if tool is None:
            return ToolResult(f"There is no tool called {call.name}.", ok=False)
        try:
            out = tool.run(dict(call.arguments))
            result = await out if inspect.isawaitable(out) else out
        except Exception as e:  # a tool's bug or an outside failure
            log.exception("the %s tool failed", call.name)
            return ToolResult(f"The {call.name} tool failed: {e}", ok=False)
        if not isinstance(result, ToolResult):
            result = ToolResult(str(result))
        return result


def definitions(tools: list[Tool]) -> list[dict[str, Any]]:
    return [t.definition() for t in tools]
