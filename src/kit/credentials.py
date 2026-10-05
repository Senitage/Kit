"""Credentials live in the data folder's secrets directory, or in environment variables.

They are never stored in settings.toml, so settings can be shown and edited freely.
"""

from __future__ import annotations

import os
import secrets

from kit.paths import KitPaths

ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_KEY_FILE = "anthropic_api_key"


def anthropic_api_key(paths: KitPaths) -> str | None:
    """The Anthropic API key from the environment, else from the secrets folder."""
    key = os.environ.get(ANTHROPIC_KEY_ENV)
    if key:
        return key.strip()
    key_file = paths.secrets_dir / ANTHROPIC_KEY_FILE
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip() or None
    return None


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
