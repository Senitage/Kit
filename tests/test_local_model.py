import asyncio
import json

import httpx
import pytest

from kit.local_model import LocalModelError, OllamaModel
from kit.settings import OllamaSettings


def model_with(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaModel(lambda: OllamaSettings(), client)


def run(model):
    async def go():
        return [p async for p in model.stream([{"role": "user", "content": "hi"}], {"x": 1})]

    return asyncio.run(go())


def test_streams_pieces_and_sends_schema():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        lines = [
            {"message": {"content": '{"a"'}, "done": False},
            {"message": {"content": ": 1}"}, "done": False},
            {"message": {"content": ""}, "done": True},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))

    assert run(model_with(handler)) == ['{"a"', ": 1}"]
    assert seen["format"] == {"x": 1} and seen["stream"] is True
    assert seen["think"] is False and seen["model"] == "qwen3:8b"
    assert seen["options"] == {"temperature": 0.7, "num_ctx": 8192}


def test_http_error_status():
    with pytest.raises(LocalModelError, match="404"):
        run(model_with(lambda r: httpx.Response(404, text="model not found")))


def test_error_line():
    with pytest.raises(LocalModelError, match="out of memory"):
        run(model_with(lambda r: httpx.Response(200, text='{"error": "out of memory"}')))


def test_unreachable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LocalModelError, match="can't reach Ollama"):
        run(model_with(handler))


def test_plain_text_and_livelier_sampling_when_asked():
    from kit.local_model import lively

    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=json.dumps({"message": {"content": "Hi."}, "done": True}))

    model = model_with(handler)
    options = lively(OllamaSettings())

    async def go():
        return await model.complete(
            [{"role": "user", "content": "hi"}], None, "gemma4:e4b", options
        )

    assert asyncio.run(go()) == "Hi."
    assert "format" not in seen and seen["model"] == "gemma4:e4b"
    assert seen["options"] == {
        "temperature": 0.95,
        "num_ctx": 8192,
        "min_p": 0.05,
        "top_k": 64,
        "top_p": 0.95,
        "repeat_penalty": 1.08,
        "repeat_last_n": 64,
    }
    json_options = lively(OllamaSettings(), plain=False)
    assert "repeat_penalty" not in json_options and "repeat_last_n" not in json_options


def test_reading_ahead_fills_the_cache_with_the_same_model_and_context():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "O"}, "done": True})

    messages = [{"role": "system", "content": "You are Kit."}]
    asyncio.run(model_with(handler).warm(messages))
    assert seen["messages"] == messages and seen["stream"] is False
    assert seen["model"] == "qwen3:8b" and "format" not in seen
    # The same context size as every other call, or Ollama would reload the model.
    assert seen["options"] == {"temperature": 0.7, "num_ctx": 8192, "num_predict": 1}
    with pytest.raises(LocalModelError, match="500"):
        asyncio.run(model_with(lambda r: httpx.Response(500, text="boom")).warm(messages))


def test_how_much_ollama_read_goes_in_the_log(caplog):
    done = {
        "message": {"content": "Hi."},
        "done": True,
        "prompt_eval_count": 120,
        "prompt_eval_duration": 80_000_000,
        "eval_count": 9,
        "eval_duration": 150_000_000,
    }
    model = model_with(lambda r: httpx.Response(200, text=json.dumps(done)))
    with caplog.at_level("INFO", logger="kit.local_model"):
        assert run(model) == ["Hi."]
    assert "read 120 tokens in 0.08 s, wrote 9 in 0.15 s" in caplog.text
