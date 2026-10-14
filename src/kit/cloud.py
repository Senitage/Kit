"""Cloud models: Claude, GPT and Gemini behind one small interface.

Each provider has an adapter that turns Kit's chat messages (a system prompt
then alternating turns) into one request and returns the text and token
counts. ``Cloud`` picks the adapter for a model profile, keeps to the monthly
budget (in Australian dollars), and logs what every call cost at the day's
prices and rate (``kit.prices``), so swapping models is a settings change.

As the budget runs low, calls give way in a set order (``SKIP_ORDER``): evals
first, then fact checks and key moments, then chat, so Kit's nightly reflection
always has the last of it.

Claude's answers can also stream (``on_text``): the brain hears the words as they
are written, so Kit starts talking a few words in rather than after the whole
answer. The other providers answer in one piece.

Claude reads a prompt from its cache when it starts the same way as the last one,
so the request is laid out stable-first: the fixed persona text (one cache
breakpoint), then the conversation so far (a breakpoint on Kit's last turn), then
Dan's new message carrying this turn's part (the time, memories, mood...). The
spend log keeps how much of each call was read from the cache.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import anthropic
import httpx

from kit.memory import Memory
from kit.prices import Prices, Usage
from kit.prompt import TURN_PART
from kit.settings import ModelProfile, PersonaSettings, Settings
from kit.tools import ToolCall

__all__ = ["Usage"]  # the providers fill one in; it lives with the prices
log = logging.getLogger(__name__)

# Who gives way as the month's budget runs low: each step stops cloud.reserve_aud
# sooner than the one before, so evals can never use up the nightly reflection's share.
# His background thoughts and pipe-ups ("life") go first, with evals: the local model can
# have them.
SKIP_ORDER = {"reflect": 0, "chat": 1, "moment": 2, "check": 2, "eval": 3, "life": 3}


class CloudError(Exception):
    """The cloud model couldn't answer. The message is said to Dan as is."""


@dataclass
class Completion:
    text: str
    model: str
    usage: Usage
    truncated: bool = False
    refused: bool = False
    calls: list[ToolCall] = field(default_factory=list)  # tools the model asked for
    # The provider's own assistant content for a turn with calls, handed back as is
    # with the results (Claude needs its thinking blocks back); None for the rest.
    content: Any = None


@dataclass
class CloudAnswer:
    text: str
    model: str
    cost_aud: float  # at the day's prices and exchange rate
    searches: int
    truncated: bool
    calls: list[ToolCall] = field(default_factory=list)
    content: Any = None


@dataclass
class Where:
    """Roughly where the owner is, so web searches find local results."""

    city: str = ""
    region: str = ""
    country: str = ""  # two-letter code, e.g. AU
    timezone: str = ""  # e.g. Australia/Sydney

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
# Called with each new piece of an answer's text as it's written (cloud.stream).
Text = Callable[[str], None]


class Provider(Protocol):
    async def complete(
        self,
        profile: ModelProfile,
        system: str,
        turns: list[dict],
        key: str,
        on_step: Step | None = None,
        where: Where | None = None,
        on_text: Text | None = None,
        tools: list[dict] | None = None,
    ) -> Completion:
        """``tools`` are kit.tools definitions (name, description, input_schema); the
        model's calls come back in the Completion. A turn in ``turns`` is plain
        (``content`` a string) or a tool exchange: an assistant turn with ``calls``
        (and the provider's ``content`` from the Completion it came from), then a
        user turn with ``results`` (call id, text), as ``tool_turns`` builds them."""
        ...


def tool_turns(said: str, calls: list[ToolCall], results: list[tuple[str, str]], content=None):
    """The two turns a tool exchange adds to the conversation: what the model said
    and asked for, then what each tool gave back."""
    return [
        {"role": "assistant", "content": said, "calls": list(calls), "raw": content},
        {"role": "user", "content": "", "results": list(results)},
    ]


