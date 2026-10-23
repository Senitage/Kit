"""Dan's apps as packs: each app's MCP server becomes one pack of Kit's tools.

An app joins by running an MCP server (kit.mcp_client) and getting a line under
``apps.servers`` in Kit's settings: its address or the command that starts it, a
token from the secrets folder, and the words and questions that load it. ``App``
keeps the connection: it connects, lists the server's tools, lists them again every
``apps.relist_minutes`` or when the server says they changed, and reconnects with
a growing wait when the app goes away. Its pack wraps each tool the server lists:
the schema and description as the server gives them, and the effect from the
tool's annotations, so a read-only tool just runs, one marked not destructive is
an ``act``, and anything else (marked destructive, or not marked at all) asks
first. Two tools of Kit's own join every app's pack: ``<app>_status`` says whether
it's reachable (so "it's out of reach" is said, not guessed) and ``<app>_find``
searches the app's saved work in memory. A server tool named ``contents`` isn't
offered to the model: once a day its rows go into the knowledge index as the
``app:<name>`` source (``write_contents``), so recall, the memory page and the
register find them. A private app's results reach a cloud model only as the local
model's summary (kit.tools.private). Kit never needs an app to run: while one is
down, only its status tool is offered. See docs/2 How Kit Works/Other Apps.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from kit.mcp_client import HttpClient, McpClient, McpError, McpGone, StdioClient
from kit.prompt import recall_results
from kit.tools import Pack, Tool, ToolResult

if TYPE_CHECKING:
    from kit.brain import Brain
    from kit.knowledge import Index
    from kit.settings import AppServer, Settings

log = logging.getLogger(__name__)

CONTENTS = "contents"  # the server tool whose rows go into memory (write_contents)
CONTENTS_MAX = 20_000
RESULT_CHARS = 8000
FIND_K = 8
WAIT_FIRST_S = 5.0
WAIT_MOST_S = 300.0
_NAME = re.compile(r"[^A-Za-z0-9_-]+")

Connect = Callable[["App"], McpClient]


def source_of(name: str) -> str:
    """The knowledge index source for an app's saved work."""
    return f"app:{name}"


def tool_name(app: str, tool: str) -> str:
    """The name Kit's models see: the app's name, then the tool's, in the characters
    every provider takes, at most 64 long."""
    return _NAME.sub("_", f"{app}_{tool}")[:64]


def effect_of(annotations: dict | None) -> str:
    """read, act or change, from the tool's MCP annotations. As the protocol has
    it, a tool that doesn't say it's read-only or harmless may change things, so it
    asks first."""
    a = annotations or {}
    if a.get("readOnlyHint") is True:
        return "read"
    if a.get("destructiveHint") is False:
        return "act"
    return "change"


def result_text(result: dict) -> str:
    """A tool call's answer as text: its text blocks joined, anything else described
    (never passed on whole), and structured content when there's no text."""
    parts: list[str] = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text", "")))
        elif kind in ("image", "audio"):
            size = len(str(block.get("data", ""))) * 3 // 4
            parts.append(f"[{'an' if kind == 'image' else 'a'} {kind}, "
                         f"{block.get('mimeType', '?')}, {size // 1024} kB]")  # fmt: skip
        elif kind == "resource":
            res = block.get("resource") or {}
            parts.append(str(res.get("text")) if "text" in res else f"[a file: {res.get('uri')}]")
        elif kind == "resource_link":
            parts.append(f"[a link: {block.get('name') or ''} {block.get('uri', '')}]".strip())
    if not any(p.strip() for p in parts) and result.get("structuredContent") is not None:
        parts = [json.dumps(result["structuredContent"], ensure_ascii=False)]
    text = "\n".join(parts).strip()
    if len(text) > RESULT_CHARS:
        text = text[:RESULT_CHARS] + f"\n[... {len(text) - RESULT_CHARS} more characters]"
    return text


