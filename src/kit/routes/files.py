"""Dan's folders (kit.files): what's indexed in each, adding, changing and removing
a root (the settings page's "Your files"), and syncing now. Every change writes the
same ``files.roots`` settings table that ``kit files`` and ``kit config`` do."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kit.files import RootError, add_root, change_root, remove_root
from kit.routes.state import AUTH, State
from kit.settings import SettingsError

log = logging.getLogger(__name__)

router = APIRouter()


class RootIn(BaseModel):
    name: str
    path: str
    private: bool = False
    ocr: bool = False


class RootChange(BaseModel):
    private: bool | None = None
    ocr: bool | None = None
    max_mb: int | None = Field(None, ge=1, le=2000)


class SyncIn(BaseModel):
    root: str | None = None
    full: bool = False


def _status(state: State) -> dict:
    s = state.store.current()
    files = state.brain.files
    return {
        "roots": files.status(),
        "running": files.running,
        "shares": s.nas.read_only_shares,  # one-tap choices for a new root
    }


def _start_sync(state: State, root: str | None = None, full: bool = False) -> bool:
    """Sync in the background (a first index can take a while); False if one's running."""
    files, recall = state.brain.files, state.brain.recall
    if files.running:
        return False
    files.running = True  # taken now, so a second tap doesn't start another

    async def go() -> None:
        try:
            report = await asyncio.to_thread(files.sync, full, root)
            log.info("files sync: %s", report.line())
            while await recall.index_pending(limit=5000):
                pass
        except Exception:
            log.exception("files sync failed")
        finally:
            files.running = False

    asyncio.get_running_loop().create_task(go())
    return True


def _settings_change(state: State, change, *args, **kw) -> None:
    try:
        change(state.store, *args, changed_by="settings-page", **kw)
    except RootError as e:
        raise HTTPException(400, str(e)) from e
    except SettingsError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/files", dependencies=AUTH)
def status(state: State) -> dict:
    return _status(state)


@router.post("/api/files/roots", dependencies=AUTH)
async def add(state: State, body: RootIn) -> dict:
    _settings_change(state, add_root, body.name, body.path, body.private, body.ocr)
    _start_sync(state, body.name)
    return _status(state)


@router.patch("/api/files/roots/{name}", dependencies=AUTH)
async def change(state: State, name: str, body: RootChange) -> dict:
    _settings_change(state, change_root, name, **body.model_dump(exclude_none=True))
    if body.private is not None:
        await asyncio.to_thread(state.brain.files.set_private, name, body.private)
    return _status(state)


@router.delete("/api/files/roots/{name}", dependencies=AUTH)
async def remove(state: State, name: str) -> dict:
    _settings_change(state, remove_root, name)
    dropped = await asyncio.to_thread(state.brain.files.drop_root, name)
    return {**_status(state), "dropped": dropped}


@router.post("/api/files/sync", dependencies=AUTH)
async def sync(state: State, body: SyncIn) -> dict:
    if body.root is not None and body.root not in state.store.current().files.roots:
        raise HTTPException(404, f"no root called {body.root}")
    started = _start_sync(state, body.root, body.full)
    return {**_status(state), "started": started}
