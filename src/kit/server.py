"""Kit's brain service: the chat and settings pages, and the API behind them.

Every /api route except /api/health needs the token from Kit's secrets folder
(`kit token`). Configurators such as home_app use the same API; Kit never
calls them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
from collections.abc import AsyncIterator
from importlib import resources
from typing import Annotated

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

import kit
from kit.brain import Brain
from kit.memory import Memory
from kit.settings import Settings, SettingsError
from kit.settings_store import SettingsStore

SUMMARY_INTERVAL_S = 3600


class ChatIn(BaseModel):
    text: str


def _page(name: str) -> str:
    return resources.files("kit").joinpath("web", name).read_text(encoding="utf-8")


def _settings_error(e: SettingsError) -> HTTPException:
    lines = [line.strip() for line in str(e).splitlines()]
    return HTTPException(422, {"message": lines[0], "problems": [x for x in lines[1:] if x]})


def create_app(
    store: SettingsStore,
    memory: Memory,
    brain: Brain,
    token: str,
    summarise_every_s: float | None = SUMMARY_INTERVAL_S,
) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if summarise_every_s:
            task = asyncio.create_task(_summarise_loop(brain, summarise_every_s))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Kit", version=kit.__version__, lifespan=lifespan)

    def require_token(authorization: Annotated[str, Header()] = "") -> None:
        given = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "missing or wrong token; run `kit token` to see it")

    auth = [Depends(require_token)]

    @app.get("/", response_class=HTMLResponse)
    def chat_page() -> str:
        return _page("chat.html")

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page() -> str:
        return _page("settings.html")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "name": store.current().persona.name, "version": kit.__version__}

    @app.get("/api/status", dependencies=auth)
    def status() -> dict:
        s = store.current()
        return {
            "name": s.persona.name,
            "version": kit.__version__,
            "settings_problem": store.problem,
            "local_model": s.ollama.model,
            "claude_model": s.claude.model,
            "claude_month_usd": round(memory.month_spend(), 4),
            "claude_cap_usd": s.claude.monthly_cap_usd,
        }

    @app.get("/api/settings", dependencies=auth)
    def get_settings() -> dict:
        return {"settings": store.current().model_dump(mode="json"), "problem": store.problem}

    @app.get("/api/settings/schema", dependencies=auth)
    def get_schema() -> dict:
        return Settings.model_json_schema()

    @app.patch("/api/settings", dependencies=auth)
    def patch_settings(
        patch: Annotated[dict, Body()], x_changed_by: Annotated[str, Header()] = "api"
    ) -> dict:
        try:
            settings = store.update(patch, x_changed_by)
        except SettingsError as e:
            raise _settings_error(e) from e
        return {"settings": settings.model_dump(mode="json"), "problem": store.problem}

    @app.get("/api/settings/history", dependencies=auth)
    def history() -> list[dict]:
        return [
            {"id": v.id, "saved_at": v.saved_at, "replaced_by": v.changed_by}
            for v in store.history()
        ]

    @app.post("/api/settings/undo", dependencies=auth)
    def undo() -> dict:
        try:
            settings = store.undo()
        except SettingsError as e:
            raise _settings_error(e) from e
        return {"settings": settings.model_dump(mode="json"), "problem": store.problem}

    @app.post("/api/chat", dependencies=auth)
    async def chat(body: ChatIn) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            async for event in brain.chat(body.text):
                yield json.dumps(event) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/messages", dependencies=auth)
    def messages(limit: int = 50) -> list[dict]:
        return [
            {
                "at": m.at,
                "role": m.role,
                "text": m.text,
                "source": m.source,
                "reply": json.loads(m.reply_json) if m.reply_json else None,
            }
            for m in memory.recent(min(limit, 500))
        ]

    @app.get("/api/memory/facts", dependencies=auth)
    def facts() -> list[dict]:
        return [{"id": f.id, "day": f.day, "text": f.text} for f in memory.facts()]

    @app.delete("/api/memory/facts/{fact_id}", dependencies=auth)
    def forget(fact_id: int) -> dict:
        if not memory.forget(fact_id):
            raise HTTPException(404, "no such fact")
        return {"ok": True}

    @app.get("/api/spend", dependencies=auth)
    def spend() -> dict:
        return {
            "month_usd": round(memory.month_spend(), 4),
            "cap_usd": store.current().claude.monthly_cap_usd,
            "log": [s.__dict__ for s in memory.spend_log()],
        }

    return app


async def _summarise_loop(brain: Brain, every_s: float) -> None:
    while True:
        with contextlib.suppress(Exception):
            await brain.summarise_past_days()
        await asyncio.sleep(every_s)
