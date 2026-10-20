"""The desk app doing what Kit asks, within the PC's own rules (kit.desk.commands),
and the recent files it reports (kit.desk.watch)."""

import os
from dataclasses import replace

from kit.desk.commands import (
    MEDIA_KEYS,
    Runner,
    allowed_path,
    apps_from_text,
    apps_text,
    log_line,
)
from kit.desk.config import DeskConfig
from kit.desk.watch import OpenWindow, Reporter, recent_files

DOCS = "C:\\Users\\Sam\\Documents"


class FakeHands:
    def __init__(self, there=(), windows=()):
        self.there = {p.lower() for p in there}
        self.wins = list(windows)
        self.did = []

    def exists(self, path):
        return path.lower() in self.there

    def open(self, path):
        self.did.append(("open", path))

    def launch(self, target, args):
        self.did.append(("launch", target, args))

    def browse(self, url):
        self.did.append(("browse", url))

    def windows(self):
        return self.wins

    def focus(self, window):
        self.did.append(("focus", window.title))
        return True

    def key(self, code):
        self.did.append(("key", code))


def runner(hands, **config):
    base = DeskConfig(open_roots=[DOCS, "\\\\NAS\\finance"])
    return Runner(lambda: replace(base, **config), hands)


def test_paths_open_only_inside_the_allowed_folders():
    roots = [DOCS, "\\\\NAS\\finance"]
    assert allowed_path(DOCS + "\\Pumps\\curve.pdf", roots) is None
    assert allowed_path("c:\\users\\sam\\documents", roots) is None  # case doesn't matter
    assert allowed_path("\\\\nas\\finance\\Rates", roots) is None
    assert "isn't in a folder" in allowed_path("C:\\Windows\\System32", roots)
    assert "isn't in a folder" in allowed_path("C:\\Users\\Sam\\DocumentsX\\a.pdf", roots)
    assert "isn't in a folder" in allowed_path("\\\\NAS\\homes\\a.pdf", roots)
    assert "steps out" in allowed_path(DOCS + "\\..\\AppData\\x.txt", roots)
    assert "full path" in allowed_path("Documents\\a.pdf", roots)
    assert "run a program" in allowed_path(DOCS + "\\setup.EXE", roots)
    assert "run a program" in allowed_path(DOCS + "\\tool.ps1", roots)
    assert "ordinary" in allowed_path("\\\\?\\C:\\Users\\Sam\\Documents\\a", roots)
    assert allowed_path("/home/sam/Docs/a.txt", ["/home/sam/Docs"]) is None
    assert allowed_path("/home/sam/a.txt", ["/home/sam/Docs"]) is not None


def test_open_path_and_show_check_each_path_and_that_it_is_there():
    there = [DOCS + "\\a.pdf", DOCS + "\\Pumps"]
    hands = FakeHands(there)
    r = runner(hands)
    assert r.run("open_path", {"path": DOCS + "\\a.pdf"}).ok
    gone = r.run("open_path", {"path": DOCS + "\\b.pdf"})
    assert not gone.ok and "isn't there" in gone.detail
    shown = r.run("show", {"paths": [DOCS + "\\Pumps", "C:\\Windows"]})
    assert shown.ok and shown.detail.startswith("opened 1 of 2")
    assert hands.did == [("open", DOCS + "\\a.pdf"), ("open", DOCS + "\\Pumps")]
    assert len(r.log) == 3 and r.log[0]["kind"] == "show"
    assert "not done" in log_line(r.log[1]) and "b.pdf" in log_line(r.log[1])


def test_apps_start_only_by_their_short_name_with_allowed_paths():
    hands = FakeHands([DOCS + "\\Kit"])
    r = runner(hands, apps={"code": "code", "excel": "excel.exe"})
    assert r.run("open_app", {"name": "Code", "args": [DOCS + "\\Kit"]}).ok
    assert hands.did == [("launch", "code", [DOCS + "\\Kit"])]
    unknown = r.run("open_app", {"name": "regedit"})
    assert not unknown.ok and "code, excel" in unknown.detail
    flag = r.run("open_app", {"name": "code", "args": ["--disable-extensions"]})
    assert not flag.ok and len(hands.did) == 1


def test_sites_open_over_http_https_or_a_listed_scheme():
    hands = FakeHands()
    r = runner(hands, url_schemes=["obsidian"])
    assert r.run("open_url", {"url": "github.com"}).ok
    assert r.run("open_url", {"url": "obsidian://open?vault=Notes"}).ok
    for bad in ("file:///C:/Windows", "javascript:alert(1)", "ms-settings:", "a b"):
        assert not r.run("open_url", {"url": bad}).ok, bad
    assert hands.did == [
        ("browse", "https://github.com"),
        ("browse", "obsidian://open?vault=Notes"),
    ]


def test_focus_skips_private_windows_and_media_presses_a_key():
    wins = [
        OpenWindow("KeePass.exe", "Passwords - KeePass"),
        OpenWindow("EXCEL.EXE", "costs.xlsx - Excel"),
    ]
    hands = FakeHands(windows=wins)
    r = runner(hands)
    assert not r.run("focus", {"window": "keepass"}).ok
    assert r.run("focus", {"window": "excel"}).ok
    assert r.run("media", {"action": "play_pause"}).ok
    assert not r.run("media", {"action": "louder"}).ok
    assert hands.did == [("focus", "costs.xlsx - Excel"), ("key", MEDIA_KEYS["play_pause"])]


def test_a_failing_windows_call_and_an_unknown_kind_come_back_as_words():
    class Broken(FakeHands):
        def key(self, code):
            raise OSError("access denied")

    r = runner(Broken())
    out = r.run("media", {"action": "mute"})
    assert not out.ok and "access denied" in out.detail
    assert "may need updating" in r.run("teleport", {}).detail


def test_the_app_list_round_trips_through_its_text():
    apps = {"excel": "excel.exe", "code": "code"}
    assert apps_from_text(apps_text(apps)) == apps
    assert apps_from_text("Paint = mspaint.exe\nnonsense\n = x") == {"paint": "mspaint.exe"}


def test_recent_files_are_names_and_times_never_private_ones(tmp_path):
    for i, name in enumerate(["costs.xlsx", "bank statement.pdf", "Pumps", "notes.md"]):
        link = tmp_path / f"{name}.lnk"
        link.write_bytes(b"")
        os.utime(link, (1.7e9 + i, 1.7e9 + i))
    found = recent_files(tmp_path, DeskConfig())
    assert [f["name"] for f in found] == ["notes.md", "costs.xlsx"]  # newest first
    assert found[0]["when"].startswith("20") and "path" not in found[0]
    assert recent_files(None, DeskConfig()) == []


def test_the_reporter_sends_recent_files_hourly():
    class Desktop:
        def windows(self):
            return []

        def focused(self):
            return None

        def focused_rect(self):
            return None

        def idle_seconds(self):
            return 0.0

        def locked(self):
            return False

    sent, now = [], [0.0]
    recent = [{"name": "a.xlsx", "when": "2026-10-20T09:00:00+10:00"}]
    rep = Reporter(
        Desktop(),
        sent.append,
        lambda: DeskConfig(),
        clock=lambda: now[0],
        host="desk",
        recent=lambda config: recent,
    )
    rep.tick()
    now[0] = 30.0
    rep.tick()  # the heartbeat: no recent files this time
    now[0] = 3700.0
    rep.tick()
    assert [bool(s.get("recent_files")) for s in sent] == [True, False, True]
