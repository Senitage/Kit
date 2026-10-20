"""``kit eval tools`` offline: matching, offering and arguments, without a model."""

import asyncio

import pytest

from kit.evals import load_tool_cases, run_tool_eval, tool_cases
from kit.memory import Memory
from kit.tools import EvalCase
from tool_helpers import Clock, house_pack, make, shopping_pack


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def test_every_pack_case_passes_offline(memory):
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack([]))
    brain.tools.add(house_pack())
    cases = tool_cases(brain.tools)
    assert {c.pack for c in cases} == {"core", "files", "pc", "shopping", "house"}
    report = asyncio.run(run_tool_eval(brain, cases))
    assert report.passed, [(r.case.question, r.why) for r in report.results if not r.passed]


def test_a_question_that_needs_no_tool_fails_when_a_pack_loads(memory):
    brain, _, _ = make(memory)
    brain.tools.add(shopping_pack([]))
    report = asyncio.run(
        run_tool_eval(brain, [EvalCase("Morning!", None), EvalCase("what a list", None)])
    )
    assert [r.passed for r in report.results] == [True, False]
    assert "shopping" in report.results[1].why


def test_wrong_arguments_or_the_wrong_pack_fail(memory):
    brain, _, _ = make(memory)
    brain.tools.add(house_pack())
    cases = [
        EvalCase("Turn the lamp on", "lamp_on", {"colour": "red"}),
        EvalCase("Turn it on", "lamp_on", {"name": "lamp"}),
    ]
    report = asyncio.run(run_tool_eval(brain, cases))
    assert not report.passed and "no argument colour" in report.results[0].why
    assert "lamp_on wasn't offered" in report.results[1].why


def test_arguments_match_loosely():
    case = EvalCase("q", "weather", {"place": "richmond"})
    assert case.matches("weather", {"place": "Richmond, NSW"})
    assert not case.matches("weather", {})
    assert not case.matches("recall", {"place": "Richmond"})


def test_dans_own_cases_load_from_toml(tmp_path):
    f = tmp_path / "tool-questions.toml"
    f.write_text(
        '[[case]]\nquestion = "Rain Saturday?"\ntool = "weather"\npack = "core"\n'
        'arguments = { place = "" }\n\n[[case]]\nquestion = "Hi"\n',
        encoding="utf-8",
    )
    cases = load_tool_cases(f)
    assert cases[0] == EvalCase("Rain Saturday?", "weather", {"place": ""}, "core")
    assert cases[1].tool is None


def test_the_live_eval_stubs_every_tool(memory):
    from fakes import FakeAnthropic, reply

    ran = []
    claude = FakeAnthropic(answer=["", reply("Beeped.")], tool_calls=[[("beep", {})]])
    brain, _, _ = make(memory, claude=claude)
    pack = shopping_pack(ran)
    brain.tools.add(pack)
    real = {t.name: t.run for t in pack.tools}
    report = asyncio.run(
        run_tool_eval(brain, [EvalCase("beep the shopping printer", "beep")], live=True)
    )
    assert report.results[0].called == "beep" and report.passed and ran == []
    assert {t.name: t.run for t in pack.tools} == real
    assert report.results[0].cost_aud > 0
