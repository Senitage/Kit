"""Talking to Kit: a message in, his reply streamed back as it's written, and the
conversation so far."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from kit import body as bodies
from kit.routes.state import AUTH, Device, State

log = logging.getLogger(__name__)

router = APIRouter()


class ChatIn(BaseModel):
    text: str
    # Where Dan is talking from (kit.channels): desk, voice, phone, web, home or terminal.
    channel: str = Field("web", max_length=20)
    # Which body it came through (kit.body_registry), if it said hello.
    body: str = Field("", max_length=40)
    # When it was written, if it waited to be sent (typed while Kit was out of reach).
    sent_at: datetime | None = None
    # Said out loud rather than typed (the phone's talk mode).
    spoken: bool = False
    # Who's talking, when it isn't Dan (kit.audience): a name, such as a visitor's.
    speaker: str | None = Field(None, max_length=50)


@router.post("/api/chat")
async def chat(state: State, body: ChatIn, device: Device) -> StreamingResponse:
    brain, turn = state.brain, state.turn
    came_through = device or body.body or None
    state.registry.used(came_through)

    async def events() -> AsyncIterator[str]:
        turn.started = time.monotonic()
        first_words = True
        moments = bodies.ChatMoments(brain.life, brain.room)  # the body feed acts it out
        try:
            async for event in brain.chat(
                body.text,
                body.channel,
                sent_at=body.sent_at,
                spoken=body.spoken,
                body=came_through,
                speaker=body.speaker,
            ):
                moments.see(event)
                if first_words and event.get("type") == "say" and event.get("text"):
                    first_words = False
                    log.info("turn: first words %.2f s after the message", turn.since())
                elif event.get("type") == "reply":
                    log.info("turn: reply done %.2f s after the message", turn.since())
                yield json.dumps(event) + "\n"
        finally:
            moments.done()

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post("/api/chat/new", dependencies=AUTH)
def new_chat(state: State) -> dict:
    state.memory.new_chat()
    return {"ok": True}


@router.get("/api/messages", dependencies=AUTH)
def messages(
    state: State, limit: int = 50, before: int | None = None, after: int | None = None
) -> list[dict]:
    """The current conversation; or, with ``before`` or ``after`` (a message id),
    a page of the whole history, for scrolling back and catching up."""
    limit = max(1, min(limit, 500))  # SQLite reads -1 as no limit at all
    if before is None and after is None:
        found = state.memory.recent(limit)
    else:
        found = state.memory.page(limit, before=before, after=after)
    return [
        {
            "id": m.id,
            "at": m.at,
            "role": m.role,
            "text": m.text,
            "source": m.source,
            "channel": m.channel,
            "reply": json.loads(m.reply_json) if m.reply_json else None,
            "meta": json.loads(m.meta_json) if m.meta_json else None,
        }
        for m in found
    ]
