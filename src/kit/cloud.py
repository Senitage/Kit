"""Cloud models: Claude, GPT and Gemini behind one small interface.

Each provider has an adapter that turns Kit's chat messages (a system prompt
then alternating turns) into one request and returns the text and token
counts. ``Cloud`` picks the adapter for a model profile, keeps to the monthly
budget, and logs what every call cost, so swapping models is a settings change.

As the budget runs low, calls give way in a set order (``SKIP_ORDER``): evals
first, then fact checks and key moments, then chat, so Kit's nightly reflection
always has the last of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol

import anthropic
import httpx

from kit.memory import Memory
from kit.prompt import TURN_PART
from kit.settings import ModelProfile, PersonaSettings, Settings

CACHE_WRITE_MULTIPLIER = 1.25  # an Anthropic 5-minute cache write costs 1.25x input
# Who gives way as the month's budget runs low: each step stops cloud.reserve_usd
# sooner than the one before, so evals can never use up the nightly reflection's share.
SKIP_ORDER = {"reflect": 0, "chat": 1, "moment": 2, "check": 2, "eval": 3}


class CloudError(Exception):
    """The cloud model couldn't answer. The message is said to Dan as is."""


@dataclass
class Usage:
    input_tokens: int = 0  # every input token, cached ones included
    output_tokens: int = 0  # thinking included
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    searches: int = 0


@dataclass
class Completion:
    text: str
    model: str
    usage: Usage
    truncated: bool = False
    refused: bool = False


@dataclass
class CloudAnswer:
    text: str
    model: str
    cost_usd: float
    searches: int
    truncated: bool


@dataclass
class Where:
    """Roughly where the owner is, so web searches find local results."""

    city: str = ""
    region: str = ""
    country: str = ""  # two-letter code, e.g. AU
    timezone: str = ""  # e.g. Australia/Perth

    @classmethod
    def of(cls, persona: PersonaSettings) -> Where:
        parts = [p.strip() for p in persona.location.split(",")]
        return cls(
            city=parts[0],
            region=parts[1] if len(parts) > 1 else "",
            country=persona.country,
            timezone=persona.timezone,
        )

    def approximate(self) -> dict | None:
        """The ``user_location`` the search tools take, or None if nothing is set."""
        known = {k: v for k, v in asdict(self).items() if v}
        return {"type": "approximate", **known} if known else None


# Called with a short note of progress, e.g. "searched the web for 'x'", while a
# model is still working, so Kit can say how it's going.
Step = Callable[[str], None]


class Provider(Protocol):
    async def complete(
        self,
        profile: ModelProfile,
        system: str,
        turns: list[dict],
        key: str,
        on_step: Step | None = None,
        where: Where | None = None,
    ) -> Completion: ...


def estimate_cost(profile: ModelProfile, usage: Usage) -> float:
    """What one call cost, from the profile's prices."""
    fresh = usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens
    return (
        fresh * profile.input_usd_per_mtok
        + usage.cache_write_tokens * profile.input_usd_per_mtok * CACHE_WRITE_MULTIPLIER
        + usage.cached_tokens * profile.cached_input_usd_per_mtok
        + usage.output_tokens * profile.output_usd_per_mtok
    ) / 1_000_000 + usage.searches * profile.search_usd_per_k / 1000


def split_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Kit's messages as (system prompt, turns). Turns alternate user and
    assistant, start with the user and end with the user, as every provider wants."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "user" if m["role"] == "user" else "assistant"
        if turns and turns[-1]["role"] == role:
            turns[-1] = {"role": role, "content": turns[-1]["content"] + "\n\n" + m["content"]}
        else:
            turns.append({"role": role, "content": m["content"]})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if not turns or turns[-1]["role"] != "user":
        raise ValueError("the last message must be from the user")
    return system, turns


# --- Anthropic (Claude) -----------------------------------------------------