class App:
    """One app's MCP server: the connection, its tools and Kit's pack for them."""

    def __init__(
        self,
        name: str,
        server: AppServer,
        token: str | None,
        settings: Callable[[], Settings],
        connect: Connect | None = None,
    ) -> None:
        self.name = name
        self.server = server
        self.token = token
        self.settings = settings
        self.connect = connect
        self.client: McpClient | None = None
        self.connected = False
        self.last_error = ""
        self.tools: list[dict] = []  # as the server lists them
        self.title = name.replace("_", " ")
        self._changed: asyncio.Event | None = None
        self.brain: Brain | None = None  # set by Brain.use_app; find searches its memory
        self.pack = Pack(
            name,
            self._card(),
            words=sorted({*server.words, name, name.replace("_", " ")}),
            questions=list(server.questions),
            systems=[name],
        )
        self.pack.tools[:] = self._own  # its status, before it's ever reached

    # The connection

    def _client(self) -> McpClient:
        if self.connect is not None:
            return self.connect(self)
        if self.server.url:
            return HttpClient(self.server.url, self.token, self._notified)
        env = {"KIT_APP_TOKEN": self.token} if self.token else {}
        return StdioClient(list(self.server.command), env, self._notified)

    def _notified(self, method: str, params: dict) -> None:
        if method == "notifications/tools/list_changed" and self._changed is not None:
            self._changed.set()

    async def connect_once(self) -> bool:
        """Connect and list the tools. False, with ``last_error``, when it can't."""
        await self._drop()
        client = self._client()
        try:
            await client.start()
            tools = await client.list_tools()
        except (McpError, OSError) as e:
            self.last_error = str(e) or type(e).__name__
            self.pack.card = self._card()
            await _quietly_close(client)
            return False
        self.client = client
        self.title = str(client.server.get("title") or client.server.get("name") or self.title)
        self._take(tools)
        self.connected = True
        self.last_error = ""
        return True

    async def relist(self) -> None:
        assert self.client is not None
        self._take(await self.client.list_tools())

    def _take(self, tools: list[dict]) -> None:
        self.tools = [t for t in tools if isinstance(t, dict) and t.get("name")]
        self.pack.card = self._card()
        self.pack.tools[:] = self._wrapped()
        named = {t["name"]: tool_name(self.name, t["name"]) for t in self.tools}
        self.pack.confirm = [named[n] for n in self.server.confirm if n in named]

    async def _drop(self) -> None:
        self.connected = False
        self.pack.card = self._card()
        client, self.client = self.client, None
        if client is not None:
            await _quietly_close(client)

    async def run(self) -> None:
        """Keep connected, for as long as Kit runs: list the tools again every
        ``apps.relist_minutes`` or when the server says they changed, and reconnect
        with a growing wait (up to five minutes) when it goes away."""
        self._changed = asyncio.Event()
        wait = WAIT_FIRST_S
        while True:
            if not self.connected:
                if await self.connect_once():
                    wait = WAIT_FIRST_S
                    log.info("%s: connected, %d tools", self.name, len(self.tools))
                else:
                    log.info("%s: out of reach (%s)", self.name, self.last_error)
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, WAIT_MOST_S)
                    continue
            gap = self.settings().apps.relist_minutes * 60
            ended = getattr(self.client, "ended", None)
            waits = {asyncio.ensure_future(self._changed.wait())}
            if ended is not None:
                waits.add(asyncio.ensure_future(ended.wait()))
            try:
                await asyncio.wait(waits, timeout=gap, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for w in waits:
                    w.cancel()
            self._changed.clear()
            try:
                if ended is not None and ended.is_set():
                    raise McpGone("the server stopped")
                await self.relist()
            except McpError as e:
                self.last_error = str(e)
                await self._drop()

    async def call(self, tool: str, arguments: dict) -> dict:
        if not self.connected or self.client is None:
            raise McpGone(self.last_error or "not connected")
        try:
            return await self.client.call_tool(tool, arguments)
        except McpGone as e:
            self.last_error = str(e)
            await self._drop()
            if self._changed is not None:
                self._changed.set()  # run() reconnects
            raise

    async def close(self) -> None:
        await self._drop()

    def has(self, tool: str) -> bool:
        return any(t["name"] == tool for t in self.tools)

    # The pack

    def _card(self) -> str:
        card = self.server.card or f"{self.title}, one of the owner's own apps"
        return card if self.connected or not self.last_error else f"{card} (out of reach now)"

    def _wrapped(self) -> list[Tool]:
        tools = [t for t in self.tools if t["name"] != CONTENTS]
        return [*(self._wrap(t) for t in tools), *self._own]

    def _wrap(self, spec: dict) -> Tool:
        name = spec["name"]
        schema = spec.get("inputSchema") or {}
        title = spec.get("title") or (spec.get("annotations") or {}).get("title") or name
        description = str(spec.get("description") or title).strip()

        async def run(args: dict) -> ToolResult:
            try:
                result = await self.call(name, args)
            except McpGone as e:
                return ToolResult(f"{self.title} is out of reach ({e}). Say so plainly.", ok=False)
            except McpError as e:
                return ToolResult(f"{self.title} said: {e}", ok=False)
            text = result_text(result) or "(done, nothing to show)"
            return ToolResult(
                text,
                step=f"used {title} in {self.title}",
                private=self.server.private,
                ok=not result.get("isError"),
            )

        return Tool(
            tool_name(self.name, name),
            f"{description} (In {self.title}.)",
            run,
            dict(schema.get("properties") or {}),
            list(schema.get("required") or []),
            effect=effect_of(spec.get("annotations")),  # type: ignore[arg-type]
            offered=lambda: self.connected,
            ask=f"use {title} in {self.title}",
            defs=dict(schema.get("$defs") or {}),
        )

    @property
    def _own(self) -> list[Tool]:
        return [self._status_tool, self._find_tool]

    @property
    def _status_tool(self) -> Tool:
        async def status(args: dict) -> ToolResult:
            if not self.connected:
                why = f" ({self.last_error})" if self.last_error else ""
                return ToolResult(
                    f"{self.title} is out of reach right now{why}. Say so plainly; "
                    "everything else about you is fine."
                )
            names = ", ".join(t["name"] for t in self.tools if t["name"] != CONTENTS)
            return ToolResult(f"{self.title} is connected. Its tools: {names or 'none'}.")

        return Tool(
            tool_name(self.name, "status"),
            f"Whether {self.title} can be reached now, and what Kit can do in it.",
            status,
        )

    @property
    def _find_tool(self) -> Tool:
        source = source_of(self.name)

        async def find(args: dict) -> ToolResult:
            query = str(args.get("query", "")).strip()
            hits = await self.brain.recall.search(query, [source], FIND_K)
            owner = self.settings().persona.owner
            return ToolResult(
                recall_results(query, hits, owner),
                step=f"looked through {self.title} for '{query}'",
                private=self.server.private,
            )

        return Tool(
            tool_name(self.name, "find"),
            f"Search {self.title}'s saved work, as Kit last read it (once a day), by "
            "words and meaning. Use it to find something to open or read with the app's "
            "own tools.",
            find,
            {"query": {"type": "string", "description": "What to look for."}},
            ["query"],
            offered=lambda: self.brain is not None and bool(self.brain.memory.index.count(source)),
        )


async def _quietly_close(client: McpClient) -> None:
    try:
        await client.close()
    except Exception:  # closing a broken connection
        log.debug("closing an MCP client failed", exc_info=True)


def rows_of(result: dict) -> list[dict]:
    """The rows a ``contents`` tool gave: ``structuredContent.rows``, or a JSON list
    (or {"rows": [...]}) in its text."""
    data: Any = result.get("structuredContent")
    if not isinstance(data, (dict, list)):
        try:
            data = json.loads(result_text({"content": result.get("content")}) or "null")
        except ValueError:
            data = None
    if isinstance(data, dict):
        data = data.get("rows")
    return [r for r in data or [] if isinstance(r, dict)] if isinstance(data, list) else []


async def write_contents(app: App, index: Index) -> int:
    """Replace the app's saved work in memory with its ``contents`` rows now: one
    item per row, ``{"kind", "ref", "text", ...}``, the rest of the row kept as its
    meta. Nothing changes when the app is down or has no such tool."""
    if not app.connected or not app.has(CONTENTS):
        return 0
    rows = rows_of(await app.call(CONTENTS, {}))
    source = source_of(app.name)
    index.delete_source(source)
    n = 0
    for row in rows[:CONTENTS_MAX]:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        meta = {k: v for k, v in row.items() if k != "text"}
        if app.server.private:
            meta["private"] = True
        title = str(row.get("title") or text.split(",")[0])[:200]
        index.add(source, str(row.get("kind") or "item"), text, title=title,
                  ref=str(row.get("ref") or "") or None, meta=meta)  # fmt: skip
        n += 1
    return n
