"""The house through Home Assistant (kit.house, the house pack): the connection, the
exposed-only model, finding things, the tools and when they ask first, noticing,
the memory items and ``kit check``."""

import asyncio
import json
from datetime import datetime

import pytest

from fakes import FakeAnthropic, collect, reply
from kit.checks import Status, check_house
from kit.evals import run_tool_eval
from kit.house import HOUSE
from kit.house.client import HomeAssistant, HouseError
from kit.house.contents import write_contents
from kit.house.model import House
from kit.memory import Memory
from kit.settings import Settings
from kit.tools import ToolCall
from kit.tools.confirm import needs_yes
from tool_helpers import Clock, make


def state(entity, value, name, **attributes):
    return {
        "entity_id": entity,
        "state": value,
        "attributes": {"friendly_name": name, **attributes},
    }


STATES = [
    {
        "entity_id": "light.study_lamp",
        "state": "on",
        "attributes": {"friendly_name": "Study lamp", "brightness": 128},
        "last_changed": "2026-10-05T03:00:00",
    },
    {
        "entity_id": "light.lounge",
        "state": "off",
        "attributes": {"friendly_name": "Lounge light"},
        "last_changed": "2026-10-05T08:00:00",
    },
    {
        "entity_id": "climate.aircon",
        "state": "cool",
        "attributes": {"friendly_name": "Aircon", "temperature": 24, "current_temperature": 27},
    },
    state("cover.garage_door", "closed", "Garage door", device_class="garage"),
    state("cover.lounge_blinds", "open", "Lounge blinds"),
    state("lock.front_door", "locked", "Front door"),
    {"entity_id": "scene.movie", "state": "scening", "attributes": {"friendly_name": "Movie"}},
    {"entity_id": "person.sam", "state": "home", "attributes": {"friendly_name": "Sam"}},
    state("switch.shed_heater", "off", "Shed heater"),
    state("switch.secret_relay", "off", "Secret relay"),
]  # fmt: skip
AREAS = [{"area_id": "study", "name": "Study"}, {"area_id": "lounge", "name": "Lounge"}]
REGISTRY = [
    {"entity_id": "light.study_lamp", "area_id": "study"},
    {"entity_id": "light.lounge", "device_id": "dev1"},
    {"entity_id": "cover.lounge_blinds", "area_id": "lounge"},
]
DEVICES = [{"id": "dev1", "area_id": "lounge"}]
EXPOSED = {s["entity_id"] for s in STATES} - {"switch.secret_relay"}


class FakeSocket:
    def __init__(self, ha):
        self.ha = ha
        self.inbox = asyncio.Queue()
        self.inbox.put_nowait({"type": "auth_required"})
        self.sub = None
        self.closed = False

    async def send(self, text):
        m = json.loads(text)
        ha = self.ha
        if m["type"] == "auth":
            ok = m["access_token"] == ha.token
            reply_ = (
                {"type": "auth_ok", "ha_version": "2026.10"}
                if ok
                else {"type": "auth_invalid", "message": "bad token"}
            )
            self.inbox.put_nowait(reply_)
            return
        ha.sent.append(m)
        results = {
            "get_states": STATES,
            "config/area_registry/list": AREAS,
            "config/entity_registry/list": REGISTRY,
            "config/device_registry/list": DEVICES,
            "auth/current_user": {"name": "kit", "is_admin": ha.admin},
            "subscribe_events": None,
            "call_service": {"context": {}},
        }
        if m["type"] == "homeassistant/expose_entity/list":
            exposed = {e: {"conversation": True} for e in EXPOSED}
            self.inbox.put_nowait(
                {
                    "id": m["id"],
                    "type": "result",
                    "success": True,
                    "result": {"exposed_entities": exposed},
                }
            )
            return
        if m["type"] == "subscribe_events":
            self.sub = m["id"]
        if m["type"] in results:
            self.inbox.put_nowait(
                {"id": m["id"], "type": "result", "success": True, "result": results[m["type"]]}
            )
        else:
            self.inbox.put_nowait(
                {
                    "id": m["id"],
                    "type": "result",
                    "success": False,
                    "error": {"message": "unknown command"},
                }
            )

    async def recv(self):
        m = await self.inbox.get()
        if m == "drop":
            raise ConnectionError("socket dropped")
        return json.dumps(m)

    async def close(self):
        self.closed = True

    def event(self, entity_id, state):
        new = {"state": state, "attributes": {}, "last_changed": "2026-10-05T09:00:00"}
        data = {"entity_id": entity_id, "new_state": new}
        self.inbox.put_nowait({"id": self.sub, "type": "event", "event": {"data": data}})