FALLBACK_BETA = "server-side-fallback-2026-07-01"
ANTHROPIC_SEARCH_TOOL = "web_search_20260209"
ANTHROPIC_FETCH_TOOL = "web_fetch_20260209"
# Haiku doesn't take the newer search tools (which filter results as they come
# in) or the server-side fallback, so it gets the basic tools and no fallback.
BASIC_SEARCH_TOOL = "web_search_20250305"
BASIC_FETCH_TOOL = "web_fetch_20250910"
MAX_SEARCHES = 5
MAX_FETCHES = 3
MAX_FETCH_TOKENS = 20_000  # a page is cut to this much text
MAX_RESUMES = 3
AnthropicFactory = Callable[[str], anthropic.AsyncAnthropic]


def make_anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key, max_retries=2, timeout=300)


class AnthropicProvider:
    def __init__(self, make_client: AnthropicFactory = make_anthropic_client) -> None:
        self.make_client = make_client

    async def complete(
        self,
        profile: ModelProfile,
        system: str,
        turns: list[dict],
        key: str,
        on_step: Step | None = None,
        where: Where | None = None,
    ) -> Completion:
        client = self.make_client(key)
        haiku = profile.model.startswith("claude-haiku")
        tools = anthropic_web_tools(where, basic=haiku) if profile.web_search else []
        fallback = {} if haiku else {"fallbacks": "default", "betas": [FALLBACK_BETA]}
        messages = list(turns)
        usage = Usage()
        text: list[str] = []
        try:
            for _ in range(MAX_RESUMES + 1):
                response = await client.beta.messages.create(
                    model=profile.model,
                    max_tokens=profile.max_tokens,
                    system=system_blocks(system),
                    messages=messages,
                    output_config={"effort": profile.effort},
                    **fallback,
                    **({"tools": tools} if tools else {}),
                )
                _add_anthropic_usage(usage, response.usage)
                text += [b.text for b in response.content if getattr(b, "type", "") == "text"]
                if response.stop_reason != "pause_turn":
                    break
                if on_step:
                    for step in _web_steps(response.content):
                        on_step(step)
                # A long web search paused; send the turn back and it carries on.
                messages = [*turns, {"role": "assistant", "content": response.content}]
        except anthropic.AuthenticationError as e:
            raise CloudError(f"{profile.name} rejected my API key.") from e
        except anthropic.RateLimitError as e:
            raise CloudError(f"{profile.name} is rate-limiting me right now.") from e
        except anthropic.NotFoundError as e:
            raise CloudError(f"{profile.name} doesn't know the model {profile.model}.") from e
        except anthropic.APIConnectionError as e:
            raise CloudError(f"I couldn't reach {profile.name}. Is the internet up?") from e
        except anthropic.APIStatusError as e:
            raise CloudError(f"{profile.name} returned an error ({e.status_code}).") from e
        finally:
            await client.close()
        return Completion(
            "".join(text).strip(),
            response.model,
            usage,
            truncated=response.stop_reason == "max_tokens",
            refused=response.stop_reason == "refusal",
        )


def anthropic_web_tools(where: Where | None, basic: bool = False) -> list[dict]:
    """Claude's web search, which finds pages, and web fetch, which opens one (say
    the weather service's page for the owner's city) so the answer isn't from an
    old search snippet. ``basic``: the older versions, for models without the new."""
    search_tool = BASIC_SEARCH_TOOL if basic else ANTHROPIC_SEARCH_TOOL
    search = {"type": search_tool, "name": "web_search", "max_uses": MAX_SEARCHES}
    near = where.approximate() if where else None
    if near:
        search["user_location"] = near
    fetch = {
        "type": BASIC_FETCH_TOOL if basic else ANTHROPIC_FETCH_TOOL,
        "name": "web_fetch",
        "max_uses": MAX_FETCHES,
        "max_content_tokens": MAX_FETCH_TOKENS,
    }
    return [search, fetch]


