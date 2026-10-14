"""What Kit remembers: the facts he's learned (add, edit, pin, forget), searching
everything he can recall, and his summaries of past days."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from kit.memory import CONVERSATION, DAYS, FACTS, SELF
from kit.notes import NOTES
from kit.routes.state import AUTH, State, item
from kit.things import THINGS

router = APIRouter()

NOW_PINNED = "A 'now' fact can't be pinned: it's how things are lately, and goes after two weeks."


class FactIn(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "other"
    pinned: bool = False


class FactEdit(BaseModel):
    text: str | None = None
    kind: str | None = None
    pinned: bool | None = None


@router.get("/api/memory/facts", dependencies=AUTH)
def facts(state: State) -> list[dict]:
    return [item(f) for f in reversed(state.memory.facts())]


@router.post("/api/memory/facts", dependencies=AUTH)
async def add_fact(state: State, body: FactIn) -> dict:
    owner = state.store.current().persona.owner
    if body.pinned and body.kind == "now":
        raise HTTPException(422, NOW_PINNED)
    learned = await state.brain.learner.learn(body.text, body.kind, owner)
    if body.pinned:
        state.memory.index.set_pinned(learned.item_id, True)
    return {"decision": learned.decision, "id": learned.item_id, "replaced": learned.replaced}


@router.patch("/api/memory/facts/{fact_id}", dependencies=AUTH)
async def edit_fact(state: State, fact_id: int, body: FactEdit) -> dict:
    memory = state.memory
    found = memory.index.get(fact_id)
    if found is None or found.source != FACTS or found.superseded_by:
        raise HTTPException(404, "no such current fact")
    kind = body.kind or found.kind
    if body.pinned and kind == "now":
        raise HTTPException(422, NOW_PINNED)
    if body.text is not None and body.text.strip() != found.text:
        fact_id = memory.replace_fact(fact_id, body.text.strip(), body.kind)
        await state.brain.recall.index_pending()
    elif body.kind is not None:
        memory.index.update(fact_id, kind=body.kind)
    if body.pinned is not None:
        memory.index.set_pinned(fact_id, body.pinned)
    if kind == "now":
        memory.index.set_pinned(fact_id, False)  # lately is never always
    return item(memory.index.get(fact_id))


@router.get("/api/memory/facts/{fact_id}/history", dependencies=AUTH)
def fact_history(state: State, fact_id: int) -> list[dict]:
    return [item(i) for i in state.memory.index.history(fact_id)]


@router.delete("/api/memory/facts/{fact_id}", dependencies=AUTH)
def forget(state: State, fact_id: int) -> dict:
    if not state.memory.forget(fact_id):
        raise HTTPException(404, "no such fact")
    return {"ok": True}


@router.get("/api/memory/search", dependencies=AUTH)
async def search(state: State, q: str, k: Annotated[int, Query(ge=1, le=100)] = 10) -> dict:
    recall = state.brain.recall
    hits = await recall.search(q, [FACTS, DAYS, CONVERSATION, THINGS, SELF, NOTES], min(k, 50))
    return {
        "words_only": recall.embed_problem is not None,
        "hits": [
            {**item(h.item), "similarity": h.similarity, "word_match": h.word_match} for h in hits
        ],
    }


@router.get("/api/memory/days", dependencies=AUTH)
def days(state: State) -> list[dict]:
    return [item(i) for i in reversed(state.memory.index.items(DAYS))]
