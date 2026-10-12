"""Phase 2 of the phone app: nudging a closed app when Kit pipes up (kit.push), and
where his phone says Dan is (kit.phone_context)."""

import asyncio
import base64
import json
from datetime import datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.body_registry import BodyRegistry
from kit.brain import Brain
from kit.cli import main
from kit.credentials import FIREBASE_FILE, firebase_service_account
from kit.devices import DEVICES_FILE, Devices
from kit.memory import Memory
from kit.phone_context import PhoneContext, PhoneReport
from kit.prompt import system_prompt
from kit.push import (
    FAILED,
    GONE,
    PIPE_UP,
    SENT,
    TEST,
    Nudger,
    ServiceAccount,
    nudge_when,
    sign_jwt,
)
from kit.recall import Recall
from kit.server import create_app, pipe_up_now
from kit.settings import Settings
from kit.settings_store import SettingsStore

TOKEN = "shared-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def account(key):
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return ServiceAccount("kit-test", "kit@kit-test.iam.gserviceaccount.com", pem)


class FakeGoogle:
    """Google's token endpoint and FCM, as the nudger sees them."""

    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []
        self.fcm_status = 200
        self.fcm_text = '{"name": "projects/kit-test/messages/1"}'
        self.tokens = 0

    async def __call__(self, url, headers, body):
        self.calls.append((url, headers, body))
        if url.endswith("/token"):
            self.tokens += 1
            return 200, json.dumps({"access_token": f"at{self.tokens}", "expires_in": 3600})
        return self.fcm_status, self.fcm_text


# The service account and the signed token


def test_the_service_account_file_is_read(paths):
    paths.ensure()
    assert firebase_service_account(paths) is None
    raw = {"project_id": "p", "client_email": "e", "private_key": "k", "token_uri": "t"}
    (paths.secrets_dir / FIREBASE_FILE).write_text(json.dumps(raw), encoding="utf-8")
    account = ServiceAccount.parse(firebase_service_account(paths))
    assert account == ServiceAccount("p", "e", "k", "t")
    assert ServiceAccount.parse("not json") is None and ServiceAccount.parse("{}") is None


