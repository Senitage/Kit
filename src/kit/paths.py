"""Where Kit keeps everything it owns.

All of Kit's state lives under one data folder, so moving Kit to another
machine or OS is a copy of that folder. Nothing outside it is written.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "KIT_DATA_DIR"


def default_data_dir() -> Path:
    """The data folder: $KIT_DATA_DIR if set, else a per-OS default."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Kit"
    return Path("/var/lib/kit")


@dataclass(frozen=True)
class KitPaths:
    root: Path

    @classmethod
    def default(cls) -> KitPaths:
        return cls(default_data_dir())

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.toml"

    @property
    def secrets_dir(self) -> Path:
        return self.root / "secrets"

    @property
    def state_dir(self) -> Path:
        """Memory, indexes and other databases."""
        return self.root / "state"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def all_dirs(self) -> list[Path]:
        return [self.config_dir, self.secrets_dir, self.state_dir, self.logs_dir]

    def ensure(self) -> None:
        for directory in self.all_dirs():
            directory.mkdir(parents=True, exist_ok=True)
