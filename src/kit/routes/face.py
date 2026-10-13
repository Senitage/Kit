"""Kit's face: the character sheet every app draws him from, and his 3D face page
and its files (kit.face.serve)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from kit.face import character as characters
from kit.face import serve as face_files
from kit.routes.state import AUTH, State

router = APIRouter()


@router.get("/api/face", dependencies=AUTH)
def face(state: State) -> dict:
    """The character sheet Kit is set to (face.character), so every app that draws
    him draws the same Kit."""
    return characters.preset(state.store.current().face.character).sheet


@router.get("/api/face/presets", dependencies=AUTH)
def face_presets(state: State) -> dict:
    """Every character Kit can be, and which one he is now."""
    return {
        "current": state.store.current().face.character,
        "presets": [{"id": n, "name": characters.preset(n).name} for n in characters.presets()],
    }


# Kit's 3D face page and its files. No token: it's a cartoon face, and the desk
# app, home_app and robots open it as a plain page (kit.face.serve).
def _face_file(data: bytes, name: str, cache: bool = False) -> Response:
    headers = {"Cache-Control": "max-age=86400" if cache else "no-cache"}
    return Response(data, media_type=face_files.content_type(name), headers=headers)


@router.get("/face/")
def face_page() -> Response:
    return _face_file(face_files.page_file("index.html"), "index.html")


@router.get("/face/{name}")
def face_page_file(name: str) -> Response:
    try:
        return _face_file(face_files.page_file(name), name)
    except face_files.FaceFileMissing as e:
        raise HTTPException(404, "no such face file") from e


@router.get("/face/vendor/{name}")
def face_vendor(name: str) -> Response:
    try:
        return _face_file(face_files.vendor_file(name), name, cache=True)
    except face_files.FaceFileMissing as e:
        raise HTTPException(404, "no such face file") from e


def _face_character(state: State, character: str) -> str:
    return character if character in characters.presets() else state.store.current().face.character


@router.get("/face/api/info")
def face_info(
    state: State, app_name: Annotated[str, Query(alias="app")] = "desk", character: str = ""
) -> dict:
    s = state.store.current()
    name = _face_character(state, character)
    return face_files.info(name, app_name, s.face.pack_folder or None)


@router.get("/face/api/version")
def face_version(
    state: State, app_name: Annotated[str, Query(alias="app")] = "desk", character: str = ""
) -> dict:
    s = state.store.current()
    name = _face_character(state, character)
    return {
        "character": name,
        "version": face_files.version(name, app_name, s.face.pack_folder or None),
    }


@router.get("/face/model/{character}/{file}")
def face_model(
    state: State,
    character: str,
    file: str,
    app_name: Annotated[str, Query(alias="app")] = "desk",
) -> Response:
    if character not in characters.presets():
        raise HTTPException(404, "no such character")
    try:
        data = face_files.asset(
            character, file, app_name, state.store.current().face.pack_folder or None
        )
    except face_files.FaceFileMissing as e:
        raise HTTPException(404, "no such face file") from e
    return _face_file(data, file)
