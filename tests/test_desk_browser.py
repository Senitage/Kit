"""Kit's Chrome extension: the desk app's listener, tab privacy, and what Kit sees."""

import base64
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from fakes import Clock
from kit.desk.browser import EXTENSION_ID, BrowserFeed, BrowserListener, clean_url
from kit.desk.config import DeskConfig
from kit.desk.watch import Privacy, Reporter, build_snapshot
from kit.pc_context import PcContext, Snapshot
from test_desk_watch import FakeDesktop

ORIGIN = {"Origin": f"chrome-extension://{EXTENSION_ID}"}
EXTENSION = Path(__file__).parents[1] / "src" / "kit" / "desk" / "browser_extension"

TABS = {
    "browser": "Chrome",
    "tabs": [
        {
            "title": "Pump sizing - MetTools",
            "url": "http://mettools.lan/pumps?id=7#top",
            "active": True,
        },
        {"title": "NetBank - Home", "url": "https://www.my.commbank.com.au/netbank/home"},
        {"title": "Home", "url": "https://www.commbank.com.au/?session=abc"},
        {"title": "lofi beats", "url": "https://www.youtube.com/watch?v=x", "audible": True},
    ],
    "focused": {"title": "Pump sizing - MetTools", "url": "http://mettools.lan/pumps?id=7"},
}


def test_extension_id_comes_from_the_manifest_key():
    key = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))["key"]
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    assert "".join(chr(ord("a") + int(c, 16)) for c in digest) == EXTENSION_ID
    for name in ("background.js", "popup.html", "popup.js", "icon.png"):
        assert (EXTENSION / name).is_file()


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://www.youtube.com/watch?v=abc#t=1",
            ("https://www.youtube.com/watch", "youtube.com"),
        ),
        ("file:///C:/Users/Dan/tax.pdf", ("file:///C:/Users/Dan/tax.pdf", "local file")),
        ("chrome://settings/passwords", ("chrome://settings", "browser page")),
        ("chrome-extension://abc/popup.html", ("", "")),
        ("data:text/html,hi", ("", "")),
    ],
)
def test_addresses_lose_their_query_strings(url, expected):
    assert clean_url(url) == expected


def test_private_sites_are_blanked():
    privacy = Privacy(DeskConfig())
    tabs = [privacy.tab(t) for t in TABS["tabs"]]
    assert tabs[0] == {
        "title": "Pump sizing - MetTools",
        "url": "http://mettools.lan/pumps",
        "site": "mettools.lan",
        "active": True,
        "audible": False,
    }
    assert tabs[1]["title"] == tabs[1]["url"] == tabs[1]["site"] == ""
    assert tabs[2]["url"] == "" and tabs[2]["site"] == ""  # "commbank" in the address
    assert tabs[3]["audible"]


def test_focused_browser_window_names_the_site():
    desk = FakeDesktop()
    desk.focus = 1  # the Chrome window
    snap = build_snapshot(desk, DeskConfig(), "DESK", None, None)
    assert "site" not in snap["focus"]  # no extension: just the window title
    feed = BrowserFeed()
    feed.update(TABS)
    desk.open[1].title = "Pump sizing - MetTools - Google Chrome"
    snap = build_snapshot(desk, DeskConfig(), "DESK", None, feed.current())
    assert snap["focus"]["site"] == "mettools.lan" and len(snap["browser"]["tabs"]) == 4
    paused = build_snapshot(desk, DeskConfig(watch=False), "DESK", None, feed.current())
    assert "browser" not in paused
    Snapshot.model_validate(snap)


def test_old_tabs_are_dropped():
    now = [0.0]
    feed = BrowserFeed(clock=lambda: now[0])
    feed.update(TABS)
    assert feed.connected
    now[0] = 200
    assert feed.current() is None


def test_switching_tabs_sends_a_report():
    feed, sent, clock = BrowserFeed(), [], [0.0]
    desk = FakeDesktop()
    desk.focus = 1
    feed.update(TABS)
    r = Reporter(
        desk, sent.append, DeskConfig, clock=lambda: clock[0], host="D", browser=feed.current
    )
    assert r.tick()
    clock[0] = 1
    assert not r.tick()
    feed.update({**TABS, "focused": TABS["tabs"][3]})
    desk.open[1].title = "lofi beats - YouTube - Google Chrome"
    clock[0] = 2
    assert r.tick() and sent[-1]["focus"]["site"] == "youtube.com"


@pytest.fixture
def listener():
    feed = BrowserFeed()
    server = BrowserListener(feed, lambda: True, port=0)
    server.start()
    yield feed, f"http://127.0.0.1:{server.port}"
    server.stop()


def test_listener_takes_tabs_from_kits_extension_only(listener):
    feed, url = listener
    assert httpx.post(f"{url}/ping", headers=ORIGIN).json() == {"ok": True, "watching": True}
    assert httpx.post(f"{url}/ping").status_code == 403
    r = httpx.post(f"{url}/tabs", json=TABS, headers=ORIGIN)
    assert r.status_code == 200
    assert r.headers["Access-Control-Allow-Origin"] == ORIGIN["Origin"]
    assert feed.current()["focused"]["title"] == "Pump sizing - MetTools"
    # A web page, or another extension, can't feed it tabs.
    for origin in ({"Origin": "https://evil.example"}, {"Origin": "chrome-extension://other"}, {}):
        assert httpx.post(f"{url}/tabs", json={"tabs": []}, headers=origin).status_code == 403
    assert len(feed.current()["tabs"]) == 4
    assert httpx.post(f"{url}/tabs", content=b"nope", headers=ORIGIN).status_code == 400
    assert httpx.post(f"{url}/other", json={}, headers=ORIGIN).status_code == 404


def test_kit_sees_tabs_and_sites():
    clock = Clock()
    pc = PcContext(clock)
    feed = BrowserFeed()
    feed.update(TABS)
    desk = FakeDesktop()
    desk.focus = 1
    desk.open[1].title = "Pump sizing - MetTools - Google Chrome"
    for _ in range(20):
        clock.now += timedelta(seconds=30)
        pc.update(
            Snapshot.model_validate(build_snapshot(desk, DeskConfig(), "D", None, feed.current()))
        )
    assert "(mettools.lan), for 10 min." in pc.now_line("Dan")
    detail = pc.detail("Dan")
    assert "Chrome tabs (4, showing ones marked *):" in detail
    assert '- * "Pump sizing - MetTools" http://mettools.lan/pumps' in detail
    assert '"lofi beats" https://www.youtube.com/watch (playing sound)' in detail
    assert "- (title hidden)" in detail
    assert "Websites today:\n- mettools.lan: 10 min" in detail
    assert "commbank" not in detail
