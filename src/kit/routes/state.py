"""What every route shares: one ``AppState`` the app is built around, the token
checks, and the small helpers that shape answers (kit.server builds the app)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from importlib import resources
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from kit.body_registry import BodyRegistry
from kit.brain import Brain
from kit.devices import Devices
from kit.knowledge import Item
from kit.known_faces import KnownFaces
from kit.known_voices import KnownVoices
from kit.memory import Memory
from kit.settings import SettingsError
from kit.settings_store import SettingsStore
from kit.speech.service import SpeechService
from kit.things import Register


class Turn:
    """When the latest chat message came in, so the log can say how long Kit took to
    start writing, finish, and make his first sound."""

    def __init__(self) -> None:
        self.started = 0.0

    def since(self) -> float:
        return time.monotonic() - self.started if self.started else 0.0


@dataclass
class AppState:
    """Everything the routes work with, made once by ``create_app``."""

    store: SettingsStore
    memory: Memory
    brain: Brain
    token: str
    faces: KnownFaces
    devices: Devices
    registry: BodyRegistry
    speech: SpeechService | None = None
    voices: KnownVoices | None = None
    # When Dan's latest message came in, for the timing lines in the log.
    turn: Turn = field(default_factory=Turn)
    register: Register = field(init=False)

    def __post_init__(self) -> None:
        self.register = Register(self.memory)


async def app_state(request: Request) -> AppState:
    return request.app.state.kit


State = Annotated[AppState, Depends(app_state)]


def require_token(request: Request, authorization: Annotated[str, Header()] = "") -> str | None:
    """Kit's shared token, or a paired device's own (kit.devices). Returns the
    device's name, or None for the shared token."""
    state: AppState = request.app.state.kit
    given = authorization.removeprefix("Bearer ").strip()
    if secrets.compare_digest(given.encode(), state.token.encode()):
        return None
    device = state.devices.match(given)
    if device is None:
        raise HTTPException(401, "missing or wrong token; run `kit token` to see it")
    state.registry.seen(device.name)
    return device.name


Device = Annotated[str | None, Depends(require_token)]


def shared_only(device: str | None, what: str = "pair or unpair devices") -> None:
    if device is not None:
        raise HTTPException(403, f"only Kit's own token can {what}, not a paired device's")


def require_shared_token(device: Device) -> None:
    """Kit's own token only. A paired device's (a phone that leaves the house)
    can talk to Kit but not change his settings, read the faces or voices he
    knows or list his bodies and devices; see Privacy."""
    shared_only(device, "change settings, read known faces or voices or list devices")


AUTH = [Depends(require_token)]
SHARED_ONLY = [Depends(require_shared_token)]


def item(found: Item | None) -> dict:
    if found is None:
        return {}
    return {
        "id": found.id,
        "source": found.source,
        "kind": found.kind,
        "title": found.title,
        "text": found.text,
        "day": found.day,
        "created": found.created,
        "updated": found.updated,
        "pinned": found.pinned,
        "superseded_by": found.superseded_by,
        "ref": found.ref,
        "meta": found.meta,
    }


def page(name: str) -> str:
    return resources.files("kit").joinpath("web", name).read_text(encoding="utf-8")


def settings_error(e: SettingsError) -> HTTPException:
    lines = [line.strip() for line in str(e).splitlines()]
    return HTTPException(422, {"message": lines[0], "problems": [x for x in lines[1:] if x]})
