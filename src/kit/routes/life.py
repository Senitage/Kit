"""Kit's inner life (kit.life, kit.notebook): his mood and drives, his notebook,
the events bodies hear (fidgets, pipe-ups), and buttons to make him think,
reflect or pipe up now."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from kit import body as bodies
from kit.brain import Brain
from kit.reply import Reply, voiced
from kit.routes.state import AUTH, State, item

router = APIRouter()


class QuirkIn(BaseModel):
    quirk: str = Field(min_length=1)


class VersionIn(BaseModel):
    id: int


async def pipe_up_now(brain: Brain, reason: str) -> dict | None:
    """Kit says something unprompted, and every body (desk app, arm) is told: the
    line, the line as his voice says it (``voice``, with any sounds) and whether to
    say it out loud (``aloud``: not when his eyes see nobody there to hear it)."""
    reply = None
    async for event in brain.pipe_up(reason):
        if event["type"] == "reply":
            reply = event
    if reply:
        sounds = brain.settings().speech.sounds
        brain.life.publish(
            {
                "type": "pipe_up",
                "reason": reason,
                "reply": reply["reply"],
                "message_id": reply["message_id"],
                "voice": voiced(Reply.model_validate(reply["reply"]), sounds) if sounds else "",
                "aloud": not brain.scene.nobody_here(),
                # The one body that says it out loud; the others only show it.
                "to": brain.voice_body(),
            }
        )
        return reply["reply"]
    return None


@router.get("/api/life", dependencies=AUTH)
def life(state: State) -> dict:
    """Kit's mood, feeling and drives, what he's thinking and wants to bring up, and
    whether he's been told to keep quiet."""
    brain = state.brain
    s = state.store.current().life
    thought = brain.notebook.latest_thought()
    return {
        **brain.life.state(),
        "thinking": thought.text if thought else None,
        "wants": [w.text for w in brain.notebook.open_wants() if w.kind == "want"],
        "later": [
            {"text": w.text, "after": w.meta.get("after")}
            for w in brain.notebook.unsaid_wants()
            if w.kind == "want" and not brain.notebook.due(w)
        ],
        "threads": [
            {"text": t.text, "after": t.meta.get("after"), "due": brain.notebook.due(t)}
            for t in brain.notebook.threads()
        ],
        "quirks": brain.quirks,
        "games_retired": brain.life.retired_games(),
        "mood_reading": brain.mood_reading(),
        "settings": s.model_dump(),
    }


@router.get("/api/life/notebook", dependencies=AUTH)
def notebook(state: State) -> dict:
    """Kit's own notebook: his self-sheet and its earlier versions, the weekly
    reviews, his quirks, wants, thoughts, opinions, moments and journal."""
    nb = state.brain.notebook
    sheet, dan = nb.sheet(), nb.dan()
    return {
        "sheet": item(sheet) if sheet else None,
        "sheet_history": [item(i) for i in nb.sheet_history()[1:]],
        "dan": item(dan) if dan else None,
        "dan_history": [item(i) for i in nb.dan_history()[1:]],
        "reviews": [item(i) for i in nb.reviews(3)],
        "quirks": state.brain.quirks,
        "retired_quirks": nb.retired_quirks(),
        "wants": [
            {**item(w), "pressure": round(nb.pressure(w), 2), "due": nb.due(w)}
            for w in nb.unsaid_wants()
            if w.kind == "want"
        ],
        "threads": [{**item(t), "due": nb.due(t)} for t in nb.entries("thread", 60)],
        "bits": [item(i) for i in nb.entries("bit", 50)],
        "thoughts": [item(i) for i in nb.entries("thought", 40)],
        "opinions": [item(i) for i in nb.entries("opinion", 100)],
        "moments": [item(i) for i in nb.entries("moment", 100)],
        "journal": [item(i) for i in nb.entries("journal", 30)],
        "vetoes": nb.vetoes(),
    }


@router.delete("/api/life/notebook/{item_id}", dependencies=AUTH)
def forget_note(state: State, item_id: int) -> dict:
    brain = state.brain
    if not brain.notebook.forget(item_id):
        raise HTTPException(404, "no such entry in Kit's notebook")
    brain.life.wanting = brain.notebook.pressing()
    return {"ok": True}


