"""Kit's settings over the API: read them, change them, see and undo past changes.
Changing them takes Kit's own token, not a paired device's."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Header

from kit.routes.state import AUTH, SHARED_ONLY, State, settings_error
from kit.settings import Settings, SettingsError

router = APIRouter()


@router.get("/api/settings", dependencies=AUTH)
def get_settings(state: State) -> dict:
    store = state.store
    return {"settings": store.current().model_dump(mode="json"), "problem": store.problem}


@router.get("/api/settings/schema", dependencies=AUTH)
def get_schema() -> dict:
    return Settings.model_json_schema()


@router.patch("/api/settings", dependencies=SHARED_ONLY)
def patch_settings(
    state: State, patch: Annotated[dict, Body()], x_changed_by: Annotated[str, Header()] = "api"
) -> dict:
    try:
        settings = state.store.update(patch, x_changed_by)
    except SettingsError as e:
        raise settings_error(e) from e
    return {"settings": settings.model_dump(mode="json"), "problem": state.store.problem}


@router.get("/api/settings/history", dependencies=AUTH)
def history(state: State) -> list[dict]:
    return [
        {"id": v.id, "saved_at": v.saved_at, "replaced_by": v.changed_by}
        for v in state.store.history()
    ]


@router.post("/api/settings/undo", dependencies=SHARED_ONLY)
def undo(state: State) -> dict:
    try:
        settings = state.store.undo()
    except SettingsError as e:
        raise settings_error(e) from e
    return {"settings": settings.model_dump(mode="json"), "problem": state.store.problem}