class FakeHA:  # fmt: skip
    def __init__(self, token="tok", admin=False):
        self.token, self.admin = token, admin
        self.sockets, self.sent, self.down = [], [], False

    async def connect(self, url):
        if self.down:
            raise OSError("connection refused")
        socket = FakeSocket(self)
        self.sockets.append(socket)
        return socket


async def no_wait(_):
    await asyncio.sleep(0)


def test_it_logs_in_answers_by_id_and_hears_changes():
    async def go():
        ha = FakeHA()
        client = HomeAssistant("ws://ha/api/websocket", "tok", ha.connect, sleep=no_wait)
        heard = []
        client.subscribe(heard.append)
        await client.start()
        assert await client.wait_ready(1) and client.version == "2026.10"
        states, user = await asyncio.gather(client.states(), client.current_user())
        assert len(states) == len(STATES) and user["name"] == "kit"
        ha.sockets[0].event("light.lounge", "on")
        await asyncio.sleep(0.01)
        assert heard[0]["entity_id"] == "light.lounge"
        with pytest.raises(HouseError, match="unknown command"):
            await client.call("nonsense")
        await client.close()

    asyncio.run(go())


def test_a_bad_token_or_a_dropped_socket_is_said_and_it_reconnects():
    async def go():
        bad = HomeAssistant("ws://ha", "wrong", FakeHA().connect, sleep=no_wait)
        await bad.start()
        assert not await bad.wait_ready(0.05)
        assert "didn't accept Kit's token" in bad.last_error
        await bad.close()

        ha = FakeHA()
        client = HomeAssistant("ws://ha", "tok", ha.connect, sleep=no_wait)
        await client.start()
        await client.wait_ready(1)
        ha.down = True
        ha.sockets[0].inbox.put_nowait("drop")
        await asyncio.sleep(0.01)
        assert not client.connected
        with pytest.raises(HouseError, match="out of reach"):
            await client.states()
        ha.down = False
        for _ in range(100):
            if client.connected:
                break
            await asyncio.sleep(0.01)
        assert client.connected and len(ha.sockets) == 2
        assert [m["type"] for m in ha.sent].count("subscribe_events") == 2  # subscribed again
        await client.close()

    asyncio.run(go())


def test_only_exposed_things_exist_with_their_rooms():
    async def go():
        ha = FakeHA()
        client = HomeAssistant("ws://ha", "tok", ha.connect, sleep=no_wait)
        house = House(client, datetime.now)
        await client.start()
        await client.wait_ready(1)
        assert await house.refresh() == len(STATES) - 1
        assert house.get("switch.secret_relay") is None
        assert house.get("light.study_lamp").area == "Study"
        assert house.get("light.lounge").area == "Lounge"  # through its device
        assert house.is_admin is False
        await client.close()
        return house

    house = asyncio.run(go())
    assert "brightness 50%" in house.get("light.study_lamp").line()
    assert "set to 24°" in house.get("climate.aircon").line()


class FakeClient:
    """A connected Home Assistant for the tool tests: records service calls."""

    def __init__(self):
        self.connected, self.last_error, self.services, self.subs = True, "", [], []

    def subscribe(self, callback):
        self.subs.append(callback)

    async def call_service(self, domain, service, data=None, entity=None):
        self.services.append((domain, service, data, entity))


def fake_house(clock=datetime.now):
    from kit.house.model import Entity

    house = House(FakeClient(), clock)
    area = {"light.study_lamp": "Study", "light.lounge": "Lounge", "cover.lounge_blinds": "Lounge"}
    for s in STATES:
        if s["entity_id"] in EXPOSED:
            a = s["attributes"]
            keep = {k: v for k, v in a.items() if k != "friendly_name"}
            house.entities[s["entity_id"]] = Entity(
                s["entity_id"], a["friendly_name"], area.get(s["entity_id"], ""), s["state"], keep,
                s.get("last_changed", ""),
            )  # fmt: skip
    return house


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-05T20:00:00"))
    yield m
    m.close()