def test_the_jwt_is_signed_with_the_accounts_key(account, key):
    jwt = sign_jwt(account, now=1_700_000_000)
    header, claims, signature = jwt.split(".")

    def unpad(part):
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))

    assert json.loads(unpad(header)) == {"alg": "RS256", "typ": "JWT"}
    got = json.loads(unpad(claims))
    assert got["iss"] == account.email and got["aud"] == account.token_url
    assert got["exp"] - got["iat"] == 3600 and "firebase.messaging" in got["scope"]
    key.public_key().verify(
        unpad(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


# Nudging


def test_when_phones_are_nudged():
    assert nudge_when("away", pc_in_use=False) and not nudge_when("away", pc_in_use=True)
    assert nudge_when("always", pc_in_use=True)
    assert not nudge_when("never", pc_in_use=False)


def test_a_nudge_carries_no_words(account):
    devices = Devices(None)
    devices.pair("phone")
    devices.set_push("phone", "fcm", "fcm-token-1")
    google = FakeGoogle()
    nudger = Nudger(devices, account, google, now=lambda: 1_700_000_000.0)
    sent = asyncio.run(nudger.nudge_all(PIPE_UP, {"id": "42"}))
    assert sent == {"phone": SENT}
    token_call, fcm_call = google.calls
    assert token_call[0] == account.token_url and "assertion" in token_call[2]
    url, headers, body = fcm_call
    assert url == "https://fcm.googleapis.com/v1/projects/kit-test/messages:send"
    assert headers["Authorization"] == "Bearer at1"
    assert body["message"]["token"] == "fcm-token-1"
    assert body["message"]["data"] == {"kit": "pipe_up", "id": "42"}
    assert "notification" not in body["message"]  # content-free: the phone fetches it
    assert body["message"]["android"]["priority"] == "high"
    # The access token is kept for the next nudge.
    asyncio.run(nudger.nudge_all(TEST))
    assert google.tokens == 1 and google.calls[-1][2]["message"]["data"] == {"kit": "test"}


def test_a_dead_token_is_forgotten_and_failures_are_not(account):
    devices = Devices(None)
    devices.pair("phone")
    devices.set_push("phone", "fcm", "old")
    google = FakeGoogle()
    nudger = Nudger(devices, account, google)
    google.fcm_status, google.fcm_text = (
        404,
        '{"error": {"details": [{"errorCode": "UNREGISTERED"}]}}',
    )
    assert asyncio.run(nudger.nudge_all(TEST)) == {"phone": GONE}
    assert devices.all()[0].push is None
    devices.set_push("phone", "fcm", "new")
    google.fcm_status, google.fcm_text = 500, "oops"
    assert asyncio.run(nudger.nudge_all(TEST)) == {"phone": FAILED}
    assert devices.all()[0].push == {"kind": "fcm", "token": "new"}


def test_a_phone_is_nudged_at_most_so_often(account):
    clock = Clock()
    devices = Devices(None)
    devices.pair("phone")
    devices.set_push("phone", "fcm", "t")
    nudger = Nudger(devices, account, FakeGoogle(), clock=clock)
    assert asyncio.run(nudger.nudge_all(PIPE_UP, per_hour=1)) == {"phone": SENT}
    assert asyncio.run(nudger.nudge_all(PIPE_UP, per_hour=1)) == {"phone": "held"}
    assert asyncio.run(nudger.nudge_all(TEST)) == {"phone": SENT}  # a test is never held
    clock.now += timedelta(hours=1, seconds=1)
    assert asyncio.run(nudger.nudge_all(PIPE_UP, per_hour=1)) == {"phone": SENT}


def test_without_an_account_nothing_is_sent():
    devices = Devices(None)
    devices.pair("phone")
    devices.set_push("phone", "fcm", "t")
    nudger = Nudger(devices, None, FakeGoogle())
    assert not nudger.enabled and asyncio.run(nudger.nudge_all(TEST)) == {"phone": FAILED}


def test_the_push_token_survives_pairing_again_and_a_restart(paths):
    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    devices.pair("phone")
    assert not devices.set_push("tablet", "fcm", "t")
    assert devices.set_push("phone", "fcm", "t")
    devices.pair("phone")
    assert Devices(paths.secrets_dir / DEVICES_FILE).all()[0].push == {"kind": "fcm", "token": "t"}
    assert devices.clear_push("phone") and not devices.clear_push("phone")


# Where his phone says Dan is


def test_the_phone_line_says_home_or_out_and_a_flat_battery():
    clock = Clock("2026-10-05T15:00:00")
    phones = PhoneContext(clock)
    assert phones.now_line("Dan") == "" and phones.place() == "unknown"
    phones.report("phone", PhoneReport(place="out", since=datetime(2026, 10, 5, 14, 5)))
    assert phones.now_line("Dan") == "Dan's phone says they're out (since 2:05 pm)."
    phones.report("phone", PhoneReport(place="home", battery=12, charging=False))
    line = phones.now_line("Dan")
    assert line.startswith("Dan's phone says they're at home.")
    assert "nearly flat (12%)" in line and phones.place() == "home"
    phones.report("phone", PhoneReport(place="home", battery=12, charging=True))
    assert "flat" not in phones.now_line("Dan")
    phones.report("phone", PhoneReport(place="unknown", battery=5))
    assert phones.now_line("Dan") == "Their phone's battery is nearly flat (5%)."


def test_the_phone_line_goes_stale_and_says_when_it_last_heard():
    clock = Clock("2026-10-05T15:00:00")
    phones = PhoneContext(clock)
    phones.report("phone", PhoneReport(place="out", since=datetime(2026, 10, 4, 22, 30)))
    assert "since Sunday 10:30 pm" in phones.now_line("Dan")
    clock.now += timedelta(hours=2)
    assert "last reported at 03:00 PM" in phones.now_line("Dan")
    clock.now += timedelta(hours=11)
    assert phones.now_line("Dan") == "" and phones.as_dict()["phone"] is None


def test_the_newest_phone_speaks_for_dan():
    clock = Clock()
    phones = PhoneContext(clock)
    phones.report("phone", PhoneReport(place="out"))
    clock.now += timedelta(minutes=1)
    phones.report("tablet", PhoneReport(place="home"))
    assert phones.as_dict()["phone"] == "tablet" and phones.place() == "home"


def test_the_prompt_carries_the_phone_line():
    from kit.recall import Recalled

    s = Settings()
    prompt = system_prompt(
        s.persona, Recalled([], [], []), datetime(2026, 10, 5, 9), phone="Dan's phone says X."
    )
    assert "Dan's phone says X." in prompt


# The API


@pytest.fixture
def api(paths, account):
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
    google = FakeGoogle()
    nudger = Nudger(devices, account, google, clock=clock)
    app = create_app(
        store,
        memory,
        brain,
        TOKEN,
        summarise_every_s=None,
        life_every_s=None,
        devices=devices,
        registry=BodyRegistry(clock),
        nudger=nudger,
    )
    with TestClient(app) as client:
        yield client, devices, google, nudger, brain, store
    memory.close()


def test_the_phone_registers_for_nudges_and_a_pipe_up_sends_one(api):
    client, devices, google, nudger, brain, _ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    got = client.post("/api/devices/phone/push", json={"token": "fcm-1"}, headers=phone)
    assert got.status_code == 200 and got.json()["nudges"] is True
    assert client.get("/api/bodies", headers=AUTH).json()["devices"][0]["notifies"] is True
    assert (
        client.post("/api/bodies/hello", json={"kind": "phone"}, headers=phone).json()["features"][
            "push"
        ]
        == 1
    )
    asyncio.run(pipe_up_now(brain, "bored", nudger))
    fcm = [c for c in google.calls if "messages:send" in c[0]]
    assert len(fcm) == 1 and fcm[0][2]["message"]["data"]["kit"] == "pipe_up"
    message_id = int(fcm[0][2]["message"]["data"]["id"])
    said = client.get(f"/api/messages?after={message_id - 1}&limit=1", headers=AUTH).json()
    assert said[0]["id"] == message_id and said[0]["source"] == "pipe_up"
    # Off again: nothing more is sent.
    assert client.delete("/api/devices/phone/push", headers=phone).status_code == 200
    asyncio.run(pipe_up_now(brain, "bored", nudger))
    assert len([c for c in google.calls if "messages:send" in c[0]]) == 1


def test_no_nudge_while_dan_is_at_a_pc(api):
    client, devices, google, nudger, brain, store = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    client.post("/api/devices/phone/push", json={"token": "fcm-1"}, headers=phone)
    pc = {"host": "DESK", "focus": {"app": "Excel", "title": "x"}}
    client.post("/api/pc/context", json=pc, headers=AUTH)
    assert brain.pc_in_use()
    asyncio.run(pipe_up_now(brain, "bored", nudger))
    assert not [c for c in google.calls if "messages:send" in c[0]]
    store.update({"phone": {"notify": "always"}}, "test")
    asyncio.run(pipe_up_now(brain, "bored", nudger))
    assert len([c for c in google.calls if "messages:send" in c[0]]) == 1


def test_only_the_device_or_kit_can_set_its_push(api):
    client, devices, *_ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    devices.pair("tablet")
    assert (
        client.post("/api/devices/tablet/push", json={"token": "t"}, headers=phone).status_code
        == 403
    )
    assert (
        client.post("/api/devices/tablet/push", json={"token": "t"}, headers=AUTH).status_code
        == 200
    )
    assert (
        client.post("/api/devices/nobody/push", json={"token": "t"}, headers=AUTH).status_code
        == 404
    )
    bad = client.post(
        "/api/devices/phone/push", json={"kind": "pigeon", "token": "t"}, headers=phone
    )
    assert bad.status_code == 422


def test_a_test_nudge_from_the_cli(api, paths, monkeypatch):
    client, devices, google, *_ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    assert client.post("/api/nudge", headers=phone).status_code == 403
    got = client.post("/api/nudge", headers=AUTH).json()
    assert got == {"enabled": True, "sent": {}}
    client.post("/api/devices/phone/push", json={"token": "t"}, headers=phone)
    assert client.post("/api/nudge", headers=AUTH).json()["sent"] == {"phone": SENT}
    assert google.calls[-1][2]["message"]["data"] == {"kit": "test"}


def test_kit_nudge_talks_to_the_running_brain(paths, capsys):
    import httpx

    paths.ensure()
    (paths.secrets_dir / "api_token").write_text(TOKEN, encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.url.path == "/api/nudge"
            and request.headers["Authorization"] == AUTH["Authorization"]
        )
        return httpx.Response(200, json={"enabled": True, "sent": {"phone": "sent"}})

    from kit.cli import cmd_nudge

    assert cmd_nudge(paths, httpx.MockTransport(handler)) == 0
    assert "phone" in capsys.readouterr().out
    assert (
        cmd_nudge(
            paths, httpx.MockTransport(lambda r: httpx.Response(200, json={"enabled": False}))
        )
        == 1
    )
    assert "firebase_service_account.json" in capsys.readouterr().out


def test_kit_nudge_is_a_command(monkeypatch):
    called = {}
    monkeypatch.setattr("kit.cli.cmd_nudge", lambda paths: called.setdefault("ok", True) and 0)
    assert main(["nudge"]) == 0 and called["ok"]


def test_the_phone_reports_where_dan_is(api):
    client, devices, _, _, brain, _ = api
    phone = {"Authorization": f"Bearer {devices.pair('phone')}"}
    report = {"place": "out", "since": "2026-10-05T08:30:00", "battery": 15, "charging": False}
    got = client.post("/api/phone/context", json=report, headers=phone).json()
    assert got["line"].startswith("Dan's phone says they're out (since 8:30 am).")
    assert "nearly flat (15%)" in got["line"]
    seen = client.get("/api/phone/context", headers=AUTH).json()
    assert seen["phone"] == "phone" and seen["place"] == "out" and seen["report"]["battery"] == 15
    status = client.get("/api/status", headers=AUTH).json()
    assert status["phone"] == got["line"]
    assert (
        client.post("/api/phone/context", json={"place": "mars"}, headers=phone).status_code == 422
    )
