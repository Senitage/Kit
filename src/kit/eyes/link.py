"""Where the eyes keep their few files, and how they find the brain.

The eyes run on the machine with the camera, which is usually not the server,
so they can't read Kit's data folder. Like the desk app they keep a small
folder of their own (``%APPDATA%\\Kit Eyes``, ``~/.config/kit-eyes`` elsewhere,
or wherever ``KIT_EYES_DIR`` points) for the brain's address, the API token (in
its own file, never in a settings file) and the downloaded model files.

All the behaviour settings (which camera, mirroring, the detector...) live in
Kit's settings under ``[eyes]`` and come from the brain, so there is one place
to change them: the settings page, ``kit config`` or home_app.

Finding the brain, in order: what was given on the command line; this folder
(``kit eyes connect URL TOKEN``); the desk app's folder, when it's set up on
this PC; Kit's own data folder, when the eyes run on the server itself.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from kit.desk.config import CONFIG_FILE as DESK_CONFIG_FILE
from kit.desk.config import desk_dir
from kit.desk.config import load_token as desk_token
from kit.paths import KitPaths

EYES_DIR_ENV = "KIT_EYES_DIR"
CONFIG_FILE = "eyes.toml"
TOKEN_FILE = "api_token"
MODELS_DIR = "models"


def eyes_dir() -> Path:
    override = os.environ.get(EYES_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Kit Eyes"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kit-eyes"


def models_dir(folder: Path | None = None) -> Path:
    return (folder or eyes_dir()) / MODELS_DIR


@dataclass
class Connection:
    url: str
    token: str
    source: str  # where it came from, for `kit eyes` to say


def save_connection(url: str, token: str, folder: Path | None = None) -> Path:
    folder = folder or eyes_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / CONFIG_FILE).write_text(
        tomli_w.dumps({"brain_url": url.rstrip("/")}), encoding="utf-8"
    )
    path = folder / TOKEN_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token.strip() + "\n")
    return folder


def _read_url(path: Path, key: str) -> str:
    try:
        return str(tomllib.loads(path.read_text(encoding="utf-8")).get(key, "")).rstrip("/")
    except (OSError, tomllib.TOMLDecodeError):
        return ""


def _read_token(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def find_connection(
    url: str | None = None,
    token: str | None = None,
    folder: Path | None = None,
    desk_folder: Path | None = None,
    paths: KitPaths | None = None,
) -> Connection | None:
    """The brain's address and token, from the first place that has them."""
    url, token = (url or "").rstrip("/"), (token or "").strip()
    if url and token:
        return Connection(url, token, "the command line")
    folder = folder or eyes_dir()
    own_url, own_token = (
        _read_url(folder / CONFIG_FILE, "brain_url"),
        _read_token(folder / TOKEN_FILE),
    )
    if (url or own_url) and (token or own_token):
        return Connection(url or own_url, token or own_token, str(folder))
    desk_folder = desk_folder or desk_dir()
    desk_url = _read_url(desk_folder / DESK_CONFIG_FILE, "brain_url")
    desk_tok = desk_token(desk_folder)
    if (url or desk_url) and (token or desk_tok):
        return Connection(url or desk_url, token or desk_tok, f"the desk app ({desk_folder})")
    paths = paths or KitPaths.default()
    if paths.settings_file.is_file() or paths.secrets_dir.is_dir():
        from kit.credentials import api_token
        from kit.settings import load_settings

        try:
            brain = load_settings(paths.settings_file).brain
        except Exception:
            return None
        host = "127.0.0.1" if brain.host in ("0.0.0.0", "::") else brain.host
        own = api_token(paths, create=False) or ""
        here = url or f"http://{host}:{brain.port}"
        if token or own:
            return Connection(here, token or own, f"Kit's data folder ({paths.root})")
    return None
