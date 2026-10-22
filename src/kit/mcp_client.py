"""A small MCP client: how Kit talks to an app's MCP server (kit.tools.mcp).

The Model Context Protocol is JSON-RPC 2.0. Kit needs only its client half: say
hello (``initialize``), list the server's tools (``tools/list``), call one
(``tools/call``) and hear that the list changed (``notifications/tools/list_changed``).
Two ways to reach a server: **streamable HTTP**, a POST per message to its URL with
the answer as JSON or a short event stream (an app on another machine), and
**stdio**, a program Kit starts and talks to line by line (a server on the same
box). Both are here in a few hundred lines rather than the ``mcp`` package, which
would bring a web server and a second HTTP library onto the box for the same four
messages. See docs/2 How Kit Works/Other Apps.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger(__name__)

PROTOCOL = "2025-06-18"
CLIENT = {"name": "kit", "version": "1"}
CALL_TIMEOUT_S = 60.0
START_TIMEOUT_S = 20.0

Notify = Callable[[str, dict], None]


class McpError(Exception):
    """The server answered with an error, or couldn't be reached (McpGone)."""


class McpGone(McpError):
    """The server can't be reached, or stopped: the connection has to start again."""


class McpClient:
    """One connection to one MCP server. ``on_notify(method, params)`` hears what
    the server says unasked (the tool list changed)."""

    def __init__(self, on_notify: Notify | None = None) -> None:
        self.on_notify = on_notify
        self.server: dict = {}  # the server's name and version, from initialize
        self.capabilities: dict = {}
        self._ids = itertools.count(1)

    async def start(self) -> None:
        await self._open()
        result = await self.request(
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT},
            START_TIMEOUT_S,
        )
        self.server = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        await self.notify("notifications/initialized")

    async def list_tools(self) -> list[dict]:
        """Every tool the server offers, following its pages."""
        tools: list[dict] = []
        cursor = None
        for _ in range(50):  # a server that never stops paging
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict,
                        timeout_s: float = CALL_TIMEOUT_S) -> dict:  # fmt: skip
        return await self.request("tools/call", {"name": name, "arguments": arguments}, timeout_s)

    async def request(self, method: str, params: dict | None = None,
                      timeout_s: float = CALL_TIMEOUT_S) -> dict:  # fmt: skip
        message = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            message["params"] = params
        answer = await self._exchange(message, timeout_s)
        if "error" in answer:
            error = answer["error"] or {}
            raise McpError(f"{method}: {error.get('message') or error}")
        return answer.get("result") or {}

    async def notify(self, method: str, params: dict | None = None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    def _heard(self, message: dict) -> None:
        if "method" in message and "id" not in message and self.on_notify is not None:
            try:
                self.on_notify(message["method"], message.get("params") or {})
            except Exception:  # a listener's bug mustn't break the connection
                log.exception("an MCP notification handler failed")

    async def close(self) -> None:
        pass

    # Each transport fills these in.

    async def _open(self) -> None:
        raise NotImplementedError

    async def _send(self, message: dict) -> None:
        raise NotImplementedError

    async def _exchange(self, message: dict, timeout_s: float) -> dict:
        raise NotImplementedError


class HttpClient(McpClient):
    """Streamable HTTP: each message is a POST; the answer comes back as JSON or as
    a short event stream ending with it. The server's session id rides on every
    request after the first."""

    def __init__(self, url: str, token: str | None = None, on_notify: Notify | None = None,
                 http: httpx.AsyncClient | None = None) -> None:  # fmt: skip
        super().__init__(on_notify)
        self.url = url
        self.token = token
        self._http = http
        self._own_http = http is None
        self.session: str | None = None

    async def _open(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(CALL_TIMEOUT_S, connect=10))

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        return headers

    async def _post(self, message: dict, timeout_s: float) -> httpx.Response:
        assert self._http is not None
        try:
            response = await self._http.post(
                self.url, json=message, headers=self._headers(), timeout=timeout_s
            )
        except httpx.HTTPError as e:
            raise McpGone(f"can't reach {self.url}: {type(e).__name__}") from e
        if response.status_code in (401, 403):
            raise McpGone(f"{self.url} refused Kit's token ({response.status_code})")
        if response.status_code == 404 and self.session:
            self.session = None  # the server forgot the session: start again
            raise McpGone(f"{self.url} ended the session")
        if response.status_code >= 400:
            raise McpGone(f"{self.url} answered {response.status_code}")
        if "mcp-session-id" in response.headers:
            self.session = response.headers["mcp-session-id"]
        return response

    async def _send(self, message: dict) -> None:
        await self._post(message, CALL_TIMEOUT_S)

    async def _exchange(self, message: dict, timeout_s: float) -> dict:
        response = await self._post(message, timeout_s)
        kind = response.headers.get("content-type", "").split(";")[0].strip()
        found: list[dict] = []
        if kind == "text/event-stream":
            for data in _events(response.text):
                found += data
        else:
            try:
                body = response.json()
            except ValueError as e:
                raise McpError(f"{self.url} didn't answer in JSON") from e
            found = body if isinstance(body, list) else [body]
        answer = None
        for item in found:
            if not isinstance(item, dict):
                continue
            if item.get("id") == message["id"] and ("result" in item or "error" in item):
                answer = item
            else:
                self._heard(item)
        if answer is None:
            raise McpError(f"{self.url} didn't answer {message['method']}")
        return answer

    async def close(self) -> None:
        if self._http is not None and self.session:
            with contextlib.suppress(httpx.HTTPError):
                await self._http.delete(self.url, headers=self._headers(), timeout=5)
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None


def _events(text: str) -> list[list[dict]]:
    """The JSON messages in an event stream, one list per event."""
    out: list[list[dict]] = []
    data: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n") + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            try:
                parsed = json.loads("\n".join(data))
            except ValueError:
                parsed = None
            if parsed is not None:
                out.append(parsed if isinstance(parsed, list) else [parsed])
            data = []
    return out


class StdioClient(McpClient):
    """A server Kit starts as a program, one JSON message per line each way."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None,
                 on_notify: Notify | None = None) -> None:  # fmt: skip
        super().__init__(on_notify)
        self.command = command
        self.env = env or {}
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._waiting: dict[Any, asyncio.Future] = {}
        self.ended = asyncio.Event()

    async def _open(self) -> None:
        if not self.command:
            raise McpError("no command to start")
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ, **self.env},
                limit=16 * 1024 * 1024,  # a long tool result is one line
            )
        except OSError as e:
            raise McpGone(f"couldn't start {self.command[0]}: {e.strerror or e}") from e
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # a server's stray print
                if not isinstance(message, dict):
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    future = self._waiting.pop(message["id"], None)
                    if future is not None and not future.done():
                        future.set_result(message)
                else:
                    self._heard(message)
        except (OSError, ValueError, asyncio.LimitOverrunError):
            pass
        finally:
            self.ended.set()
            for future in self._waiting.values():
                if not future.done():
                    future.set_exception(McpGone(f"{self.command[0]} stopped"))
            self._waiting.clear()

    async def _send(self, message: dict) -> None:
        if self._proc is None or self._proc.stdin is None or self.ended.is_set():
            raise McpGone(f"{self.command[0]} isn't running")
        try:
            self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()
        except (OSError, RuntimeError) as e:
            raise McpGone(f"{self.command[0]} stopped") from e

    async def _exchange(self, message: dict, timeout_s: float) -> dict:
        future = asyncio.get_running_loop().create_future()
        self._waiting[message["id"]] = future
        await self._send(message)
        done, _ = await asyncio.wait({future}, timeout=timeout_s)
        if not done:
            self._waiting.pop(message["id"], None)
            raise McpGone(f"{self.command[0]} didn't answer {message['method']} in time")
        return future.result()

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.stdin is not None:
                with contextlib.suppress(OSError, RuntimeError):
                    proc.stdin.close()
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                done, _ = await asyncio.wait({asyncio.ensure_future(proc.wait())}, timeout=3)
                if not done:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()
        if self._reader is not None:
            await asyncio.wait({self._reader}, timeout=3)
            self._reader = None
