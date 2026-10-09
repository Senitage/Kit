"""The desk app's update check against GitHub Releases, with a fake GitHub."""

import hashlib

import httpx
import pytest

from kit.desk import update
from kit.desk.update import UpdateError, Updater, is_newer, version_key

INSTALLER = b"MZ" + b"kit" * 1000


def release(version, asset=True, draft=False, digest=True, tag=None):
    assets = []
    if asset:
        assets.append(
            {
                "name": f"Kit-Desk-Setup-{version}.exe",
                "url": f"https://api.github.com/repos/Senitage/Kit/releases/assets/{version}",
                "size": len(INSTALLER),
                "digest": "sha256:" + hashlib.sha256(INSTALLER).hexdigest() if digest else None,
            }
        )
    return {
        "tag_name": tag or f"desk-v{version}",
        "draft": draft,
        "prerelease": False,
        "body": f"Notes for {version}",
        "html_url": f"https://github.com/Senitage/Kit/releases/tag/desk-v{version}",
        "published_at": "2026-10-07T00:00:00Z",
        "assets": assets,
    }


def github(releases, status=200, body=INSTALLER, seen=None, compare=None):
    """``compare``: what GitHub says of "<commit>...<tag>" (ahead, diverged...)."""

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path.endswith("/releases"):
            return httpx.Response(status, json=releases if status == 200 else {})
        if "/compare/" in request.url.path:
            said = (compare or {}).get(request.url.path.rpartition("/compare/")[2])
            return httpx.Response(200, json={"status": said}) if said else httpx.Response(404)
        if "/releases/assets/" in request.url.path:
            # GitHub sends the file from its own store.
            return httpx.Response(302, headers={"Location": "https://objects.example/kit.exe"})
        if request.url.host == "objects.example":
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def test_versions_compare_by_number():
    assert version_key("0.1.0.57") == (0, 1, 0, 57)
    assert is_newer("0.1.0.10", "0.1.0.9") and not is_newer("0.1.0.9", "0.1.0.9")
    assert is_newer("0.2.0.1", "0.1.0.99")


def test_the_newest_published_desk_release_is_found():
    releases = [
        release("0.1.0.9"),
        release("0.1.0.12"),
        release("0.1.0.20", draft=True),  # not published yet
        release("0.1.0.30", asset=False),  # build failed to attach
        release("0.1.0.40", tag="v0.1.0.40"),  # some other release
    ]
    up = Updater("Senitage/Kit", "tok", current="0.1.0.10", transport=github(releases))
    latest = up.latest()
    assert latest.version == "0.1.0.12" and latest.asset == "Kit-Desk-Setup-0.1.0.12.exe"
    assert up.newer() == latest
    assert Updater("Senitage/Kit", current="0.1.0.12", transport=github(releases)).newer() is None


def test_a_test_build_is_only_offered_a_release_with_its_changes():
    """Builds are numbered by run, so main's next release can outnumber a pull
    request's test build while still lacking its work (Kit lost his voice that way)."""
    commit = "8a08c20" + "0" * 33
    releases = [release("0.1.0.46"), release("0.1.0.50")]

    def check(said, current="0.1.0.49", test_commit=commit, seen=None):
        compare = {f"{commit}...desk-v0.1.0.50": said} if said else {}
        transport = github(releases, seen=seen, compare=compare)
        return Updater("Senitage/Kit", "tok", current, transport, test_commit=test_commit).newer()

    held = check("diverged")  # main moved on without the pull request
    assert held.version == "0.1.0.50" and not held.has_this_build
    assert not check("behind").has_this_build  # built before the test build's commit
    assert not check(None).has_this_build  # GitHub didn't say: no swap on a guess
    assert check("ahead").has_this_build  # the pull request is merged into it
    assert check("identical").has_this_build
    seen = []
    assert check("diverged", current="0.1.0.50", seen=seen) is None  # nothing newer
    assert check("diverged", test_commit="", seen=seen).has_this_build  # a build of main
    assert not [r for r in seen if "/compare/" in r.url.path]  # neither asks


def test_a_private_repo_without_a_token_says_what_to_do():
    up = Updater("Senitage/Kit", "", transport=github([], status=404))
    with pytest.raises(UpdateError, match="add a read-only token"):
        up.latest()
    with pytest.raises(UpdateError, match="didn't accept the token"):
        Updater("Senitage/Kit", "bad", transport=github([], status=401)).latest()


def test_the_download_is_checked_and_the_token_stays_with_github(tmp_path):
    seen = []
    up = Updater("Senitage/Kit", "secret", transport=github([release("0.1.0.12")], seen=seen))
    (tmp_path / "Kit-Desk-Setup-0.1.0.11.exe").write_bytes(b"old")
    got = []
    path = up.download(up.latest(), tmp_path, lambda n, total: got.append(n))
    assert path.read_bytes() == INSTALLER and got[-1] == len(INSTALLER)
    assert [p.name for p in tmp_path.iterdir()] == ["Kit-Desk-Setup-0.1.0.12.exe"]
    store = [r for r in seen if r.url.host == "objects.example"]
    assert store and "authorization" not in store[0].headers


def test_a_damaged_download_is_thrown_away(tmp_path):
    up = Updater("Senitage/Kit", "tok", transport=github([release("0.1.0.12")], body=b"MZ junk"))
    with pytest.raises(UpdateError, match="wrong size"):
        up.download(up.latest(), tmp_path)
    assert list(tmp_path.iterdir()) == []
    same_size = b"X" * len(INSTALLER)
    up = Updater("Senitage/Kit", "tok", transport=github([release("0.1.0.12")], body=same_size))
    with pytest.raises(UpdateError, match="checksum"):
        up.download(up.latest(), tmp_path)


def test_the_installer_runs_quietly_and_restarts_kit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(update.sys, "platform", "win32")
    update.run_installer(tmp_path / "setup.exe", popen=lambda args, **kw: calls.append(args))
    assert calls[0][1:] == ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/update=1"]
    monkeypatch.setattr(update.sys, "platform", "linux")
    with pytest.raises(UpdateError):
        update.run_installer(tmp_path / "setup.exe", popen=lambda *a, **k: None)
