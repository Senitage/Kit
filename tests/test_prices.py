"""The price table: fetched from LiteLLM and the exchange rate feed, kept in the data
folder, built in until then; and what a call costs in Australian dollars."""

import json
import logging
from datetime import date

import httpx
import pytest

from kit import checks
from kit.checks import Status
from kit.prices import (
    BUILT_IN,
    BUILT_IN_RATE,
    BUILT_IN_SOURCE,
    PRICES_SOURCE,
    PRICES_URL,
    RATE_SOURCE,
    RATE_URL,
    Price,
    Prices,
    Usage,
    estimate_cost,
    price_from_litellm,
)
from kit.settings import Settings

TODAY = date(2026, 10, 14)
LITELLM = {
    "claude-sonnet-5-5": {
        "input_cost_per_token": 3e-06,
        "cache_read_input_token_cost": 3e-07,
        "cache_creation_input_token_cost": 3.75e-06,
        "output_cost_per_token": 1.5e-05,
        "search_context_cost_per_query": {"search_context_size_medium": 0.01},
        "litellm_provider": "anthropic",
        "mode": "chat",
    },
    "gemini/gemini-4-flash": {"input_cost_per_token": 1e-06, "output_cost_per_token": 4e-06},
    "text-embedding-x": {"mode": "embedding"},  # no prices: left out
}


