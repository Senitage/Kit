"""Dan's apps as packs (kit.tools.mcp) over the small MCP client (kit.mcp_client),
against a made-up trip planner's server (fake_mcp_server)."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from fake_mcp_server import Server
from fakes import FakeAnthropic, collect, reply
from kit.checks import Status, check_apps
from kit.mcp_client import HttpClient, McpClient, McpGone, StdioClient
from kit.memory import Memory
from kit.settings import Settings
from kit.tools import ToolCall
from kit.tools.confirm import needs_yes
from kit.tools.mcp import App, effect_of, result_text, rows_of, source_of, tool_name
from tool_helpers import Clock, make

SERVER = str(Path(__file__).with_name("fake_mcp_server.py"))


class InProcess(McpClient):
    """A client whose server is a ``Server`` in the same process."""

    def __init__(self, server: Server, on_notify=None, up=True):
        super().__init__(on_notify)
        self.fake = server
        self.up = up

    async def _open(self):
        if not self.up:
            raise McpGone("connection refused")

    async def _send(self, message):
        self.fake.handle(message)

    async def _exchange(self, message, timeout_s):
        if not self.up:
            raise McpGone("connection refused")
        replies = self.fake.handle(message)
        for r in replies[:-1]:
            self._heard(r)
        return replies[-1]


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def settings(**server) -> Settings:
    return Settings.model_validate(
        {
            "memory": {"min_similarity": 0.3},
            "routing": {"mode": "cloud-only"},
            "apps": {"servers": {"trips": {"url": "http://192.168.1.50:8001/mcp", **server}}},
        }
    )


def trips(memory, fake=None, claude=None, **server):
    s = settings(**server)
    brain, _, claude = make(memory, settings=s, claude=claude)
    fake = fake or Server()
    holder = {}

    def connect(app):
        holder["client"] = InProcess(fake, app._notified, up=holder.get("up", True))
        return holder["client"]

    app = App("trips", s.apps.servers["trips"], "tok", lambda: s, connect)
    brain.use_app(app)
    asyncio.run(app.connect_once())
    return brain, app, fake, holder


def run(brain, tool, **args):
    return asyncio.run(brain.tools.run(ToolCall("1", tool, args)))


def test_the_servers_tools_become_a_pack(memory):
    brain, app, _, _ = trips(memory)
    assert app.connected and app.title == "Trip Planner"
    names = {t.name for t in brain.tools.offered(["trips"])}
    assert names == {
        "trips_list_trips",
        "trips_add_stop",
        "trips_mark_packed",
        "trips_grow",
        "trips_picture",
        "trips_status",
    }  # contents stays out of the model's way; find waits for saved work
    add = brain.tools.get("trips_add_stop")
    assert add.schema()["required"] == ["trip", "place"]
    assert add.description == "Add a stop to a trip. (In Trip Planner.)"
    assert [
        brain.tools.get(f"trips_{n}").effect for n in ("list_trips", "mark_packed", "grow")
    ] == [
        "read",
        "act",
        "change",
    ]
    assert "trips" in brain.tools.packs["trips"].words


def test_effects_and_names():
    assert effect_of({"readOnlyHint": True}) == "read"
    assert effect_of({"destructiveHint": False}) == "act"
    assert effect_of({"destructiveHint": True}) == "change"
    assert effect_of(None) == "change"  # not marked: it may change things, so it asks
    assert tool_name("home_app", "trips.edit") == "home_app_trips_edit"
    assert len(tool_name("a" * 40, "b" * 40)) == 64


def test_a_call_gives_text_and_describes_the_rest(memory):
    brain, _, fake, _ = trips(memory)
    out = run(brain, "trips_list_trips")
    assert out.ok and out.text == "Riverbend trip: Richmond" and not out.private
    picture = run(brain, "trips_picture").text
    assert picture == "Here's the map.\n[an image, image/png, 3 kB]"
    assert run(brain, "trips_mark_packed").text == '{"packed": true}'
    assert fake.calls[0] == ("list_trips", {})
    assert result_text({"content": [{"type": "text", "text": "x" * 9000}]}).endswith(
        "[... 1000 more characters]"
    )


def test_what_asks_first(memory):
    brain, app, _, _ = trips(memory, confirm=["mark_packed"])
    pack, s = brain.tools.packs["trips"], brain.settings()
    asks = {
        n: needs_yes(brain.tools.get(n), pack, s, {}) for n in brain.tools.tool_names(["trips"])
    }
    assert asks["trips_add_stop"] and asks["trips_grow"] and asks["trips_mark_packed"]
    assert not asks["trips_list_trips"] and not asks["trips_status"]


def test_a_change_waits_for_a_yes_in_the_chat(memory):
    claude = FakeAnthropic(
        answer=["", reply("Add Bathurst to the Riverbend trip?"), reply("Added.")],
        tool_calls=[[("trips_add_stop", {"trip": "Riverbend", "place": "Bathurst"})]],
    )
    brain, _, fake, _ = trips(memory, claude=claude)
    collect(brain.chat("add a stop in Bathurst on the Riverbend trip in trips"))
    assert fake.stops == ["Richmond"] and brain.pending_tool is not None
    collect(brain.chat("yes"))
    assert fake.stops == ["Richmond", "Bathurst"]


def test_a_private_app_is_summarised_for_the_cloud(memory):
    brain, _, _, _ = trips(memory, private=True)
    assert run(brain, "trips_list_trips").private


def test_out_of_reach_only_the_status_is_offered(memory):
    brain, app, _, holder = trips(memory)
    holder["client"].up = False
    out = run(brain, "trips_list_trips")
    assert not out.ok and "out of reach" in out.text and not app.connected
    assert {t.name for t in brain.tools.offered(["trips"])} == {"trips_status"}
    assert "out of reach right now (connection refused)" in run(brain, "trips_status").text
    assert brain.tools.cards(["trips"]) == [
        "trips: Trip Planner, one of the owner's own apps (out of reach now)"
    ]
    holder["up"] = True
    assert asyncio.run(app.connect_once())
    assert "trips_list_trips" in {t.name for t in brain.tools.offered(["trips"])}
    assert "is connected. Its tools: list_trips" in run(brain, "trips_status").text


def test_a_changed_tool_list_is_read_again(memory):
    brain, app, _, _ = trips(memory)
    seen = []

    async def go():
        app._changed = asyncio.Event()
        await app.call("grow", {})
        seen.append(app._changed.is_set())
        await app.relist()

    asyncio.run(go())
    assert seen == [True] and brain.tools.get("trips_new_trick") is not None


def test_saved_work_goes_into_memory_once_a_day(memory):
    brain, app, _, _ = trips(memory, private=True)
    assert asyncio.run(brain.app_contents()) == 2
    items = memory.index.items(source_of("trips"))
    calc = next(i for i in items if i.kind == "calc")
    assert calc.ref == "calc:12" and calc.title == "Slurry pump duty" and calc.meta["private"]
    assert asyncio.run(brain.app_contents()) == 0  # not again today
    assert "trips_find" in {t.name for t in brain.tools.offered(["trips"])}
    assert run(brain, "trips_find", query="pump duty").private
    assert rows_of({"content": [{"type": "text", "text": json.dumps(ROWS_TEXT)}]}) == ROWS_TEXT


ROWS_TEXT = [{"kind": "x", "ref": "x:1", "text": "One"}]


def test_kit_check_says_what_each_app_offers(memory):
    s = settings()
    fake = Server()
    up = [check_apps(s, lambda n, t: None, lambda app: InProcess(fake, app._notified))]
    assert up[0][0].status is Status.PASS
    assert up[0][0].detail == "connected to Trip Planner, 5 tools, and saved work for his memory"
    down = check_apps(s, lambda n, t: None, lambda app: InProcess(fake, up=False))
    assert down[0].status is Status.FAIL and "connection refused" in down[0].detail
    missing = check_apps(settings(token_secret="trips_token"), lambda n, t: None)
    assert missing[0].status is Status.FAIL and "trips_token" in missing[0].detail


def test_the_phone_is_told_rather_than_opened():
    from kit.channels import CHANNELS

    assert "tell them things rather than opening them" in CHANNELS["phone"][1]
    assert "say it happened there" in CHANNELS["phone"][1]


def test_stdio_talks_to_a_program_and_notices_it_stopping():
    heard = []

    async def go():
        client = StdioClient([sys.executable, SERVER], on_notify=lambda m, p: heard.append(m))
        await client.start()
        tools = await client.list_tools()
        out = await client.call_tool("grow", {})
        await asyncio.sleep(0.05)
        await client.notify("ping")
        try:
            await client.call_tool("quit", {}, timeout_s=5)
        except McpGone:
            pass
        await asyncio.wait_for(client.ended.wait(), 5)
        with pytest.raises(McpGone):
            await client.call_tool("list_trips", {})
        await client.close()
        return client, tools, out

    client, tools, out = asyncio.run(go())
    assert client.server["name"] == "trips" and len(tools) == 6
    assert out["content"][0]["text"] == "Learned." and heard == ["notifications/tools/list_changed"]


def test_stdio_that_wont_start():
    async def go():
        with pytest.raises(McpGone, match="couldn't start"):
            await StdioClient(["no-such-program-for-kit"]).start()

    asyncio.run(go())


def test_http_with_json_or_an_event_stream_and_a_session():
    fake = Server()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers.get("authorization"), request.headers.get("mcp-session-id")))
        if request.method == "DELETE":
            return httpx.Response(200)
        replies = fake.handle(json.loads(request.content))
        if not replies:
            return httpx.Response(202)
        headers = {"mcp-session-id": "s1"}
        if len(replies) > 1 or json.loads(request.content)["method"] == "tools/list":
            body = "".join(f"event: message\ndata: {json.dumps(r)}\n\n" for r in replies)
            return httpx.Response(
                200, text=body, headers={**headers, "content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=replies[0], headers=headers)

    heard = []

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HttpClient(
            "http://192.168.1.50:8001/mcp", "tok", lambda m, p: heard.append(m), http
        )
        await client.start()
        tools = await client.list_tools()
        await client.call_tool("grow", {})
        await client.close()
        await http.aclose()
        return tools

    tools = asyncio.run(go())
    assert len(tools) == 6 and heard == ["notifications/tools/list_changed"]
    assert seen[0] == ("Bearer tok", None) and seen[1] == ("Bearer tok", "s1")

    def refused(request):
        return httpx.Response(401)

    async def no():
        http = httpx.AsyncClient(transport=httpx.MockTransport(refused))
        with pytest.raises(McpGone, match="refused Kit's token"):
            await HttpClient("http://192.168.1.50:8001/mcp", "bad", http=http).start()
        await http.aclose()

    asyncio.run(no())


def test_apps_come_from_the_settings_with_their_tokens(paths, memory, monkeypatch):
    from kit.credentials import app_token
    from kit.server import _apps_from_settings
    from kit.settings_store import SettingsStore

    paths.ensure()
    (paths.secrets_dir / "trips_token").write_text("secret\n", encoding="utf-8")
    assert app_token(paths, "trips", "trips_token") == "secret"
    assert app_token(paths, "trips", "../settings.toml") is None  # only the secrets folder
    monkeypatch.setenv("KIT_APP_HOME_APP_TOKEN", "from-env")
    assert app_token(paths, "home_app", "") == "from-env"
    store = SettingsStore(paths)
    servers = {
        "trips": {"url": "http://192.168.1.50:8001/mcp", "token_secret": "trips_token"},
        "off": {"url": "http://192.168.1.50:9/mcp", "enabled": False},
    }
    store.update({"apps": {"servers": servers}}, "test")
    brain, _, _ = make(memory)
    apps = _apps_from_settings(store, brain)
    assert [(a.name, a.token) for a in apps] == [("trips", "secret")]


def test_it_keeps_trying_until_the_app_is_back(memory, monkeypatch):
    import kit.tools.mcp as mcp

    monkeypatch.setattr(mcp, "WAIT_FIRST_S", 0.01)
    s = settings()
    fake = Server()
    tries = []

    def connect(app):
        tries.append(1)
        return InProcess(fake, app._notified, up=len(tries) >= 3)

    app = App("trips", s.apps.servers["trips"], None, lambda: s, connect)

    async def go():
        task = asyncio.create_task(app.run())
        for _ in range(200):
            if app.connected:
                break
            await asyncio.sleep(0.01)
        await app.call("grow", {})  # the list changed: run() reads it again
        for _ in range(200):
            if app.has("new_trick"):
                break
            await asyncio.sleep(0.01)
        task.cancel()
        await app.close()

    asyncio.run(go())
    assert len(tries) == 3 and app.has("new_trick")
