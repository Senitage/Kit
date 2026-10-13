"""The chat, settings and memory pages. No token: the pages ask for it and send it
with every /api call they make."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from kit.routes.state import page

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def chat_page() -> str:
    return page("chat.html")


@router.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    return page("settings.html")


@router.get("/memory", response_class=HTMLResponse)
def memory_page() -> str:
    return page("memory.html")
