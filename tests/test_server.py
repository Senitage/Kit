import json

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, reply
from kit.brain import Brain
from kit.expert import Expert
from kit.memory import Memory
from kit.recall import Recall
from kit.server import create_app
from kit.settings_store import SettingsStore

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def setup(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    model = FakeModel(reply("Hi Dan.", "Ready."))
    recall = Recall(memory, FakeEmbedder(), store.current)
    expert = Expert(memory, lambda: "k", FakeAnthropic().factory)
    brain = Brain(store.current, memory, model, expert, recall)
    app = create_app(store, memory, brain, TOKEN, summarise_every_s=None)
    with TestClient(app) as client:
        yield client, store, model
    memory.close()


def test_pages_and_health_need_no_token(setup):
    client, _, _ = setup
    assert "<title>Kit</title>" in client.get("/").text
    assert "Kit settings" in client.get("/settings").text
    assert "What Kit remembers" in client.get("/memory").text
    assert client.get("/api/health").json()["name"] == "Kit"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_api_needs_the_token(setup, headers):
    client, _, _ = setup
    assert client.get("/api/settings", headers=headers).status_code == 401
    assert client.post("/api/chat", json={"text": "hi"}, headers=headers).status_code == 401


def test_chat_streams_ndjson(setup):
    client, _, _ = setup
    r = client.post("/api/chat", json={"text": "hi"}, headers=AUTH)
    assert r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines()]
    assert events[-1]["reply"]["segments"][0]["say"] == "Hi Dan."
    history = client.get("/api/messages", headers=AUTH).json()
    assert [m["role"] for m in history] == ["user", "kit"]


def test_settings_change_and_undo(setup):
    client, _, model = setup
    r = client.patch(
        "/api/settings",
        json={"persona": {"name": "Kip"}},
        headers={**AUTH, "X-Changed-By": "home_app"},
    )
    assert r.status_code == 200 and r.json()["settings"]["persona"]["name"] == "Kip"
    assert client.get("/api/settings/history", headers=AUTH).json()[0]["replaced_by"] == "home_app"
    client.post("/api/chat", json={"text": "hi"}, headers=AUTH)
    assert "You are Kip" in model.calls[-1][0]["content"]
    r = client.post("/api/settings/undo", headers=AUTH)
    assert r.json()["settings"]["persona"]["name"] == "Kit"


def test_bad_change_is_refused_clearly(setup):
    client, _, _ = setup
    r = client.patch("/api/settings", json={"brain": {"port": 0}}, headers=AUTH)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any("brain.port" in p for p in detail["problems"])


def test_undo_with_nothing_to_undo(setup):
    client, _, _ = setup
    assert client.post("/api/settings/undo", headers=AUTH).status_code == 422


def test_schema_and_status(setup, paths):
    client, _, _ = setup
    schema = client.get("/api/settings/schema", headers=AUTH).json()
    assert "persona" in schema["properties"]
    paths.settings_file.write_text("[persona\n", encoding="utf-8")
    status = client.get("/api/status", headers=AUTH).json()
    assert "not valid TOML" in status["settings_problem"]


def test_facts_and_spend(setup):
    client, _, _ = setup
    client.post("/api/chat", json={"text": "ask claude why"}, headers=AUTH)
    spend = client.get("/api/spend", headers=AUTH).json()
    assert spend["month_usd"] > 0 and spend["log"][0]["question"] == "ask claude why"
    assert client.get("/api/memory/facts", headers=AUTH).json() == []
    assert client.delete("/api/memory/facts/1", headers=AUTH).status_code == 404


def test_memory_api(setup):
    client, _, _ = setup
    r = client.post(
        "/api/memory/facts",
        json={"text": "Tax returns are in Documents/Tax.", "kind": "place"},
        headers=AUTH,
    )
    assert r.json()["decision"] == "new"
    fact_id = r.json()["id"]
    facts = client.get("/api/memory/facts", headers=AUTH).json()
    assert facts[0]["kind"] == "place" and not facts[0]["pinned"]

    edited = client.patch(
        f"/api/memory/facts/{fact_id}",
        json={"text": "Tax returns are in Documents/Finance/Tax.", "pinned": True},
        headers=AUTH,
    ).json()
    assert edited["id"] != fact_id and edited["pinned"]
    history = client.get(f"/api/memory/facts/{edited['id']}/history", headers=AUTH).json()
    assert [h["text"] for h in history][1] == "Tax returns are in Documents/Tax."
    assert client.patch(f"/api/memory/facts/{fact_id}", json={}, headers=AUTH).status_code == 404

    found = client.get("/api/memory/search", params={"q": "tax"}, headers=AUTH).json()
    assert found["hits"][0]["text"].endswith("Finance/Tax.") and not found["words_only"]
    assert client.get("/api/memory/days", headers=AUTH).json() == []
    assert client.delete(f"/api/memory/facts/{edited['id']}", headers=AUTH).json()["ok"]
    assert client.get("/api/status", headers=AUTH).json()["memory_facts"] == 0


def test_upkeep_backs_up_and_indexes(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    memory.add_fact("Rex is the dog.")
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, FakeModel(), Expert(memory, lambda: None), recall)
    app = create_app(store, memory, brain, TOKEN, summarise_every_s=3600, paths=paths)
    with TestClient(app):
        import time

        for _ in range(50):
            if list(paths.backups_dir.glob("memory-*.db")):
                break
            time.sleep(0.05)
    assert list(paths.backups_dir.glob("memory-*.db"))
    assert memory.index.missing_vectors("fake-embed") == []
    memory.close()
