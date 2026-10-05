"""Credentials live in the data folder's secrets directory, or in environment variables.

They are never stored in settings.toml, so settings can be shown and edited freely.
"""

from __future__ import annotations

import os

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
