import asyncio
import json

import anthropic
import httpx
import pytest

from fakes import Clock, FakeAnthropic, make_cloud
from kit.cloud import (
    ANTHROPIC_SEARCH_TOOL,
    BASIC_FETCH_TOOL,
    BASIC_SEARCH_TOOL,
    FALLBACK_BETA,
    CloudError,
    GoogleProvider,
    OpenAIProvider,
    Usage,
    Where,
    _web_steps,
    estimate_cost,
    split_messages,
)
from kit.memory import Memory
from kit.settings import ModelProfile, Settings


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


MESSAGES = [
    {"role": "system", "content": "You are Kit."},
    {"role": "user", "content": "Why?"},
]


def ask(cloud, name="opus", settings=None, messages=MESSAGES):
    settings = settings or Settings()
    return asyncio.run(cloud.answer(settings.models[name], messages, settings))


def test_claude_answer_and_spend_logged(memory):
    fake = FakeAnthropic()
    answer = ask(make_cloud(memory, fake))
    assert answer.text == "The answer is 42."
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == [FALLBACK_BETA]
    assert call["output_config"] == {"effort": "medium"}
    system = call["system"][0]
    assert system["text"] == "You are Kit." and system["cache_control"] == {"type": "ephemeral"}
    assert call["messages"] == [{"role": "user", "content": "Why?"}]
    assert call["tools"][0]["type"] == ANTHROPIC_SEARCH_TOOL
    # 1000 in at $4/M + 2000 out at $20/M
    assert answer.cost_usd == pytest.approx(0.044)
    assert memory.month_spend() == pytest.approx(0.044)


def test_web_search_can_be_turned_off(memory):
    fake = FakeAnthropic()
    s = Settings.model_validate({"models": {"opus": {"web_search": False}}})
    ask(make_cloud(memory, fake), settings=s)
    assert "tools" not in fake.calls[0]


def test_haiku_gets_the_basic_web_tools_and_no_fallback(memory):
    fake = FakeAnthropic()
    answer = ask(make_cloud(memory, fake), "haiku")
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert [t["type"] for t in call["tools"]] == [BASIC_SEARCH_TOOL, BASIC_FETCH_TOOL]
    assert "fallbacks" not in call and "betas" not in call
    # 1000 in at $0.10/M + 2000 out at $0.50/M
    assert answer.cost_usd == pytest.approx(0.0011)


def test_searches_are_counted_and_priced(memory):
    answer = ask(make_cloud(memory, FakeAnthropic(searches=2)))
    # 0.044 for tokens + 2 searches at $10 per 1,000
    assert answer.searches == 2 and answer.cost_usd == pytest.approx(0.064)


def test_paused_search_is_resumed(memory):
    fake = FakeAnthropic(answer=["Looking. ", "Found it."], stop_reason=["pause_turn", "end_turn"])
    answer = ask(make_cloud(memory, fake))
    assert answer.text == "Looking. Found it." and len(fake.calls) == 2
    assert fake.calls[1]["messages"][-1]["role"] == "assistant"
    assert answer.cost_usd == pytest.approx(0.088)  # both calls billed


def test_progress_is_reported_while_a_search_runs(memory):
    fake = FakeAnthropic(
        answer=["Looking. ", "Found it."],
        stop_reason=["pause_turn", "end_turn"],
        queries=["pump curves"],
    )
    steps = []
    cloud = make_cloud(memory, fake)
    profile = Settings().models["sonnet"]
    asyncio.run(cloud.answer(profile, MESSAGES, Settings(), on_step=steps.append))
    assert steps == ["searched the web for 'pump curves'"]


PERTH = {"persona": {"location": "Perth, WA", "country": "AU", "timezone": "Australia/Perth"}}


def test_searches_know_where_dan_is(memory):
    fake = FakeAnthropic()
    ask(make_cloud(memory, fake), settings=Settings.model_validate(PERTH))
    search, fetch = fake.calls[0]["tools"]
    assert search["user_location"] == {
        "type": "approximate",
        "city": "Perth",
        "region": "WA",
        "country": "AU",
        "timezone": "Australia/Perth",
    }
    assert fetch["name"] == "web_fetch" and fetch["max_content_tokens"] > 0


def test_no_location_means_no_user_location(memory):
    fake = FakeAnthropic()
    ask(make_cloud(memory, fake))
    assert "user_location" not in fake.calls[0]["tools"][0]
    assert Where.of(Settings().persona).approximate() is None
    assert Where.of(Settings.model_validate({"persona": {"location": "Perth"}}).persona).city == (
        "Perth"
    )


def test_bad_country_code_is_refused():
    with pytest.raises(ValueError):
        Settings.model_validate({"persona": {"country": "Australia"}})