def _plain(turn: dict) -> bool:
    """A turn of words only: no tool calls or results, before or after it is
    converted to a provider's shape."""
    return (
        not turn.get("calls") and not turn.get("results") and isinstance(turn.get("content"), str)
    )


def _calls_from(items: list[dict]) -> list[ToolCall]:
    return [ToolCall(str(c["id"]), str(c["name"]), dict(c.get("arguments") or {})) for c in items]


def split_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Kit's messages as (system prompt, turns). Turns alternate user and
    assistant, start with the user and end with the user, as every provider wants."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "user" if m["role"] == "user" else "assistant"
        if turns and turns[-1]["role"] == role and _plain(turns[-1]) and _plain(m):
            turns[-1] = {"role": role, "content": turns[-1]["content"] + "\n\n" + m["content"]}
        else:
            turns.append({**m, "role": role})
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
NO_THINKING_EFFORTS = ("low", "medium", "high")  # thinking can only be turned off at these
AnthropicFactory = Callable[[str], anthropic.AsyncAnthropic]


# A dead connection is given up on quickly, so the local model can step in; a long
# answer (a web search) may still take minutes to write.
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 300.0


def make_anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=api_key,
        max_retries=2,
        # The SDK's own Timeout: newer SDKs run on httpx2 and refuse an httpx one.
        timeout=anthropic.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
    )


class AnthropicProvider:
    """One client per API key, kept for the life of the process: every call reuses
    its connection, rather than paying a new TLS handshake before the first word."""

    def __init__(self, make_client: AnthropicFactory = make_anthropic_client) -> None:
        self.make_client = make_client
        self._clients: dict[str, anthropic.AsyncAnthropic] = {}

    def _client(self, key: str) -> anthropic.AsyncAnthropic:
        client = self._clients.get(key)
        if client is None:
            client = self._clients[key] = self.make_client(key)
        return client

    async def close(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.close()

    async def complete(
        self,
        profile: ModelProfile,
        system: str,
        turns: list[dict],
        key: str,
        on_step: Step | None = None,
        where: Where | None = None,
        on_text: Text | None = None,
        tools: list[dict] | None = None,
    ) -> Completion:
        """``on_text`` hears the answer's text as it's written (it's streamed)."""
        try:
            client = self._client(key)
        except (TypeError, ValueError) as e:  # an SDK that won't take these settings
            raise CloudError(f"I couldn't set up {profile.name}: {e}") from e
        haiku = profile.model.startswith("claude-haiku")
        web = anthropic_web_tools(where, basic=haiku) if profile.web_search else []
        tools = [*anthropic_tools(tools or []), *web]
        fallback = {} if haiku else {"fallbacks": "default", "betas": [FALLBACK_BETA]}
        # Haiku can skip thinking (at effort up to high) and answer straight away;
        # Sonnet and Opus refuse the request, so for them the flag changes nothing.
        thinking = (
            {"thinking": {"type": "disabled"}}
            if haiku and not profile.thinking and profile.effort in NO_THINKING_EFFORTS
            else {}
        )
        turns = cached_turns(anthropic_turns(turns))
        messages = list(turns)
        usage = Usage()
        text: list[str] = []
        calls: list[ToolCall] = []
        try:
            for _ in range(MAX_RESUMES + 1):
                request = {
                    "model": profile.model,
                    "max_tokens": profile.max_tokens,
                    "system": system_blocks(system),
                    "messages": messages,
                    "output_config": {"effort": profile.effort},
                    **thinking,
                    **fallback,
                    **({"tools": tools} if tools else {}),
                }
                if on_text is None:
                    response = await client.beta.messages.create(**request)
                else:
                    response = await _streamed(client, request, on_text)
                _add_anthropic_usage(usage, response.usage)
                text += [b.text for b in response.content if getattr(b, "type", "") == "text"]
                calls += [
                    ToolCall(str(b.id), str(b.name), dict(b.input or {}))
                    for b in response.content
                    if getattr(b, "type", "") == "tool_use"
                ]
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
        return Completion(
            "".join(text).strip(),
            response.model,
            usage,
            truncated=response.stop_reason == "max_tokens",
            refused=response.stop_reason == "refusal",
            calls=calls,
            content=list(response.content) if calls else None,
        )


async def _streamed(client: anthropic.AsyncAnthropic, request: dict, on_text: Text):
    """One Claude request, streamed: ``on_text`` hears each piece of text as it comes,
    and the whole response is returned at the end, as ``create`` would."""
    async with client.beta.messages.stream(**request) as stream:
        async for event in stream:
            if getattr(event, "type", "") == "text" and event.text:
                on_text(event.text)
        return await stream.get_final_message()


def anthropic_tools(definitions: list[dict]) -> list[dict]:
    """kit.tools definitions as Claude's tool list."""
    return [
        {"name": d["name"], "description": d["description"], "input_schema": d["input_schema"]}
        for d in definitions
    ]


def anthropic_turns(turns: list[dict]) -> list[dict]:
    """The turns as Claude's messages: a tool exchange becomes the assistant's own
    content back (text, thinking and tool_use blocks, kept whole so a thinking
    model's blocks aren't lost) and a user turn of tool_result blocks."""
    out: list[dict] = []
    for t in turns:
        if t.get("calls"):
            content = t.get("raw")
            if content is None:
                content = [
                    *([{"type": "text", "text": t["content"]}] if t.get("content") else []),
                    *(
                        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                        for c in t["calls"]
                    ),
                ]
            out.append({"role": "assistant", "content": content})
        elif t.get("results"):
            out.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": call_id, "content": text}
                        for call_id, text in t["results"]
                    ],
                }
            )
        else:
            out.append({"role": t["role"], "content": t["content"]})
    return out


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


