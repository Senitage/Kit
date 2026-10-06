import asyncio
from datetime import datetime
from itertools import count

from fakes import FakeModel, reply
from kit.evals import PROMPTS, run_eval
from kit.settings import Settings


def test_there_are_fifty_prompts():
    assert len(PROMPTS) == 50 and len(set(PROMPTS)) == 50


def test_report_counts_valid_replies_and_first_word_time():
    model = FakeModel(reply("Fine."), "broken", reply("Also fine."))
    ticks = count()
    report = asyncio.run(
        run_eval(model, Settings(), ["a", "b", "c"], datetime(2026, 10, 5), lambda: next(ticks))
    )
    assert report.valid == 2
    assert not report.results[1].valid and report.results[1].error
    assert report.latency(0.5) is not None


def test_compare_asks_every_model_every_prompt(paths):
    from fakes import Clock, FakeAnthropic, make_cloud
    from kit.evals import compare_report, run_compare
    from kit.memory import Memory

    memory = Memory(paths.state_dir / "memory.db", Clock())
    claude = FakeAnthropic(answer=reply("Sunny.", text=""))
    cloud = make_cloud(memory, claude)
    ticks = count()
    results = asyncio.run(
        run_compare(
            cloud,
            Settings(),
            ["sonnet", "opus", "gpt-sol"],
            ["weather?", "price?"],
            datetime(2026, 10, 6),
            lambda: next(ticks),
        )
    )
    memory.close()
    assert [(r.prompt, r.model) for r in results][:3] == [
        ("weather?", "sonnet"),
        ("weather?", "opus"),
        ("weather?", "gpt-sol"),
    ]
    assert [c["model"] for c in claude.calls] == ["claude-sonnet-5-5", "claude-opus-5-5"] * 2
    assert results[0].ok and results[0].said == "Sunny." and results[0].cost_usd > 0
    assert not results[2].ok and "openai" in results[2].error  # no GPT adapter in this test
    report = compare_report(results, ["sonnet", "opus", "gpt-sol"])
    assert "**sonnet**: 2/2 answered" in report and "**gpt-sol**: 0/2" in report
    assert "## weather?" in report and "### opus" in report