def test_opening_a_page_is_reported():
    from types import SimpleNamespace as NS

    content = [
        NS(type="server_tool_use", input={"query": "perth forecast"}),
        NS(
            type="server_tool_use", input={"url": "https://www.bom.gov.au/wa/forecasts/perth.shtml"}
        ),
        NS(type="text", text="hi"),
    ]
    assert _web_steps(content) == [
        "searched the web for 'perth forecast'",
        "opened https://www.bom.gov.au/wa/forecasts/perth.shtml",
    ]


def test_cost_estimate():
    opus = Settings().models["opus"]
    assert estimate_cost(opus, Usage(input_tokens=1_000_000)) == 4.0
    assert estimate_cost(opus, Usage(output_tokens=1_000_000)) == 20.0
    # On Opus 5.5 a cache read costs 0.05x input; a cache write costs 1.25x.
    assert estimate_cost(opus, Usage(1_000_000, cached_tokens=1_000_000)) == 0.2
    assert estimate_cost(opus, Usage(1_000_000, cache_write_tokens=1_000_000)) == 5.0
    assert estimate_cost(opus, Usage(searches=1000)) == 10.0


def test_cached_tokens_are_billed_at_the_cache_rate(memory):
    answer = ask(make_cloud(memory, FakeAnthropic(cache_read_input_tokens=1000)))
    # 1000 fresh at $4/M + 1000 cached at $0.20/M + 2000 out at $20/M
    assert answer.cost_usd == pytest.approx(0.0442)


def test_cap_stops_calls(memory):
    memory.record_spend("m", 0, 0, 40.0, "earlier")
    fake = FakeAnthropic()
    with pytest.raises(CloudError, match="budget"):
        ask(make_cloud(memory, fake))
    assert fake.calls == []


def test_no_key(memory):
    with pytest.raises(CloudError, match="API key"):
        ask(make_cloud(memory, key=None))


def test_refusal_is_reported_but_still_costed(memory):
    with pytest.raises(CloudError, match="declined"):
        ask(make_cloud(memory, FakeAnthropic(stop_reason="refusal")))
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
def test_claude_errors_become_plain_messages(memory, error, words):
    with pytest.raises(CloudError, match=words):
        ask(make_cloud(memory, FakeAnthropic(error=error)))


def test_fixed_prompt_is_cached_and_this_turn_is_not():
    from kit.cloud import system_blocks

    blocks = system_blocks("You are Kit.\nRules.\n\nIt is Monday.\nMemories.")
    assert blocks[0] == {
        "type": "text",
        "text": "You are Kit.\nRules.",
        "cache_control": {"type": "ephemeral"},
    }
    assert blocks[1] == {"type": "text", "text": "\n\nIt is Monday.\nMemories."}
    assert system_blocks("No turn part.") == [
        {"type": "text", "text": "No turn part.", "cache_control": {"type": "ephemeral"}}
    ]


def test_messages_are_split_and_made_to_alternate():
    system, turns = split_messages(
        [
            {"role": "system", "content": "S"},
            {"role": "assistant", "content": "dropped: before the first user turn"},
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
            {"role": "user", "content": "d"},
        ]
    )
    assert system == "S"
    assert turns == [
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
        {"role": "user", "content": "d"},
    ]


# --- OpenAI and Gemini, through a fake HTTP server ---------------------------


def fake_http(handler, seen):
    def record(request):
        seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(record))


OPENAI_OK = {
    "model": "gpt-6.1-sol-2026-09-22",
    "status": "completed",
    "output": [
        {"type": "reasoning", "summary": []},
        {"type": "web_search_call", "action": {"type": "search", "queries": ["perth weather"]}},
        {"type": "message", "content": [{"type": "output_text", "text": "Sunny, 24."}]},
    ],
    "usage": {
        "input_tokens": 2000,
        "output_tokens": 500,
        "input_tokens_details": {"cached_tokens": 1000},
    },
}


def openai_cloud(memory, handler, seen):
    client = fake_http(handler, seen)
    return make_cloud(memory, openai=OpenAIProvider(client))


def test_openai_request_and_answer(memory):
    seen = []
    cloud = openai_cloud(memory, lambda r: httpx.Response(200, json=OPENAI_OK), seen)
    answer = ask(cloud, "gpt-sol")
    body = json.loads(seen[0].content)
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert body["model"] == "gpt-6.1-sol" and body["instructions"] == "You are Kit."
    assert body["input"] == [{"role": "user", "content": "Why?"}]
    assert body["reasoning"] == {"effort": "low"} and body["store"] is False
    assert body["tools"] == [{"type": "web_search"}]
    assert answer.text == "Sunny, 24." and answer.searches == 1
    # 1000 fresh at $2/M + 1000 cached at $0.10/M + 500 out at $10/M + 1 search at $10/1000
    assert answer.cost_usd == pytest.approx(0.002 + 0.0001 + 0.005 + 0.01)
    assert memory.spend_log()[0].model == "gpt-6.1-sol-2026-09-22"


