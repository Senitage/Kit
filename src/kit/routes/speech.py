"""Kit's voice (kit.speech): whether it's on, one sentence of his speech at a
time, streamed as it's made or sent as one WAV file, and the voice link a voice
program on another computer dials in to (kit.speech.link)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
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
    # False for a clip that won't be played in the room (the ears learning his voice).
    aloud: bool = True


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
    hearing = state.brain.hearing if body.aloud else None  # his voice, in the room
    if whole:
        headers["X-Audio-Ms"] = f"{said.audio_ms:.0f}"
        if hearing is not None:
            hearing.spoke(body.text, said.audio_ms / 1000)
        return Response(said.wav, media_type="audio/wav", headers=headers)
    headers["X-Sample-Rate"] = str(said.rate)
    pieces = said.pieces
    if hearing is not None:
        pieces = _heard_as_it_goes(hearing, body.text, pieces, said.rate)
    return StreamingResponse(
        iterate_in_threadpool(pieces),
        media_type=f"audio/L16; rate={said.rate}",
        headers=headers,
    )


def _heard_as_it_goes(hearing, text: str, pieces: Iterator[bytes], rate: int) -> Iterator[bytes]:
    """The pieces of a streamed sentence, telling his ears (kit.heard) how long he'll
    be talking as each one goes out, so they know his own voice coming back."""
    hearing.spoke(text, 0.0)
    for piece in pieces:
        hearing.spoke("", len(piece) / 2 / rate)  # 16-bit mono samples
        yield piece


HELLO_S = 10  # a voice program says hello this soon after connecting, or it's closed


@router.websocket("/api/speech/link")
async def speech_link(websocket: WebSocket) -> None:
    """The voice program on another computer (``kit voice``) dials in here with Kit's
    own token (a paired phone's won't do) and makes his remote engine's lines. The
    messages are in kit.speech.link. One program at a time: a new one replaces the
    old. When it goes, Kit speaks with ``speech.fallback`` at once."""
    state = websocket.app.state.kit
    given = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(given.encode(), state.token.encode()):
        await websocket.close(code=1008, reason="wrong token; run `kit token` on Kit's server")
        return
    speech = state.speech
    if speech is None:
        await websocket.close(code=1011, reason="this Kit has no voice")
        return
    await websocket.accept()
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), HELLO_S)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        with contextlib.suppress(Exception):
            await websocket.close(code=1002, reason="say hello first")
        return
    hello = hello if isinstance(hello, dict) else {}
    link = speech.link
    outbox: asyncio.Queue = asyncio.Queue()
    number = link.attach(asyncio.get_running_loop(), outbox, hello)
    log.info("voice link: %s connected", link.name)

    async def send() -> None:
        while (message := await outbox.get()) is not None:
            await websocket.send_text(json.dumps(message))
        await websocket.close(code=1000, reason="another voice program dialled in")

    sender = asyncio.create_task(send())
    if state.store.current().speech.enabled:
        await asyncio.to_thread(_offer, speech)  # it loads at once, not at the next check
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                link.received_sound(message["bytes"])
            elif message.get("text"):
                with contextlib.suppress(ValueError):
                    link.received(json.loads(message["text"]))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        link.detach(number)
        sender.cancel()
        log.info("voice link: %s went away", hello.get("name") or "the voice program")


def _offer(speech) -> None:
    with contextlib.suppress(SpeechError):
        speech.offer_link()
