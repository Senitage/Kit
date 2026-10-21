"""The tool loop (kit.tools): packs and the registry, the core pack, a cloud model
calling tools natively and the local model's action going through the same loop."""

import asyncio
import json

import pytest

from fakes import (
    Clock,
    FakeAnthropic,
    FakeEmbedder,
    FakeModel,
    FakeWeather,
    collect,
    make_cloud,
    reply,
)
from kit.brain import Brain
from kit.memory import Memory
from kit.pc_context import Snapshot, Window
from kit.recall import Recall
from kit.settings import Settings
from kit.tools import Context, Pack, Registry, Tool, ToolCall, ToolResult, definitions
from kit.tools.core import core_pack


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def make(memory, *outputs, claude=None, settings=None, weather=None):
    s = settings or Settings.model_validate(
        {"memory": {"min_similarity": 0.3}, "routing": {"mode": "cloud-only"}}
    )
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude), recall, weather=weather)
    return brain, model, claude


# --- the registry ------------------------------------------------------------


def echo_tool(**kw):
    async def run(args):
        return ToolResult(f"echo {args.get('text', '')}", step="echoed")

    return Tool("echo", "Says it back.", run, {"text": {"type": "string"}}, ["text"], **kw)


def test_a_tool_definition_is_provider_neutral_with_examples_in_the_description():
    tool = echo_tool(examples=[{"text": "hi"}])
    d = tool.definition()
    assert (
        d["name"] == "echo"
        and d["description"] == 'Says it back. Example arguments: {"text": "hi"}.'
    )
    assert d["input_schema"] == {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    assert definitions([tool]) == [d]


def test_the_registry_runs_a_call_and_survives_a_missing_or_broken_tool():
    async def broken(args):
        raise RuntimeError("no disk")

    reg = Registry()
    reg.add(Pack("test", "testing", [echo_tool(), Tool("broken", "Breaks.", broken)]))
    assert asyncio.run(reg.run(ToolCall("1", "echo", {"text": "hi"}))).text == "echo hi"
    missing = asyncio.run(reg.run(ToolCall("2", "nothing", {})))
    assert not missing.ok and "no tool called nothing" in missing.text
    failed = asyncio.run(reg.run(ToolCall("3", "broken", {})))
    assert not failed.ok and "no disk" in failed.text
    assert reg.pack_of("echo") == "test" and reg.pack_of("x") == ""


def test_a_tool_is_offered_only_when_there_is_somewhere_to_look():
    reg = Registry()
    on = {"yes": False}
    reg.add(Pack("p", "a pack", [echo_tool(offered=lambda: on["yes"])]))
    assert reg.offered() == [] and reg.cards() == []
    on["yes"] = True
    assert [t.name for t in reg.offered()] == ["echo"] and reg.cards() == ["p: a pack"]
    assert reg.offered(["nope"]) == []


def test_a_call_line_shows_its_arguments():
    assert ToolCall("1", "recall", {"query": "tax", "year": ""}).line() == "recall(query='tax')"


def test_the_context_marks_a_look_as_taken():
    ctx = Context(pc=True, scene=True, weather=True, notes=True)
    for name in ("look_at_pc", "look_around", "weather", "read_note"):
        ctx.looked(name)
    assert ctx.pc_detail and ctx.scene_detail and ctx.forecast and ctx.note_done


# --- the core pack -----------------------------------------------------------


def test_the_core_pack_offers_looks_only_where_there_is_something_to_see(memory):
    brain, _, _ = make(memory, weather=FakeWeather())
    names = lambda: sorted(t.name for t in brain.tools.offered(["core"]))  # noqa: E731
    brain.tool_context = Context()
    assert names() == ["recall"]
    brain.tool_context = Context(pc=True, scene=True, weather=True, notes=True)
    assert names() == ["look_around", "look_at_pc", "read_note", "recall", "weather"]
    brain.tool_context = Context(pc=True, pc_detail=True, weather=True, forecast=True)
    assert names() == ["recall"]


def test_the_core_tools_run(memory):
    memory.add_fact("Dan's tax returns are in Documents/Finance/Tax.", "place")
    brain, _, _ = make(memory, weather=FakeWeather())
    brain.pc.update(Snapshot(host="desk", focus=Window(app="Excel", title="Budget")))
    pack = core_pack(brain)
    run = lambda name, **args: asyncio.run(brain.tools.run(ToolCall("1", name, args)))  # noqa: E731
    found = run("recall", query="tax returns")
    assert "Documents/Finance/Tax" in found.text and found.event["found"] == 1
    assert "Excel" in run("look_at_pc").text
    forecast = run("weather", place="Broome")
    assert forecast.event == {"type": "weather", "place": "Broome"} and "Broome" in forecast.step
    assert brain._weather_at is not None
    assert {t.name for t in pack.tools} == {
        "recall",
        "look_at_pc",
        "look_around",
        "weather",
        "read_note",
    }


# --- the loop with a cloud model --------------------------------------------


def test_a_cloud_model_calls_a_tool_natively_then_answers(memory):
    memory.add_fact("Dan's tax returns are in Documents/Finance/Tax.", "place")
    claude = FakeAnthropic(
        answer=["", reply("They're in Documents/Finance/Tax.")],
        tool_calls=[[("recall", {"query": "tax returns"})]],
    )
    brain, model, _ = make(memory, claude=claude)
    events = collect(brain.chat("Where did I say my returns were?"))
    kinds = [e["type"] for e in events]
    assert model.calls == [] and len(claude.calls) == 2
    assert kinds.count("reply") == 1 and "tool_calls" in kinds and "recalled" in kinds
    assert next(e for e in events if e["type"] == "tool")["line"] == "recall(query='tax returns')"
    # The first request offered the core tools; the second carried the call and result.
    first, second = claude.calls
    ours = [t for t in first["tools"] if "input_schema" in t]  # besides Claude's web tools
    assert [t["name"] for t in ours] == ["recall"]
    assert ours[0]["input_schema"]["required"] == ["query"]
    call_turn, result_turn = second["messages"][-2], second["messages"][-1]
    assert call_turn["role"] == "assistant"
    assert [b.type for b in call_turn["content"]] == ["thinking", "tool_use"]
    assert result_turn["content"][0]["type"] == "tool_result"
    assert result_turn["content"][0]["tool_use_id"] == call_turn["content"][1].id
    assert "Documents/Finance/Tax" in result_turn["content"][0]["content"]
    # The prompt says there are tools, and no longer lists recall as an action.
    system = first["system"][0]["text"]
    assert "Tools: you have tools" in system and "- recall:" not in system
    # The chat shows one answer; the working step is kept aside, and the call is logged.
    assert [m.text for m in memory.recent(10)] == [
        "Where did I say my returns were?",
        "They're in Documents/Finance/Tax.",
    ]
    logged = memory.tool_calls()
    assert logged[0]["tool"] == "recall" and logged[0]["arguments"] == {"query": "tax returns"}
    assert logged[0]["effect"] == "read" and logged[0]["ok"] and logged[0]["role"] == "chat"


def test_words_said_before_a_tool_call_are_spoken(memory):
    claude = FakeAnthropic(
        answer=[reply("Let me think."), reply("Nothing on that.")],
        tool_calls=[[("recall", {"query": "cat"})]],
    )
    brain, _, _ = make(memory, claude=claude)
    events = collect(brain.chat("What's my cat called?"))
    said = "".join(e["text"] for e in events if e["type"] == "say")
    assert said == "Let me think.Nothing on that."
    assert [e["type"] for e in events].count("reply") == 2


def test_the_loop_stops_at_the_hop_limit(memory):
    s = Settings.model_validate({"routing": {"mode": "cloud-only"}, "tools": {"hops": 2}})
    claude = FakeAnthropic(
        answer="", tool_calls=[[("recall", {"query": f"q{i}"})] for i in range(9)]
    )
    brain, _, _ = make(memory, claude=claude, settings=s)
    events = collect(brain.chat("hunt"))
    assert len(claude.calls) == 4  # the first answer, two hops, then one answer in words
    assert [e["type"] for e in events].count("recalled") == 2
    assert "tools" not in claude.calls[-1] or not [
        t for t in claude.calls[-1]["tools"] if "input_schema" in t
    ]
    assert "No more tools this turn" in claude.calls[-1]["messages"][-1]["content"][0]["content"]


def test_the_same_call_twice_is_not_run_again(memory):
    claude = FakeAnthropic(
        answer=["", "", reply("Done.")],
        tool_calls=[[("recall", {"query": "x"})], [("recall", {"query": "x"})]],
    )
    brain, _, _ = make(memory, claude=claude)
    events = collect(brain.chat("again"))
    assert [e["type"] for e in events].count("recalled") == 1
    repeat = claude.calls[2]["messages"][-1]["content"][0]["content"]
    assert "already ran recall(query='x')" in repeat


def test_a_look_at_the_pc_is_offered_once_a_turn(memory):
    claude = FakeAnthropic(answer=["", reply("Excel's open.")], tool_calls=[[("look_at_pc", {})]])
    brain, _, _ = make(memory, claude=claude)
    brain.pc.update(Snapshot(host="desk", focus=Window(app="Excel", title="Budget")))
    collect(brain.chat("What am I running?"))
    first, second = claude.calls
    assert "look_at_pc" in [t["name"] for t in first["tools"]]
    assert "look_at_pc" not in [t["name"] for t in second["tools"]]


def test_an_unknown_tool_is_answered_not_crashed(memory):
    claude = FakeAnthropic(answer=["", reply("Sorry.")], tool_calls=[[("teleport", {"to": "x"})]])
    brain, _, _ = make(memory, claude=claude)
    events = collect(brain.chat("teleport"))
    assert [e["type"] for e in events].count("reply") == 1
    result = claude.calls[1]["messages"][-1]["content"][0]["content"]
    assert "no tool called teleport" in result
    assert not memory.tool_calls()[0]["ok"]


# --- the local model's action goes through the same loop --------------------


def test_the_local_model_action_runs_as_a_tool_call(memory):
    memory.add_fact("Dan's tax returns are in Documents/Finance/Tax.", "place")
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}})
    brain, model, claude = make(
        memory,
        reply("Let me think.", action="recall", text="tax returns"),
        reply("Documents/Finance/Tax."),
        settings=s,
    )
    events = collect(brain.chat("Where are my returns?"))
    assert claude.calls == [] and "recalled" in [e["type"] for e in events]
    assert next(e for e in events if e["type"] == "tool")["tool"] == "recall"
    second = model.calls[1]
    assert second[-2] == {"role": "assistant", "content": "Let me think."}
    assert "Documents/Finance/Tax" in second[-1]["content"]
    assert memory.tool_calls()[0]["role"] == "local"
    # The local model keeps its actions in the prompt: no tools paragraph for it.
    assert "- recall:" in model.calls[0][0]["content"]
    assert "Tools: you have tools" not in model.calls[0][0]["content"]


def test_the_status_lists_packs_and_recent_calls(memory, paths):
    from fastapi.testclient import TestClient

    from kit.server import create_app
    from kit.settings_store import SettingsStore

    paths.ensure()
    brain, _, _ = make(memory)
    memory.log_tool_call(None, "recall", {"query": "x"}, "read", "found 1")
    app = create_app(SettingsStore(paths), memory, brain, "t", summarise_every_s=None)
    with TestClient(app) as client:
        status = client.get("/api/status", headers={"Authorization": "Bearer t"}).json()
    assert status["tools"]["packs"] == ["core", "files", "notes", "pc"]
    assert status["tools"]["hops"] == 6
    assert status["tools"]["recent"][0]["tool"] == "recall"


def test_tool_calls_are_logged_short(memory):
    memory.log_tool_call(3, "recall", {"query": "x"}, "read", "a " * 500, True, "chat")
    row = memory.tool_calls()[0]
    assert row["message_id"] == 3 and len(row["result"]) <= 300
    assert json.loads(json.dumps(row))  # serialisable for the API
