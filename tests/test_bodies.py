"""Kit's bodies saying hello, paired devices with their own tokens, and what a
phone needs from the API: history pages, messages written earlier, spoken ones."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.body_registry import ONLINE_FOR, BodyRegistry, Hello
from kit.brain import Brain
from kit.channels import Arrival, channel_line
from kit.cli import main
from kit.devices import DEVICES_FILE, DeviceError, Devices, pairing_link
from kit.memory import Memory
from kit.recall import Recall
from kit.server import create_app
from kit.settings_store import SettingsStore

TOKEN = "shared-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PHONE = {"id": "", "kind": "phone", "abilities": ["screen", "speaker", "notify", "jetpack"]}


# Paired devices


def test_a_paired_device_has_its_own_token(paths):
    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    token = devices.pair("phone")
    assert devices.match(token).name == "phone"
    assert devices.match("nope") is None and devices.match("") is None
    assert token not in (paths.secrets_dir / DEVICES_FILE).read_text(encoding="utf-8")


def test_pairing_again_or_forgetting_stops_the_old_token(paths):
    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    old = devices.pair("phone")
    new = devices.pair("phone")
    assert devices.match(old) is None and devices.match(new).name == "phone"
    assert devices.forget("phone") and not devices.forget("phone")
    assert devices.match(new) is None


def test_pairing_done_elsewhere_is_picked_up(paths):
    running = Devices(paths.secrets_dir / DEVICES_FILE)  # the brain's copy
    token = Devices(paths.secrets_dir / DEVICES_FILE).pair("tablet", "tablet")  # kit pair
    assert running.match(token).kind == "tablet"


@pytest.mark.parametrize("name,kind", [("My Phone", "phone"), ("phone", "toaster"), ("", "phone")])
def test_bad_device_names_and_kinds(name, kind):
    with pytest.raises(DeviceError):
        Devices(None).pair(name, kind)


def test_the_pairing_link_carries_address_name_and_token():
    link = urlparse(pairing_link("http://192.168.1.50:8600/", "phone", "abc"))
    assert (link.scheme, link.netloc) == ("kit", "pair")
    assert parse_qs(link.query) == {
        "url": ["http://192.168.1.50:8600"],
        "name": ["phone"],
        "token": ["abc"],
    }


# The registry


def test_a_body_says_hello_and_goes_quiet():
    clock = Clock()
    registry = BodyRegistry(clock)
    body = registry.hello(Hello(id="desk-pc", kind="desk", abilities=["screen", "pc", "x"]))
    assert body.abilities == ("screen", "pc") and body.unknown == ("x",)
    assert [b.id for b in registry.online()] == ["desk-pc"]
    clock.now += ONLINE_FOR + timedelta(seconds=1)
    assert registry.online() == []
    registry.seen("desk-pc")
    assert registry.online()[0].id == "desk-pc"


def test_a_paired_device_is_known_by_its_device_name():
    registry = BodyRegistry(Clock())
    assert registry.hello(Hello(id="whatever", kind="phone"), device="phone").id == "phone"
    assert registry.hello(Hello(kind="home_app")).id == "home_app"


def test_the_body_dan_used_last():
    clock = Clock()
    registry = BodyRegistry(clock)
    registry.hello(Hello(id="desk", kind="desk"))
    registry.hello(Hello(id="phone", kind="phone"))
    assert registry.last_used() is None
    registry.used("desk")
    clock.now += timedelta(seconds=10)
    registry.used("phone")
    assert registry.last_used().id == "phone"
    registry.used("nobody")  # a body that never said hello is let go
    first = registry.get("desk").first_seen
    registry.hello(Hello(id="desk", kind="desk"))  # again, after the app restarts
    assert registry.get("desk").first_seen == first and registry.get("desk").last_used


# Kit knowing how a message came


def test_a_spoken_message_is_answered_short():
    line = channel_line("phone", "Dan", Arrival(spoken=True))
    assert "on their phone" in line and "out loud" in line
    assert "out loud, not typing" not in channel_line("voice", "Dan", Arrival(spoken=True))


def test_a_message_that_waited_is_old_news():
    now = datetime.fromisoformat("2026-10-05T09:40:00")
    late = channel_line("phone", "Dan", Arrival(sent_at=now - timedelta(minutes=29)), now)
    assert "wrote this at 09:11, 29 minutes ago" in late
    soon = channel_line("phone", "Dan", Arrival(sent_at=now - timedelta(seconds=30)), now)
    assert "wrote this" not in soon
    # Two hours earlier, given in UTC: the gap is the same whatever zone this PC is in.
    local = now.astimezone()
    aware = (local - timedelta(hours=2)).astimezone(UTC)
    assert "ago" in channel_line("phone", "Dan", Arrival(sent_at=aware), local)


# The API


@pytest.fixture
def api(paths):
    paths.ensure()
    store = SettingsStore(paths)
    clock = Clock()
    memory = Memory(paths.state_dir / "memory.db", clock)
    model = FakeModel(reply("Hi Dan.", "Ready."))
    brain = Brain(
        store.current,
        memory,
        model,
        make_cloud(memory, key="k"),
        Recall(memory, FakeEmbedder(), store.current),
    )
    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    registry = BodyRegistry(clock)
    app = create_app(
        store,
        memory,
        brain,
        TOKEN,
        summarise_every_s=None,
        life_every_s=None,
        devices=devices,
        registry=registry,
    )
    with TestClient(app) as client:
        yield client, devices, registry, model, memory, clock, brain
    memory.close()


def test_a_device_token_opens_the_api_until_forgotten(api):
    client, devices, *_ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    assert client.get("/api/life", headers=phone).status_code == 200
    devices.forget("phone")
    assert client.get("/api/life", headers=phone).status_code == 401


def test_hello_answers_with_what_the_brain_can_do(api):
    client, devices, registry, *_ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    got = client.post("/api/bodies/hello", json=PHONE, headers=phone).json()
    assert got["api"] == 1 and got["body"]["id"] == "phone" and got["body"]["device"] == "phone"
    assert got["features"]["chat"] == 2 and got["features"]["messages"] == 2
    assert "voice_out" not in got["features"]  # no voice engine in this brain
    assert "pipe_up" in got["events"] and got["unknown_abilities"] == ["jetpack"]
    assert got["face"]["page"] == "/face/?app=phone" and got["face"]["character"]
    listed = client.get("/api/bodies", headers=AUTH).json()
    assert listed["bodies"][0]["online"] and listed["devices"][0]["name"] == "phone"


def test_chat_from_a_body_is_remembered_with_how_it_came(api):
    client, devices, registry, model, memory, clock, _ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    client.post("/api/bodies/hello", json=PHONE, headers=phone)
    written = (clock.now - timedelta(minutes=20)).isoformat()
    sent = {"text": "dentist at 3", "channel": "phone", "sent_at": written, "spoken": True}
    client.post("/api/chat", json=sent, headers=phone).read()
    assert registry.last_used().id == "phone"
    system = model.calls[-1][0]["content"]
    assert "on their phone" in system and "20 minutes ago" in system and "out loud" in system
    stored = client.get("/api/messages", headers=AUTH).json()[0]
    assert stored["meta"] == {"body": "phone", "sent_at": written, "spoken": True}


def test_the_shared_token_can_name_its_body(api):
    client, _, registry, *_ = api
    client.post("/api/bodies/hello", json={"id": "desk-pc", "kind": "desk"}, headers=AUTH)
    client.post("/api/chat", json={"text": "hi", "body": "desk-pc"}, headers=AUTH).read()
    assert registry.last_used().id == "desk-pc"
    assert client.get("/api/messages", headers=AUTH).json()[0]["meta"] == {"body": "desk-pc"}


def test_history_pages_reach_past_a_new_chat(api):
    client, *_, memory, _, _ = api
    for i in range(6):
        memory.add_message("user", f"m{i}")
        if i == 3:
            memory.new_chat()
    current = client.get("/api/messages", headers=AUTH).json()
    assert [m["text"] for m in current] == ["m4", "m5"]
    back = client.get(f"/api/messages?before={current[0]['id']}&limit=3", headers=AUTH).json()
    assert [m["text"] for m in back] == ["m1", "m2", "m3"]
    since = client.get(f"/api/messages?after={back[0]['id']}&limit=2", headers=AUTH).json()
    assert [m["text"] for m in since] == ["m2", "m3"]
    both = f"/api/messages?after={back[0]['id']}&before={current[0]['id']}"
    assert [m["text"] for m in client.get(both, headers=AUTH).json()] == ["m2", "m3"]


# The commands


def test_kit_pair_prints_a_code_and_kit_devices_forgets(paths, capsys):
    assert main(["pair", "phone", "--address", "192.168.1.50:8600"]) == 0
    out = capsys.readouterr().out
    link = next(w for w in out.split() if w.startswith("kit://pair?"))
    query = parse_qs(urlparse(link).query)
    assert query["url"] == ["http://192.168.1.50:8600"] and query["name"] == ["phone"]
    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    assert devices.match(query["token"][0]).name == "phone"
    main(["devices"])
    assert "phone" in capsys.readouterr().out
    assert main(["devices", "forget", "phone"]) == 0
    assert devices.match(query["token"][0]) is None
    assert main(["devices", "forget", "phone"]) == 1


def test_kit_pair_finds_the_tailscale_address(paths, capsys, monkeypatch):
    import kit.cli

    monkeypatch.setattr(kit.cli, "tailscale_address", lambda: "100.64.0.9")
    assert main(["pair", "tablet", "--kind", "tablet"]) == 0
    assert "http://100.64.0.9:8600" in capsys.readouterr().out
    monkeypatch.setattr(kit.cli, "tailscale_address", lambda: None)
    assert main(["pair", "phone"]) == 1
    assert main(["pair", "Bad Name", "--address", "x"]) == 2


def test_tailscale_address_reads_the_first_one():
    import subprocess

    from kit.cli import tailscale_address

    def run(cmd):
        return subprocess.CompletedProcess(cmd, 0, "100.64.0.9\n", "")

    def broken(cmd):
        raise FileNotFoundError("tailscale")

    assert tailscale_address(run) == "100.64.0.9"
    assert tailscale_address(broken) is None
    assert tailscale_address(lambda c: subprocess.CompletedProcess(c, 1, "", "")) is None


# Several PCs and one voice


def test_each_pc_is_a_body_and_one_speaks():
    from kit.body_registry import desk_id, speaks_here

    clock = Clock()
    registry = BodyRegistry(clock)
    assert registry.speaker(None, False) is None  # nothing known: every body decides
    registry.desk_report("DESK")
    registry.desk_report("LAPTOP")
    assert {b.id for b in registry.online()} == {"desk:desk", "desk:laptop"}
    assert registry.speaker("DESK", True) == "desk:desk"
    registry.hello(Hello(id="phone", kind="phone", abilities=["screen", "speaker"]))
    clock.now += timedelta(seconds=5)
    registry.used("phone")
    assert registry.speaker("DESK", True) == "desk:desk"  # he's at the desk
    assert registry.speaker("DESK", False) == "phone"  # he's out, chatting on his phone
    clock.now += ONLINE_FOR * 2
    registry.desk_report("DESK")
    assert registry.speaker("DESK", False) == "desk:desk"  # the phone's gone quiet
    assert speaks_here("desk:desk", desk_id("DESK")) and not speaks_here("phone", "desk:desk")
    assert speaks_here(None, "desk:desk")


def test_pipe_ups_name_the_pc_dan_is_on(api):
    import asyncio

    from kit.server import pipe_up_now

    client, *_, brain = api
    pc = {"host": "DESK", "focus": {"app": "Excel", "title": "x"}}
    client.post("/api/pc/context", json=pc, headers=AUTH)
    client.post("/api/pc/context", json={"host": "LAPTOP", "locked": True}, headers=AUTH)
    listed = client.get("/api/bodies", headers=AUTH).json()["bodies"]
    assert {b["id"] for b in listed} == {"desk:desk", "desk:laptop"}
    assert brain.voice_body() == "desk:desk"
    asyncio.run(pipe_up_now(brain, "bored"))
    events = client.get("/api/life/events?after=0&wait=0", headers=AUTH).json()["events"]
    pipe_ups = [e for e in events if e["type"] == "pipe_up"]
    assert pipe_ups and pipe_ups[-1]["to"] == "desk:desk"


# Pairing from the app


def test_the_app_pairs_itself_with_kits_token(api):
    client, devices, registry, *_ = api
    got = client.post("/api/devices/pair", json={"name": "phone"}, headers=AUTH).json()
    phone = {"Authorization": f"Bearer {got['token']}"}
    assert got["kind"] == "phone" and client.get("/api/life", headers=phone).status_code == 200
    # A device can't pair others, but can unpair itself.
    assert client.post("/api/devices/pair", json={"name": "x"}, headers=phone).status_code == 403
    assert client.delete("/api/devices/tablet", headers=phone).status_code == 403
    bad = client.post("/api/devices/pair", json={"name": "My Phone"}, headers=AUTH)
    assert bad.status_code == 422
    assert client.delete("/api/devices/phone", headers=phone).json() == {"ok": True}
    assert client.get("/api/life", headers=phone).status_code == 401
    assert client.delete("/api/devices/phone", headers=AUTH).status_code == 404
