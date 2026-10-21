"""Asking the desk app to do something on Dan's PC: open a file, a folder, an app or
a site, bring a window forward, pause the music. Nothing listens on the PC, so a
command goes out the way everything else reaches the desk: as a ``desk_command``
life event the desk app is already long-polling for (kit.life). The desk app
claims it (so a command that waited too long, or that another PC took, never runs
late), does it if its own rules allow (kit.desk.commands), and says how it went.
The brain waits ``pc.command_timeout_s`` for that answer. See
docs/2 How Kit Works/Desk App.md."""

from __future__ import annotations

import asyncio
import itertools
import logging
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kit.body_registry import desk_id

if TYPE_CHECKING:
    from kit.life import Life
    from kit.pc_context import PcContext

log = logging.getLogger(__name__)

KINDS = ("open_path", "open_app", "open_url", "focus", "media", "show")
OFFLINE = "I can't reach your PC right now: the desk app isn't running there."
NO_ANSWER = "The desk app didn't answer in time, so it may not have happened."


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    detail: str


@dataclass
class _Pending:
    kind: str
    args: dict
    future: asyncio.Future
    claimed: bool = False


class DeskCommands:
    """The commands waiting for the desk app, by id."""

    def __init__(self, life: Life, pc: PcContext) -> None:
        self.life = life
        self.pc = pc
        self.pending: dict[str, _Pending] = {}
        self._ids = itertools.count(1)
        self.recent: list[dict] = []  # the last few, for /api/status

    async def send(self, kind: str, args: dict, timeout_s: float) -> CommandResult:
        """Ask the PC Dan's on to do ``kind``; the desk app's answer, or why there's none."""
        if kind not in KINDS:
            return CommandResult(False, f"There's no PC command called {kind}.")
        if not self.pc.online():
            return self._done(kind, args, CommandResult(False, OFFLINE))
        command_id = f"{next(self._ids)}-{secrets.token_hex(4)}"
        future = asyncio.get_running_loop().create_future()
        self.pending[command_id] = _Pending(kind, args, future)
        self.life.publish(
            {
                "type": "desk_command",
                "command": command_id,
                "kind": kind,
                "args": args,
                "to": desk_id(self.pc.host() or ""),
            }
        )
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout_s)
        except TimeoutError:
            result = CommandResult(False, NO_ANSWER)
        finally:
            self.pending.pop(command_id, None)
        return self._done(kind, args, result)

    def claim(self, command_id: str) -> dict | None:
        """The desk app taking a command: what to do, or None when it's gone (it
        timed out, or another PC claimed it), so it isn't done late or twice."""
        waiting = self.pending.get(command_id)
        if waiting is None or waiting.claimed or waiting.future.done():
            return None
        waiting.claimed = True
        return {"kind": waiting.kind, "args": waiting.args}

    def done(self, command_id: str, ok: bool, detail: str) -> bool:
        waiting = self.pending.get(command_id)
        if waiting is None or waiting.future.done():
            return False
        waiting.future.set_result(CommandResult(ok, detail[:500]))
        return True

    def _done(self, kind: str, args: dict, result: CommandResult) -> CommandResult:
        log.info("desk command %s %s: %s", kind, args, result.detail)
        line = {"kind": kind, "args": args, "ok": result.ok, "detail": result.detail}
        self.recent = [line, *self.recent[:9]]
        return result