def _web_steps(content) -> list[str]:
    """What a (paused) Claude response has done on the web so far."""
    out = []
    for block in content:
        if getattr(block, "type", "") != "server_tool_use":
            continue
        given = getattr(block, "input", None) or {}
        if not isinstance(given, dict):
            continue
        if given.get("query"):
            out.append(f"searched the web for '{given['query']}'")
        elif given.get("url"):
            out.append(f"opened {given['url']}")
    return out


def system_blocks(system: str) -> list[dict]:
    """The system prompt as Claude blocks, cached up to where this turn's part (the
    time and recalled memories, which Kit's prompt puts last) begins, so the fixed
    persona text is read from the cache on later turns."""
    fixed, found, turn = system.rpartition(TURN_PART)
    cached = {"type": "text", "text": fixed if found else system}
    cached["cache_control"] = {"type": "ephemeral"}
    return [cached, {"type": "text", "text": found + turn}] if found else [cached]


def _add_anthropic_usage(total: Usage, u) -> None:
    cache_read = u.cache_read_input_tokens or 0
    cache_write = u.cache_creation_input_tokens or 0
    total.input_tokens += u.input_tokens + cache_read + cache_write
    total.cached_tokens += cache_read
    total.cache_write_tokens += cache_write
    total.output_tokens += u.output_tokens
    server = getattr(u, "server_tool_use", None)
    total.searches += (getattr(server, "web_search_requests", 0) or 0) if server else 0


# --- OpenAI (GPT), through the Responses API --------------------------------

OPENAI_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider:
    def __init__(self, client: httpx.AsyncClient, url: str = OPENAI_URL) -> None:
        self.client = client
        self.url = url

    async def complete(
        self,
        profile: ModelProfile,
        system: str,
        turns: list[dict],
        key: str,
        on_step: Step | None = None,
        where: Where | None = None,
    ) -> Completion:
        body: dict = {
            "model": profile.model,
            "instructions": system,
            "input": [{"role": t["role"], "content": t["content"]} for t in turns],
            "max_output_tokens": profile.max_tokens,
            "reasoning": {"effort": profile.effort},
            "store": False,
        }
        if profile.web_search:
            near = where.approximate() if where else None
            body["tools"] = [{"type": "web_search", **({"user_location": near} if near else {})}]
        data = await _post_json(
            self.client, self.url, body, {"Authorization": f"Bearer {key}"}, profile
        )
        text, searches, refused = [], 0, False
        for item in data.get("output", []):
            if item.get("type") == "web_search_call":
                searches += 1
            elif item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text.append(part.get("text", ""))
                    elif part.get("type") == "refusal":
                        refused = True
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=u.get("input_tokens", 0),
            output_tokens=u.get("output_tokens", 0),
            cached_tokens=(u.get("input_tokens_details") or {}).get("cached_tokens", 0),
            searches=searches,
        )
        truncated = (
            data.get("status") == "incomplete"
            and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
        )
        return Completion(
            "".join(text).strip(), data.get("model", profile.model), usage, truncated, refused
        )


# --- Google (Gemini) ---------------------------------------------------------

