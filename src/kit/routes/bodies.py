"""Kit's bodies (kit.body_registry) and paired devices (kit.devices): a body's
hello, pairing and unpairing, and the list of both."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import kit
from kit.body_registry import API_VERSION, LIFE_EVENTS, Hello
from kit.devices import DeviceError
from kit.face import character as characters
from kit.routes.state import SHARED_ONLY, Device, State, shared_only

router = APIRouter()


class PairIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)  # what to call it, e.g. phone
    kind: str = Field("phone", max_length=20)


def features(voice_out: bool) -> dict[str, int]:
    """What this brain can do, each with a version; a body uses only these."""
    found = {
        "chat": 2,  # 2: body, sent_at and spoken on /api/chat
        "messages": 2,  # 2: ids, and paging with before and after
        "life": 1,
        "life_events": 1,
        "memory": 1,
        "things": 1,
        "settings": 1,
        "spend": 1,
        "face": 1,
        "pc_context": 1,
        "eyes": 1,
        "bodies": 1,
        "pairing": 1,
    }
    if voice_out:
        found["voice_out"] = 1
    return found


@router.post("/api/bodies/hello")
def body_hello(state: State, hello: Hello, device: Device) -> dict:
    """A body says what it is and what it can do; the brain answers with what it
    can do, so new features light up only where both sides know them."""
    store, registry = state.store, state.registry
    body = registry.hello(hello, device)
    name = store.current().face.character
    look = characters.preset(name).look(body.kind, styles=("glow", "model"))
    return {
        "api": API_VERSION,
        "kit": kit.__version__,
        "name": store.current().persona.name,
        "body": body.as_dict(registry.clock()),
        "features": features(state.speech is not None),
        "events": list(LIFE_EVENTS),
        "face": {"character": name, "style": look["style"], "page": f"/face/?app={body.kind}"},
        "unknown_abilities": list(body.unknown),
    }


@router.post("/api/devices/pair")
def pair_device(state: State, body: PairIn, device: Device) -> dict:
    """Pair a device from the device itself: the app is given Kit's address and
    token once, swaps the token for one of its own, and keeps only that. Pairing
    a name again replaces its old token."""
    shared_only(device)
    try:
        token = state.devices.pair(body.name, body.kind)
    except DeviceError as e:
        raise HTTPException(422, str(e)) from e
    return {"name": body.name, "kind": body.kind, "token": token}


@router.delete("/api/devices/{name}")
def unpair_device(state: State, name: str, device: Device) -> dict:
    """Unpair a device: its token stops working. A device may unpair itself."""
    if device is not None and device != name:
        shared_only(device)
    if not state.devices.forget(name):
        raise HTTPException(404, f"no paired device called {name}")
    state.registry.forget(name)
    return {"ok": True}


@router.get("/api/bodies", dependencies=SHARED_ONLY)
def bodies_list(state: State) -> dict:
    """Every body that's said hello since the brain started, and the paired devices."""
    return {
        "bodies": state.registry.listing(),
        "devices": [
            {"name": d.name, "kind": d.kind, "created": d.created} for d in state.devices.all()
        ],
    }
