"""How Kit is: the open health check, his status, and what the cloud has cost (in
Australian dollars, at the day's prices and rate)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

import kit
from kit.routes.hearing import hearing_line
from kit.routes.state import AUTH, State

router = APIRouter()


@router.get("/api/health")
def health(state: State) -> dict:
    return {"ok": True, "name": state.store.current().persona.name, "version": kit.__version__}


@router.get("/api/status", dependencies=AUTH)
def status(state: State) -> dict:
    store, memory, brain = state.store, state.memory, state.brain
    s = store.current()
    return {
        "name": s.persona.name,
        "version": kit.__version__,
        "settings_problem": store.problem,
        "routing": s.routing.mode,
        "local_model": s.ollama.model,
        "work_model": s.profile("work").model,
        "expert_model": s.profile("expert").model,
        "cloud_month_aud": round(memory.month_spend(), 4),
        "cloud_cap_aud": s.cloud.monthly_cap_aud,
        "prices": brain.cloud.prices.table.line(),
        "working_on": brain.busy(),
        "face": s.face.character,
        "memory_facts": len(memory.facts()),
        "memory_items": memory.index.count(),
        "memory_search": "words only: " + brain.recall.embed_problem
        if brain.recall.embed_problem
        else "words and meaning",
        "pc": brain.pc.now_line(s.persona.owner) or "the desk app hasn't reported yet",
        "eyes": brain.scene.now_line(s.persona.owner) or "the eyes haven't reported yet",
        "eyes_paused": brain.eyes_paused,
        "hearing": hearing_line(state),
        "hearing_paused": brain.hearing_paused,
    }


@router.get("/api/spend", dependencies=AUTH)
def spend(state: State, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict:
    return {
        "month_aud": round(state.memory.month_spend(), 4),
        "cap_aud": state.store.current().cloud.monthly_cap_aud,
        "aud_per_usd": state.brain.cloud.prices.table.aud_per_usd,
        "prices": state.brain.cloud.prices.table.line(),
        "log": [s.__dict__ for s in state.memory.spend_log(limit)],
    }


@router.get("/api/spend/summary", dependencies=AUTH)
def spend_summary(state: State, days: Annotated[int, Query(ge=1, le=366)] = 30) -> dict:
    """Cloud spend per day and per model, for a chart (the home_app Kit page)."""
    return {
        **state.memory.spend_summary(days),
        "month_aud": round(state.memory.month_spend(), 4),
        "cap_aud": state.store.current().cloud.monthly_cap_aud,
    }
