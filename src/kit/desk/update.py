"""Keeping the desk app up to date from GitHub Releases.

Every change that lands on main is built by the "Desk app" workflow and
published as a GitHub Release tagged ``desk-v<version>``, with
Kit-Desk-Setup-<version>.exe attached. The desk app asks GitHub for the newest
of those, and when it's newer than itself it downloads the installer, checks
it arrived whole (size and SHA-256), and, once Dan says yes, runs it quietly.
The installer closes Kit, replaces the files and starts Kit again.

A pull request's build (from its run's Artifacts) is a test build. Builds are
numbered by run, so main's next release can outnumber a test build while still
lacking its work: a test build is only offered a release that has its commit in
it, which is once the pull request is merged.

Kit's repo is private, so GitHub only answers with a token. A fine-grained
token with read-only access to the Kit repo's contents is enough; it lives in
its own file in the desk app's folder (``github_token``), never in desk.toml.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

import kit

TAG_PREFIX = "desk-v"
ASSET = re.compile(r"^Kit-Desk-Setup-[\d.]+\.exe$")
API = "https://api.github.com"
CHECK_EVERY_S = 24 * 3600
FIRST_CHECK_S = 90  # after starting, so logging on stays quick
TIMEOUT = httpx.Timeout(10.0, read=60.0)
# The installer's quiet mode: no wizard, no questions; /update=1 tells it to
# start Kit again afterwards (see kit-desk.iss).
INSTALL_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/update=1"]

try:  # written by packaging/windows/build.ps1; absent when running from source
    from kit.desk._build import BUILD  # type: ignore[import-not-found]
except ImportError:
    BUILD = 0
try:  # the pull request a test build is of (0 for main) and the commit it was built from
    from kit.desk._build import COMMIT, PULL  # type: ignore[import-not-found]
except ImportError:
    COMMIT, PULL = "", 0

VERSION = f"{kit.__version__}.{BUILD}"
TEST_COMMIT = COMMIT if PULL else ""  # what a release must have in it to be offered


class UpdateError(Exception):
    """Checking or downloading failed. The message is fit to show Dan."""


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    notes: str
    published: str
    page: str  # the release on github.com
    asset: str  # installer file name
    asset_api: str  # where to download it from with the token
    size: int
    sha256: str  # from GitHub's asset digest; "" if GitHub didn't give one
    has_this_build: bool = True  # False: built without this test build's changes


def version_key(version: str) -> tuple[int, ...]:
    """'0.1.0.57' -> (0, 1, 0, 57), for comparing."""
    return tuple(int(x) for x in re.findall(r"\d+", version))


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return version_key(candidate) > version_key(current)


class Updater:
    def __init__(
        self,
        repo: str,
        token: str = "",
        current: str = VERSION,
        transport: httpx.BaseTransport | None = None,
        test_commit: str = TEST_COMMIT,
    ) -> None:
        self.repo = repo.strip().strip("/")
        self.current = current
        self.test_commit = test_commit
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "kit-desk"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=API, headers=headers, timeout=TIMEOUT, transport=transport
        )
        self.token = bool(token)

    def close(self) -> None:
        self._http.close()

    def latest(self) -> Release | None:
        """The newest published desk app release, or None if there isn't one yet."""
        try:
            r = self._http.get(f"/repos/{self.repo}/releases", params={"per_page": 20})
        except httpx.HTTPError as e:
            raise UpdateError(f"Can't reach GitHub ({type(e).__name__}).") from e
        if r.status_code in (401, 403):
            raise UpdateError("GitHub didn't accept the token. Check it on the Updates page.")
        if r.status_code == 404:
            raise UpdateError(
                f"GitHub can't find {self.repo}. It's private, so add a read-only token on "
                "the Updates page."
                if not self.token
                else f"GitHub can't find {self.repo} with this token. Check the token can "
                "read that repository."
            )
        if r.status_code >= 400:
            raise UpdateError(f"GitHub answered {r.status_code}.")
        found = []
        for rel in r.json():
            tag = rel.get("tag_name", "")
            if rel.get("draft") or rel.get("prerelease") or not tag.startswith(TAG_PREFIX):
                continue
            asset = next((a for a in rel.get("assets", []) if ASSET.match(a.get("name", ""))), None)
            if asset is None:
                continue
            digest = asset.get("digest") or ""
            found.append(
                Release(
                    version=tag[len(TAG_PREFIX) :],
                    tag=tag,
                    notes=rel.get("body") or "",
                    published=rel.get("published_at") or "",
                    page=rel.get("html_url") or "",
                    asset=asset["name"],
                    asset_api=asset["url"],
                    size=int(asset.get("size") or 0),
                    sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else "",
                )
            )
        return max(found, key=lambda x: version_key(x.version), default=None)

    def newer(self) -> Release | None:
        """The newest release, if it's newer than this build. On a test build, a
        release built without its changes comes back with ``has_this_build`` False."""
        release = self.latest()
        if release is None or not is_newer(release.version, self.current):
            return None
        if self.test_commit and not self._has(release, self.test_commit):
            return replace(release, has_this_build=False)
        return release

    def _has(self, release: Release, commit: str) -> bool:
        """Whether ``release`` was built from code with ``commit`` in it. GitHub not
        saying counts as no, so a test build is never swapped on a guess."""
        try:
            r = self._http.get(
                f"/repos/{self.repo}/compare/{commit}...{release.tag}", params={"per_page": 1}
            )
            return r.status_code == 200 and r.json().get("status") in ("ahead", "identical")
        except (httpx.HTTPError, ValueError):
            return False

    def download(
        self, release: Release, folder: Path, progress: Callable[[int, int], None] | None = None
    ) -> Path:
        """Fetch the installer into ``folder`` and check it arrived whole."""
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / release.asset
        part = target.with_name(target.name + ".part")
        sha = hashlib.sha256()
        got = 0
        try:
            with self._http.stream(
                "GET",
                release.asset_api,
                headers={"Accept": "application/octet-stream"},
                follow_redirects=True,  # to GitHub's file store; httpx drops the token there
            ) as r:
                if r.status_code >= 400:
                    raise UpdateError(f"GitHub answered {r.status_code} for the download.")
                with part.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
                        sha.update(chunk)
                        got += len(chunk)
                        if progress:
                            progress(got, release.size)
        except httpx.HTTPError as e:
            part.unlink(missing_ok=True)
            raise UpdateError(f"The download stopped ({type(e).__name__}). Try again.") from e
        if release.size and got != release.size:
            part.unlink(missing_ok=True)
            raise UpdateError("The download came out the wrong size. Try again.")
        if release.sha256 and sha.hexdigest() != release.sha256.lower():
            part.unlink(missing_ok=True)
            raise UpdateError("The download doesn't match GitHub's checksum, so it wasn't used.")
        part.replace(target)
        for old in folder.glob("Kit-Desk-Setup-*.exe"):  # earlier updates' installers
            if old != target:
                old.unlink(missing_ok=True)
        return target


def run_installer(path: Path, popen: Callable = subprocess.Popen) -> None:
    """Start the installer quietly. It closes Kit, updates him and starts him again."""
    if sys.platform != "win32":
        raise UpdateError("Updates install on Windows only.")
    popen([str(path), *INSTALL_ARGS], close_fds=True)
