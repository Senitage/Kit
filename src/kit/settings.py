"""Kit's settings: one TOML file in the data folder, validated by a schema.

The schema (``Settings.model_json_schema()``) is what configurators such as
home_app will draw their forms from, so every field carries a description.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = 1


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OllamaSettings(_Section):
    url: str = Field(
        "http://127.0.0.1:11434", description="Address of the Ollama server on this machine."
    )
    model: str = Field("qwen3:8b", description="Local model for everyday chat.")

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/")


class ClaudeSettings(_Section):
    model: str = Field("claude-opus-5-5", description="Claude model for hard tasks.")


class NasSettings(_Section):
    read_only_shares: dict[str, str] = Field(
        default_factory=dict,
        description="Shares Kit may read but never change, by name. "
        r"A UNC path on Windows (\\NAS\photo) or a mount point on Linux (/mnt/nas/photo).",
    )
    vault: str | None = Field(
        None, description="The Obsidian vault folder, the only place on the NAS Kit may write."
    )


class Settings(_Section):
    schema_version: Literal[1] = SCHEMA_VERSION
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    nas: NasSettings = Field(default_factory=NasSettings)


class SettingsError(Exception):
    """The settings file can't be read or doesn't match the schema."""


def load_settings(path: Path) -> Settings:
    """Load settings from ``path``; a missing file means all defaults."""
    if not path.exists():
        return Settings()
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{path} is not valid TOML: {e}") from e
    try:
        return Settings.model_validate(raw)
    except ValidationError as e:
        problems = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise SettingsError(f"{path} has invalid settings:\n{problems}") from e