CACHE = {"type": "ephemeral"}


def system_blocks(system: str) -> list[dict]:
    """The system prompt as Claude blocks, cached up to where this turn's part (the
    time and recalled memories, which Kit's prompt puts last) begins, so the fixed
    persona text is read from the cache on later turns. The brain moves that part
    into Dan's message (``prompt.with_now``) before it gets here, so the whole
    system prompt is usually the fixed part; a caller that leaves it in still
    gets the split."""
    fixed, found, turn = system.rpartition(TURN_PART)
    cached = {"type": "text", "text": fixed if found else system, "cache_control": CACHE}
    return [cached, {"type": "text", "text": found + turn}] if found else [cached]


def cached_turns(turns: list[dict]) -> list[dict]:
    """The turns with a cache breakpoint on the last assistant one, so the whole
    conversation up to Dan's new message is read from the cache next turn (the
    system prompt comes first in the cache, so it's covered too). Nothing to mark
    on a first message: the system prompt's breakpoint does the work."""
    last = max(
        (i for i, t in enumerate(turns) if t["role"] == "assistant" and _plain(t)),
        default=-1,
    )
    if last < 0:
        return list(turns)
    marked = {
        "role": "assistant",
        "content": [{"type": "text", "text": turns[last]["content"], "cache_control": CACHE}],
    }
    return [*turns[:last], marked, *turns[last + 1 :]]


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
# The Responses API takes low, medium and high; the two efforts above are high there.
OPENAI_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


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
        on_text: Text | None = None,
        tools: list[dict] | None = None,
    ) -> Completion:
        body: dict = {
            "model": profile.model,
            "instructions": system,
            "input": openai_input(turns),
            "max_output_tokens": profile.max_tokens,
            "reasoning": {"effort": OPENAI_EFFORT[profile.effort]},
            "store": False,
        }
        body_tools = [
            {
                "type": "function",
                "name": d["name"],
                "description": d["description"],
                "parameters": d["input_schema"],
            }
            for d in tools or []
        ]
        if profile.web_search:
            near = where.approximate() if where else None
            body_tools.append({"type": "web_search", **({"user_location": near} if near else {})})
        if body_tools:
            body["tools"] = body_tools
        data = await _post_json(
            self.client, self.url, body, {"Authorization": f"Bearer {key}"}, profile
        )
        text, searches, refused, calls = [], 0, False, []
        for item in data.get("output", []):
            if item.get("type") == "web_search_call":
                searches += 1
            elif item.get("type") == "function_call":
                call_id, name = str(item.get("call_id", "")), str(item.get("name", ""))
                calls.append(ToolCall(call_id, name, _json_args(item.get("arguments"))))
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
            "".join(text).strip(),
            data.get("model", profile.model),
            usage,
            truncated,
            refused,
            calls=calls,
        )


