"""The desk app's plain-Python parts: settings, the brain client, and the desktop feed.

None of this needs Windows, Qt or a network: the desktop is a fake, and the
brain is the real API in-process.
"""

import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.brain import Brain
from kit.desk.client import BrainClient, BrainError
from kit.desk.config import DeskConfig, load_token, save_token
from kit.desk.watch import (
    OpenWindow,
    Privacy,
    Reporter,
    WindowsDesktop,
    app_name,
    build_snapshot,
    system_status,
)
from kit.memory import Memory
from kit.pc_context import Snapshot
from kit.recall import Recall
from kit.server import create_app
from kit.settings_store import SettingsStore


class FakeDesktop:
    def __init__(self):
        self.open = [
            OpenWindow("Code.exe", "pump.py - METTOOLS - Visual Studio Code", pid=11),
            OpenWindow("chrome.exe", "NetBank - Commonwealth Bank - Google Chrome", pid=12),
            OpenWindow("KeePassXC.exe", "Passwords.kdbx - KeePassXC", True, pid=13),
            OpenWindow("ApplicationFrameHost.exe", "Calculator", pid=14),
        ]
        self.focus = 0
        self.idle = 0.0
        self.is_locked = False

    def windows(self):
        return list(self.open)

    def focused(self):
        return self.open[self.focus]

    def idle_seconds(self):
        return self.idle

    def locked(self):
        return self.is_locked


def test_friendly_app_names():
    assert app_name("Code.exe") == "VS Code"
    assert app_name("EXCEL.EXE") == "Excel"
    assert app_name("ApplicationFrameHost.exe", "Settings") == "Settings"
    assert app_name("MyPlantDash.exe") == "MyPlantDash"


def test_private_titles_never_leave_the_pc():
    privacy = Privacy(DeskConfig())
    rows = [privacy.window(w) for w in FakeDesktop().open]
    assert rows[0] == {
        "app": "VS Code",
        "title": "pump.py - METTOOLS - Visual Studio Code",
        "minimised": False,
    }
    assert rows[1] == {"app": "Chrome", "title": "", "minimised": False}  # banking word
    assert rows[2]["title"] == "" and rows[2]["minimised"]  # password manager
    # Whole words only: "enable" doesn't trip "nab", "Banking" does.
    assert not privacy.hides("x.exe", "x", "Enable logging")
    assert privacy.hides("x.exe", "x", "Online Banking")


def test_snapshot_matches_the_brains_shape():
    snap = build_snapshot(FakeDesktop(), DeskConfig(), "DESK", {"cpu_percent": 5})
    parsed = Snapshot.model_validate(snap)
    assert parsed.focus.app == "VS Code" and len(parsed.windows) == 4
    assert parsed.system.cpu_percent == 5


def test_paused_or_locked_sends_no_windows():
    desk = FakeDesktop()
    snap = build_snapshot(desk, DeskConfig(watch=False), "DESK", None)
    assert snap["watching"] is False and snap["windows"] == [] and snap["focus"] is None
    desk.is_locked = True
    snap = build_snapshot(desk, DeskConfig(), "DESK", None)
    assert snap["locked"] and snap["windows"] == []


def test_reporter_sends_on_change_and_heartbeat():
    sent, clock = [], [0.0]
    desk = FakeDesktop()
    config = DeskConfig(heartbeat_seconds=20)
    r = Reporter(desk, sent.append, lambda: config, clock=lambda: clock[0], host="DESK")
    assert r.tick()  # first look always reports
    clock[0] = 2
    assert not r.tick()  # nothing changed
    desk.focus = 3
    clock[0] = 4
    assert r.tick() and sent[-1]["focus"]["app"] == "Calculator"
    clock[0] = 25
    assert r.tick()  # heartbeat
    desk.idle = 90
    clock[0] = 26
    assert r.tick()  # went idle


def test_reporter_retries_after_a_failed_send():
    calls = []

    def send(snap):
        calls.append(snap)
        if len(calls) == 1:
            raise BrainError("offline")

    clock = [0.0]
    r = Reporter(FakeDesktop(), send, DeskConfig, clock=lambda: clock[0], host="DESK")
    assert not r.tick() and r.error == "offline"
    clock[0] = 1
    assert r.tick() and r.error is None


def test_reporter_survives_a_broken_system_reading():
    def broken():
        raise RuntimeError("no sensors")

    sent = []
    r = Reporter(FakeDesktop(), sent.append, DeskConfig, system=broken, host="DESK")
    assert r.tick() and sent[0]["system"] is None


