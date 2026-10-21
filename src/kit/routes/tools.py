"""Kit's tools (kit.tools): every pack and tool with its effect, and running one
by hand (``kit tools run``) to try it. A tool that changes something of Dan's
runs from here only with ``yes`` set, since nobody is asked first."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kit.routes.state import AUTH, State
from kit.tools import ToolCall
from kit.tools.confirm import needs_yes
from kit.tools.match import allowed

router = APIRouter()


class RunIn(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}
    yes: bool = False


@router.get("/api/tools", dependencies=AUTH)
def tools(state: State) -> dict:
    brain, s = state.brain, state.store.current()
    enabled = set(allowed(brain.tools, s))
    return {
        "packs": [
            {
                "name": pack.name,
                "card": pack.card,
                "enabled": pack.name in enabled,
                "always": pack.always,
                "words": pack.words,
                "tools": [
                    {
                        "name": t.name,
                        "effect": t.effect,
                        "asks_first": needs_yes(t, pack, s),
                        "description": t.description,
                    }
                    for t in pack.tools
                ],
            }
            for pack in brain.tools.packs.values()
        ]
    }


@router.post("/api/tools/run", dependencies=AUTH)
async def run(state: State, body: RunIn) -> dict:
    brain, s = state.brain, state.store.current()
    tool = brain.tools.get(body.tool)
    if tool is None:
        raise HTTPException(404, f"there's no tool called {body.tool}")
    pack = brain.tools.packs.get(brain.tools.pack_of(body.tool))
    if needs_yes(tool, pack, s, body.arguments) and not body.yes:
        raise HTTPException(409, f"{body.tool} changes something of yours: pass --yes to run it")
    result = await brain.tools.run(ToolCall("by-hand", body.tool, body.arguments))
    state.memory.log_tool_call(
        None, body.tool, body.arguments, tool.effect, result.text, result.ok, "by hand"
    )
    return {"ok": result.ok, "text": result.text, "private": result.private}
