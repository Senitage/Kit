"""Watching the desktop for Kit: window titles, app names, idle time and PC health.

No screenshots and no image processing. ``WindowsDesktop`` asks Windows which
top-level windows are open, which has focus, and when the keyboard or mouse was
last used. ``system_status`` reads CPU, memory, disks, battery and the busiest
apps through psutil. ``Reporter`` turns those into the brain's ``Snapshot``
shape, blanks private titles, and sends a report whenever focus changes and at
least every ``heartbeat_seconds`` otherwise.

Only ``WindowsDesktop`` is Windows-specific; everything else is plain Python
that tests drive with a fake desktop on any OS.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from kit.desk.config import DeskConfig

log = logging.getLogger(__name__)

MAX_WINDOWS = 60
SYSTEM_EVERY_S = 10.0

# Friendlier names for common apps, by exe name (lower case).
APP_NAMES = {
    "code.exe": "VS Code",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook",
    "olk.exe": "Outlook",
    "onenote.exe": "OneNote",
    "msaccess.exe": "Access",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "explorer.exe": "File Explorer",
    "windowsterminal.exe": "Terminal",
    "cmd.exe": "Command Prompt",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "obsidian.exe": "Obsidian",
    "claude.exe": "Claude",
    "ms-teams.exe": "Teams",
    "teams.exe": "Teams",
    "slack.exe": "Slack",
    "spotify.exe": "Spotify",
    "notepad.exe": "Notepad",
    "notepad++.exe": "Notepad++",
    "acrobat.exe": "Acrobat",
    "acrord32.exe": "Acrobat Reader",
    "sumatrapdf.exe": "SumatraPDF",
    "python.exe": "Python",
    "pythonw.exe": "Python",
    "ultimaker-cura.exe": "Cura",
    "creality print.exe": "Creality Print",
    "freecad.exe": "FreeCAD",
    "fusion360.exe": "Fusion 360",
    "arduino ide.exe": "Arduino IDE",
    "pbidesktop.exe": "Power BI",
    "ssms.exe": "SQL Server Management Studio",
    "vlc.exe": "VLC",
    "discord.exe": "Discord",
    "taskmgr.exe": "Task Manager",
}
# Store apps all run inside this host; their window title names the app.
FRAME_HOSTS = {"applicationframehost.exe"}
IGNORED_EXES = {"textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe"}
IGNORED_TITLES = {"Program Manager", "Windows Input Experience"}


@dataclass
class OpenWindow:
    exe: str
    title: str
    minimised: bool = False
    pid: int = 0


class Desktop(Protocol):
    def windows(self) -> list[OpenWindow]: ...
    def focused(self) -> OpenWindow | None: ...
    def idle_seconds(self) -> float: ...
    def locked(self) -> bool: ...


def app_name(exe: str, title: str = "") -> str:
    key = exe.lower()
    if key in FRAME_HOSTS:
        return title.split(" - ")[-1].strip() or "Windows app"
    if key in APP_NAMES:
        return APP_NAMES[key]
    stem = exe.rsplit(".", 1)[0] if key.endswith(".exe") else exe
    return stem or "Unknown app"


def _word_pattern(words: list[str]) -> re.Pattern | None:
    words = [w.strip() for w in words if w.strip()]
    if not words:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.IGNORECASE)


class Privacy:
    """Decides which titles stay on the PC."""

    def __init__(self, config: DeskConfig) -> None:
        self.apps = [a.lower() for a in config.hidden_apps if a.strip()]
        self.words = _word_pattern(config.hidden_words)

    def hides(self, exe: str, app: str, title: str) -> bool:
        names = (exe.lower(), app.lower())
        if any(a in n for a in self.apps for n in names):
            return True
        return bool(self.words and self.words.search(title))

    def window(self, w: OpenWindow) -> dict:
        app = app_name(w.exe, w.title)
        title = "" if self.hides(w.exe, app, w.title) else w.title
        return {"app": app, "title": title, "minimised": w.minimised}


def build_snapshot(desktop: Desktop, config: DeskConfig, host: str, system: dict | None) -> dict:
    """One report, in the brain's ``kit.pc_context.Snapshot`` shape."""
    snap: dict = {
        "host": host,
        "watching": config.watch,
        "idle_seconds": round(desktop.idle_seconds(), 1),
        "locked": desktop.locked(),
        "focus": None,
        "windows": [],
        "system": system,
    }
    if not config.watch or snap["locked"]:
        return snap
    privacy = Privacy(config)
    own = os.getpid()
    focus = desktop.focused()
    if focus and focus.pid != own:
        snap["focus"] = privacy.window(focus)
    snap["windows"] = [privacy.window(w) for w in desktop.windows() if w.pid != own][:MAX_WINDOWS]
    return snap


