"""The desk app's reports of Dan's PC (kit.pc_context), and what Kit makes of them."""

from __future__ import annotations

from fastapi import APIRouter

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
