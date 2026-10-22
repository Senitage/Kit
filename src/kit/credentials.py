"""Credentials live in the data folder's secrets directory, or in environment variables.

They are never stored in settings.toml, so settings can be shown and edited freely.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from kit.paths import KitPaths

# Where each cloud provider's API key is looked for: environment variables first,
# then a file in the secrets folder.
API_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "anthropic": (("ANTHROPIC_API_KEY",), "anthropic_api_key"),
    "openai": (("OPENAI_API_KEY",), "openai_api_key"),
    "google": (("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini_api_key"),
}


def cloud_api_key(paths: KitPaths, provider: str) -> str | None:
    """A provider's API key from the environment, else from the secrets folder."""
    if provider not in API_KEYS:
        return None
    env_names, file_name = API_KEYS[provider]
    for env in env_names:
        key = os.environ.get(env)
        if key and key.strip():
            return key.strip()
    key_file = paths.secrets_dir / file_name
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip() or None
    return None


def anthropic_api_key(paths: KitPaths) -> str | None:
    return cloud_api_key(paths, "anthropic")


API_TOKEN_FILE = "api_token"


def api_token(paths: KitPaths, create: bool = True) -> str | None:
    """The token configurators use for Kit's API. Made on first use."""
    token_file = paths.secrets_dir / API_TOKEN_FILE
    if token_file.is_file():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return token
    if not create:
        return None
    token = secrets.token_urlsafe(32)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    # Owner-only on Linux; Windows ignores the mode (the stage 0 icacls step covers it).
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


HOME_ASSISTANT_TOKEN_FILE = "home_assistant_token"


def home_assistant_token(paths: KitPaths) -> str | None:
    """The long-lived token of Kit's own (non-admin) Home Assistant user, from the
    secrets folder or ``KIT_HOME_ASSISTANT_TOKEN``."""
    token = os.environ.get("KIT_HOME_ASSISTANT_TOKEN", "").strip()
    if token:
        return token
    path = paths.secrets_dir / HOME_ASSISTANT_TOKEN_FILE
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def app_token(paths: KitPaths, name: str, secret: str) -> str | None:
    """An app's token for Kit (``apps.servers.<name>.token_secret``), from the secrets
    folder or ``KIT_APP_<NAME>_TOKEN``. A secret name that isn't a plain file name is
    ignored, so a setting can't point outside the secrets folder."""
    env = "KIT_APP_" + "".join(c if c.isalnum() else "_" for c in name).upper() + "_TOKEN"
    token = os.environ.get(env, "").strip()
    if token:
        return token
    if not secret or secret != Path(secret).name or secret.startswith("."):
        return None
    path = paths.secrets_dir / secret
    if path.is_file():
        return path.read_text(encoding="utf-8").strip() or None
    return None
