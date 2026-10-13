"""Kit's eyes (kit.eyes): their reports of who and what is in view, the faces they
know, and the "Let Kit see me" switch. The known faces take Kit's own token."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kit.known_faces import Enrolment
from kit.routes.state import AUTH, SHARED_ONLY, State
from kit.scene_context import SceneReport

router = APIRouter()


class EyesSwitch(BaseModel):
    paused: bool


def _eyes_paused(state: State) -> bool:
    return state.brain.eyes_paused or not state.store.current().eyes.enabled


@router.post("/api/eyes/scene", dependencies=AUTH)
def eyes_report(state: State, report: SceneReport) -> dict:
    """The eyes' report (kit.eyes): who and what is in view, what just happened.
    The answer carries the switch, whether Kit's asleep and the eyes' settings,
    so a running pair of eyes follows changes to any of them."""
    state.brain.saw(report)
    return {
        "ok": True,
        "paused": _eyes_paused(state),
        "asleep": state.brain.life.asleep,  # shut eyes let the camera and their models go
        "settings": state.store.current().eyes.model_dump(),
        "faces_version": state.faces.version,
    }


@router.get("/api/eyes/faces", dependencies=SHARED_ONLY)
def known_faces(state: State) -> dict:
    """The people Kit's eyes know (kit.known_faces): names and face numbers."""
    return state.faces.as_dict()


@router.post("/api/eyes/faces", dependencies=SHARED_ONLY)
def enrol_face(state: State, body: Enrolment) -> dict:
    """More looks at someone, from `kit eyes enrol NAME`."""
    try:
        name, count = state.faces.add(body.name, body.embeddings)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"name": name, "count": count, "version": state.faces.version}


@router.delete("/api/eyes/faces/{name}", dependencies=SHARED_ONLY)
def forget_face(state: State, name: str) -> dict:
    """Forget someone's face completely (`kit eyes forget NAME`)."""
    gone = state.faces.forget(name)
    if gone is None:
        raise HTTPException(404, f"Kit's eyes don't know anyone called {name}")
    return {"forgot": gone, "version": state.faces.version}


@router.get("/api/eyes/scene", dependencies=AUTH)
def eyes_scene(state: State) -> dict:
    """What Kit can see through his eyes, as Kit sees it."""
    owner = state.store.current().persona.owner
    return {**state.brain.scene.as_dict(owner), "paused": _eyes_paused(state)}


@router.post("/api/eyes/pause", dependencies=AUTH)
def eyes_switch(state: State, body: EyesSwitch) -> dict:
    """The "Let Kit see me" switch: paused eyes release the camera until it's on again."""
    state.brain.pause_eyes(body.paused)
    return {"paused": _eyes_paused(state)}
