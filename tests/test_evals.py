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
