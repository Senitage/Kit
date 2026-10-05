import asyncio

import anthropic
import httpx
import pytest

from fakes import Clock, FakeAnthropic
from kit.expert import FALLBACK_BETA, Expert, estimate_cost
from kit.memory import Memory
from kit.settings import ClaudeSettings, PersonaSettings


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def ask(expert, claude=None):
    return asyncio.run(expert.ask("Why?", [], claude or ClaudeSettings(), PersonaSettings()))


def test_answer_is_returned_and_spend_logged(memory):
    fake = FakeAnthropic()
    answer = ask(Expert(memory, lambda: "sk-test", fake.factory))
    assert answer.ok and answer.text == "The answer is 42."
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == [FALLBACK_BETA]
    assert call["output_config"] == {"effort": "medium"}
    assert "Kit" in call["system"] and call["messages"][-1]["content"] == "Why?"
    # 1000 in at $5/M + 2000 out at $25/M
    assert answer.cost_usd == pytest.approx(0.055)
    assert memory.month_spend() == pytest.approx(0.055)


def test_cost_estimate():
    assert estimate_cost(ClaudeSettings(), 1_000_000, 0) == 5.0


def test_cap_stops_calls(memory):
    memory.record_spend("m", 0, 0, 20.0, "earlier")
    fake = FakeAnthropic()
    answer = ask(Expert(memory, lambda: "sk-test", fake.factory))
    assert not answer.ok and "budget" in answer.text and fake.calls == []


def test_no_key(memory):
    answer = ask(Expert(memory, lambda: None, FakeAnthropic().factory))
    assert not answer.ok and "API key" in answer.text


def test_refusal_is_reported_but_still_costed(memory):
    fake = FakeAnthropic(stop_reason="refusal")
    answer = ask(Expert(memory, lambda: "k", fake.factory))
    assert not answer.ok and "declined" in answer.text
    assert memory.month_spend() > 0


def _error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("nope", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (_error(anthropic.AuthenticationError, 401), "rejected"),
        (_error(anthropic.RateLimitError, 429), "rate-limiting"),
        (_error(anthropic.InternalServerError, 500), "500"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "reach"),
    ],
)
def test_errors_become_plain_answers(memory, error, words):
    answer = ask(Expert(memory, lambda: "k", FakeAnthropic(error=error).factory))
    assert not answer.ok and words in answer.text