def openai_input(turns: list[dict]) -> list[dict]:
    """The turns as Responses API input items: a tool exchange becomes the
    assistant's words (if any) plus one function_call item per call, then one
    function_call_output item per result."""
    items: list[dict] = []
    for t in turns:
        if t.get("calls"):
            if t.get("content"):
                items.append({"role": "assistant", "content": t["content"]})
            items += [
                {
                    "type": "function_call",
                    "call_id": c.id,
                    "name": c.name,
                    "arguments": json.dumps(c.arguments),
                }
                for c in t["calls"]
            ]
        elif t.get("results"):
            items += [
                {"type": "function_call_output", "call_id": call_id, "output": text}
                for call_id, text in t["results"]
            ]
        else:
            items.append({"role": t["role"], "content": t["content"]})
    return items


def _json_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


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
        on_text: Text | None = None,
        tools: list[dict] | None = None,
    ) -> Completion:
        body: dict = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": gemini_contents(turns),
            "generationConfig": {
                "maxOutputTokens": profile.max_tokens,
                # Gemini 3 thinks at low, medium or high.
                "thinkingConfig": {"thinkingLevel": GEMINI_THINKING[profile.effort]},
            },
        }
        body_tools: list[dict] = []
        if tools:
            body_tools.append(
                {
                    "functionDeclarations": [
                        {
                            "name": d["name"],
                            "description": d["description"],
                            "parameters": _gemini_schema(d["input_schema"]),
                        }
                        for d in tools
                    ]
                }
            )
        if profile.web_search:
            body_tools.append({"google_search": {}})
        if body_tools:
            body["tools"] = body_tools
        url = self.url.format(model=profile.model)
        data = await _post_json(self.client, url, body, {"x-goog-api-key": key}, profile)
        blocked = bool((data.get("promptFeedback") or {}).get("blockReason"))
        candidate = (data.get("candidates") or [{}])[0]
        finish = candidate.get("finishReason", "STOP")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        calls = [
            ToolCall(str(fc.get("name", "")), str(fc.get("name", "")), dict(fc.get("args") or {}))
            for p in parts
            if (fc := p.get("functionCall"))
        ]
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
            calls=calls,
        )


def gemini_contents(turns: list[dict]) -> list[dict]:
    """The turns as Gemini contents: a tool exchange becomes a model turn with
    functionCall parts and a user turn with functionResponse parts. Gemini has no
    call ids, so a call is known by its name."""
    out: list[dict] = []
    for t in turns:
        if t.get("calls"):
            parts = [{"text": t["content"]}] if t.get("content") else []
            parts += [{"functionCall": {"name": c.name, "args": c.arguments}} for c in t["calls"]]
            out.append({"role": "model", "parts": parts})
        elif t.get("results"):
            out.append(
                {
                    "role": "user",
                    "parts": [
                        {"functionResponse": {"name": name, "response": {"result": text}}}
                        for name, text in t["results"]
                    ],
                }
            )
        else:
            role = "user" if t["role"] == "user" else "model"
            out.append({"role": role, "parts": [{"text": t["content"]}]})
    return out


def _gemini_schema(schema: dict) -> dict:
    """Gemini's OpenAPI subset: no additionalProperties."""
    return {k: v for k, v in schema.items() if k != "additionalProperties"}


# A busy or stumbling provider (429, 5xx, a dropped connection) gets this many more
# goes, this long apart, the way the Anthropic SDK retries for Claude.
RETRY_BACKOFF_S = (1.0, 2.0)


