"""Doing what Kit asks on the PC, within rules that live on the PC.

Kit's brain sends a ``desk_command`` (kit.desk_commands); this decides whether it's
allowed and does it. The rules are the desk app's own ("What Kit may open" on the
This PC page), so nothing the brain says can widen them:

- a file or folder opens only if it's inside one of ``open_roots`` (no ``..``, no
  other share), and never a program or script (``RUNNABLE``);
- an app starts only by a short name in ``apps``, and only with paths that pass the
  same check as its arguments;
- a site opens only over http, https or one of ``url_schemes``;
- ``focus`` brings forward a window whose title isn't one the PC keeps private, and
  ``media`` presses one of the media keys.

The Windows calls are behind ``Hands`` so tests use a fake on any OS;
``WindowsHands`` is the real one.
"""

from __future__ import annotations

import logging
import ntpath
import os
import posixpath
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from kit.desk.config import DeskConfig
from kit.desk.watch import OpenWindow, Privacy, app_name

log = logging.getLogger(__name__)

SHOW_MAX = 5
MAX_ARGS = 5
# Opening these would run something, not show it.
RUNNABLE = {
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".msi", ".msp", ".scr", ".hta", ".lnk", ".url", ".pif", ".reg",
    ".jar", ".py", ".pyw", ".appref-ms", ".cpl", ".msc", ".sh",
}  # fmt: skip
MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")


@dataclass(frozen=True)
class Outcome:
    ok: bool
    detail: str


class Hands(Protocol):
    def exists(self, path: str) -> bool: ...
    def open(self, path: str) -> None: ...
    def launch(self, target: str, args: list[str]) -> None: ...
    def browse(self, url: str) -> None: ...
    def windows(self) -> list[OpenWindow]: ...
    def focus(self, window: OpenWindow) -> bool: ...
    def key(self, code: int) -> None: ...


def _windows_style(path: str) -> bool:
    return "\\" in path or bool(re.match(r"^[A-Za-z]:", path))


def _norm(path: str) -> str:
    """A path in one comparable form: Windows paths case-folded with backslashes."""
    if _windows_style(path):
        return ntpath.normcase(ntpath.normpath(path))
    return posixpath.normpath(path)


def expand(root: str) -> str:
    """A root as written in the settings (``~``, ``%USERPROFILE%``) as a real path."""
    return os.path.expandvars(os.path.expanduser(root.strip()))


def allowed_path(path: str, roots: list[str]) -> str | None:
    """Why ``path`` mayn't be opened, or None when it may."""
    path = path.strip().strip('"')
    if not path:
        return "no path was given"
    flavour = ntpath if _windows_style(path) else posixpath
    if not flavour.isabs(path):
        return f"{path} isn't a full path"
    parts = re.split(r"[\\/]+", path)
    if ".." in parts:
        return f"{path} steps out of its folder"
    if path.startswith(("\\\\?\\", "\\\\.\\")):
        return f"{path} isn't an ordinary path"
    _, ext = flavour.splitext(path)
    if ext.lower() in RUNNABLE:
        return f"{flavour.basename(path)} would run a program, so Kit doesn't open it"
    here = _norm(path)
    for root in roots:
        base = _norm(expand(root)) if root.strip() else ""
        if not base:
            continue
        sep = "\\" if _windows_style(base) else "/"
        if here == base or here.startswith(base.rstrip(sep) + sep):
            return None
    return f"{path} isn't in a folder this PC lets Kit open (This PC, What Kit may open)"


def _url(url: str, schemes: list[str]) -> str | None:
    """``url`` ready to open (https added when it has none), or None when its kind
    of address isn't allowed (``file:``, ``javascript:``, an app Dan didn't list)."""
    url = url.strip()
    if not url or any(c.isspace() for c in url):
        return None
    m = _SCHEME.match(url)
    if m is None:
        return "https://" + url
    allowed = {"http", "https", *(s.lower().rstrip(":") for s in schemes)}
    return url if m.group(1).lower() in allowed else None


def apps_text(apps: dict[str, str]) -> str:
    """The app list as the This PC page shows it: ``name = program``, one a line."""
    return "\n".join(f"{name} = {target}" for name, target in apps.items())


def apps_from_text(text: str) -> dict[str, str]:
    """The This PC page's app list back into ``DeskConfig.apps``; bad lines are skipped."""
    apps = {}
    for line in text.splitlines():
        name, eq, target = line.partition("=")
        if eq and name.strip() and target.strip():
            apps[name.strip().lower()] = target.strip()
    return apps


def log_line(line: dict) -> str:
    """One entry of ``Runner.log`` for the This PC page."""
    args = ", ".join(str(v) for v in (line.get("args") or {}).values() if v)
    mark = "done" if line.get("ok") else f"not done: {line.get('detail', '')}"
    return f"{line.get('at', '')}  {line.get('kind', '')} {args}  ({mark})"


