"""The desk app's reports of Dan's PC (kit.pc_context), and what Kit makes of them."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kit.pc_context import Snapshot
from kit.routes.state import AUTH, State

router = APIRouter()


@router.post("/api/pc/context", dependencies=AUTH)
def pc_report(state: State, snap: Snapshot) -> dict:
    """The desk app's report: open windows, focus, idle time and PC health."""
    brain = state.brain
    brain.pc.update(snap)
    brain.bodies.desk_report(snap.host)
    brain.life.on_report()
    return {"ok": True}


@router.get("/api/pc/context", dependencies=AUTH)
def pc_context(state: State) -> dict:
    """What Kit can see of Dan's PC, as Kit sees it."""
    return state.brain.pc.as_dict(state.store.current().persona.owner)


class CommandDone(BaseModel):
    ok: bool
    detail: str = Field("", max_length=2000)


@router.post("/api/desk/commands/{command_id}/claim", dependencies=AUTH)
async def claim_command(state: State, command_id: str) -> dict:
    """The desk app taking a ``desk_command`` (kit.desk_commands) before doing it;
    410 when it's no longer wanted, so it's never done late or twice."""
    command = state.brain.desk.claim(command_id)
    if command is None:
        raise HTTPException(410, "that command isn't waiting any more")
    return command


@router.post("/api/desk/commands/{command_id}/done", dependencies=AUTH)
async def command_done(state: State, command_id: str, body: CommandDone) -> dict:
    """How a command went on the PC, in words Kit can say."""
    if not state.brain.desk.done(command_id, body.ok, body.detail):
        raise HTTPException(404, "no command with that id is waiting")
    return {"ok": True}