def test_system_status_from_psutil():
    ns = SimpleNamespace
    proc = [
        ns(info={"name": "chrome.exe", "cpu_percent": 40.0, "memory_info": ns(rss=2**30)}),
        ns(info={"name": "chrome.exe", "cpu_percent": 20.0, "memory_info": ns(rss=2**29)}),
        ns(info={"name": "Code.exe", "cpu_percent": 8.0, "memory_info": ns(rss=2**28)}),
        ns(info={"name": "System Idle Process", "cpu_percent": 700.0, "memory_info": None}),
    ]
    ps = ns(
        virtual_memory=lambda: ns(percent=50.0, total=16 * 2**30, available=8 * 2**30),
        disk_partitions=lambda all: [ns(device="C:\\", mountpoint="C:\\", opts="rw,fixed")],
        disk_usage=lambda m: ns(free=100e9, total=500e9),
        sensors_battery=lambda: None,
        net_if_stats=lambda: {"Ethernet": ns(isup=True), "Loopback": ns(isup=True)},
        cpu_count=lambda: 4,
        process_iter=lambda attrs: proc,
        cpu_percent=lambda interval: 12.5,
        boot_time=lambda: 0.0,
    )
    s = system_status(ps)
    assert s["memory_used_gb"] == 8.0 and s["online"] and s["battery"] is None
    assert s["busiest"][0] == {"app": "Chrome", "cpu_percent": 15.0, "memory_mb": 1536}
    assert len(s["disks"]) == 1 and s["disks"][0]["free_gb"] == 100
    Snapshot.model_validate({"system": s})


def test_config_round_trip_and_broken_file(tmp_path):
    config = DeskConfig(brain_url="http://10.0.0.5:8600/", face_x=10, face_y=20)
    config.save(tmp_path)
    loaded = DeskConfig.load(tmp_path)
    assert loaded.brain_url == "http://10.0.0.5:8600" and loaded.face_x == 10
    (tmp_path / "desk.toml").write_text("not = [valid", encoding="utf-8")
    assert DeskConfig.load(tmp_path) == DeskConfig()
    assert load_token(tmp_path) == ""
    save_token(" abc \n", tmp_path)
    assert load_token(tmp_path) == "abc"
    assert "abc" not in (tmp_path / "desk.toml").read_text(encoding="utf-8")


@pytest.fixture
def brain_api(paths):
    """The real brain API, in-process, with a fake local model."""
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    model = FakeModel(reply("Hi Dan.", "Ready."))
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    app = create_app(store, memory, brain, "tok", summarise_every_s=None)
    with TestClient(app) as tc:
        yield tc, brain
    memory.close()


class Through(httpx.BaseTransport):
    """Sends the desk client's requests to the in-process app."""

    def __init__(self, tc):
        self.tc = tc

    def handle_request(self, request):
        r = self.tc.request(
            request.method,
            request.url.raw_path.decode(),
            headers=request.headers,
            content=request.read(),
        )
        return httpx.Response(r.status_code, headers=r.headers, content=r.content)


def client_for(tc, token="tok"):
    return BrainClient("http://testserver", token, transport=Through(tc))


def test_client_chats_and_reports_to_the_real_api(brain_api):
    tc, brain = brain_api
    client = client_for(tc)
    assert client.check()["name"] == "Kit"
    events = list(client.chat("hello"))
    assert events[-1]["type"] == "reply"
    assert "".join(e["text"] for e in events if e["type"] == "say") == "Hi Dan. Ready."
    assert [m["role"] for m in client.messages()] == ["user", "kit"]

    sent = []
    r = Reporter(FakeDesktop(), client.report, DeskConfig, host="DESK")
    r.send = lambda snap: (sent.append(snap), client.report(snap))
    assert r.tick()
    line = brain.pc.now_line("Dan")
    assert 'VS Code: "pump.py - METTOOLS - Visual Studio Code"' in line
    assert "NetBank" not in str(brain.pc.latest.model_dump())


def test_client_explains_a_wrong_token_and_no_brain(brain_api):
    tc, _ = brain_api
    with pytest.raises(BrainError, match="kit token"):
        client_for(tc, "wrong").check()
    with pytest.raises(BrainError, match="kit token"):
        list(client_for(tc, "wrong").chat("hi"))

    def refuse(request):
        raise httpx.ConnectError("refused")

    down = BrainClient("http://kit-server:8600", "t", transport=httpx.MockTransport(refuse))
    with pytest.raises(BrainError, match="Can't reach Kit at http://kit-server:8600"):
        down.check()
    with pytest.raises(BrainError, match="Lost touch"):
        list(down.chat("hi"))


@pytest.mark.skipif(sys.platform != "win32", reason="reads real Windows windows")
def test_windows_desktop_reads_this_pc():
    pytest.importorskip("psutil")
    desktop = WindowsDesktop()
    windows = desktop.windows()
    assert all(isinstance(w, OpenWindow) and w.title for w in windows)
    desktop.focused()
    assert desktop.idle_seconds() >= 0
    assert isinstance(desktop.locked(), bool)
    Snapshot.model_validate(build_snapshot(desktop, DeskConfig(), "CI", system_status()))


def test_kits_window_saves_settings_and_memory_through_the_real_api(brain_api, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets", reason="desk extra (PySide6) not installed")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kit.desk import window

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(window, "SYNC", True)
    tc, brain = brain_api
    client = client_for(tc)
    page = window.BrainSettingsPage(lambda: client, lambda: "")
    page.refresh()
    assert page.fields and page.note.text() == ""
    for section, _entry, key, _kind, control in page.fields:
        if (section, key) == ("brain", "history_messages"):
            control.setValue(12)
    page.save()
    assert page.note.text().startswith("Saved"), page.note.text()
    assert brain.settings().brain.history_messages == 12

    memory = window.MemoryPage(lambda: client, lambda: "")
    memory.teach.setText("Dan's tax returns are in Documents/Finance/Tax")
    memory.remember()
    assert memory.facts.count() == 1, memory.note.text()
