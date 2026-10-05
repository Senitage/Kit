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