async def _post_json(
    client: httpx.AsyncClient, url: str, body: dict, headers: dict, profile: ModelProfile
) -> dict:
    for attempt, wait in enumerate((*RETRY_BACKOFF_S, None)):
        try:
            response = await client.post(url, json=body, headers=headers, timeout=300)
        except httpx.HTTPError as e:
            if wait is None:
                raise CloudError(f"I couldn't reach {profile.name}. Is the internet up?") from e
            log.info("%s didn't answer (%s); trying again in %ss", profile.name, e, wait)
            await asyncio.sleep(wait)
            continue
        if wait is None or (response.status_code != 429 and response.status_code < 500):
            break
        log.info(
            "%s answered %s (go %s); trying again in %ss",
            profile.name,
            response.status_code,
            attempt + 1,
            wait,
        )
        await asyncio.sleep(wait)
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
        prices: Prices | None = None,
    ) -> None:
        self.memory = memory
        self.api_key = api_key
        self.providers = providers
        self.prices = prices or Prices(None)  # built-in prices until one is given

    async def close(self) -> None:
        """Let go of the providers' connections (when Kit stops)."""
        for provider in self.providers.values():
            close = getattr(provider, "close", None)
            if close is not None:
                await close()

    async def answer(
        self,
        profile: ModelProfile,
        messages: list[dict],
        settings: Settings,
        question: str = "",
        on_step: Step | None = None,
        priority: str = "chat",
        on_text: Text | None = None,
        tools: list[dict] | None = None,
    ) -> CloudAnswer:
        """``question`` is what Dan asked, for the spend log. ``on_step`` hears about
        progress (web searches so far) while the model is still working. ``priority``
        is the call's place in ``SKIP_ORDER``. ``on_text`` hears the answer as it's
        written, where the provider can stream (Claude); the rest answer in one go."""
        provider = self.providers.get(profile.provider)
        if provider is None:
            raise CloudError(f"I don't know how to talk to {profile.provider} models.")
        spent = self.memory.month_spend()
        cap = settings.cloud.monthly_cap_aud
        kept = settings.cloud.reserve_aud * SKIP_ORDER.get(priority, 1)
        if spent >= cap - kept:
            saving = f", keeping the last A${kept:.2f} for my nightly reflection" if kept else ""
            raise CloudError(
                f"I've used this month's cloud budget (A${spent:.2f} of A${cap:.2f}{saving}). "
                "You can raise cloud.monthly_cap_aud in my settings."
            )
        key = self.api_key(profile.provider)
        if not key:
            raise CloudError(
                f"I can't reach {profile.name}: there's no {profile.provider} API key in my "
                "secrets folder."
            )
        system, turns = split_messages(messages)
        where = Where.of(settings.persona)
        if on_text is None and not tools:
            done = await provider.complete(profile, system, turns, key, on_step, where)
        else:
            done = await provider.complete(
                profile, system, turns, key, on_step, where, on_text, tools=tools or None
            )
        cost = self.prices.cost(profile.model, profile.provider, done.usage)
        question = question or _last_words(turns)
        self.memory.record_spend(
            done.model,
            done.usage.input_tokens,
            done.usage.output_tokens,
            cost.usd,
            question,
            cached_tokens=done.usage.cached_tokens,
            cache_write_tokens=done.usage.cache_write_tokens,
            searches=done.usage.searches,
            cost_aud=cost.aud,
            aud_per_usd=cost.aud_per_usd,
        )
        if done.refused:
            raise CloudError(f"{profile.name} declined to answer that one.")
        if not done.text and not done.calls:
            raise CloudError(f"{profile.name} came back empty.")
        return CloudAnswer(
            done.text,
            done.model,
            cost.aud,
            done.usage.searches,
            done.truncated,
            calls=done.calls,
            content=done.content,
        )


def _last_words(turns: list[dict]) -> str:
    """The last thing Dan said, for the spend log: a tool-result turn has no words
    of his, so the turn before it is used."""
    for t in reversed(turns):
        if t["role"] == "user" and isinstance(t.get("content"), str) and t["content"]:
            return t["content"]
    return ""
