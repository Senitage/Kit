"""Kit's settings: one TOML file in the data folder, validated by a schema.

The schema (``Settings.model_json_schema()``) is what configurators such as
home_app will draw their forms from, so every field carries a description.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
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

    think: bool = Field(
        False, description="Let the local model think before answering. Slower; off for chat."
    )
    temperature: float = Field(
        0.7, ge=0, le=2, description="Higher is livelier, lower is steadier."
    )


class ClaudeSettings(_Section):
    model: str = Field("claude-opus-5-5", description="Claude model for hard tasks.")
    effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        "medium", description="How hard Claude works on each question. Higher costs more."
    )
    max_tokens: int = Field(
        16000, ge=1000, le=64000, description="Longest answer, thinking included, in tokens."
    )
    monthly_cap_usd: float = Field(
        20.0, ge=0, description="Kit stops asking Claude once this month's spend reaches this."
    )
    input_usd_per_mtok: float = Field(
        5.0, ge=0, description="Price per million input tokens, for the spend log."
    )
    output_usd_per_mtok: float = Field(
        25.0, ge=0, description="Price per million output tokens, for the spend log."
    )


class NasSettings(_Section):
    read_only_shares: dict[str, str] = Field(
        default_factory=dict,
        description="Shares Kit may read but never change, by name. "
        r"A UNC path on Windows (\\NAS\photo) or a mount point on Linux (/mnt/nas/photo).",
    )
    vault: str | None = Field(
        None, description="The Obsidian vault folder, the only place on the NAS Kit may write."
    )


class Example(_Section):
    user: str = Field(description="Something Dan says.")
    kit: str = Field(description="How Kit answers.")


class PersonaSettings(_Section):
    name: str = Field("Kit", min_length=1, description="The assistant's name.")
    owner: str = Field("Dan", min_length=1, description="Who Kit works for.")
    backstory: str = Field(
        "A small desk assistant who woke up on an engineer's desk and decided it likes "
        "process plants, Python and a tidy data pipeline.",
        description="Who Kit is, in a sentence or two.",
    )
    traits: list[str] = Field(
        default_factory=lambda: [
            "curious",
            "dry sense of humour",
            "loyal and practical",
            "a bit impatient with slow builds",
        ],
        description="Three to five core traits.",
    )
    speech: str = Field(
        "Short sentences, plain words, Australian-casual. One or two sentences unless asked "
        "for detail. Never gushes, never says 'as an AI'.",
        description="How Kit talks.",
    )
    knows: str = Field(
        "Dan is a mining plant process engineer who moved into data work. He builds site apps "
        "in Python, codes in VS Code, and keeps notes in Obsidian.",
        description="What Kit knows about the owner.",
    )
    rules: list[str] = Field(
        default_factory=lambda: [
            "Keep replies short; offer detail rather than dumping it.",
            "If you are not sure, say so instead of guessing.",
            "Hand hard maths, long code and deep technical questions to Claude.",
        ],
        description="Rules Kit always follows.",
    )
    examples: list[Example] = Field(
        default_factory=lambda: [
            Example(user="Morning.", kit="Morning. Coffee first, or straight into it?"),
            Example(
                user="The build failed again.",
                kit="Third time today. Want me to look at the log with you?",
            ),
            Example(
                user="What's a good flotation recovery?",
                kit="Depends on the ore, but high eighties is decent for copper sulphides.",
            ),
        ],
        description="Sample exchanges. Small models keep character best with a few of these.",
    )


class BrainSettings(_Section):
    host: str = Field(
        "127.0.0.1",
        description="Address the brain listens on. 127.0.0.1 is this PC only; "
        "0.0.0.0 lets the home network and Tailscale in.",
    )
    port: int = Field(8600, ge=1, le=65535, description="Port for the chat page and API.")
    history_messages: int = Field(
        20, ge=2, le=200, description="Recent messages Kit sees each turn."
    )
    facts_in_prompt: int = Field(
        30, ge=0, le=200, description="Remembered facts Kit sees each turn, newest first."
    )


class Settings(_Section):
    schema_version: Literal[1] = SCHEMA_VERSION
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    nas: NasSettings = Field(default_factory=NasSettings)
    persona: PersonaSettings = Field(default_factory=PersonaSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)


class SettingsError(Exception):
    """The settings file can't be read or doesn't match the schema."""


def problems(error: ValidationError) -> list[str]:
    """One "field.path: message" line per problem, for people to read."""
    return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in error.errors()]


def validate_settings(raw: dict, source: str = "settings") -> Settings:
    try:
        return Settings.model_validate(raw)
    except ValidationError as e:
        lines = "\n".join(f"  {p}" for p in problems(e))
        raise SettingsError(f"{source} has invalid settings:\n{lines}") from e


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{path} is not valid TOML: {e}") from e


def load_settings(path: Path) -> Settings:
    """Load settings from ``path``; a missing file means all defaults."""
    if not path.exists():
        return Settings()
    return validate_settings(read_toml(path), str(path))


def settings_to_toml(settings: Settings) -> str:
    """The settings as TOML. Unset optional values are left out (TOML has no null)."""
    return tomli_w.dumps(settings.model_dump(mode="json", exclude_none=True))