class Runner:
    """Carries out one command; ``log`` keeps the last 50 for the This PC page."""

    def __init__(self, config: Callable[[], DeskConfig], hands: Hands) -> None:
        self.config = config
        self.hands = hands
        self.log: list[dict] = []

    def run(self, kind: str, args: dict) -> Outcome:
        try:
            outcome = self._run(kind, args or {})
        except Exception as e:  # a Windows call failing must come back as words
            log.exception("desk command %s failed", kind)
            outcome = Outcome(False, f"it didn't work on this PC ({e or type(e).__name__})")
        line = {"at": time.strftime("%H:%M"), "kind": kind, "args": args, **outcome.__dict__}
        self.log = [line, *self.log[:49]]
        return outcome

    def _run(self, kind: str, args: dict) -> Outcome:
        config = self.config()
        if kind == "open_path":
            return self._open(str(args.get("path", "")), config)
        if kind == "show":
            paths = [str(p) for p in args.get("paths") or []][:SHOW_MAX]
            done = [self._open(p, config) for p in paths]
            opened = sum(o.ok for o in done)
            why = "; ".join(o.detail for o in done if not o.ok)
            detail = f"opened {opened} of {len(done)}" + (f" ({why})" if why else "")
            return Outcome(opened > 0, detail)
        if kind == "open_app":
            return self._launch(str(args.get("name", "")), args.get("args") or [], config)
        if kind == "open_url":
            url = _url(str(args.get("url", "")), config.url_schemes)
            if url is None:
                return Outcome(False, "that isn't a web address Kit may open")
            self.hands.browse(url)
            return Outcome(True, "")
        if kind == "focus":
            return self._focus(str(args.get("window", "")), config)
        if kind == "media":
            code = MEDIA_KEYS.get(str(args.get("action", "")))
            if code is None:
                return Outcome(False, "there's no media key like that")
            self.hands.key(code)
            return Outcome(True, "")
        return Outcome(False, f"this desk app can't do {kind}; it may need updating")

    def _open(self, path: str, config: DeskConfig) -> Outcome:
        path = path.strip().strip('"')
        why = allowed_path(path, config.open_roots)
        if why:
            return Outcome(False, why)
        if not self.hands.exists(path):
            return Outcome(False, f"{path} isn't there on this PC")
        self.hands.open(path)
        return Outcome(True, "")

    def _launch(self, name: str, args: list, config: DeskConfig) -> Outcome:
        apps = {k.lower(): v for k, v in config.apps.items()}
        target = apps.get(name.strip().lower())
        if not target:
            known = ", ".join(sorted(apps)) or "none"
            return Outcome(False, f"{name} isn't one of the apps Kit may start ({known})")
        clean = []
        for arg in [str(a).strip().strip('"') for a in args][:MAX_ARGS]:
            why = allowed_path(arg, config.open_roots)
            if why:
                return Outcome(False, why)
            if not self.hands.exists(arg):
                return Outcome(False, f"{arg} isn't there on this PC")
            clean.append(arg)
        self.hands.launch(target, clean)
        return Outcome(True, "")

    def _focus(self, words: str, config: DeskConfig) -> Outcome:
        words = words.strip().lower()
        if not words:
            return Outcome(False, "which window? Give words from its title")
        privacy = Privacy(config)
        for w in self.hands.windows():
            app = app_name(w.exe, w.title)
            if privacy.hides(w.exe, app, w.title):
                continue
            if words in w.title.lower() or words == app.lower():
                if self.hands.focus(w):
                    return Outcome(True, w.title[:80])
                return Outcome(False, "Windows wouldn't bring it to the front")
        return Outcome(False, f"no open window matches '{words}'")


class NoHands:
    """Off Windows (trying the desk app out on Linux): nothing can be done."""

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def _no(self, *args) -> None:
        raise RuntimeError("only the desk app on Windows can do that")

    open = launch = browse = key = _no

    def windows(self) -> list[OpenWindow]:
        return []

    def focus(self, window: OpenWindow) -> bool:
        return False


class WindowsHands:
    """The real thing, on Windows: ShellExecute to open, the default browser for
    sites, and user32 for windows and media keys."""

    SW_RESTORE = 9
    KEYEVENTF_KEYUP = 0x0002
    VK_MENU = 0x12

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        from kit.desk.watch import WindowsDesktop

        self.desktop = WindowsDesktop()
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._hwnds: dict[tuple[int, str], int] = {}
        u = self.user32
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def open(self, path: str) -> None:
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only

    def launch(self, target: str, args: list[str]) -> None:
        params = subprocess.list2cmdline(args) if args else ""
        os.startfile(target, "open", params)  # type: ignore[attr-defined,call-arg]

    def browse(self, url: str) -> None:
        os.startfile(url)  # type: ignore[attr-defined]  # the default browser or app

    def windows(self) -> list[OpenWindow]:
        return self.desktop.windows_with_handles(self._hwnds)

    def focus(self, window: OpenWindow) -> bool:
        hwnd = self._hwnds.get((window.pid, window.title))
        if not hwnd:
            return False
        if window.minimised:
            self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        # Windows only lets the app the user last used take the front; a tap of Alt
        # counts as using this one.
        self.user32.keybd_event(self.VK_MENU, 0, 0, None)
        self.user32.keybd_event(self.VK_MENU, 0, self.KEYEVENTF_KEYUP, None)
        return bool(self.user32.SetForegroundWindow(hwnd))

    def key(self, code: int) -> None:
        self.user32.keybd_event(code, 0, 0, None)
        self.user32.keybd_event(code, 0, self.KEYEVENTF_KEYUP, None)