def fake_client(prices=LITELLM, rate=1.6, fail=()):
    """Answers the two feeds; ``fail`` names the ones that are down."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host in fail:
            return httpx.Response(503, text="down")
        if str(request.url) == PRICES_URL:
            return httpx.Response(200, json=prices)
        if str(request.url) == RATE_URL:
            return httpx.Response(200, json={"base": "USD", "rates": {"AUD": rate}})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def test_a_litellm_entry_becomes_a_price_per_million():
    price = price_from_litellm(LITELLM["claude-sonnet-5-5"])
    assert price == Price(3.0, 0.3, 3.75, 15.0, 10.0)
    # No cache write price: 1.25 times input, as Anthropic charges; no search: free.
    assert price_from_litellm(LITELLM["gemini/gemini-4-flash"]) == Price(1.0, 0.0, 1.25, 4.0, 0.0)
    assert price_from_litellm(LITELLM["text-embedding-x"]) is None
    assert price_from_litellm("nonsense") is None


def test_built_in_prices_until_the_first_fetch(tmp_path):
    prices = Prices(tmp_path / "prices.json", today=lambda: TODAY)
    assert prices.table.source == BUILT_IN_SOURCE and prices.table.aud_per_usd == BUILT_IN_RATE
    assert prices.price_of("claude-opus-5-5", "anthropic") == BUILT_IN["claude-opus-5-5"]
    assert "built in" in prices.table.line() and "A$1.52 to US$1" in prices.table.line()
    assert not prices.fetched_today() and prices.age_days() == 1


def test_a_model_is_found_by_provider_prefix_or_without_its_date():
    prices = Prices(None)
    prices.table.prices["gemini/gemini-4-flash"] = Price(1.0, 0, 1.25, 4.0, 0)
    assert prices.price_of("gemini-4-flash", "google").input_per_mtok == 1.0
    assert (
        prices.price_of("claude-sonnet-5-5-20260922", "anthropic") == BUILT_IN["claude-sonnet-5-5"]
    )
    assert prices.price_of("claude-9", "anthropic") is None


def test_cost_in_both_currencies(caplog):
    prices = Prices(None)
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = prices.cost("claude-opus-5-5", "anthropic", usage)
    assert (cost.usd, cost.aud, cost.aud_per_usd) == (24.0, pytest.approx(24.0 * 1.52), 1.52)
    local = prices.cost("qwen3:8b", "ollama", usage)
    assert (local.usd, local.aud, local.aud_per_usd) == (0.0, 0.0, 1.52)
    with caplog.at_level(logging.WARNING):
        unknown = prices.cost("claude-9", "anthropic", usage)
        prices.cost("claude-9", "anthropic", usage)
    assert unknown.usd == 0.0 and unknown.aud == 0.0
    assert caplog.text.count("no price known for claude-9") == 1  # said once


def test_estimate_cost_counts_every_kind_of_token():
    price = Price(4.0, 0.2, 5.0, 20.0, 10.0)
    assert estimate_cost(price, Usage(input_tokens=1_000_000)) == 4.0
    assert estimate_cost(price, Usage(1_000_000, cached_tokens=1_000_000)) == 0.2
    assert estimate_cost(price, Usage(1_000_000, cache_write_tokens=1_000_000)) == 5.0
    assert estimate_cost(price, Usage(output_tokens=1_000_000)) == 20.0
    assert estimate_cost(price, Usage(searches=1000)) == 10.0


def test_refresh_fetches_both_feeds_and_keeps_them(tmp_path):
    client, seen = fake_client()
    path = tmp_path / "prices.json"
    prices = Prices(path, client, today=lambda: TODAY)
    assert asyncio_run(prices.refresh()) == []
    assert seen == [PRICES_URL, RATE_URL]
    table = prices.table
    assert table.source == PRICES_SOURCE and table.fetched == "2026-10-14"
    assert table.rate_source == RATE_SOURCE and table.aud_per_usd == 1.6
    assert set(table.prices) == {"claude-sonnet-5-5", "gemini/gemini-4-flash"}
    assert prices.fetched_today() and prices.age_days() == 0
    assert prices.cost("claude-sonnet-5-5", "anthropic", Usage(input_tokens=1_000_000)).aud == (
        pytest.approx(3.0 * 1.6)
    )
    assert "LiteLLM" in table.line() and "14 Oct 2026" in table.line()
    # The next Kit reads the file, and the built-in table is gone from it.
    again = Prices(path, today=lambda: TODAY)
    assert again.table == table
    assert json.loads(path.read_text(encoding="utf-8"))["aud_per_usd"] == 1.6


def test_a_feed_that_is_down_keeps_what_was_there(tmp_path):
    client, _ = fake_client(fail={"api.frankfurter.dev"})
    prices = Prices(tmp_path / "prices.json", client, today=lambda: TODAY)
    problems = asyncio_run(prices.refresh())
    assert len(problems) == 1 and "exchange rate" in problems[0]
    assert prices.table.source == PRICES_SOURCE and prices.table.aud_per_usd == BUILT_IN_RATE
    assert not prices.fetched_today()  # the rate is still yesterday's
    client, _ = fake_client(fail={"raw.githubusercontent.com"}, rate=1.7)
    prices.client = client
    problems = asyncio_run(prices.refresh())
    assert len(problems) == 1 and "price list" in problems[0]
    assert prices.table.aud_per_usd == 1.7 and prices.table.source == PRICES_SOURCE


def test_bad_answers_are_problems_not_prices(tmp_path):
    client, _ = fake_client(prices={"x": {"mode": "chat"}}, rate=42)
    prices = Prices(tmp_path / "prices.json", client, today=lambda: TODAY)
    problems = asyncio_run(prices.refresh())
    assert len(problems) == 2 and "no prices" in problems[0] and "look right" in problems[1]
    assert prices.table.source == BUILT_IN_SOURCE and not (tmp_path / "prices.json").exists()
    assert asyncio_run(Prices(None).refresh()) == ["no way to fetch prices here"]


def test_a_broken_file_falls_back_to_built_in(tmp_path, caplog):
    path = tmp_path / "prices.json"
    path.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        prices = Prices(path)
    assert prices.table.source == BUILT_IN_SOURCE and "couldn't read" in caplog.text


def test_check_prices_says_when_the_table_is_old_or_a_model_has_no_price(tmp_path):
    settings = Settings()
    prices = Prices(None, today=lambda: TODAY)
    built_in = checks.check_prices(settings, prices)
    assert built_in.status is Status.WARN and "kit models prices" in built_in.detail
    client, _ = fake_client(prices={**LITELLM, **{k: _entry(v) for k, v in BUILT_IN.items()}})
    prices.client = client
    asyncio_run(prices.refresh())
    fresh = checks.check_prices(settings, prices)
    assert fresh.status is Status.PASS and "LiteLLM" in fresh.detail
    odd = Settings.model_validate(
        {
            "routing": {"work": "new"},
            "models": {**Settings().models, "new": {"provider": "anthropic", "model": "claude-9"}},
        }
    )
    assert checks.check_prices(odd, prices).status is Status.WARN
    prices.today = lambda: date(2026, 10, 30)
    assert checks.check_prices(settings, prices).status is Status.WARN  # 16 days old


def _entry(price: Price) -> dict:
    return {
        "input_cost_per_token": price.input_per_mtok / 1e6,
        "cache_read_input_token_cost": price.cached_input_per_mtok / 1e6,
        "cache_creation_input_token_cost": price.cache_write_per_mtok / 1e6,
        "output_cost_per_token": price.output_per_mtok / 1e6,
        "search_context_cost_per_query": {"search_context_size_medium": price.search_per_k / 1e3},
    }


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