GEMINI_REFUSALS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
GEMINI_THINKING = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GoogleProvider:
    def __init__(self, client: httpx.AsyncClient, url: str = GEMINI_URL) -> None:
        self.client = client
        self.url = url

    async def complete(
        self,
        profile: ModelProfile,
        system: str,
        turns: list[dict],
        key: str,
        on_step: Step | None = None,
        where: Where | None = None,
    ) -> Completion:
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "user" if t["role"] == "user" else "model",
                    "parts": [{"text": t["content"]}],
                }
                for t in turns
            ],
            "generationConfig": {
                "maxOutputTokens": profile.max_tokens,
                # Gemini 3 thinks at low, medium or high.
                "thinkingConfig": {"thinkingLevel": GEMINI_THINKING[profile.effort]},
            },
        }
        if profile.web_search:
            body["tools"] = [{"google_search": {}}]
        url = self.url.format(model=profile.model)
        data = await _post_json(self.client, url, body, {"x-goog-api-key": key}, profile)
        blocked = bool((data.get("promptFeedback") or {}).get("blockReason"))
        candidate = (data.get("candidates") or [{}])[0]
        finish = candidate.get("finishReason", "STOP")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        grounding = candidate.get("groundingMetadata") or {}
        u = data.get("usageMetadata") or {}
        usage = Usage(
            input_tokens=u.get("promptTokenCount", 0) + u.get("toolUsePromptTokenCount", 0),
            output_tokens=u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
            cached_tokens=u.get("cachedContentTokenCount", 0),
            # Gemini 3 bills each search query the model runs.
            searches=len([q for q in grounding.get("webSearchQueries") or [] if q]),
        )
        return Completion(
            text.strip(),
            data.get("modelVersion", profile.model),
            usage,
            truncated=finish == "MAX_TOKENS",
            refused=blocked or finish in GEMINI_REFUSALS,
        )


async def _post_json(
    client: httpx.AsyncClient, url: str, body: dict, headers: dict, profile: ModelProfile
) -> dict:
    try:
        response = await client.post(url, json=body, headers=headers, timeout=300)
    except httpx.HTTPError as e:
        raise CloudError(f"I couldn't reach {profile.name}. Is the internet up?") from e
    if response.status_code in (401, 403):
        raise CloudError(f"{profile.name} rejected my API key.")
    if response.status_code == 429:
        raise CloudError(f"{profile.name} is rate-limiting me right now.")
    if response.status_code == 404:
        raise CloudError(f"{profile.name} doesn't know the model {profile.model}.")
    if response.status_code != 200:
        raise CloudError(f"{profile.name} returned an error ({response.status_code}).")
    return response.json()


# --- Choosing a provider, the budget and the spend log ----------------------


class Cloud:
    """Answers with whichever cloud model a profile names, within the budget."""

    def __init__(
        self,
        memory: Memory,
        api_key: Callable[[str], str | None],
        providers: dict[str, Provider],
    ) -> None:
        self.memory = memory
        self.api_key = api_key
        self.providers = providers

    async def answer(
        self,
        profile: ModelProfile,
        messages: list[dict],
        settings: Settings,
        question: str = "",
        on_step: Step | None = None,
        priority: str = "chat",
    ) -> CloudAnswer:
        """``question`` is what Dan asked, for the spend log. ``on_step`` hears about
        progress (web searches so far) while the model is still working. ``priority``
        is the call's place in ``SKIP_ORDER``."""
        provider = self.providers.get(profile.provider)
        if provider is None:
            raise CloudError(f"I don't know how to talk to {profile.provider} models.")
        spent = self.memory.month_spend()
        cap = settings.cloud.monthly_cap_usd
        kept = settings.cloud.reserve_usd * SKIP_ORDER.get(priority, 1)
        if spent >= cap - kept:
            saving = f", keeping the last ${kept:.2f} for my nightly reflection" if kept else ""
            raise CloudError(
                f"I've used this month's cloud budget (${spent:.2f} of ${cap:.2f}{saving}). "
                "You can raise cloud.monthly_cap_usd in my settings."
            )
        key = self.api_key(profile.provider)
        if not key:
            raise CloudError(
                f"I can't reach {profile.name}: there's no {profile.provider} API key in my "
                "secrets folder."
            )
        system, turns = split_messages(messages)
        where = Where.of(settings.persona)
        done = await provider.complete(profile, system, turns, key, on_step, where)
        cost = estimate_cost(profile, done.usage)
        question = question or turns[-1]["content"]
        self.memory.record_spend(
            done.model, done.usage.input_tokens, done.usage.output_tokens, cost, question
        )
        if done.refused:
            raise CloudError(f"{profile.name} declined to answer that one.")
        if not done.text:
            raise CloudError(f"{profile.name} came back empty.")
        return CloudAnswer(done.text, done.model, cost, done.usage.searches, done.truncated)
