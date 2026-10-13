"""Where the ears keep their few files: the brain's address, the API token (in
its own file) and the downloaded models, in ``%APPDATA%\\Kit Hearing``,
``~/.config/kit-hearing`` elsewhere, or wherever ``KIT_HEARING_DIR`` points.

Finding the brain works as it does for the eyes (kit.eyes.link): the command
line, this folder (``kit hearing connect URL TOKEN``), the desk app's folder on
this PC, or Kit's own data folder when the ears run on the server itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kit.eyes import link as eyes_link
from kit.paths import KitPaths

HEARING_DIR_ENV = "KIT_HEARING_DIR"
MODELS_DIR = "models"


def hearing_dir() -> Path:
    override = os.environ.get(HEARING_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Kit Hearing"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kit-hearing"


def models_dir(folder: Path | None = None) -> Path:
    return (folder or hearing_dir()) / MODELS_DIR


def save_connection(url: str, token: str, folder: Path | None = None) -> Path:
    return eyes_link.save_connection(url, token, folder or hearing_dir())


def find_connection(
    url: str | None = None,
    token: str | None = None,
    folder: Path | None = None,
    desk_folder: Path | None = None,
    paths: KitPaths | None = None,
) -> eyes_link.Connection | None:
    return eyes_link.find_connection(url, token, folder or hearing_dir(), desk_folder, paths)