class Reporter:
    """Sends a report when focus changes, and a heartbeat in between."""

    def __init__(
        self,
        desktop: Desktop,
        send: Callable[[dict], None],
        config: Callable[[], DeskConfig],
        system: Callable[[], dict | None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
        host: str | None = None,
    ) -> None:
        self.desktop = desktop
        self.send = send
        self.config = config
        self.system = system
        self.clock = clock
        self.host = host or socket.gethostname()
        self.error: str | None = None
        self._last_key: tuple | None = None
        self._last_sent = float("-inf")
        self._system: dict | None = None
        self._system_at = float("-inf")

    def tick(self) -> bool:
        """Check the desktop once; returns True if a report went to Kit."""
        config = self.config()
        now = self.clock()
        if now - self._system_at >= SYSTEM_EVERY_S:
            try:
                self._system = self.system()
            except Exception:  # health numbers are a nice-to-have; never stop reporting
                log.exception("reading system status failed")
            self._system_at = now
        snap = build_snapshot(self.desktop, config, self.host, self._system)
        focus = snap["focus"] or {}
        key = (
            focus.get("app"),
            focus.get("title"),
            snap["watching"],
            snap["locked"],
            snap["idle_seconds"] >= 60,
        )
        if key == self._last_key and now - self._last_sent < config.heartbeat_seconds:
            return False
        try:
            self.send(snap)
        except Exception as e:
            self.error = str(e)
            self._last_key = None  # try again next tick
            return False
        self.error = None
        self._last_key, self._last_sent = key, now
        return True


def system_status(ps=None) -> dict:
    """CPU, memory, fixed disks, battery, uptime, network and the busiest apps."""
    if ps is None:
        import psutil as ps
    mem = ps.virtual_memory()
    disks = []
    for part in ps.disk_partitions(all=False):
        if sys.platform == "win32" and "fixed" not in part.opts:
            continue  # skip DVD drives, card readers and mapped network drives
        try:
            use = ps.disk_usage(part.mountpoint)
        except OSError:
            continue
        if use.total < 1e9:
            continue  # tiny system mounts, not real disks
        name = part.device.rstrip("\\") if sys.platform == "win32" else part.mountpoint
        disks.append({"name": name, "free_gb": use.free / 1e9, "total_gb": use.total / 1e9})
    battery = ps.sensors_battery() if hasattr(ps, "sensors_battery") else None
    stats = ps.net_if_stats()
    online = any(s.isup for n, s in stats.items() if not n.lower().startswith(("lo", "loop")))
    per_app: dict[str, list[float]] = {}
    count = ps.cpu_count() or 1
    for p in ps.process_iter(["name", "cpu_percent", "memory_info"]):
        info = p.info
        name = info.get("name") or ""
        if not name or name.lower() in ("system idle process", "idle"):
            continue
        app = app_name(name)
        row = per_app.setdefault(app, [0.0, 0.0])
        row[0] += (info.get("cpu_percent") or 0.0) / count
        mi = info.get("memory_info")
        row[1] += (mi.rss if mi else 0) / 2**20
    busiest = sorted(per_app.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[:5]
    return {
        "cpu_percent": ps.cpu_percent(interval=None),
        "memory_percent": mem.percent,
        "memory_used_gb": round((mem.total - mem.available) / 2**30, 1),
        "memory_total_gb": round(mem.total / 2**30, 1),
        "disks": disks[:26],
        "battery": {"percent": battery.percent, "plugged_in": bool(battery.power_plugged)}
        if battery
        else None,
        "uptime_hours": round((time.time() - ps.boot_time()) / 3600, 1),
        "online": online,
        "busiest": [
            {"app": app, "cpu_percent": round(c, 1), "memory_mb": round(m)}
            for app, (c, m) in busiest
        ],
    }


class WindowsDesktop:
    """Reads open windows, focus, idle time and the lock screen through the Win32 API."""

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    GW_OWNER = 4
    DWMWA_CLOAKED = 14
    DESKTOP_SWITCHDESKTOP = 0x0100

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        import psutil

        self._ct, self._wt, self._psutil = ctypes, wintypes, psutil
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32")
        self.dwmapi = ctypes.WinDLL("dwmapi")
        # Every handle is pointer-sized; without these, 64-bit handles would be cut short.
        u, hwnd = self.user32, wintypes.HWND
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [hwnd, ctypes.c_int]
        u.GetWindow.restype = hwnd
        u.GetWindow.argtypes = [hwnd, wintypes.UINT]
        u.GetForegroundWindow.restype = hwnd
        u.IsWindowVisible.argtypes = [hwnd]
        u.IsIconic.argtypes = [hwnd]
        u.GetWindowTextLengthW.argtypes = [hwnd]
        u.GetWindowTextW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(wintypes.DWORD)]
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        self.dwmapi.DwmGetWindowAttribute.argtypes = [
            hwnd,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel32.GetTickCount64.restype = ctypes.c_ulonglong

        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self._LastInput = LastInput
        u.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
        self._exe_by_pid: dict[int, str] = {}

    def _title(self, hwnd) -> str:
        n = self.user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = self._ct.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _pid(self, hwnd) -> int:
        pid = self._wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self._ct.byref(pid))
        return pid.value

    def _exe(self, pid: int) -> str:
        if pid not in self._exe_by_pid:
            try:
                self._exe_by_pid[pid] = self._psutil.Process(pid).name()
            except (self._psutil.Error, OSError):
                return ""
            if len(self._exe_by_pid) > 2000:
                self._exe_by_pid.clear()
        return self._exe_by_pid[pid]

    def _cloaked(self, hwnd) -> bool:
        value = self._wt.DWORD()
        hr = self.dwmapi.DwmGetWindowAttribute(
            hwnd, self.DWMWA_CLOAKED, self._ct.byref(value), self._ct.sizeof(value)
        )
        return hr == 0 and value.value != 0

    def _window(self, hwnd) -> OpenWindow | None:
        title = self._title(hwnd)
        if not title or title in IGNORED_TITLES:
            return None
        pid = self._pid(hwnd)
        exe = self._exe(pid)
        if exe.lower() in IGNORED_EXES:
            return None
        return OpenWindow(exe, title, bool(self.user32.IsIconic(hwnd)), pid)

    def windows(self) -> list[OpenWindow]:
        """The windows on the taskbar, front to back."""
        found: list[OpenWindow] = []
        user32 = self.user32

        @self._ct.WINFUNCTYPE(self._wt.BOOL, self._wt.HWND, self._wt.LPARAM)
        def each(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, self.GW_OWNER):
                    return True
                if user32.GetWindowLongPtrW(hwnd, self.GWL_EXSTYLE) & self.WS_EX_TOOLWINDOW:
                    return True
                if self._cloaked(hwnd):
                    return True
                w = self._window(hwnd)
                if w:
                    found.append(w)
            except Exception:
                log.exception("reading a window failed")
            return True

        user32.EnumWindows(each, 0)
        return found

    def focused(self) -> OpenWindow | None:
        hwnd = self.user32.GetForegroundWindow()
        return self._window(hwnd) if hwnd else None

    def idle_seconds(self) -> float:
        info = self._LastInput(self._ct.sizeof(self._LastInput), 0)
        if not self.user32.GetLastInputInfo(self._ct.byref(info)):
            return 0.0
        now = self.kernel32.GetTickCount64() & 0xFFFFFFFF  # dwTime is 32-bit and wraps
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def locked(self) -> bool:
        # While locked, the input desktop is the secure one and can't be opened.
        desk = self.user32.OpenInputDesktop(0, False, self.DESKTOP_SWITCHDESKTOP)
        if not desk:
            return True
        self.user32.CloseDesktop(desk)
        focus = self.focused()
        return bool(focus and focus.exe.lower() == "lockapp.exe")
