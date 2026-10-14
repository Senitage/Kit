"""Asking first (kit.tools.confirm): a change waits for Dan's yes."""

from datetime import timedelta

import pytest

from fakes import FakeAnthropic, collect, reply
from kit.memory import Memory
from kit.settings import Settings
from kit.tools import ToolCall
from kit.tools.confirm import needs_yes
from tool_helpers import Clock, make, shopping_pack


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def asking(memory, ran, answers, calls, settings=None):
    claude = FakeAnthropic(answer=answers, tool_calls=calls)
    brain, _, _ = make(memory, claude=claude, settings=settings)
    brain.tools.add(shopping_pack(ran))
    return brain, claude


def test_a_change_is_held_and_the_model_told_to_ask(memory):
    ran = []
    brain, claude = asking(
        memory,
        ran,
        ["", reply("Want me to tick filament off the list?")],
        [[("tick_item", {"item": "filament"})]],
    )
    events = collect(brain.chat("I bought the filament, tick it off the shopping list"))
    assert ran == []
    confirm = next(e for e in events if e["type"] == "confirm")
    assert confirm["ask"] == "tick 'filament' off the list" and confirm["tool"] == "tick_item"
    told = claude.calls[1]["messages"][-1]["content"][0]["content"]
    assert "Not run yet" in told and "tick 'filament' off the list" in told
    assert brain.pending_tool.call.arguments == {"item": "filament"}


def test_yes_runs_it_and_he_says_what_happened(memory):
    ran = []
    brain, claude = asking(
        memory,
        ran,
        ["", reply("Tick filament off?"), reply("Done, it's off the list.")],
        [[("tick_item", {"item": "filament"})]],
    )
    collect(brain.chat("tick filament off the shopping list"))
    events = collect(brain.chat("yes"))
    assert ran == [("tick", "filament")] and brain.pending_tool is None
    assert any(e["type"] == "tool" and e["tool"] == "tick_item" for e in events)
    said_yes = claude.calls[-1]["messages"][-1]
    text = said_yes["content"] if isinstance(said_yes["content"], str) else str(said_yes["content"])
    assert "said yes" in text and "Ticked filament" in text
    assert memory.tool_calls()[0]["tool"] == "tick_item"


def test_no_drops_it(memory):
    ran = []
    brain, claude = asking(
        memory, ran, ["", reply("Tick it?")], [[("tick_item", {"item": "filament"})]]
    )
    collect(brain.chat("tick filament off the shopping list"))
    events = collect(brain.chat("no thanks"))
    assert ran == [] and brain.pending_tool is None
    assert "leave it" in "".join(e.get("text", "") for e in events if e["type"] == "say")
    assert len(claude.calls) == 2  # no model for the no


def test_anything_else_or_a_long_wait_lets_it_lapse(memory, clock):
    ran = []
    brain, _ = asking(
        memory,
        ran,
        ["", reply("Tick it?"), reply("Sure."), "", reply("Tick it?"), reply("Ok.")],
        [[("tick_item", {"item": "filament"})], [], [("tick_item", {"item": "filament"})]],
    )
    collect(brain.chat("tick filament off the shopping list"))
    collect(brain.chat("actually what time is it"))
    assert brain.pending_tool is None
    collect(brain.chat("tick filament off the shopping list"))
    clock.now += timedelta(minutes=11)
    collect(brain.chat("yes"))
    assert ran == []


def test_one_at_a_time(memory):
    ran = []
    brain, claude = asking(
        memory,
        ran,
        ["", reply("Which first?")],
        [[("tick_item", {"item": "filament"}), ("tick_item", {"item": "milk"})]],
    )
    collect(brain.chat("tick filament and milk off the shopping list"))
    results = claude.calls[1]["messages"][-1]["content"]
    assert "Not run yet" in results[0]["content"]
    assert "one thing at a time" in results[1]["content"]
    assert brain.pending_tool.call.arguments == {"item": "filament"}


def test_the_setting_makes_an_act_tool_ask(memory):
    pack = shopping_pack([])
    beep = next(t for t in pack.tools if t.name == "beep")
    assert not needs_yes(beep, pack, Settings())
    assert needs_yes(beep, pack, Settings.model_validate({"tools": {"confirm": ["beep"]}}))
    pack.confirm = ["beep"]
    assert needs_yes(beep, pack, Settings())


def test_an_ask_that_does_not_fit_falls_back_to_the_call_line():
    pack = shopping_pack([])
    tick = next(t for t in pack.tools if t.name == "tick_item")
    assert tick.asking(ToolCall("1", "tick_item", {})) == "tick_item()"
