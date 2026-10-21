"""Asking first. A tool whose effect is ``change`` (it alters something of Dan's: a
note, a file, a lock) never runs on the model's say-so. The loop holds the call,
tells the model to ask Dan in one short sentence, and the call waits on
``Brain.pending_tool``. Dan's next message decides: a yes runs it and Kit says what
happened, a no drops it, anything else (or ``tools.confirm_lapse_minutes``) lets it
lapse, like a note Kit offered to write. One call waits at a time. A pack's
``confirm`` list and the ``tools.confirm`` setting make an ``act`` tool ask too.
See docs/2 How Kit Works/Tools and Packs.md#Asking first."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kit.settings import Settings
    from kit.tools import Pack, Tool, ToolCall


def needs_yes(
    tool: Tool, pack: Pack | None, settings: Settings, arguments: dict | None = None
) -> bool:
    """Whether ``tool`` waits for Dan's yes before it runs. With the call's
    ``arguments``, a tool's own ``confirm_if`` can ask too (the garage, not the blinds)."""
    if (
        tool.effect == "change"
        or (pack is not None and tool.name in pack.confirm)
        or tool.name in settings.tools.confirm
    ):
        return True
    if arguments is None or tool.confirm_if is None:
        return False
    return tool.confirm_if(arguments, settings)


@dataclass
class Held:
    """A call waiting for Dan's yes: what it was, the question it came from (``said``),
    who asked for it and when Kit asked."""

    call: ToolCall
    pack: str
    said: str
    role: str
    message_id: int | None
    asked_at: datetime
    asking: str

    def lapsed(self, now: datetime, minutes: int) -> bool:
        return (now - self.asked_at).total_seconds() > minutes * 60


def ask_first(owner: str, asking: str) -> str:
    """What the model reads instead of a result, for a call that waits for a yes."""
    return (
        f"Not run yet: this needs {owner}'s yes. Ask them, in one short sentence, whether "
        f"to {asking}; then stop and wait for their answer."
    )


def one_at_a_time(first: str) -> str:
    return f"Not run: one thing at a time. Ask about {first} first, and wait for the answer."


def said_yes(owner: str, line: str) -> str:
    """The aside on the turn after a yes: the call ran, here's what it gave."""
    return (
        f"[{owner} said yes, so you just ran {line}; its result follows. Tell them what "
        f"happened in a sentence. It's done: don't run it again.]"
    )