def test_finding_things_by_name_room_kind_and_register_link(memory):
    brain, _, _ = make(memory)
    house = fake_house()
    assert [e.id for e in house.find("the study lamp")] == ["light.study_lamp"]
    assert [e.id for e in house.find("light.lounge")] == ["light.lounge"]
    assert [e.id for e in house.find("is the aircon on?")] == ["climate.aircon"]
    assert [e.id for e in house.find("lounge lights")] == ["light.lounge"]
    assert house.find("the secret relay") == []  # not exposed
    lights = {e.id for e in house.find("turn the lights off")}
    assert lights == {"light.study_lamp", "light.lounge"}
    brain.register.add(
        "Shed", "place", links=[{"system": "home_assistant", "target": "switch.shed_heater"}]
    )
    assert [e.id for e in house.find("is the Shed warm?", brain.register)] == ["switch.shed_heater"]


def house_brain(memory, settings=None, claude=None):
    brain, _, claude = make(memory, settings=settings, claude=claude)
    house = fake_house(memory.clock)
    brain.use_house(house)
    return brain, house, claude


def run(brain, name, **args):
    return asyncio.run(brain.tools.run(ToolCall("1", name, args)))


def test_lights_switches_scenes_and_states(memory):
    brain, house, _ = house_brain(memory)
    out = run(brain, "house_set", entity="study lamp", on=False)
    assert out.ok and out.text == "Done: turned the Study lamp off."
    run(brain, "house_set", entity="lounge light", on=True, brightness=40, colour="Warm White")
    run(brain, "house_scene", scene="movie")
    assert house.client.services == [
        ("light", "turn_off", {}, "light.study_lamp"),
        ("light", "turn_on", {"brightness_pct": 40, "color_name": "warm white"}, "light.lounge"),
        ("scene", "turn_on", None, "scene.movie"),
    ]
    assert "Aircon" in run(brain, "house_state", entity="aircon").text
    assert "could be several" in run(brain, "house_set", entity="lights", on=False).text
    assert "use house_secure" in run(brain, "house_set", entity="front door", on=False).text
    assert "- Sam: home" in run(brain, "who_is_home").text
    assert "Study lamp" in run(brain, "house_find", query="study").text


def test_what_asks_first(memory):
    brain, house, _ = house_brain(memory)
    s = brain.settings()
    pack = brain.tools.packs["house"]
    tool = brain.tools.get
    assert needs_yes(tool("house_secure"), pack, s, {"entity": "front door", "action": "lock"})
    assert needs_yes(tool("house_cover"), pack, s, {"entity": "garage", "action": "open"})
    assert not needs_yes(
        tool("house_cover"), pack, s, {"entity": "lounge blinds", "action": "close"}
    )
    climate = {"entity": "aircon", "temperature": 23}
    assert needs_yes(tool("house_climate"), pack, s, climate)
    assert run(brain, "house_climate", **climate).ok  # after the yes
    assert not needs_yes(tool("house_climate"), pack, s, climate)  # not again today
    assert house.client.services[-1] == (
        "climate",
        "set_temperature",
        {"temperature": 23.0},
        "climate.aircon",
    )
    memory.clock.now = datetime(2026, 10, 6, 9)
    assert needs_yes(tool("house_climate"), pack, s, climate)  # a new day asks again
    off = Settings.model_validate(
        {"routing": {"mode": "cloud-only"}, "house": {"climate_confirm_daily": False}}
    )
    assert not needs_yes(tool("house_climate"), pack, off, climate)
    lamp = {"entity": "study lamp", "on": False}
    assert not needs_yes(tool("house_set"), pack, s, lamp)
    lights_ask = Settings.model_validate(
        {"routing": {"mode": "cloud-only"}, "house": {"confirm": ["light", "cover"]}}
    )
    assert needs_yes(tool("house_set"), pack, lights_ask, lamp)
    blinds = {"entity": "lounge blinds", "action": "close"}
    assert needs_yes(tool("house_cover"), pack, lights_ask, blinds)


def test_locking_waits_for_a_yes_in_the_chat(memory):
    claude = FakeAnthropic(
        answer=["", reply("Lock the front door?"), reply("Locked.")],
        tool_calls=[[("house_secure", {"entity": "front door", "action": "lock"})]],
    )
    brain, house, _ = house_brain(memory, claude=claude)
    collect(brain.chat("lock the front door"))
    assert house.client.services == [] and brain.pending_tool is not None
    collect(brain.chat("yes"))
    assert house.client.services == [("lock", "lock", None, "lock.front_door")]