@router.post("/api/life/sheet/restore", dependencies=AUTH)
def restore_sheet(state: State, body: VersionIn) -> dict:
    """Go back to an earlier version of Kit's self-sheet. He's told it was undone."""
    owner = state.store.current().persona.owner
    new_id = state.brain.notebook.restore_sheet(body.id, owner)
    if new_id is None:
        raise HTTPException(404, "no such version of Kit's self-sheet")
    return item(state.memory.index.get(new_id))


def _quirks(state: State) -> dict:
    return {"quirks": state.brain.quirks, "retired_quirks": state.brain.notebook.retired_quirks()}


@router.post("/api/life/quirks/retire", dependencies=AUTH)
def retire_quirk(state: State, body: QuirkIn) -> dict:
    """Take a quirk away; Kit won't pick it up again."""
    if not state.brain.notebook.retire_quirk(body.quirk, state.store.current().persona.owner):
        raise HTTPException(404, "Kit doesn't have that quirk")
    return _quirks(state)


@router.post("/api/life/quirks/restore", dependencies=AUTH)
def restore_quirk(state: State, body: QuirkIn) -> dict:
    """Give a retired quirk back."""
    if not state.brain.notebook.restore_quirk(body.quirk, state.store.current().persona.owner):
        raise HTTPException(404, "that isn't one of Kit's retired quirks")
    return _quirks(state)


@router.post("/api/life/think", dependencies=AUTH)
async def think(state: State) -> dict:
    """Make Kit have a thought now, whatever his schedule says (for testing)."""
    thought = await state.brain.think(("asked", "A moment to yourself."))
    return {"thought": thought.as_dict() if thought else None}


@router.post("/api/life/reflect", dependencies=AUTH)
async def reflect(state: State) -> dict:
    """Make Kit reflect on today so far, now (for testing). Tonight's reflection
    replaces today's journal entry; earlier versions stay in its history."""
    brain = state.brain
    if state.store.current().life.reflect_with == "off":
        raise HTTPException(409, "Kit's reflection is off (life.reflect_with)")
    first = brain.notebook.sheet() is None and await brain.reflector.first_sheet()
    done = await brain.reflector.reflect_day(state.memory.today())
    if done is None:
        raise HTTPException(503, "no model could reflect just now; see logs/kit.log")
    await brain.recall.index_pending()
    return {**done.as_dict(), "first_sheet": first}


@router.get("/api/life/events", dependencies=AUTH)
async def life_events(
    state: State, after: int = 0, wait: Annotated[float, Query(ge=0, le=60)] = 25
) -> dict:
    """Fidgets and pipe-ups after event ``after``. Waits up to ``wait`` seconds for
    one, so the desk app (and later the arm) hears about them at once."""
    life = state.brain.life
    events = await life.wait_for_events(after, wait)
    found = {"events": events, "last": life.state()["last_event"]}
    if life.missed_since(after):
        found["resync"] = True  # older events are gone: re-read /api/life
    return found


@router.get("/api/body/feed", dependencies=AUTH, response_class=PlainTextResponse)
async def body_feed(
    state: State, after: int | None = None, wait: Annotated[float, Query(ge=0, le=60)] = 20
) -> str:
    """For a robot body (the Pod): Kit's face, sleep and liveliness now, then what
    happened after event ``after``, one plain line each (see kit.body). Without
    ``after`` (a body that's just started) it answers at once, with no old events."""
    life = state.brain.life
    events = [] if after is None else await life.wait_for_events(after, wait)
    return bodies.feed(life, events)


@router.post("/api/body/touch", dependencies=AUTH)
def body_touch(state: State) -> dict:
    """Dan patted a body's head."""
    bodies.touched(state.brain.life, state.store.current().persona.owner)
    return {"ok": True}


@router.post("/api/life/poke", dependencies=AUTH)
async def life_poke(state: State) -> dict:
    """Make Kit pipe up now, whatever his manners say (for testing)."""
    reply = await pipe_up_now(state.brain, "bored")
    return {"ok": reply is not None, "reply": reply}


@router.post("/api/life/snooze", dependencies=AUTH)
def snooze(
    state: State, minutes: Annotated[float, Body(embed=True, ge=0, le=24 * 60)] = 60
) -> dict:
    """Keep Kit from piping up for a while (0 lets him again)."""
    life = state.brain.life
    if minutes:
        life.snooze(minutes)
    else:
        life.wake()
    return life.state()
