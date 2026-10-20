"""Kit asking the desk app to do things on the PC (kit.desk_commands, the pc pack's
open tools and the claim and done routes)."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from kit.desk_commands import NO_ANSWER, OFFLINE, DeskCommands
from kit.files import FILES
from kit.memory import Memory
from kit.pc_context import Snapshot
from kit.server import create_app
from kit.settings import Settings
from kit.settings_store import SettingsStore
from kit.tools import ToolCall
from tool_helpers import Clock, make

AUTH = {"Authorization": "Bearer t"}


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def online(brain, host="DESK"):
    brain.pc.update(Snapshot.model_validate({"host": host, "focus": None}))


async def desk_answers(brain, ok=True, detail="", seen=None):
    """A desk app: waits for a desk_command, claims it and says how it went."""
    for _ in range(200):
        events = [e for e in brain.life.events_after(0) if e["type"] == "desk_command"]
        if events:
            event = events[-1]
            command = brain.desk.claim(event["command"])
            if seen is not None:
                seen.append((event, command))
            brain.desk.done(event["command"], ok, detail)
            return
        await asyncio.sleep(0.005)


def run_with_desk(brain, name, args, **answer):
    seen = []

    async def go():
        call = brain.tools.run(ToolCall("1", name, args))
        result, _ = await asyncio.gather(call, desk_answers(brain, seen=seen, **answer))
        return result

    brain.tool_context.desk = True
    return asyncio.run(go()), seen


def test_a_command_goes_to_the_pc_dan_is_on_and_waits_for_its_answer(memory):
    brain, _, _ = make(memory)
    online(brain)
    out, seen = run_with_desk(brain, "open_app", {"name": "excel"})
    event, command = seen[0]
    assert event["to"] == "desk:desk" and event["kind"] == "open_app"
    assert command == {"kind": "open_app", "args": {"name": "excel", "args": []}}
    assert out.ok and out.text.startswith("Done: opened excel")
    assert brain.desk.recent[0]["ok"] and brain.desk.pending == {}


def test_a_refusal_on_the_pc_comes_back_in_words(memory):
    brain, _, _ = make(memory)
    online(brain)
    out, _ = run_with_desk(brain, "open_path", {"path": "C:\\Windows"}, ok=False, detail="nope")
    assert not out.ok and out.text == "It didn't happen: nope"


def test_with_no_desk_app_nothing_is_sent(memory):
    brain, _, _ = make(memory)
    desk = DeskCommands(brain.life, brain.pc)
    result = asyncio.run(desk.send("media", {"action": "mute"}, 1))
    assert not result.ok and result.detail == OFFLINE
    assert not [e for e in brain.life.events_after(0) if e["type"] == "desk_command"]


def test_a_command_nobody_answers_times_out_and_cant_be_claimed_late(memory):
    brain, _, _ = make(memory)
    online(brain)
    result = asyncio.run(brain.desk.send("media", {"action": "mute"}, 0.01))
    assert not result.ok and result.detail == NO_ANSWER
    event = [e for e in brain.life.events_after(0) if e["type"] == "desk_command"][0]
    assert brain.desk.claim(event["command"]) is None
    assert not brain.desk.done(event["command"], True, "")
    assert asyncio.run(brain.desk.send("format_c", {}, 1)).ok is False


def test_a_command_is_claimed_once(memory):
    brain, _, _ = make(memory)
    online(brain)

    async def go():
        task = asyncio.ensure_future(brain.desk.send("media", {"action": "mute"}, 1))
        await asyncio.sleep(0)
        command_id = next(iter(brain.desk.pending))
        first, second = brain.desk.claim(command_id), brain.desk.claim(command_id)
        brain.desk.done(command_id, True, "")
        return first, second, await task

    first, second, result = asyncio.run(go())
    assert first is not None and second is None and result.ok


def test_the_routes_claim_and_finish_a_command(memory, paths):
    paths.ensure()
    brain, _, _ = make(memory)
    app = create_app(SettingsStore(paths), memory, brain, "t", summarise_every_s=None)
    with TestClient(app) as client:
        assert client.post("/api/desk/commands/9-x/claim", headers=AUTH).status_code == 410
        body = {"ok": True, "detail": ""}
        assert (
            client.post("/api/desk/commands/9-x/done", json=body, headers=AUTH).status_code == 404
        )


def test_open_document_opens_an_indexed_file_where_the_pc_sees_it(memory):
    s = Settings.model_validate(
        {
            "routing": {"mode": "cloud-only"},
            "files": {
                "roots": {"finance": {"path": "/srv/finance", "pc_path": "\\\\NAS\\finance"}}
            },
        }
    )
    brain, _, _ = make(memory, settings=s)
    online(brain)
    meta = {"root": "finance", "rel": "Rates/2025 notice.pdf", "page": 1, "chunk": 1}
    memory.index.add(
        FILES,
        "pdf",
        "Rates.",
        title="2025 notice.pdf",
        ref="finance:Rates/2025 notice.pdf",
        meta=meta,
    )
    out, seen = run_with_desk(
        brain, "open_document", {"ref": "[finance:Rates/2025 notice.pdf, page 1]"}
    )
    assert seen[0][1]["args"] == {"path": "\\\\NAS\\finance\\Rates\\2025 notice.pdf"}
    assert out.ok and "2025 notice.pdf" in out.step
    missing = asyncio.run(brain.tools.run(ToolCall("1", "open_document", {"ref": "finance:x.pdf"})))
    assert not missing.ok and "find_documents" in missing.text


def test_the_open_tools_are_offered_only_while_a_desk_app_reports(memory):
    brain, _, _ = make(memory)
    names = lambda: {t.name for t in brain.tools.offered(["pc"])}  # noqa: E731
    assert names() == set()
    brain.tool_context.desk = True
    assert {"open_path", "open_app", "open_url", "show", "focus", "media"} <= names()
    assert "open_project" not in names()  # no projects folder


def test_media_wants_a_known_action(memory):
    brain, _, _ = make(memory)
    brain.tool_context.desk = True
    out = asyncio.run(brain.tools.run(ToolCall("1", "media", {"action": "louder"})))
    assert not out.ok and "play_pause" in out.text