def test_unlocking_is_refused_from_the_phone(memory):
    from kit.brain import CHANNEL

    brain, house, _ = house_brain(memory)
    token = CHANNEL.set("phone")
    try:
        out = run(brain, "house_secure", entity="front door", action="unlock")
    finally:
        CHANNEL.reset(token)
    assert not out.ok and "from the phone is off" in out.text and house.client.services == []
    assert run(brain, "house_secure", entity="front door", action="unlock").ok  # at home


def test_with_home_assistant_down_the_house_is_out_of_reach(memory):
    brain, house, _ = house_brain(memory)
    house.client.connected, house.client.last_error = False, "connection refused"
    offered = {t.name for t in brain.tools.offered(["house"])}
    assert offered == {"house_find"}
    out = run(brain, "house_set", entity="study lamp", on=False)
    assert not out.ok and "out of reach" in out.text and "connection refused" in out.text
    house.client.connected = True
    assert "house_set" in {t.name for t in brain.tools.offered(["house"])}


def test_without_a_house_there_is_no_house_pack(memory):
    brain, _, _ = make(memory)
    assert "house" not in brain.tools.packs


def test_noticing_the_garage_after_dark_and_someone_coming_home(memory):
    brain, house, _ = house_brain(memory)
    garage, sam = house.get("cover.garage_door"), house.get("person.sam")
    from dataclasses import replace

    house.entities[garage.id] = replace(garage, state="open")
    house._on_change[0](garage, house.entities[garage.id])
    event = [e for e in brain.life.events_after(0) if e["type"] == "house"][-1]
    assert event["what"] == "the Garage door just opened, after dark"
    assert brain.life.curious_kind == "house" and brain.life.spotted is not None
    house._on_change[0](sam, replace(sam, state="not_home"))
    assert "Sam just left home" in brain.life.events_after(0)[-1]["what"]
    memory.clock.now = datetime(2026, 10, 5, 10)
    before = len(brain.life.events_after(0))
    house._on_change[0](house.entities[garage.id], replace(garage, state="closed"))
    house._on_change[0](garage, replace(garage, state="open"))  # in daylight: nothing
    assert len(brain.life.events_after(0)) == before


def test_a_light_left_on_is_mentioned_once(memory):
    brain, house, _ = house_brain(memory)
    brain.house_watch.tick()  # the study lamp: on since 03:00, it's 20:00
    said = [e["what"] for e in brain.life.events_after(0) if e["type"] == "house"]
    assert said == ["the Study lamp in the Study has been on for 17 hours"]
    brain.house_watch.tick()
    assert len([e for e in brain.life.events_after(0) if e["type"] == "house"]) == 1


def test_the_rooms_and_things_go_into_memory(memory):
    house = fake_house()
    from kit.house.model import Area

    house.areas = {"study": Area("study", "Study"), "lounge": Area("lounge", "Lounge")}
    n = write_contents(memory.index, house)
    assert n == len(EXPOSED) + 2
    lamp = memory.index.with_ref(HOUSE, "light.study_lamp")[0]
    assert lamp.text == "Study lamp, a light in the Study (Home Assistant light.study_lamp)."
    study = memory.index.with_ref(HOUSE, "area:Study")[0]
    assert "In it: Study lamp." in study.text
    write_contents(memory.index, house)
    assert memory.index.count(HOUSE) == n  # replaced, not added to


def test_kit_check_says_whether_kit_is_a_non_admin_and_what_it_sees():
    s = Settings.model_validate({"house": {"enabled": True, "url": "ws://ha/api/websocket"}})
    assert check_house(Settings(), "tok").status is Status.SKIP
    assert "token" in check_house(s, None).detail
    good = check_house(s, "tok", FakeHA().connect)
    assert good.status is Status.PASS and "not an admin" in good.detail
    assert f"{len(EXPOSED)} things" in good.detail
    admin = check_house(s, "tok", FakeHA(admin=True).connect)
    assert admin.status is Status.WARN and "admin" in admin.detail
    down = FakeHA()
    down.down = True
    assert check_house(s, "tok", down.connect).status is Status.FAIL


def test_the_house_cases_pass_offline(memory):
    brain, _, _ = house_brain(memory)
    report = asyncio.run(run_tool_eval(brain, brain.tools.packs["house"].cases))
    assert report.passed, [r.why for r in report.results if not r.passed]
