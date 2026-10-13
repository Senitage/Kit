"""What cloud models cost, kept up to date by themselves, in Australian dollars.

No provider's API says what its models cost, so Kit reads the price list that
LiteLLM keeps for every model (``PRICES_URL``) and the day's US dollar to
Australian dollar rate from the European Central Bank's feed (``RATE_URL``), once
a day, and keeps both in ``prices.json`` in the data folder. Between fetches,
and on a machine that can't reach them, the last copy is used, and before any
fetch the table shipped in this module (``BUILT_IN``). Every call's cost is
worked out from the price of the moment and written to the spend log in both
currencies with the rate, so a rate that moves later never rewrites the past.

The prices live here and nowhere else: a model profile in settings only names
the model, and ``kit models`` shows what each one costs today.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

PRICES_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
PRICES_SOURCE = "LiteLLM's price list"
RATE_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=AUD"
RATE_SOURCE = "the European Central Bank"
BUILT_IN_SOURCE = "built in"
PRICES_FILE = "prices.json"  # in the data folder's state/
STALE_DAYS = 7  # older than this, kit check says so
FETCH_TIMEOUT_S = 20.0
CACHE_WRITE_MULTIPLIER = 1.25  # a cache write costs this much of input when the list doesn't say
# LiteLLM names Google's models "gemini/..." as well as bare; Kit's providers are
# anthropic, openai, google and ollama.
PROVIDER_PREFIX = {"google": "gemini"}


@dataclass(frozen=True)
class Price:
    """What one model costs, in US dollars as its provider quotes it."""

    input_per_mtok: float = 0.0  # per million input tokens
    cached_input_per_mtok: float = 0.0  # ...read from the prompt cache
    cache_write_per_mtok: float = 0.0  # ...written to it
    output_per_mtok: float = 0.0  # per million output tokens, thinking included
    search_per_k: float = 0.0  # per 1,000 web searches


@dataclass
class Usage:
    """What one call used."""

    input_tokens: int = 0  # every input token, cached ones included
    output_tokens: int = 0  # thinking included
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    searches: int = 0


@dataclass(frozen=True)
class Cost:
    usd: float
    aud: float
    aud_per_usd: float


@dataclass(frozen=True)
class Table:
    """The prices in force, and where and when they came from."""

    prices: dict[str, Price]
    fetched: str  # the day the list was fetched (YYYY-MM-DD)
    source: str
    aud_per_usd: float
    rate_fetched: str
    rate_source: str

    def line(self) -> str:
        """One line for people: where today's prices and rate come from."""
        return (
            f"prices from {self.source} ({_day(self.fetched)}); "
            f"A${self.aud_per_usd:.2f} to US$1 from {self.rate_source} ({_day(self.rate_fetched)})"
        )


def _day(iso: str) -> str:
    try:
        day = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{day.day} {day:%b %Y}"


# The price list as fetched on 13 October 2026, for before the first fetch and for
# tests. The rate is a round figure for the same month; the first fetch replaces it.
BUILT_IN_DATE = "2026-10-13"
BUILT_IN_RATE = 1.52
BUILT_IN: dict[str, Price] = {
    "claude-opus-5-5": Price(4.0, 0.2, 5.0, 20.0, 10.0),
    "claude-sonnet-5-5": Price(2.0, 0.1, 2.5, 10.0, 10.0),
    "claude-haiku-5-5": Price(0.1, 0.01, 0.125, 0.5, 10.0),
    "gpt-6.1-sol": Price(2.0, 0.1, 2.5, 10.0, 10.0),
    "gemini-3.8-flash": Price(0.75, 0.075, 0.9375, 3.75, 14.0),
}


def built_in() -> Table:
    return Table(
        dict(BUILT_IN),
        BUILT_IN_DATE,
        BUILT_IN_SOURCE,
        BUILT_IN_RATE,
        BUILT_IN_DATE,
        BUILT_IN_SOURCE,
    )


def estimate_cost(price: Price, usage: Usage) -> float:
    """What one call cost in US dollars, from its price."""
    fresh = usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens
    return (
        fresh * price.input_per_mtok
        + usage.cache_write_tokens * price.cache_write_per_mtok
        + usage.cached_tokens * price.cached_input_per_mtok
        + usage.output_tokens * price.output_per_mtok
    ) / 1_000_000 + usage.searches * price.search_per_k / 1000