def test_openai_cut_short_and_refusal(memory):
    cut = {
        **OPENAI_OK,
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
    }
    seen = []
    answer = ask(openai_cloud(memory, lambda r: httpx.Response(200, json=cut), seen), "gpt-sol")
    assert answer.truncated
    refusal = {**OPENAI_OK, "output": [{"type": "message", "content": [{"type": "refusal"}]}]}
    cloud = openai_cloud(memory, lambda r: httpx.Response(200, json=refusal), seen)
    with pytest.raises(CloudError, match="declined"):
        ask(cloud, "gpt-sol")


@pytest.mark.parametrize(
    ("status", "words"), [(401, "rejected"), (429, "rate-limiting"), (404, "doesn't know")]
)
def test_openai_errors(memory, status, words):
    cloud = openai_cloud(memory, lambda r: httpx.Response(status, json={"error": {}}), [])
    with pytest.raises(CloudError, match=words):
        ask(cloud, "gpt-sol")


def test_openai_offline(memory):
    def down(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(CloudError, match="reach"):
        ask(openai_cloud(memory, down, []), "gpt-sol")


GEMINI_OK = {
    "modelVersion": "gemini-3.8-flash",
    "candidates": [
        {
            "finishReason": "STOP",
            "content": {
                "role": "model",
                "parts": [{"text": "private thoughts", "thought": True}, {"text": "Sunny."}],
            },
            "groundingMetadata": {"webSearchQueries": ["perth weather", "perth forecast"]},
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 2000,
        "cachedContentTokenCount": 1000,
        "candidatesTokenCount": 300,
        "thoughtsTokenCount": 200,
    },
}


def gemini_cloud(memory, handler, seen):
    return make_cloud(memory, google=GoogleProvider(fake_http(handler, seen)))


def test_gemini_request_and_answer(memory):
    seen = []
    cloud = gemini_cloud(memory, lambda r: httpx.Response(200, json=GEMINI_OK), seen)
    s = Settings.model_validate({"models": {"gemini-flash": {"effort": "max"}}})
    answer = ask(cloud, "gemini-flash", settings=s)
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-3.8-flash:generateContent")
    assert request.headers["x-goog-api-key"] == "sk-test"
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": "You are Kit."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Why?"}]}]
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}
    assert body["tools"] == [{"google_search": {}}]
    assert answer.text == "Sunny." and answer.searches == 2
    # 1000 fresh at $0.75/M + 1000 cached at $0.075/M + 500 out (thinking included)
    # at $3.75/M + 2 searches at $14/1000
    assert answer.cost_usd == pytest.approx(0.00075 + 0.000075 + 0.001875 + 0.028)


def test_gemini_assistant_turns_are_model_turns(memory):
    seen = []
    cloud = gemini_cloud(memory, lambda r: httpx.Response(200, json=GEMINI_OK), seen)
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    ask(cloud, "gemini-flash", messages=messages)
    roles = [c["role"] for c in json.loads(seen[0].content)["contents"]]
    assert roles == ["user", "model", "user"]


def test_gemini_blocked_is_declined(memory):
    blocked = {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {}}
    cloud = gemini_cloud(memory, lambda r: httpx.Response(200, json=blocked), [])
    with pytest.raises(CloudError, match="declined"):
        ask(cloud, "gemini-flash")


def test_unknown_provider(memory):
    s = Settings.model_validate({"models": {"odd": {"provider": "openai", "model": "x"}}})
    cloud = make_cloud(memory)  # no openai provider given
    with pytest.raises(CloudError, match="openai"):
        asyncio.run(cloud.answer(s.models["odd"], MESSAGES, s))


def test_profile_name_prefers_label():
    assert ModelProfile(provider="openai", model="gpt-x").name == "gpt-x"
    assert ModelProfile(provider="openai", model="gpt-x", label="GPT").name == "GPT"


def test_openai_search_knows_where_dan_is(memory):
    seen = []
    cloud = openai_cloud(memory, lambda r: httpx.Response(200, json=OPENAI_OK), seen)
    ask(cloud, "gpt-sol", settings=Settings.model_validate(PERTH))
    tool = json.loads(seen[0].content)["tools"][0]
    assert tool["user_location"]["city"] == "Perth" and tool["user_location"]["country"] == "AU"
