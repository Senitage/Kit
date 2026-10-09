"""The desk app's own settings, kept on the desk PC.

The desk app runs on Dan's Windows PC, not on Kit's server, so it can't use
Kit's data folder. Its few settings (where the brain is, what to hide) live in
``%APPDATA%\\Kit Desk`` (``~/.config/kit-desk`` elsewhere, for trying it out),
or wherever ``KIT_DESK_DIR`` points. The API token sits in its own file there,
never in desk.toml, so the settings can be shown and shared freely.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

DESK_DIR_ENV = "KIT_DESK_DIR"
CONFIG_FILE = "desk.toml"
TOKEN_FILE = "api_token"
# A read-only GitHub token, only needed while Kit's repo is private (see kit.desk.update).
UPDATE_TOKEN_FILE = "github_token"

# Titles from these apps are never sent to Kit (matched against the app or exe name).
HIDDEN_APPS = ["KeePass", "KeePassXC", "1Password", "Bitwarden", "LastPass", "Dashlane"]
# Nor titles containing these whole words: banking, private browsing, passwords.
HIDDEN_WORDS = [
    "bank",
    "banking",
    "netbank",
    "commbank",
    "westpac",
    "anz",
    "nab",
    "ing",
    "paypal",
    "password",
    "passwords",
    "inprivate",
    "incognito",
    "private browsing",
]


def desk_dir() -> Path:
    override = os.environ.get(DESK_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Kit Desk"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kit-desk"


@dataclass
class DeskConfig:
    brain_url: str = "http://kit-server:8600"
    watch: bool = True  # report open windows and focus to Kit
    share_playing: bool = False  # tell Kit what's playing (a song, a video), for his away life
    poll_seconds: float = 2.0  # how often the desktop is checked
    heartbeat_seconds: float = 20.0  # report at least this often, even with no change
    hidden_apps: list[str] = field(default_factory=lambda: list(HIDDEN_APPS))
    hidden_words: list[str] = field(default_factory=lambda: list(HIDDEN_WORDS))
    show_face: bool = True
    face_size: int = 150
    face_x: int | None = None  # where Dan last left the face (its top left); None: bottom right
    face_y: int | None = None
    # How Kit looks (the Look page).
    theme: str = "system"  # system, dark or light
    accent: str = "#3b78d8"
    eye_colour: str = "#7ef3e6"
    font_pt: float = 10.5
    speech_bubble: bool = True  # say what Kit says in a bubble under his face
    words_with_voice: bool = True  # with his voice on, his words show as he says them
    boop: bool = True  # a little noise when he says something (kit.desk.sound)
    movement: str = "lively"  # how much he moves: still, a_little, lively or bouncy
    chat_width: int = 460
    chat_height: int = 640
    # Updates (kit.desk.update).
    check_updates: bool = True
    update_repo: str = "Senitage/Kit"

    @classmethod
    def load(cls, folder: Path | None = None) -> DeskConfig:
        path = (folder or desk_dir()) / CONFIG_FILE
        if not path.is_file():
            return cls()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return cls()  # a broken file must never stop the app; Settings rewrites it
        known = {f.name for f in fields(cls)}
        config = cls(**{k: v for k, v in data.items() if k in known})
        config.brain_url = config.brain_url.rstrip("/")
        return config

    def save(self, folder: Path | None = None) -> None:
        folder = folder or desk_dir()
        folder.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in asdict(self).items() if v is not None}
        (folder / CONFIG_FILE).write_text(tomli_w.dumps(data), encoding="utf-8")


def load_token(folder: Path | None = None, name: str = TOKEN_FILE) -> str:
    path = (folder or desk_dir()) / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_token(token: str, folder: Path | None = None, name: str = TOKEN_FILE) -> None:
    folder = folder or desk_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    # Owner-only on Linux; on Windows %APPDATA% is already private to Dan's account.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token.strip() + "\n")