def price_from_litellm(entry: dict) -> Price | None:
    """One of LiteLLM's entries as a Price, or None if it doesn't say what tokens cost."""
    if not isinstance(entry, dict) or "input_cost_per_token" not in entry:
        return None
    per_mtok = 1_000_000
    inp = float(entry.get("input_cost_per_token") or 0) * per_mtok
    cached = float(entry.get("cache_read_input_token_cost") or 0) * per_mtok
    write = entry.get("cache_creation_input_token_cost")
    write = float(write) * per_mtok if write else inp * CACHE_WRITE_MULTIPLIER
    out = float(entry.get("output_cost_per_token") or 0) * per_mtok
    search = entry.get("search_context_cost_per_query")
    per_query = search.get("search_context_size_medium", 0) if isinstance(search, dict) else 0
    return Price(inp, cached, write, out, float(per_query or 0) * 1000)


def table_from_litellm(raw: dict) -> dict[str, Price]:
    out = {}
    for name, entry in raw.items():
        price = price_from_litellm(entry)
        if price is not None:
            out[str(name)] = price
    return out


def _dump(table: Table) -> dict:
    return {**asdict(table), "prices": {k: asdict(v) for k, v in table.prices.items()}}


def _load(raw: dict) -> Table:
    prices = {str(k): Price(**v) for k, v in raw["prices"].items()}
    return Table(
        prices,
        str(raw["fetched"]),
        str(raw["source"]),
        float(raw["aud_per_usd"]),
        str(raw["rate_fetched"]),
        str(raw["rate_source"]),
    )


class Prices:
    """The price table in force, loaded from the data folder, refreshed daily."""

    def __init__(
        self,
        path: Path | None,
        client: httpx.AsyncClient | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.path = path
        self.client = client
        self.today = today
        self.table = built_in()
        self._unknown: set[str] = set()  # models warned about once
        if path is not None and path.exists():
            try:
                self.table = _load(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError) as e:
                log.warning("couldn't read %s, using the built-in prices: %s", path, e)

    def price_of(self, model: str, provider: str = "") -> Price | None:
        """The price of a provider's model, or None if the list doesn't have it."""
        prices = self.table.prices
        prefix = PROVIDER_PREFIX.get(provider, provider)
        for name in (model, f"{prefix}/{model}", _undated(model), f"{prefix}/{_undated(model)}"):
            if name in prices:
                return prices[name]
        return None

    def cost(self, model: str, provider: str, usage: Usage) -> Cost:
        """What one call cost. A model the list doesn't know counts as free, with a
        warning once, so the budget is never stopped by a missing price."""
        if provider == "ollama":
            return Cost(0.0, 0.0, self.table.aud_per_usd)
        price = self.price_of(model, provider)
        if price is None:
            if model not in self._unknown:
                self._unknown.add(model)
                log.warning("no price known for %s; its calls count as free", model)
            price = Price()
        usd = estimate_cost(price, usage)
        return Cost(usd, usd * self.table.aud_per_usd, self.table.aud_per_usd)

    def to_aud(self, usd: float) -> float:
        return usd * self.table.aud_per_usd

    def fetched_today(self) -> bool:
        day = self.today().isoformat()
        return self.table.fetched == day and self.table.rate_fetched == day

    def age_days(self) -> int:
        """How old the older of the list and the rate is."""
        try:
            oldest = min(
                date.fromisoformat(self.table.fetched),
                date.fromisoformat(self.table.rate_fetched),
            )
        except ValueError:
            return STALE_DAYS + 1
        return (self.today() - oldest).days

    async def refresh(self) -> list[str]:
        """Fetch today's list and rate, keep what came, and say what didn't."""
        if self.client is None:
            return ["no way to fetch prices here"]
        problems = []
        table = self.table
        today = self.today().isoformat()
        try:
            raw = await self._get(PRICES_URL)
            prices = table_from_litellm(json.loads(raw))
            if not prices:
                raise ValueError("the list has no prices in it")
            table = replace(table, prices=prices, fetched=today, source=PRICES_SOURCE)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as e:
            problems.append(f"couldn't fetch the price list: {e}")
        try:
            raw = await self._get(RATE_URL)
            rate = float(json.loads(raw)["rates"]["AUD"])
            if not 0.5 < rate < 5:
                raise ValueError(f"rate {rate} doesn't look right")
            table = replace(table, aud_per_usd=rate, rate_fetched=today, rate_source=RATE_SOURCE)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            problems.append(f"couldn't fetch the exchange rate: {e}")
        if table != self.table:
            self.table = table
            self._save()
        for problem in problems:
            log.warning(problem)
        return problems

    async def _get(self, url: str) -> str:
        response = await self.client.get(url, timeout=FETCH_TIMEOUT_S, follow_redirects=True)
        response.raise_for_status()
        return response.text

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(_dump(self.table)), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            log.warning("couldn't save prices to %s: %s", self.path, e)


def _undated(model: str) -> str:
    """``claude-sonnet-5-5-20260922`` as ``claude-sonnet-5-5``."""
    head, _, tail = model.rpartition("-")
    return head if len(tail) == 8 and tail.isdigit() else model
