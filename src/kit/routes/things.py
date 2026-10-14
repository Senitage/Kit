"""The things register (kit.things): each person, vehicle, room, project or piece of
equipment Kit knows by name, the ones he suggests adding, and each one's history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kit.routes.state import AUTH, State

router = APIRouter()


class LinkIn(BaseModel):
    system: str
    target: str


class ThingIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "other"
    aliases: list[str] = []
    links: list[LinkIn] = []
    about: str = ""


class ThingEdit(BaseModel):
    name: str | None = None
    kind: str | None = None
    aliases: list[str] | None = None
    links: list[LinkIn] | None = None
    about: str | None = None


def _thing(state: State, thing_id: int) -> dict:
    thing = state.register.get(thing_id)
    if thing is None:
        raise HTTPException(404, "no such thing")
    return thing.as_dict()


@router.get("/api/things", dependencies=AUTH)
def things(state: State) -> list[dict]:
    return [t.as_dict() for t in sorted(state.register.all(), key=lambda t: t.name.lower())]


@router.get("/api/things/suggestions", dependencies=AUTH)
def thing_suggestions(state: State) -> list[dict]:
    return [t.as_dict() for t in state.register.suggestions()]


@router.post("/api/things", dependencies=AUTH)
async def add_thing(state: State, body: ThingIn) -> dict:
    links = [x.model_dump() for x in body.links]
    new_id = state.register.add(body.name, body.kind, body.aliases, links, body.about)
    await state.brain.recall.index_pending()
    return _thing(state, new_id)


@router.patch("/api/things/{thing_id}", dependencies=AUTH)
async def edit_thing(state: State, thing_id: int, body: ThingEdit) -> dict:
    links = None if body.links is None else [x.model_dump() for x in body.links]
    try:
        new_id = state.register.change(
            thing_id, body.name, body.kind, body.aliases, links, body.about
        )
    except KeyError:
        raise HTTPException(404, "no such thing") from None
    await state.brain.recall.index_pending()
    return _thing(state, new_id)


@router.post("/api/things/{thing_id}/confirm", dependencies=AUTH)
async def confirm_thing(state: State, thing_id: int) -> dict:
    new_id = state.register.confirm(thing_id)
    if new_id is None:
        raise HTTPException(404, "no such suggestion")
    await state.brain.recall.index_pending()
    return _thing(state, new_id)


@router.post("/api/things/{thing_id}/reject", dependencies=AUTH)
def reject_thing(state: State, thing_id: int) -> dict:
    if not state.register.reject(thing_id):
        raise HTTPException(404, "no such suggestion")
    return {"ok": True}


@router.get("/api/things/{thing_id}/history", dependencies=AUTH)
def thing_history(state: State, thing_id: int) -> list[dict]:
    return [t.as_dict() for t in state.register.history(thing_id)]


@router.delete("/api/things/{thing_id}", dependencies=AUTH)
def forget_thing(state: State, thing_id: int) -> dict:
    if not state.register.forget(thing_id):
        raise HTTPException(404, "no such thing")
    return {"ok": True}
