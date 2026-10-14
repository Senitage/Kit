"""Private results (kit.tools.private): a cloud model reads a local summary only."""

import asyncio

import pytest

from fakes import FakeAnthropic, FakeModel, collect, reply
from kit.local_model import LocalModelError
from kit.memory import Memory
from kit.tools import ToolResult
from kit.tools.private import MARK, NO_LOCAL, for_cloud
from tool_helpers import Clock, make, shopping_pack


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def test_a_result_that_isnt_private_passes_as_it_is():
    assert asyncio.run(for_cloud(ToolResult("plain"), "q", FakeModel())) == "plain"


def test_a_private_result_is_summarised_locally():
    model = FakeModel("Filament is on it.")
    out = asyncio.run(
        for_cloud(ToolResult("Milk, eggs, filament.", private=True), "filament?", model)
    )
    assert out == f"{MARK} Filament is on it."
    asked = (model.calls or model.speak_calls)[0]
    assert "Persona" not in asked[0]["content"] and "filament?" in asked[1]["content"]


def test_with_the_local_model_off_the_cloud_is_told_its_private():
    model = FakeModel(error="ollama is off")
    model.stream = _raise
    assert asyncio.run(for_cloud(ToolResult("secret", private=True), "q", model)) == NO_LOCAL


async def _raise(*args, **kwargs):
    raise LocalModelError("off")
    yield  # pragma: no cover


def test_no_private_text_reaches_the_cloud(memory):
    claude = FakeAnthropic(
        answer=["", reply("Filament's on the list.")], tool_calls=[[("show_list", {})]]
    )
    brain, model, _ = make(memory, "Filament: yes, it's there.", claude=claude)
    brain.tools.add(shopping_pack([], private=True))
    collect(brain.chat("Is filament on the shopping list?"))
    sent = str(claude.calls[1]["messages"])
    assert "Milk, eggs" not in sent and MARK in sent
    assert all("Milk" not in s.question for s in memory.spend_log())
