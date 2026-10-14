"""``/api/tools`` and ``/api/tools/run``, and ``kit tools`` through them."""

import argparse

import httpx
import pytest
from fastapi.testclient import TestClient

from kit.cli import cmd_tools
from kit.credentials import api_token
from kit.memory import Memory
from kit.server import create_app
from kit.settings_store import SettingsStore
from tool_helpers import Clock, make, shopping_pack


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


@pytest.fixture
def app(paths, memory):
    paths.ensure()
    ran = []
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack(ran))
    token = api_token(paths)
    app = create_app(SettingsStore(paths), memory, brain, token, summarise_every_s=None)
    app.ran = ran
    return app


@pytest.fixture
def auth(paths):
    return {"Authorization": f"Bearer {api_token(paths)}"}


def test_the_routes_need_the_token(app):
    with TestClient(app) as client:
        assert client.get("/api/tools").status_code == 401
        assert client.post("/api/tools/run", json={"tool": "beep"}).status_code == 401


def test_the_packs_and_tools_with_their_effects(app, auth):
    with TestClient(app) as client:
        packs = client.get("/api/tools", headers=auth).json()["packs"]
    shopping = next(p for p in packs if p["name"] == "shopping")
    tick = next(t for t in shopping["tools"] if t["name"] == "tick_item")
    assert tick["effect"] == "change" and tick["asks_first"]
    assert next(p for p in packs if p["name"] == "core")["always"]


def test_a_change_runs_by_hand_only_with_yes(app, auth):
    with TestClient(app) as client:
        body = {"tool": "tick_item", "arguments": {"item": "milk"}}
        assert client.post("/api/tools/run", json=body, headers=auth).status_code == 409
        out = client.post("/api/tools/run", json={**body, "yes": True}, headers=auth).json()
        assert out == {"ok": True, "text": "Ticked milk.", "private": False}
        assert client.post("/api/tools/run", json={"tool": "x"}, headers=auth).status_code == 404
    assert app.ran == [("tick", "milk")]


def test_the_status_shows_what_loaded_and_whats_waiting(app, auth):
    with TestClient(app) as client:
        tools = client.get("/api/status", headers=auth).json()["tools"]
    assert tools["loaded"] == ["core"] and tools["pending"] is None


def test_kit_tools_talks_to_the_running_kit(app, paths, capsys):
    with TestClient(app) as client:

        def handler(request: httpx.Request) -> httpx.Response:
            r = client.request(
                request.method,
                request.url.path,
                content=request.content,
                headers=dict(request.headers),
            )
            return httpx.Response(r.status_code, content=r.content, headers=r.headers)

        transport = httpx.MockTransport(handler)
        args = argparse.Namespace(action="list", tool="", args="{}", yes=False)
        assert cmd_tools(paths, args, transport) == 0
        assert "tick_item" in capsys.readouterr().out
        args = argparse.Namespace(action="run", tool="tick_item", args='{"item": "x"}', yes=False)
        assert cmd_tools(paths, args, transport) == 1
        assert "pass --yes" in capsys.readouterr().out
