"""Kit's settings file, with change history, undo and a last-good copy.

Every configurator (the built-in page, ``kit config``, home_app) changes
settings through this store, so each change is checked against the schema and
the previous version is kept. Hand edits to settings.toml are picked up too: a
valid edit becomes the new last-good copy, a broken one is reported and Kit
keeps running on the last good version.
"""

from __future__ import annotations

import functools
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from kit.paths import KitPaths
from kit.settings import (
    Settings,
    SettingsError,
    load_settings,
    read_toml,
    settings_to_toml,
    validate_settings,
)

Clock = Callable[[], datetime]
HISTORY_KEEP = 100


@dataclass(frozen=True)
class Version:
    """The settings as they were just before a change made by ``changed_by``."""

    id: str
    saved_at: str
    changed_by: str
    path: Path


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _merge(base: dict, patch: dict) -> dict:
    """Apply a change section by section. A field's new value replaces the old one
    whole, so removing an entry from a list or table works."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _safe_name(who: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", who).strip("-")[:40] or "unknown"


def _locked(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class SettingsStore:
    def __init__(self, paths: KitPaths, clock: Clock = _utc_now) -> None:
        self.paths = paths
        self.clock = clock
        self._settings: Settings | None = None
        self._seen: tuple[int, int] | None = None
        self.problem: str | None = None
        self._lock = threading.RLock()  # the server reads from several threads

    @property
    def last_good_file(self) -> Path:
        return self.paths.config_dir / "settings.last-good.toml"

    @property
    def history_dir(self) -> Path:
        return self.paths.config_dir / "history"

    @_locked
    def current(self) -> Settings:
        """The settings in force, re-read if the file changed since last time."""
        signature = self._signature()
        if self._settings is None or signature != self._seen:
            self._reload()
            self._seen = signature
        assert self._settings is not None
        return self._settings

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.paths.settings_file.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _reload(self) -> None:
        try:
            settings = load_settings(self.paths.settings_file)
        except SettingsError as e:
            self._settings = self._fallback()
            source = "the last good version" if self.last_good_file.exists() else "defaults"
            self.problem = f"{e}\nKit is running on {source} until the file is fixed."
            return
        self._settings = settings
        self.problem = None
        if self.paths.settings_file.exists():
            _write_atomic(self.last_good_file, settings_to_toml(settings))

    def _fallback(self) -> Settings:
        if self._settings is not None:
            return self._settings
        try:
            return load_settings(self.last_good_file)
        except SettingsError:
            return Settings()

    @_locked
    def update(self, patch: dict, changed_by: str) -> Settings:
        """Apply a partial change. Raises SettingsError, changing nothing, if it's invalid."""
        before = self.current()
        raw = _merge(before.model_dump(mode="json", exclude_none=True), patch)
        after = validate_settings(raw, "the change")
        if after != before:
            self._save_version(before, changed_by)
            self._write(after)
        return after

    @_locked
    def replace(self, settings: Settings, changed_by: str) -> Settings:
        before = self.current()
        if settings != before:
            self._save_version(before, changed_by)
            self._write(settings)
        return settings

    def history(self) -> list[Version]:
        """Saved versions, newest first."""
        versions = []
        for path in sorted(self.history_dir.glob("*.toml"), reverse=True):
            stamp, _, who = path.stem.partition("_")
            versions.append(Version(path.stem, stamp, who, path))
        return versions

    @_locked
    def undo(self) -> Settings:
        """Go back to the version before the last change."""
        versions = self.history()
        if not versions:
            raise SettingsError("there is no earlier version to go back to")
        latest = versions[0]
        restored = validate_settings(read_toml(latest.path), latest.path.name)
        self._write(restored)
        latest.path.unlink()
        return restored

    @_locked
    def restore(self, version_id: str, changed_by: str) -> Settings:
        match = [v for v in self.history() if v.id == version_id]
        if not match:
            raise SettingsError(f"no saved version called {version_id}")
        restored = validate_settings(read_toml(match[0].path), match[0].path.name)
        return self.replace(restored, changed_by)

    def _save_version(self, settings: Settings, changed_by: str) -> None:
        stamp = self.clock().strftime("%Y%m%dT%H%M%S%fZ")
        path = self.history_dir / f"{stamp}_{_safe_name(changed_by)}.toml"
        _write_atomic(path, settings_to_toml(settings))
        for old in self.history()[HISTORY_KEEP:]:
            old.path.unlink()

    def _write(self, settings: Settings) -> None:
        _write_atomic(self.paths.settings_file, settings_to_toml(settings))
        _write_atomic(self.last_good_file, settings_to_toml(settings))
        self._settings = settings
        self._seen = self._signature()
        self.problem = None
