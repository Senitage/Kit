"""Kit's settings: one TOML file in the data folder, validated by a schema.

The schema (``Settings.model_json_schema()``) is what configurators such as
home_app will draw their forms from, so every field carries a description.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

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

    num_ctx: int = Field(
        8192,
        ge=2048,
        le=131072,
        description="Context window in tokens. Must hold the persona, memories and history; "
        "bigger uses more GPU memory.",
    )
    think: bool = Field(
        False, description="Let the local model think before answering. Slower; off for chat."
    )
    temperature: float = Field(
        0.7, ge=0, le=2, description="Higher is livelier, lower is steadier."
    )


Provider = Literal["anthropic", "openai", "google", "ollama"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ModelProfile(_Section):
    """One model Kit can use, with what it costs. Swap models by pointing a role
    (``routing.work``, ``routing.expert``) at a different profile."""

    label: str = Field("", description="Name Kit uses when it mentions this model.")
    provider: Provider = Field(
        description="Who runs it. anthropic, openai and google need an API key in "
        "Kit's secrets folder; ollama runs on this machine."
    )
    model: str = Field(min_length=1, description="The provider's model id.")
    effort: Effort = Field(
        "medium", description="How hard the model thinks before answering. Higher costs more."
    )
    max_tokens: int = Field(
        16000, ge=1000, le=128000, description="Longest answer, thinking included, in tokens."
    )
    web_search: bool = Field(
        True, description="Let the model search the web (the provider's own search)."
    )
    input_usd_per_mtok: float = Field(0, ge=0, description="Price per million input tokens.")
    cached_input_usd_per_mtok: float = Field(
        0, ge=0, description="Price per million input tokens read from the prompt cache."
    )
    output_usd_per_mtok: float = Field(
        0, ge=0, description="Price per million output tokens, thinking included."
    )
    search_usd_per_k: float = Field(0, ge=0, description="Price per 1,000 web searches.")

    @property
    def name(self) -> str:
        return self.label or self.model


# Prices are US dollars from each provider's price list on 6 October 2026.
DEFAULT_MODELS: dict[str, dict] = {
    "sonnet": {
        "label": "Sonnet",
        "provider": "anthropic",
        "model": "claude-sonnet-5-5",
        "effort": "low",
        "input_usd_per_mtok": 2.0,
        "cached_input_usd_per_mtok": 0.2,
        "output_usd_per_mtok": 10.0,
        "search_usd_per_k": 10.0,
    },
    "opus": {
        "label": "Opus",
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "effort": "medium",
        "input_usd_per_mtok": 4.0,
        "cached_input_usd_per_mtok": 0.2,
        "output_usd_per_mtok": 20.0,
        "search_usd_per_k": 10.0,
    },
    "gpt-sol": {
        "label": "GPT",
        "provider": "openai",
        "model": "gpt-6.1-sol",
        "effort": "low",
        "input_usd_per_mtok": 2.0,
        "cached_input_usd_per_mtok": 0.1,
        "output_usd_per_mtok": 10.0,
        "search_usd_per_k": 10.0,
    },
    "gemini-flash": {
        "label": "Gemini",
        "provider": "google",
        "model": "gemini-3.8-flash",
        "effort": "low",
        # Introductory prices until 31 December 2026, when they double.
        "input_usd_per_mtok": 0.75,
        "cached_input_usd_per_mtok": 0.075,
        "output_usd_per_mtok": 3.75,
        # 5,000 grounded requests a month are free; this prices the ones after that.
        "search_usd_per_k": 14.0,
    },
}


def _default_models() -> dict[str, ModelProfile]:
    return {name: ModelProfile.model_validate(p) for name, p in DEFAULT_MODELS.items()}


Mode = Literal["local-heavy", "balanced", "cloud-first"]


class RoutingSettings(_Section):
    mode: Mode = Field(
        "balanced",
        description="How much Kit leans on the local model. local-heavy: the local model "
        "answers and only hands over what it can't do. balanced: the local model takes "
        "small talk and quick commands, the cloud takes real questions and work. "
        "cloud-first: the cloud answers everything.",
    )
    work: str = Field(
        "sonnet", description="Model profile for real questions, work and web searches."
    )
    expert: str = Field("opus", description="Model profile for the hardest questions.")
    fallback_to_local: bool = Field(
        True,
        description="If the cloud can't be reached (offline, no key, budget used up), "
        "the local model answers instead.",
    )


class CloudSettings(_Section):
    monthly_cap_usd: float = Field(
        40.0, ge=0, description="Kit stops using cloud models once this month's spend reaches this."
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
    location: str = Field(
        "",
        description="Where the owner is, for weather and local searches, as 'city, state', "
        "e.g. Perth, WA.",
    )
    country: str = Field(
        "",
        pattern=r"^([A-Z]{2})?$",
        description="The owner's country as a two-letter code, e.g. AU.",
    )
    timezone: str = Field("", description="The owner's time zone, e.g. Australia/Perth.")
    knows: str = Field(
        "Dan is a mining plant process engineer who moved into data work. He builds site apps "
        "in Python, codes in VS Code, and keeps notes in Obsidian.",
        description="What Kit knows about the owner.",
    )
    rules: list[str] = Field(
        default_factory=lambda: [
            "Keep replies short; offer detail rather than dumping it.",
            "If you are not sure, say so instead of guessing.",
            "Hand real questions, maths, code and anything current to the cloud.",
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
    new_chat_after_minutes: int = Field(
        120,
        ge=0,
        le=10080,
        description="Start a fresh conversation when you come back after this long quiet "
        "(the old one stays in memory). 0 never does.",
    )
    new_topic_below: float = Field(
        0.45,
        ge=0,
        le=1,
        description="Start fresh when a message's meaning is this far from your last few "
        "(similarity below this, 0 to 1). 0 never does. Short or 'that/it' messages never "
        "count as a new topic.",
    )
    history_messages: int = Field(
        20, ge=2, le=200, description="Recent messages Kit sees each turn."
    )


class LifeSettings(_Section):
    enabled: bool = Field(
        True, description="Kit fidgets, gets bored and sometimes pipes up on his own."
    )
    cheek: float = Field(
        0.6,
        ge=0,
        le=1,
        description="How cheeky Kit is, in chat and when he pipes up: 0 polite, 1 larrikin.",
    )
    chattiness: float = Field(
        0.5,
        ge=0,
        le=1,
        description="How readily Kit speaks first. 0 never (he still fidgets), 1 whenever he "
        "feels like it, within the hourly limit. From 0.8 he follows along with what you're "
        "doing, nags when ignored and now and then butts in while you type.",
    )
    max_per_hour: int = Field(
        3, ge=0, le=30, description="Most times an hour Kit pipes up unprompted."
    )
    quiet_from: str = Field("22:00", description="Kit doesn't pipe up from this time...")
    quiet_until: str = Field("07:00", description="...until this time.")
    sleep_after_minutes: int = Field(
        10, ge=1, le=240, description="Kit dozes off after you've been away this long."
    )

    @field_validator("quiet_from", "quiet_until")
    @classmethod
    def _clock_time(cls, value: str) -> str:
        h, _, m = value.partition(":")
        if not (h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60 and len(m) == 2):
            raise ValueError("must be a time like 22:00")
        return f"{int(h):02d}:{m}"


class MemorySettings(_Section):
    embed_model: str = Field(
        "nomic-embed-text",
        description="Ollama model that turns text into meaning vectors, so Kit can find "
        "memories by meaning as well as by words. Changing it re-indexes everything.",
    )
    query_prefix: str = Field(
        "search_query: ", description="Text the embedding model wants before a search."
    )
    document_prefix: str = Field(
        "search_document: ", description="Text the embedding model wants before stored text."
    )
    relevant_memories: int = Field(
        8, ge=0, le=50, description="Memories recalled into each turn, most relevant first."
    )
    relevant_things: int = Field(
        5,
        ge=0,
        le=20,
        description="Entries from the register of things recalled into each turn, with "
        "where each lives. Things named in the message always come first.",
    )
    conversation_snippets: int = Field(
        4, ge=0, le=20, description="Older conversation snippets recalled into each turn."
    )
    min_similarity: float = Field(
        0.59,  # measured for nomic-embed-text with `kit eval memory` (2026-10-06)
        ge=0,
        le=1,
        description="How close in meaning a memory must be to count as relevant (0 to 1). "
        "It depends on the embedding model: `kit eval memory` suggests a value.",
    )
    backups_keep: int = Field(14, ge=1, le=365, description="Daily memory backups to keep.")


class Settings(_Section):
    schema_version: Literal[1] = SCHEMA_VERSION
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    models: dict[str, ModelProfile] = Field(
        default_factory=_default_models,
        description="Models Kit can use, by name. Built-in profiles are always there; "
        "change their fields or add your own.",
    )
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    nas: NasSettings = Field(default_factory=NasSettings)
    persona: PersonaSettings = Field(default_factory=PersonaSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    life: LifeSettings = Field(default_factory=LifeSettings)

    @field_validator("models", mode="before")
    @classmethod
    def _keep_built_in_models(cls, value):
        """Built-in profiles stay available; settings change their fields or add more."""
        if not isinstance(value, dict):
            return value
        merged = {name: dict(p) for name, p in DEFAULT_MODELS.items()}
        for name, profile in value.items():
            if isinstance(profile, BaseModel):
                profile = profile.model_dump()
            if isinstance(profile, dict):
                merged[name] = {**merged.get(name, {}), **profile}
            else:
                merged[name] = profile
        return merged

    @model_validator(mode="after")
    def _roles_name_models(self) -> Settings:
        for role in ("work", "expert"):
            name = getattr(self.routing, role)
            if name not in self.models:
                known = ", ".join(sorted(self.models))
                raise ValueError(f"routing.{role} is '{name}', which isn't a model ({known})")
        return self

    def profile(self, role: str) -> ModelProfile:
        """The model profile a role ("work" or "expert") points at."""
        return self.models[getattr(self.routing, role)]


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
