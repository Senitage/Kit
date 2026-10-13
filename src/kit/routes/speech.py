"""Kit's voice (kit.speech): whether it's on, and one sentence of his speech at a
time, streamed as it's made or sent as one WAV file."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from kit.routes.state import AUTH, State
from kit.speech.service import Loading, SpeechError, Stale

log = logging.getLogger(__name__)

router = APIRouter()


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    emotion: str = Field("neutral", max_length=20)
    # The opening of a reply, where an engine may add a sound (a sigh, a chuckle).
    first: bool = False
    # Numbers the reply this line is from, going up with each one the desk begins. Once
    # a higher number has been seen, lines from a lower one (a reply Dan interrupted)
    # are dropped with 410 instead of being made. Left out, every line is made.
    generation: int | None = Field(None, ge=0)


@router.get("/api/speech", dependencies=AUTH)
def speech_status(state: State) -> dict:
    if state.speech is None:
        return {"enabled": False, "available": False}
    return {"available": True, **state.speech.status()}


@router.post("/api/speech/say", dependencies=AUTH)
async def speech_say(state: State, body: SpeakIn, request: Request, wav: bool = False) -> Response:
    """One sentence of Kit's speech in the voice engine in use, sent in pieces as
    it's made: 16-bit mono samples (``audio/L16``) with the rate in
    ``X-Sample-Rate``, so the desk can start playing before the rest exists.
    With ``Accept: audio/wav`` or ``?wav=1`` the whole sentence comes as one WAV
    file instead (older desks, the command line). 503 while the engine is still
    loading (it loads in the background; ask again in a moment), 410 for a line
    from a reply that's been overtaken, which also cuts short a line under way."""
    speech = state.speech
    if speech is None or not state.store.current().speech.enabled:
        raise HTTPException(409, "speech is off; turn it on with `kit speech on`")
    whole = wav or "audio/wav" in request.headers.get("accept", "")
    args = (body.text, body.emotion, None, body.first)
    try:
        said = await asyncio.to_thread(
            speech.speak if whole else speech.stream,
            *args,
            generation=body.generation,
            wait=False,
        )
    except Loading as e:
        raise HTTPException(503, str(e), headers={"Retry-After": "1"}) from e
    except Stale as e:
        raise HTTPException(410, str(e)) from e
    except SpeechError as e:
        raise HTTPException(503, str(e)) from e
    if body.first:
        log.info(
            "turn: first sound made in %.2f s, %.2f s after the message",
            said.synth_ms / 1000,
            state.turn.since(),
        )
    headers = {"X-Synth-Ms": f"{said.synth_ms:.0f}", "X-Engine": said.engine}
    if whole:
        headers["X-Audio-Ms"] = f"{said.audio_ms:.0f}"
        return Response(said.wav, media_type="audio/wav", headers=headers)
    headers["X-Sample-Rate"] = str(said.rate)
    return StreamingResponse(
        iterate_in_threadpool(said.pieces),
        media_type=f"audio/L16; rate={said.rate}",
        headers=headers,
    )
