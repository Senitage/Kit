"""Kit's ears (kit.hearing beside the mic; kit.heard on the brain): the ears
checking in, what they heard, Kit's reply to it, talking over him, the "Let Kit
hear me" switch and the voices he knows."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from kit.heard import Utterance
from kit.known_faces import Enrolment
from kit.known_voices import KnownVoices
from kit.routes.eyes import EyesSwitch
from kit.routes.state import AUTH, SHARED_ONLY, AppState, State

router = APIRouter()


class EarsReport(BaseModel):
    """The ears checking in (kit.hearing), every few seconds."""

    mic: str = Field("desk", max_length=20)
    listening: bool = True


def _voices(state: AppState) -> KnownVoices:
    if state.voices is None:
        state.voices = KnownVoices(None)
    return state.voices


def hearing_paused(state: AppState) -> bool:
    return state.brain.hearing_paused or not state.store.current().hearing.enabled


def hearing_line(state: AppState) -> str:
    hearing = state.brain.hearing
    if not hearing.online():
        return "the ears haven't reported lately"
    return "switched off" if hearing_paused(state) else f"listening ({hearing.mic})"


@router.post("/api/hearing/report", dependencies=AUTH)
def ears_report(state: State, body: EarsReport) -> dict:
    """The ears checking in. The answer carries the switch, the ears' settings,
    which voices Kit knows, and his voice engine (the ears learn his own voice
    from it, so they can ignore it coming back from the speakers)."""
    state.brain.hearing.report(body.mic)
    s = state.store.current()
    return {
        "ok": True,
        "paused": hearing_paused(state),
        "settings": s.hearing.model_dump(),
        "voices_version": _voices(state).version,
        "speech": s.speech.engine if s.speech.enabled and state.speech is not None else "",
    }


@router.post("/api/hearing/heard", dependencies=AUTH)
async def ears_heard(state: State, body: Utterance) -> dict:
    """Something the ears heard, in words. Talk meant for Kit starts a reply at
    once ("turn": read it from /api/hearing/turns/{turn}); the rest is let go."""
    if hearing_paused(state):
        return {"heard": "ignore", "why": "his ears are switched off"}
    if body.who is not None and body.who not in _voices(state).people:
        body = body.model_copy(update={"who": None})  # a voice he's since forgotten
    return await state.brain.hear(body)


@router.get("/api/hearing/turns/{turn}", dependencies=AUTH)
async def heard_turn(state: State, turn: int) -> StreamingResponse:
    """Kit's reply to something he heard, as it's made: the same events as /api/chat."""
    turns = state.brain.heard_turns
    if turn not in turns:
        raise HTTPException(404, "no such heard turn (they're kept for the last 20)")

    async def events() -> AsyncIterator[str]:
        async for event in turns.stream(turn):
            yield json.dumps(event) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post("/api/hearing/hush", dependencies=AUTH)
def ears_hush(state: State) -> dict:
    """Someone is talking over Kit: his voice stops (a "hush" event for the bodies)."""
    on = state.store.current().hearing.barge_in and not hearing_paused(state)
    return {"hushed": on and state.brain.hush()}


@router.get("/api/hearing", dependencies=AUTH)
def ears_status(state: State) -> dict:
    """Whether Kit's ears are listening, and what he last made of something (never
    the words: talk that wasn't for him isn't kept)."""
    return {
        **state.brain.hearing.as_dict(),
        "paused": hearing_paused(state),
        "voices": _voices(state).names(),
    }


@router.post("/api/hearing/pause", dependencies=AUTH)
def ears_switch(state: State, body: EyesSwitch) -> dict:
    """The "Let Kit hear me" switch: paused ears let the mic go until it's on again."""
    state.brain.pause_hearing(body.paused)
    return {"paused": hearing_paused(state)}


# Voice prints are like faces: only Kit's own token reads or changes them.


@router.get("/api/hearing/voices", dependencies=SHARED_ONLY)
def known_voices(state: State) -> dict:
    """The people Kit's ears know (kit.known_voices): names and voice prints."""
    return _voices(state).as_dict()


@router.post("/api/hearing/voices", dependencies=SHARED_ONLY)
def enrol_voice(state: State, body: Enrolment) -> dict:
    """Voice prints of someone, from `kit hearing enrol NAME`."""
    try:
        name, count = _voices(state).add(body.name, body.embeddings)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"name": name, "count": count, "version": _voices(state).version}


@router.delete("/api/hearing/voices/{name}", dependencies=SHARED_ONLY)
def forget_voice(state: State, name: str) -> dict:
    """Forget someone's voice completely (`kit hearing forget NAME`)."""
    gone = _voices(state).forget(name)
    if gone is None:
        raise HTTPException(404, f"Kit's ears don't know anyone called {name}")
    return {"forgot": gone, "version": _voices(state).version}
