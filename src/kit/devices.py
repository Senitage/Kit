"""Devices paired with Kit, each with a token of its own (``kit pair``).

The desk app, home_app and the pages use Kit's one shared token (``kit token``).
A device that leaves the house, like a phone, gets its own instead, so losing it
means forgetting one device (``kit devices forget phone``) rather than changing
the token everywhere. Only a hash of each token is kept, in the secrets folder
beside the shared token; the token itself is shown once, in the pairing code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

DEVICES_FILE = "devices.json"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
KINDS = ("phone", "tablet", "watch", "pc", "robot", "other")


class DeviceError(ValueError):
    pass


@dataclass(frozen=True)
class Device:
    name: str  # also the body id it answers to (kit.body_registry)
    kind: str
    created: str
    token_hash: str
    # How to nudge it when Kit pipes up and its app is closed (kit.push): the push
    # service ("kind": fcm) and the phone's token there. None until the app registers.
    push: dict | None = None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pairing_link(url: str, name: str, token: str) -> str:
    """What the pairing QR code holds: where Kit is, this device's name and its token."""
    return "kit://pair?" + urlencode({"url": url.rstrip("/"), "name": name, "token": token})


class Devices:
    """The paired devices, kept in ``devices.json`` in the secrets folder (or only in
    memory, for tests, when ``file`` is None)."""

    def __init__(self, file: Path | None, clock: Callable[[], datetime] | None = None) -> None:
        self.file = file
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._devices: dict[str, Device] = {}
        self._mtime = None
        self._load()

    def _load(self) -> None:
        if self.file is None or not self.file.is_file():
            return
        mtime = self.file.stat().st_mtime_ns
        if mtime == self._mtime:
            return
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            found = {d["name"]: Device(**d) for d in raw.get("devices", [])}
            found = {n: d for n, d in found.items() if isinstance(d.push, dict | None)}
        except (ValueError, TypeError, KeyError):
            found = {}  # a broken file pairs nothing, rather than letting anything in
        self._devices, self._mtime = found, mtime

    def _save(self) -> None:
        if self.file is None:
            return
        self.file.parent.mkdir(parents=True, exist_ok=True)
        data = {"devices": [asdict(d) for d in self._devices.values()]}
        # Owner-only on Linux, like the shared token; Windows ignores the mode.
        fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._mtime = self.file.stat().st_mtime_ns

    def pair(self, name: str, kind: str = "phone") -> str:
        """Pair a device (or pair it again, which stops its old token working) and
        return its new token."""
        if not NAME.match(name):
            raise DeviceError(
                "a device name is lower case letters, digits and dashes, like phone or dans-tablet"
            )
        if kind not in KINDS:
            raise DeviceError(f"kind must be one of {', '.join(KINDS)}")
        self._load()
        token = secrets.token_urlsafe(32)
        now = self.clock().isoformat(timespec="seconds")
        old = self._devices.get(name)
        self._devices[name] = Device(name, kind, now, _hash(token), old.push if old else None)
        self._save()
        return token

    def set_push(self, name: str, kind: str, token: str) -> bool:
        """Remember how to nudge a device (the phone registered for notifications).
        False if there's no such device."""
        self._load()
        device = self._devices.get(name)
        if device is None:
            return False
        self._devices[name] = replace(device, push={"kind": kind, "token": token})
        self._save()
        return True

    def clear_push(self, name: str) -> bool:
        """Stop nudging a device (notifications turned off, or its token died)."""
        self._load()
        device = self._devices.get(name)
        if device is None or device.push is None:
            return False
        self._devices[name] = replace(device, push=None)
        self._save()
        return True

    def forget(self, name: str) -> bool:
        """Unpair a device: its token stops working at once."""
        self._load()
        if self._devices.pop(name, None) is None:
            return False
        self._save()
        return True

    def all(self) -> list[Device]:
        self._load()
        return sorted(self._devices.values(), key=lambda d: d.name)

    def match(self, token: str) -> Device | None:
        """The device this token belongs to, if any. Picks up pairing done by
        ``kit pair`` while the brain is running."""
        if not token:
            return None
        self._load()
        given = _hash(token)
        for device in self._devices.values():
            if secrets.compare_digest(given, device.token_hash):
                return device
        return None
