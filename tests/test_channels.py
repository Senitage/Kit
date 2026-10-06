"""Kit knows where Dan is talking from, and answers to suit."""

import asyncio
import sqlite3

from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.channels import channel_line, known
from kit.memory import Memory
from kit.recall import Recall
from kit.server import create_app
from kit.settings_store import SettingsStore


def make(paths, *outputs):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    return brain, memory, model, store


def test_unknown_channels_count_as_the_chat_page():
    assert known("phone") == "phone"
    assert known("fax") == known(None) == "web"
    assert channel_line("voice", "Dan").startswith("Dan is talking to you out loud")


def test_each_message_says_where_it_came_from(paths):
    brain, memory, model, _ = make(paths, reply("Hi."), reply("Yep."), reply("Sure."))
    collect(brain.chat("hello", "phone"))
    assert "Dan is on their phone, probably away from the desk." in model.calls[0][0]["content"]
    collect(brain.chat("back now", "desk"))
    system = model.calls[1][0]["content"]
    assert "typing in the desk app on their PC" in system and "phone" not in system
    # Earlier turns from elsewhere are marked; ones from here aren't.
    assert model.calls[1][1] == {"role": "user", "content": "(from their phone) hello"}
    collect(brain.chat("and again", "desk"))
    assert model.calls[2][3] == {"role": "user", "content": "back now"}
    assert [m.channel for m in memory.recent(10) if m.role == "user"] == [
        "phone",
        "desk",
        "desk",
    ]
    memory.close()


def test_turns_running_at_once_keep_their_own_channel(paths):
    brain, memory, model, _ = make(paths)

    async def ask(text, channel):
        return [e async for e in brain.chat(text, channel)]

    async def both():
        await asyncio.gather(ask("one", "voice"), ask("two", None))

    asyncio.run(both())
    systems = {c[-1]["content"]: c[0]["content"] for c in model.calls}
    assert "out loud" in systems["one"] and "out loud" not in systems["two"]
    assert "chat page in a browser" in systems["two"]
    memory.close()


def test_api_takes_the_channel_and_lists_it(paths):
    brain, memory, _, store = make(paths, reply("Hi."))
    app = create_app(store, memory, brain, "t", summarise_every_s=None)
    auth = {"Authorization": "Bearer t"}
    with TestClient(app) as client:
        client.post("/api/chat", json={"text": "hi", "channel": "desk"}, headers=auth).read()
        listed = client.get("/api/messages", headers=auth).json()
    assert listed[0]["channel"] == "desk" and listed[1]["channel"] is None
    memory.close()


def test_old_memory_gets_the_channel_column(paths):
    paths.ensure()
    db = paths.state_dir / "memory.db"
    Memory(db, Clock()).close()
    with sqlite3.connect(db) as con:
        columns = [r[1] for r in con.execute("PRAGMA table_info(messages)")]
        assert "channel" in columns
