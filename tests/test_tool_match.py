"""Which packs a message loads (kit.tools.match): always, words, register links,
meaning, the limit and the allowed list."""

import asyncio

import pytest

from fakes import FakeEmbedder
from kit.memory import Memory
from kit.settings import Settings
from kit.things import Link
from kit.tools.match import has_words, match
from tool_helpers import Clock, house_pack, make, shopping_pack


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def loaded(brain, text, **tools):
    s = Settings.model_validate({"tools": tools}) if tools else brain.settings()
    return asyncio.run(match(text, brain.tools, brain.recall, brain.register, s))


def test_whole_words_only():
    assert has_words("What's on the shopping list?", ["list"])
    assert not has_words("He's listless", ["list"])
    assert has_words("Turn  ON the lamp", ["turn on"])
    assert has_words("what’s up", ["what's up"])


def test_a_plain_message_loads_only_core(memory):
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack([]))
    brain.tools.add(house_pack())
    assert loaded(brain, "Morning!") == ["core"]


def test_a_word_loads_its_pack_with_core_first(memory):
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack([]))
    brain.tools.add(house_pack())
    assert loaded(brain, "Add bread to the shopping list") == ["core", "shopping"]
    assert loaded(brain, "lamp and shopping please") == ["core", "house", "shopping"]


def test_a_register_link_loads_the_pack_for_that_system(memory):
    brain, _, _ = make(memory)
    brain.tools.add(house_pack())
    brain.register.add(
        "Study light", "equipment", ["desk light"], [Link("home_assistant", "light.study")]
    )
    assert loaded(brain, "Is the desk light still going?") == ["core", "house"]


def test_meaning_loads_a_close_pack(memory):
    embedder = FakeEmbedder(same={"groceries": "shops"})
    brain, _, _ = make(memory, embedder=embedder)
    brain.tools.add(shopping_pack([]))
    brain.tools.add(house_pack())
    assert loaded(brain, "what do we need from the groceries", match_similarity=0.5) == [
        "core",
        "shopping",
    ]
    assert loaded(brain, "tell me a joke about pumps", match_similarity=0.5) == ["core"]


def test_meaning_stops_at_max_packs_but_words_dont(memory):
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack([]))
    brain.tools.add(house_pack())
    text = "what do we need from the shops, and switch the lights on in the lounge"
    assert len(loaded(brain, text, match_similarity=0.1, max_packs=2)) == 2
    assert loaded(brain, "shopping and the lamp", max_packs=1) == ["core", "house", "shopping"]


def test_the_allowed_list_limits_what_ever_loads(memory):
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack([]))
    brain.tools.add(house_pack())
    assert loaded(brain, "shopping and the lamp", packs=["core", "house"]) == ["core", "house"]


def test_the_turn_offers_only_loaded_tools(memory):
    from fakes import FakeAnthropic, collect, reply

    claude = FakeAnthropic(answer=reply("Morning."))
    brain, _, _ = make(memory, claude=claude)
    brain.tools.add(shopping_pack([]))
    collect(brain.chat("Morning!"))
    names = [t["name"] for t in claude.calls[0]["tools"] if "input_schema" in t]
    assert "show_list" not in names and brain.loaded_packs == ["core"]
    system = claude.calls[0]["system"][0]["text"]
    assert "shopping:" not in system
    collect(brain.chat("What's on the shopping list?"))
    names = [t["name"] for t in claude.calls[1]["tools"] if "input_schema" in t]
    assert {"show_list", "tick_item", "beep"} <= set(names)
    assert "shopping: the shopping list" in claude.calls[1]["system"][0]["text"]


def test_a_call_to_a_tool_not_loaded_is_refused(memory):
    from fakes import FakeAnthropic, collect, reply

    ran = []
    claude = FakeAnthropic(answer=["", reply("Hm.")], tool_calls=[[("beep", {})]])
    brain, _, _ = make(memory, claude=claude)
    brain.tools.add(shopping_pack(ran))
    collect(brain.chat("Morning!"))
    assert ran == []
    assert "no tool called beep" in claude.calls[1]["messages"][-1]["content"][0]["content"]
