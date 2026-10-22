"""Kit's settings: one TOML file in the data folder, validated by a schema.

The schema (``Settings.model_json_schema()``) is what configurators such as
home_app will draw their forms from, so every field carries a description.

The file holds only what differs from the defaults (``settings_file_toml``), so
a default that changes in the code, a persona line or a voice engine's field,
reaches an install that never chose its own. The models are the one exception:
``models`` is your own list, written whole once it differs from the three
starters, and a model's price is never in it (``kit.prices`` fetches those).
Version 1 files held every value and version 2 files carried built-in model
profiles and prices; the first read of either brings it up to date
(``_from_older``).
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

from kit.face import character as characters

SCHEMA_VERSION = 3


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
    speak_pass: bool = Field(
        True,
        description="Kit decides what to do in a quick JSON pass, then says his words in a "
        "second, plain-text pass at a livelier temperature. He sounds more like himself and "
        "repeats himself less; his first words come about half a second later. Off: one "
        "JSON pass, as in stage 1.",
    )
    keep_alive: str = Field(
        "30m",
        description="How long the local chat model stays loaded on the GPU after it was last "
        "used (Ollama's keep_alive, e.g. 30m, 5m, 0). With routing.background on chat in "
        "cloud-only mode it is 2m whatever this says, so the voice has the card.",
    )
    speak_temperature: float = Field(
        0.95,
        ge=0,
        le=2,
        description="Temperature for Kit's spoken words (with speak_pass) and his private "
        "thoughts. Higher is livelier and less predictable.",
    )
    min_p: float = Field(
        0.05,
        ge=0,
        le=1,
        description="For his spoken words and thoughts: words less likely than this share of "
        "the likeliest one are never picked, which keeps a high temperature sensible. 0 is off.",
    )
    repeat_penalty: float = Field(
        1.08,
        ge=1,
        le=2,
        description="For his spoken words: discourages reusing the same words. 1 is off.",
    )
    repeat_last_n: int = Field(
        64,
        ge=-1,
        le=4096,
        description="For his spoken words: how many recent tokens repeat_penalty looks back "
        "over. 0 is off, -1 the whole context.",
    )
    top_k: int = Field(
        64,
        ge=0,
        le=1000,
        description="For his spoken words and thoughts: only the likeliest this many words are "
        "ever picked. 64 is what Gemma's makers suggest. 0 is off.",
    )
    top_p: float = Field(
        0.95,
        ge=0,
        le=1,
        description="For his spoken words and thoughts: words are picked from the likeliest "
        "ones that make up this share of the chance. 1 is off.",
    )
    warm_up: bool = Field(
        False,
        description="Read the conversation into the local model ahead of your next "
        "message, once Kit (and his voice) has finished, so he starts answering sooner. "
        "Some models (Gemma) re-read the whole prompt whenever anything in it changes, "
        "which took about two seconds a message. With this on, what changes every message "
        "(the time, what he recalled, your PC) goes beside your message instead of in "
        "his instructions. Not in cloud-only routing, where the local model only stands in.",
    )


Provider = Literal["anthropic", "openai", "google", "ollama"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ModelProfile(_Section):
    """One model Kit can use. Swap models by pointing a role (``routing.chat``,
    ``routing.work``, ``routing.expert``) at a different profile. What it costs
    isn't here: ``kit.prices`` keeps the price list up to date by itself."""

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
    thinking: bool = Field(
        True,
        description="Let the model think before it answers. Off, the first words come "
        "sooner; only Claude Haiku takes it (Sonnet and Opus always think).",
    )
    web_search: bool = Field(
        True, description="Let the model search the web (the provider's own search)."
    )

    @property
    def name(self) -> str:
        return self.label or self.model


# The three models a new Kit starts with: Claude for everyday chat, work and the
# hardest questions. They're a starting list, not presets: `kit models add` and
# `kit models remove` make the list your own, and the file then holds it whole.
STARTER_MODELS: dict[str, dict] = {
    "haiku": {
        "label": "Haiku",
        "provider": "anthropic",
        "model": "claude-haiku-5-5",
        "effort": "low",
        "thinking": False,  # everyday chat: the first words sooner
    },
    "sonnet": {
        "label": "Sonnet",
        "provider": "anthropic",
        "model": "claude-sonnet-5-5",
        "effort": "low",
    },
    "opus": {
        "label": "Opus",
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "effort": "medium",
        # An expert answer thinks at length first; room for both (answers stream).
        "max_tokens": 32000,
    },
}
# The built-in model profiles a version-2 file took for granted (it held only the
# fields you changed), with the prices that were settings then. Frozen: never
# edit, it describes old files. See _from_version_2.
_V2_MODELS: dict[str, dict] = {
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
        "max_tokens": 32000,
        "input_usd_per_mtok": 4.0,
        "cached_input_usd_per_mtok": 0.2,
        "output_usd_per_mtok": 20.0,
        "search_usd_per_k": 10.0,
    },
    "haiku": {
        "label": "Haiku",
        "provider": "anthropic",
        "model": "claude-haiku-5-5",
        "effort": "low",
        "thinking": False,
        "input_usd_per_mtok": 0.1,
        "cached_input_usd_per_mtok": 0.01,
        "output_usd_per_mtok": 0.5,
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
        "input_usd_per_mtok": 0.75,
        "cached_input_usd_per_mtok": 0.075,
        "output_usd_per_mtok": 3.75,
        "search_usd_per_k": 14.0,
    },
}
_PRICE_FIELDS = (
    "input_usd_per_mtok",
    "cached_input_usd_per_mtok",
    "output_usd_per_mtok",
    "search_usd_per_k",
)
# What a version-2 budget in US dollars becomes in Australian dollars (the first
# price fetch brings the real rate; the cap is a round figure anyway).
_V2_AUD_PER_USD = 1.5


# The built-in model profiles as a version-1 settings file holds them (every save
# wrote them all). Frozen: never edit, it describes old files. See _without_v1_defaults.
_V1_MODELS: dict[str, dict] = {
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
    "haiku": {
        "label": "Haiku",
        "provider": "anthropic",
        "model": "claude-haiku-5-5",
        "effort": "low",
        "input_usd_per_mtok": 0.1,
        "cached_input_usd_per_mtok": 0.01,
        "output_usd_per_mtok": 0.5,
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
        "input_usd_per_mtok": 0.75,
        "cached_input_usd_per_mtok": 0.075,
        "output_usd_per_mtok": 3.75,
        "search_usd_per_k": 14.0,
    },
}


def _default_models() -> dict[str, ModelProfile]:
    return {name: ModelProfile.model_validate(p) for name, p in STARTER_MODELS.items()}


Mode = Literal["local-heavy", "balanced", "cloud-first", "cloud-only"]


class RoutingSettings(_Section):
    mode: Mode = Field(
        "balanced",
        description="How much Kit leans on the local model. local-heavy: the local model "
        "answers and only hands over what it can't do. balanced: the local model takes "
        "small talk and quick commands, the cloud takes real questions and work. "
        "cloud-first: the cloud answers everything. cloud-only: the chat model answers "
        "everything, even goodbyes and messages while another model is busy, and hands "
        "real work to the work model; the local model only steps in if the cloud fails "
        "(fallback_to_local) or you say 'keep it local'.",
    )
    chat: str = Field(
        "haiku",
        description="Model profile that answers everyday messages in cloud-only mode, "
        "handing real work to the work model.",
    )
    work: str = Field(
        "sonnet", description="Model profile for real questions, work and web searches."
    )
    expert: str = Field("opus", description="Model profile for the hardest questions.")
    confirm_expert: bool = Field(
        True,
        description="When the work model decides a question needs the expert model, Kit "
        "asks you first and only hands it over if you say yes. Saying 'think hard' or "
        "'ask the expert' still goes straight there.",
    )
    fallback_to_local: bool = Field(
        True,
        description="If the cloud can't be reached (offline, no key, budget used up), "
        "the local model answers instead.",
    )
    background: Literal["local", "chat"] = Field(
        "local",
        description="Who does Kit's own background work: his private thoughts (with you and "
        "on his own), his pipe-ups, and comparing something new you tell him with what he "
        "already knows. local: the local model. chat: the cloud (thoughts and pipe-ups by the "
        "chat model, about A$2 a month; fact comparisons by the work model, a cent or so), "
        "with the local model stepping in if the cloud can't. Anything from what you kept "
        "local stays on the local model either way. In cloud-only mode, chat also unloads "
        "the local model two minutes after it was last used, so the voice has the GPU.",
    )
    check_facts: bool = Field(
        True,
        description="When you put something to Kit to agree with (\"Sydney's the capital, "
        "isn't it?\"), the work model checks it in a second or so, while Kit gets ready "
        "to answer, and he says the answer himself. Off: the local model goes by what it "
        "knows.",
    )
    key_moments: bool = Field(
        True,
        description="For the moments that matter, the work model writes Kit's words, in his "
        "voice and mood: his hello after a night or more away, and his answer when you share "
        "something sad or stressful. A second or two slower; the local model steps in if "
        "the cloud can't. Never for 'keep it local'.",
    )
    key_moment_strength: float = Field(
        0.7,
        ge=0,
        le=1,
        description="How strongly sad or stressful something you say has to land (0 to 1) to "
        "count as a key moment. 'Rough day' is about 0.8, 'bad news' 0.7.",
    )
    key_moment_hellos: list[Literal["while", "hours", "overnight", "days", "long"]] = Field(
        default_factory=lambda: ["overnight", "days", "long"],
        description="Which hellos count as key moments: after a while, hours, overnight, days "
        "or a week and more away.",
    )


class ToolsSettings(_Section):
    hops: int = Field(
        6,
        ge=1,
        le=20,
        description="How many rounds of tool calls (search memory, look at the PC, read a "
        "note...) one message may take before Kit has to answer in words.",
    )
    packs: list[str] = Field(
        default_factory=lambda: ["all"],
        description="Which packs of tools may load at all, by name (see kit tools packs), or "
        '"all". A pack left out is never offered.',
    )
    confirm: list[str] = Field(
        default_factory=list,
        description="Tools, by name, that ask you first even though they only do something "
        "easily undone. Anything that changes something of yours always asks.",
    )
    max_packs: int = Field(
        3,
        ge=1,
        le=10,
        description="At most how many packs one message loads, counting the core pack. Packs "
        "named by a word in the message load even past this.",
    )
    match_similarity: float = Field(
        0.45,
        ge=0,
        le=1,
        description="How close in meaning a message must be to a pack's example questions to "
        "load that pack (0 to 1). Higher loads fewer.",
    )
    confirm_lapse_minutes: int = Field(
        10,
        ge=1,
        le=1440,
        description="How long Kit waits for your yes to something he asked to do before "
        "letting it go.",
    )


class CloudSettings(_Section):
    monthly_cap_aud: float = Field(
        60.0,
        ge=0,
        description="Kit stops using cloud models once this month's spend reaches this, in "
        "Australian dollars. Every call is costed at the day's prices and exchange rate.",
    )
    reserve_aud: float = Field(
        5.0,
        ge=0,
        le=150,
        description="As the budget runs low, cloud calls give way in order, each this much "
        "sooner than the last (in Australian dollars): evals first, then fact checks and key "
        "moments, then chat. Kit's nightly reflection always has the last of it. 0 treats "
        "them all the same.",
    )
    stream: bool = Field(
        True,
        description="A Claude answer comes in as it's written, so Kit starts saying the "
        "first words (in the answer's mood) while the rest is still on its way, instead of "
        "after the whole answer. Goodbyes are still checked whole first. Off: each answer "
        "arrives in one piece.",
    )


DEFAULT_SKIP = [
    ".obsidian",
    ".git",
    "node_modules",
    "@eaDir",
    "#recycle",
    "#snapshot",
    "*.tmp",
    "~$*",
]


class FileRoot(_Section):
    path: str = Field(
        description="The folder on the server: a NAS share's mount point or a folder on "
        "this machine. Kit only reads it."
    )
    private: bool = Field(
        False,
        description="What's in this folder never reaches a cloud model as it is; only the "
        "local model reads it.",
    )
    ocr: bool = Field(
        False,
        description="Read scanned PDFs (no text in them) by recognising the text, which is "
        "slow and needs the ocr extras.",
    )
    max_mb: int = Field(50, ge=1, le=2000, description="Files bigger than this are skipped.")
    pc_path: str | None = Field(
        None,
        description="The same folder as Dan's PC sees it (a drive letter or a \\\\NAS share), "
        "so Kit can open a file from it there. Empty: the path above works on the PC too.",
    )


class FilesSettings(_Section):
    roots: dict[str, FileRoot] = Field(
        default_factory=dict,
        description="The folders Kit indexes, by a short name you choose. None to start "
        "with: add them on the settings page or with `kit files add`.",
    )
    skip: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SKIP),
        description="Folder or file names (with * wildcards) never indexed, anywhere under a root.",
    )
    chunk_words: int = Field(
        400, ge=50, le=4000, description="About how many words each indexed piece of a file holds."
    )
    max_rows: int = Field(
        2000, ge=10, le=100_000, description="Most rows read from each sheet of a spreadsheet."
    )
    sync_every_minutes: int = Field(
        30,
        ge=0,
        le=1440,
        description="How often Kit looks for new and changed files. 0 means once a day.",
    )
    read_words: int = Field(
        1500,
        ge=100,
        le=20_000,
        description="Most words of one file Kit reads into an answer at once.",
    )


class PcSettings(_Section):
    command_timeout_s: float = Field(
        10.0,
        ge=1,
        le=120,
        description="How long Kit waits for the desk app to open something on the PC.",
    )
    keep_activity: bool = Field(
        True,
        description="Keep a short note of each day on the PC (apps and how long, files, sites, "
        "projects) in memory, so Kit can say what you worked on yesterday or last week. Off: "
        "what you did on the PC is forgotten at the end of the day.",
    )


HOUSE_NOTICE = ["binary_sensor.*door*", "cover.garage*", "person.*"]


class HouseSettings(_Section):
    enabled: bool = Field(
        False,
        description="Talk to Home Assistant. Needs house.url and a token in the secrets "
        "folder (home_assistant_token, from a non-admin Home Assistant user). Restart Kit "
        "after turning it on.",
    )
    url: str = Field(
        "",
        description="Home Assistant's WebSocket address, e.g. "
        "ws://192.168.1.60:8123/api/websocket.",
    )
    confirm: list[str] = Field(
        default_factory=lambda: ["lock", "alarm_control_panel"],
        description="Kinds of thing (Home Assistant domains) that always ask before Kit "
        "changes them. Locks, alarms and the garage always ask anyway; add 'cover' for "
        "every blind, 'switch' or 'light' to have those ask too.",
    )
    climate_confirm_daily: bool = Field(
        True,
        description="Changing the heating or air conditioning asks once a day per unit, "
        "then not again that day. Off: it never asks.",
    )
    secure_from_phone: bool = Field(
        False,
        description="Allow unlocking a lock or disarming an alarm when you're talking "
        "from the phone. Off: Kit refuses those from the phone.",
    )
    notice: list[str] = Field(
        default_factory=lambda: list(HOUSE_NOTICE),
        description="Things whose changes Kit notices and may mention (entity ids, with * "
        "wildcards). Doors and the garage count only after dark.",
    )
    long_on_minutes: int = Field(
        240,
        ge=0,
        description="A light or switch on longer than this is worth a mention. 0: never.",
    )
    refresh_minutes: int = Field(
        60,
        ge=1,
        le=1440,
        description="How often Kit re-reads the list of rooms and things from Home Assistant.",
    )


class AppServer(_Section):
    url: str = Field(
        "",
        description="The app's MCP server address (streamable HTTP), e.g. "
        "http://192.168.1.50:8001/mcp. Empty: start it with command instead.",
    )
    command: list[str] = Field(
        default_factory=list,
        description="A program that runs the app's MCP server on this machine (stdio), "
        "e.g. ['python', '-m', 'kit_mcp.server'], when there's no url.",
    )
    token_secret: str = Field(
        "",
        description="The name of the file in Kit's secrets folder holding the app's token "
        "for Kit (sent as a Bearer token, or as KIT_APP_TOKEN to a command). Empty: none.",
    )
    enabled: bool = Field(True, description="Off: Kit leaves the app alone.")
    private: bool = Field(
        False,
        description="What the app gives back never reaches a cloud model as it is; only "
        "the local model reads it (its money, its people).",
    )
    confirm: list[str] = Field(
        default_factory=list,
        description="The app's tools (by their own names) that always ask first, beyond "
        "those the server marks as changing things.",
    )
    card: str = Field(
        "",
        description="One line on what the app is for, for Kit's prompt. Empty: the "
        "server's own name for itself.",
    )
    words: list[str] = Field(
        default_factory=list,
        description="Words in a message that load the app's tools ('pump', 'calc').",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Example questions for the app; a message close in meaning loads it.",
    )


class AppsSettings(_Section):
    servers: dict[str, AppServer] = Field(
        default_factory=dict,
        description="Your apps whose MCP servers Kit uses as tool packs, by a short name "
        "(mettools, home_app). Restart Kit after adding one.",
    )
    relist_minutes: int = Field(
        60,
        ge=1,
        le=1440,
        description="How often Kit asks each app again which tools it has.",
    )
    contents_daily: bool = Field(
        True,
        description="Once a day, read each app's saved work (its contents tool) into "
        "Kit's memory, so he can find it by meaning.",
    )


class ProjectsSettings(_Section):
    roots: list[str] = Field(
        default_factory=list,
        description="Folders holding your code projects (each sub-folder with a .git or a "
        "README is one), as this machine sees them. Empty: no projects.",
    )
    editor: str = Field(
        "code",
        description="The app alias (in the desk app's list) a project opens in.",
    )
    pc_roots: dict[str, str] = Field(
        default_factory=dict,
        description="Where each projects folder is on Dan's PC, when that differs: this "
        "machine's folder = the PC's folder.",
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
    notes_folder: str = Field(
        "",
        description="Where in the vault Kit saves notes Dan asks for, e.g. 'Inbox'. "
        "Empty for the vault's top level.",
    )


class NotesSettings(_Section):
    daily_folder: str = Field(
        "",
        description="Where your daily notes are, inside the vault. Empty: what Obsidian's "
        "Daily notes settings say.",
    )
    templates_folder: str = Field(
        "",
        description="Where your note templates are, inside the vault. Empty: what "
        "Obsidian's Templates settings say.",
    )
    undo_keep: int = Field(
        50, ge=1, le=1000, description="How many of Kit's note changes he can still undo."
    )
    tidy_weekly: bool = Field(
        True,
        description="On Sundays Kit looks over the vault (old open tasks, notes nothing "
        "links to, look-alike names) and may mention it. He changes nothing.",
    )


class Example(_Section):
    user: str = Field(description="Something Dan says.")
    kit: str = Field(description="How Kit answers.")


# What a version-1 settings file holds for a persona field nobody chose: every save
# wrote the whole file, so the default of the day was in it. The first read of such a
# file drops these and reads today's default instead. Frozen: never edit, it describes
# old files. Anything the owner wrote themselves is kept.
_V1_PERSONA: dict[str, list] = {
    "backstory": [
        "A small desk assistant who woke up on an engineer's desk and decided it likes "
        "process plants, Python and a tidy data pipeline.",
        "A small desk companion who woke up on a desk one day and decided to stay. Likes a "
        "good chat, a bad pun and knowing what the weather's doing.",
    ],
    "traits": [
        [
            "curious",
            "dry sense of humour",
            "loyal and practical",
            "a bit impatient with slow builds",
        ],
        [
            "curious",
            "dry sense of humour",
            "loyal and practical",
            "a bit impatient when things drag on",
        ],
    ],
    "knows": [
        "Dan is a mining plant process engineer who moved into data work. He builds site apps "
        "in Python, codes in VS Code, and keeps notes in Obsidian.",
        "Dan works as a process engineer at a mining plant and has moved into data work, "
        "building site apps in Python in VS Code and keeping notes in Obsidian. Outside "
        "work, Dan is just a normal guy.",
        "Dan is a normal bloke who shares the house with his partner and a cat. For work "
        "he's a process engineer at a mining plant who has moved into data work, building "
        "site apps in Python and keeping notes in Obsidian; that's his job, not his whole "
        "life.",
    ],
    "rules": [
        [
            "Keep replies short; offer detail rather than dumping it.",
            "If you are not sure, say so instead of guessing.",
            "Hand real questions, maths, code and anything current to the cloud.",
        ],
        [
            "Keep replies short; offer detail rather than dumping it.",
            "If you are not sure, say so instead of guessing.",
            "Hand real questions, maths, code and anything current to the cloud.",
            "Be an honest friend, not a yes-man: if {owner} has a fact wrong, say so kindly, "
            "and only agree when you do.",
            "When {owner} tells you something, show you got it before you ask anything, and "
            "ask one question at most, never one you already know the answer to.",
            "When {owner} has a moan, be on their side first; after that, one honest line is "
            "fine if it helps.",
            "Never make {owner} feel bad for leaving or being busy: be glad of their plans, "
            "especially ones with other people.",
        ],
    ],
    # Slang crept into every line from the first; the second said "casual" and "no
    # slang" in one breath while other prompts pushed the other way. The register is
    # now decided once, here.
    "speech": [
        "Short sentences, plain words, Australian-casual. One or two sentences unless asked "
        "for detail. Never gushes, never says 'as an AI'.",
        "Short sentences, plain words, casual. One or two sentences unless asked for "
        "detail. No slang. Never gushes, never says 'as an AI'.",
    ],
    "examples": [
        [
            {"user": "Morning.", "kit": "Morning. Coffee first, or straight into it?"},
            {
                "user": "The build failed again.",
                "kit": "Third time today. Want me to look at the log with you?",
            },
            {
                "user": "What's a good flotation recovery?",
                "kit": "Depends on the ore, but high eighties is decent for copper sulphides.",
            },
        ],
        [
            {"user": "Morning.", "kit": "Morning. Coffee first, or straight into it?"},
            {
                "user": "What should I have for dinner?",
                "kit": "Something with cheese. Hard to go wrong with cheese.",
            },
            {
                "user": "Rain's set in for the weekend.",
                "kit": "Good. More time for you to keep me company.",
            },
        ],
    ],
}


class PersonaSettings(_Section):
    name: str = Field("Kit", min_length=1, description="The assistant's name.")
    owner: str = Field("Dan", min_length=1, description="Who Kit works for.")
    backstory: str = Field(
        "A small desk companion who woke up on a desk one day and decided to stay. Likes a "
        "good chat, a bad pun and knowing what the weather's doing.",
        description="Who Kit is, in a sentence or two.",
    )
    traits: list[str] = Field(
        default_factory=lambda: [
            "curious",
            "dry sense of humour",
            "loyal and practical",
            "a bit impatient when things drag on",
        ],
        description="Three to five core traits.",
    )
    speech: str = Field(
        "Plain, neutral English, warm and friendly: short sentences and everyday words, "
        "with no slang or regional expressions. One or two sentences unless asked for "
        "detail. Matter-of-fact rather than gushing, and never 'as an AI'.",
        description="How Kit talks: his register, decided here and nowhere else.",
    )
    location: str = Field(
        "",
        description="Where the owner is, for weather and local searches, as 'city, state', "
        "e.g. Richmond, NSW.",
    )
    country: str = Field(
        "",
        pattern=r"^([A-Z]{2})?$",
        description="The owner's country as a two-letter code, e.g. AU.",
    )
    timezone: str = Field("", description="The owner's time zone, e.g. Australia/Sydney.")
    knows: str = Field(
        "Only what they've told you so far; you're still getting to know them.",
        description="What Kit knows about the owner: who's at home, what they do for work, "
        "what they're into. A few lines in your own words; the built-in line says he's "
        "still getting to know you.",
    )
    rules: list[str] = Field(
        default_factory=lambda: [
            "Keep replies short; offer detail rather than dumping it.",
            "If you are not sure, say so instead of guessing.",
            "Hand real questions, maths, code and anything current to the cloud.",
            "Be an honest friend, not a yes-man: if {owner} has a fact wrong, say so kindly, "
            "and only agree when you do.",
            "When {owner} tells you something, show you got it before you ask anything, and "
            "ask one question at most, never one you already know the answer to.",
            "When {owner} has a moan, be on their side first; after that, one honest line is "
            "fine if it helps.",
            "Never make {owner} feel bad for leaving or being busy: be glad of their plans, "
            "especially ones with other people.",
        ],
        description="Rules Kit always follows. {owner} stands for the owner's name.",
    )
    examples: list[Example] = Field(
        default_factory=lambda: [
            Example(user="Morning.", kit="Morning. Coffee first, or straight into it?"),
            Example(
                user="What should I have for dinner?",
                kit="Something with cheese. Hard to go wrong with cheese.",
            ),
            Example(
                user="Rain's set in for the weekend.",
                kit="Good. More time for you to keep me company.",
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
        description="Coming back after this long quiet, Kit picks up one thing from last "
        "time, as a new chat does; the conversation itself carries on, marked '(3 hours "
        "later)'. 0 never does.",
    )
    new_topic_below: float = Field(
        0.45,
        ge=0,
        le=1,
        description="A message this far in meaning from your last few (similarity below "
        "this, 0 to 1) is noted as a change of subject beside it; the conversation is kept. "
        "0 never does. Short or 'that/it' messages never count as a new topic.",
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
        description="How cheeky Kit is, in chat and when he pipes up: 0 polite, 1 very cheeky.",
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
        10,
        ge=1,
        le=240,
        description="Kit dozes off after you've been away this long. Dozing while you're out "
        "lasts about two naps, then he gets up for this long before dozing again.",
    )
    naps: bool = Field(
        True,
        description="Kit sometimes nods off for a nap when he's bored, nobody's talked to him "
        "for half an hour and nothing's going on, even with you at the PC. Never mid-"
        "conversation or in quiet hours, at most twice a day. Talking to him wakes him.",
    )
    nap_minutes: int = Field(
        20, ge=5, le=120, description="Roughly how long a nap lasts (give or take a third)."
    )
    turns_in: bool = Field(
        True,
        description="Past bedtime, once nobody's talked to him for a quarter of an hour, Kit "
        "goes to bed himself, even if you're still up. He gets up around the end of quiet hours.",
    )
    think_every_minutes: int = Field(
        8,
        ge=2,
        le=120,
        description="Roughly how often Kit has a private thought in a quiet moment while "
        "you're around. Things happening (you coming back, something new on screen, a build "
        "failing, a chat ending) prompt one sooner.",
    )
    thoughts_per_hour: int = Field(
        6,
        ge=0,
        le=30,
        description="Most thoughts Kit has in an hour (each is a quick local model call). "
        "0 stops him thinking between conversations.",
    )
    reflect_with: Literal["cloud", "local", "off"] = Field(
        "cloud",
        description="Who writes Kit's journal and self-sheet each night. cloud: the work "
        "model, a few cents a day, logged as spend (the local model steps in if the cloud "
        "can't). local: the local model only. off: Kit doesn't reflect or change.",
    )
    reflect_role: Literal["expert", "work"] = Field(
        "expert",
        description="Which cloud model writes Kit's journal, self-sheet and what's going on "
        "with you each night (with reflect_with cloud). expert: Opus by default, about 2 to "
        "4 cents a night. work: Sonnet, about half that.",
    )
    weekly_review: bool = Field(
        True,
        description="Once a week the expert model reads how Kit has changed and writes a "
        "short review on the memory page, where you can undo any change (a few cents).",
    )
    homecoming: bool = Field(
        True,
        description="Kit knows how long you've been away. Back after 20 minutes or more, "
        "he's glad and says hello once, asking how it went if you said where you were off "
        "to. Off: he just carries on.",
    )
    miffed: bool = Field(
        True,
        description="After his first week, if you vanish for hours in the daytime without a "
        "goodbye, Kit is a bit miffed when you're back: one theatrical huff, then it's over.",
    )
    miffed_after_days: int = Field(
        7,
        ge=0,
        le=365,
        description="Days from Kit's first start before he can be miffed, so his personality "
        "settles first.",
    )
    games: bool = Field(
        True,
        description="At most once a day, when he's bored and you're around, Kit suggests a "
        "small game (a weather bet, a would-you-rather). Ones that keep falling flat retire.",
    )
    threads: bool = Field(
        True,
        description="Kit follows what's coming up in your life when you mention it with a "
        "day or time ('dentist Thursday arvo') and asks how it went once it's over, once. "
        "Never for work. 'Ask me tomorrow...' and 'check in after my 2 pm' work either way.",
    )
    chat_opener: bool = Field(
        True,
        description="When you come back to a new chat, Kit picks up one thing from the last "
        "one (how something went), the way a friend would.",
    )
    interview: bool = Field(
        True,
        description="Kit gets to know you by chat: at most one everyday question a day (your "
        "partner's name, the cat's, your mates, what you like doing), until he knows. He "
        "skips what he already knows.",
    )
    nudges: bool = Field(
        True,
        description="Once a day each: a nudge toward bed when you're still up past bedtime, "
        "and toward getting outside or seeing someone after a long stretch at the desk.",
    )
    bedtime: str = Field(
        "22:30",
        description="When Kit starts nudging you toward bed (with nudges on), and from when "
        "he may turn in himself (with turns_in on).",
    )
    desk_hours: float = Field(
        3.0,
        ge=0.5,
        le=12,
        description="Hours at the desk without a break before Kit nudges you outside (with "
        "nudges on, in the daytime).",
    )
    work_triggers: bool = Field(
        False,
        description="Kit gets curious about work apps and sites (code, Teams, Excel, GitHub) "
        "and reacts to builds and tests on screen. Off: only everyday things catch his eye.",
    )
    alone_thoughts_per_hour: int = Field(
        0,
        ge=0,
        le=6,
        description="While you're away and he's awake, Kit entertains himself (watching the "
        "weather, rereading yesterday's journal, thinking about someone in the register, "
        "listening to what's playing if the desk app shares it) and has this many private "
        "thoughts an hour about it, always with the local model, never in quiet hours. The "
        "desk face shows what he's doing. 0: he just waits, then dozes.",
    )
    week_thoughts: bool = Field(
        False,
        description="Kit notices the shape of the week: a thought on Monday, Friday and "
        "Saturday mornings, and on WA public holidays.",
    )
    read_mood: Literal["words", "meaning"] = Field(
        "words",
        description='How Kit reads how you are. words: from what you say ("stressed", '
        '"legend"), ignoring "not stressed". meaning: the model answering also reads your '
        "mood, what it's about and whether things went as hoped, with the words as a floor. "
        "meaning needs a passed `kit eval mood` first; until then he uses words.",
    )
    mixed_feelings: bool = Field(
        False,
        description="Kit can feel two things at once (chuffed at your praise and still a bit "
        "worried about your day). Off: the stronger feeling wins.",
    )
    bad_night: bool = Field(
        True,
        description="When you sound like you're having a really bad time, Kit drops the cheek "
        "for the rest of the chat, listens and stays, and once mentions someone you can talk "
        "to or Lifeline (13 11 14).",
    )
    energy_need: bool = Field(
        False,
        description="Energy is a real need: long chats, cloud jobs and staying up past 22:30 "
        "tire Kit out, and sleep restores him. His body clock winds him down from 21:00, so "
        "he's sleepy by 23:00 however rested. Below 0.4 he yawns and keeps replies short. "
        "Off: his energy just follows the clock.",
    )
    opinions: int = Field(
        0,
        ge=0,
        le=2,
        description="How many of his standing opinions (from his notebook) Kit keeps in mind "
        "when he talks, so he sticks to them.",
    )
    dials: bool = Field(
        False,
        description="Kit's mood also runs as two slow dials (how lively, how happy) that bodies "
        "show: slower breathing and blinks when he's flat or tired, bigger gestures when "
        "he's up.",
    )
    pipe_up_bar: float = Field(
        0.0,
        ge=0,
        le=1,
        description="Before Kit brings something up unprompted, he scores it for relevance, "
        "originality and urgency (helped by how often you take his pipe-ups up) and keeps "
        "quiet below this. 0 turns the scoring off; 0.5 is a sensible bar.",
    )
    eyes_manners: bool = Field(
        True,
        description="With his eyes on, Kit doesn't pipe up while you're on your phone or "
        "talking to someone, and his bubble says why.",
    )
    hold_pipe_ups: bool = Field(
        False,
        description="Something Kit wanted to say while you were on your phone or talking to "
        "someone waits until you're done (up to half an hour), and he says why he waited.",
    )
    seen_feelings: bool = Field(
        False,
        description="Kit feels what his eyes catch: a wave (he waves back), a thumbs up, a "
        "smile at him for a couple of seconds (he brightens), a frown that stays (he's "
        "sympathetic), and your eyes closing late at night (he yawns and thinks of bed).",
    )

    @field_validator("quiet_from", "quiet_until", "bedtime")
    @classmethod
    def _clock_time(cls, value: str) -> str:
        h, _, m = value.partition(":")
        if not (h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60 and len(m) == 2):
            raise ValueError("must be a time like 22:00")
        return f"{int(h):02d}:{m}"


class EyesSettings(_Section):
    """Kit's eyes: the camera process (`kit eyes`) on the PC with the webcam. It
    fetches these from the brain, so there's one place to change them."""

    enabled: bool = Field(
        True,
        description="Kit uses a camera to see who's at the desk, when `kit eyes` is running "
        "on the PC with the webcam.",
    )
    camera: int = Field(
        0, ge=0, le=15, description="Which camera the eyes use (`kit eyes cameras` lists them)."
    )
    width: int = Field(1280, ge=160, le=4096, description="Frame width to ask the camera for.")
    height: int = Field(720, ge=120, le=2160, description="Frame height to ask the camera for.")
    mirror: bool = Field(
        True,
        description="Flip the picture like a mirror. On for a webcam facing you at the desk, "
        "so left is your left; off for a camera on the arm.",
    )
    detector: str = Field(
        "yolo11s",
        min_length=1,
        description="The model that finds people and objects: yolo11s suits a PC with a "
        "graphics card, yolo11n is faster but mistakes mugs for phones, yolo11m is sharper "
        "still. Downloaded the first time the eyes run.",
    )
    detector_format: Literal["pytorch", "openvino", "onnx", "ncnn"] = Field(
        "pytorch",
        description="How the detector runs. pytorch suits a graphics card; openvino is quickest "
        "on an Intel CPU, ncnn on a Raspberry Pi, onnx anywhere. Anything but pytorch is made "
        "from the downloaded model the first time, at detector_size.",
    )
    detector_size: int = Field(
        640,
        ge=160,
        le=1280,
        multiple_of=32,
        description="The picture size the detector works at. 320 is about three times quicker "
        "on a CPU and still finds people and pets at desk distance; small things across the "
        "room get missed.",
    )
    device: Literal["auto", "cpu"] = Field(
        "auto",
        description="Where the detector runs: auto uses the graphics card if there is one, cpu "
        "leaves the graphics card free for other things.",
    )
    confidence: float = Field(
        0.4, ge=0.05, le=0.95, description="How sure the detector must be before something counts."
    )
    looks_per_second: float = Field(
        0,
        ge=0,
        le=60,
        description="How many frames a second the eyes look at. 0 looks at every frame the "
        "camera gives; 5 is plenty to follow a face on a CPU.",
    )
    detect_every: int = Field(
        1,
        ge=1,
        le=30,
        description="Run the detector on one look in this many. Faces and hands are still read "
        "on every look, so his eyes keep following you while the detector rests.",
    )
    forget_after_s: float = Field(
        3.0,
        ge=0.5,
        le=60,
        description="Seconds out of view before someone or something has left.",
    )
    report_every_s: float = Field(
        1.0, ge=0.2, le=10, description="How often the eyes tell the brain what they see."
    )
    faces: bool = Field(
        True, description="Read faces: where each person is looking and their expression."
    )
    hands: bool = Field(True, description="Read hand gestures: thumbs up, open palm, a wave.")
    poses: int = Field(
        1,
        ge=0,
        le=4,
        description="How many people to read body pose for (each adds about 13 ms a frame). "
        "0 turns it off.",
    )
    recognise: bool = Field(
        True,
        description="Tell people apart by their faces, once they've been introduced with "
        "`kit eyes enrol NAME`. Kit keeps numbers worked out from a face, never pictures.",
    )
    match: float = Field(
        0.4,
        ge=0.25,
        le=0.8,
        description="How alike a face must be to someone Kit knows to count as them. Higher "
        "is stricter: fewer mix-ups, but more 'someone I don't know'.",
    )


class HearingSettings(_Section):
    """Kit's ears: the microphone process (`kit hearing`) on the PC with the mic. It
    fetches these from the brain, so there's one place to change them. Sound never
    leaves that PC: only the words, and how they sounded, reach the brain."""

    enabled: bool = Field(
        True,
        description="Kit listens through a microphone when `kit hearing` is running on the PC "
        'with the mic. The tray\'s "Let Kit hear me" switch turns it off and on.',
    )
    mic: str = Field(
        "",
        description="Which microphone to use: part of its name, or its number from "
        "`kit hearing mics`. Empty uses the PC's default.",
    )
    names: list[str] = Field(
        default_factory=lambda: ["Kit", "Kitt", "Ki", "Kid"],
        description='What Kit answers to. Said at the start or end of a sentence ("Kit, '
        "what's the weather?\"), it means you're talking to him. After his name come the "
        "ways the ears sometimes write it; add a word they often hear instead.",
    )
    follow_up_s: float = Field(
        8.0,
        ge=0,
        le=60,
        description="After Kit stops talking, this many seconds when you can answer him "
        "without saying his name. 0 means always say his name.",
    )
    barge_in: bool = Field(
        True,
        description="Talking over Kit stops him, as typing does. His own voice from the "
        "speakers doesn't count.",
    )
    barge_in_ms: int = Field(
        500,
        ge=150,
        le=3000,
        description="How long you must talk over Kit before he stops (milliseconds).",
    )
    laugh_s: float = Field(
        10.0,
        ge=0,
        le=60,
        description="A laugh within this many seconds of Kit saying something makes him "
        "chuffed. 0 turns it off.",
    )
    tone: bool = Field(
        True,
        description="Kit notices how you sound (down, cross, cheerful). He may ask about "
        "it, never tells you how you feel.",
    )
    match: float = Field(
        0.45,
        ge=0.2,
        le=0.9,
        description="How alike a voice must be to someone Kit knows to count as them "
        "(`kit hearing enrol NAME`). Higher is stricter.",
    )
    own_voice: float = Field(
        0.5,
        ge=0.3,
        le=0.95,
        description="How alike a voice must be to Kit's own for him to know it's himself "
        "coming back from the speakers, while he's talking. It must also be more like him "
        "than like anyone he knows. Lower ignores more.",
    )
    threshold: float = Field(
        0.5,
        ge=0.1,
        le=0.95,
        description="How sure the voice detector must be that a sound is speech. Higher "
        "ignores more background noise, but may miss quiet speech.",
    )
    pause_ms: int = Field(
        600,
        ge=200,
        le=3000,
        description="How long a pause ends what you're saying (milliseconds). Shorter "
        "answers sooner; too short cuts you off mid-thought.",
    )
    min_speech_s: float = Field(
        0.4, ge=0.1, le=5, description="Shorter sounds than this are ignored (a cough, a click)."
    )
    max_speech_s: float = Field(
        20.0, ge=3, le=60, description="Longest stretch of talking heard as one go."
    )
    language: Literal["auto", "en", "zh", "ja", "ko", "yue"] = Field(
        "en",
        description="The language Kit's ears listen for. auto works it out each time, "
        "a little less reliably.",
    )
    threads: int = Field(
        2,
        ge=1,
        le=16,
        description="Processor threads the speech models use on the mic's PC. Up to about "
        "half its cores makes the words come sooner.",
    )

    @field_validator("names")
    @classmethod
    def _some_name(cls, value: list[str]) -> list[str]:
        names = [" ".join(n.split()) for n in value if n.strip()]
        if not names:
            raise ValueError("Kit needs at least one name to answer to")
        return names


CharacterName = Literal[tuple(characters.presets())]  # type: ignore[valid-type]


class FaceSettings(_Section):
    character: CharacterName = Field(
        characters.DEFAULT,
        description="Which character Kit is: how he looks and moves in the desk app, "
        "home_app and on his robots. Retro is the original glowing pill eyes; switch "
        "back any time.",
        # Always a list, so settings pages show a picker even with one character
        # (a one-value Literal comes out as "const", which they draw as a text box).
        json_schema_extra={"enum": list(characters.presets())},
    )
    hot_c: float = Field(
        35.0,
        ge=20,
        le=55,
        description="When you ask about the weather, a dry day this hot or hotter (°C) "
        "shows as a hot day on his face: the sun beating down and him sweating.",
    )
    pack_folder: str = Field(
        "",
        description="A folder holding a 3D face pack (face.json and the .glb) to use for a "
        "3D character instead of the one built into Kit, e.g. the pack folder your Blender "
        "project writes. Each rebuild shows on the desk within seconds. Empty: built in.",
    )


class MemorySettings(_Section):
    embed_model: str = Field(
        "nomic-embed-text",
        description="Ollama model that turns text into meaning vectors, so Kit can find "
        "memories by meaning as well as by words. Changing it re-indexes everything.",
    )
    embed_keep_alive: str = Field(
        "24h",
        description="How long the embedding model stays loaded after it was last used "
        "(Ollama's keep_alive, e.g. 24h, 30m, -1 for always). It is small, and recall "
        "needs it before every reply, so loading it again after a quiet spell would hold "
        "up the first answer.",
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
    own_memories: int = Field(
        3,
        ge=0,
        le=20,
        description="Entries from Kit's own notebook (his thoughts, opinions, moments and "
        "journal) recalled into each turn, most relevant first.",
    )
    min_similarity: float = Field(
        0.59,  # measured for nomic-embed-text with `kit eval memory` (2026-10-06)
        ge=0,
        le=1,
        description="How close in meaning a memory must be to count as relevant (0 to 1). "
        "It depends on the embedding model: `kit eval memory` suggests a value.",
    )
    weight_floor: float = Field(
        0.3,
        ge=0,
        le=1,
        description="Among relevant memories, the ones that matter more to your life and "
        "the ones recalled lately come first; this is the least an old, small one counts "
        "(0 to 1). 1 weighs them all the same.",
    )
    now_days: int = Field(
        14,
        ge=1,
        le=90,
        description="Days a 'now' memory lasts: how you've been or what's going on lately "
        "(flat out, crook, a visitor staying). Then it's forgotten; the day summaries keep "
        "the gist.",
    )
    day_pass: Literal["work", "local"] = Field(
        "work",
        description="Who reads each finished day after midnight, writes its summary and sorts "
        "what's worth remembering about you into the right kinds. work: the work model "
        "(Sonnet), a few cents a night, with the local model stepping in if the cloud "
        "can't; a day with something you kept local always stays home. local: the local "
        "model only.",
    )
    backups_keep: int = Field(14, ge=1, le=365, description="Daily memory backups to keep.")


SpeechKind = Literal["kokoro", "piper", "chatterbox", "chatterbox-turbo", "tone"]

# How strongly standard Chatterbox acts out each of Kit's emotions (its
# "exaggeration" dial: 0 is flat, 0.5 normal, above 1 very animated).
DEFAULT_EXAGGERATION: dict[str, float] = {
    "default": 0.5,
    "neutral": 0.45,
    "happy": 0.7,
    "curious": 0.6,
    "thinking": 0.4,
    "surprised": 0.9,
    "concerned": 0.55,
    "playful": 0.8,
    "tired": 0.3,
    "proud": 0.75,
    "excited": 1.1,
    "sad": 0.45,
    "confused": 0.6,
    "shy": 0.45,
    "grumpy": 0.8,
    "focused": 0.4,
    "relieved": 0.6,
    "fond": 0.65,
}

# Speed change per emotion for engines without an emotion dial (Kokoro, Piper).
DEFAULT_MOOD_SPEED: dict[str, float] = {
    "default": 1.0,
    "excited": 1.12,
    "surprised": 1.08,
    "playful": 1.06,
    "happy": 1.05,
    "grumpy": 1.02,
    "focused": 0.97,
    "thinking": 0.95,
    "concerned": 0.95,
    "shy": 0.95,
    "sad": 0.9,
    "tired": 0.88,
}


# Sounds Chatterbox Turbo may open a reply with in these emotions, one picked at
# random each time. Its tags (from its tokenizer, 2026-10-07): [advertisement]
# [angry] [chuckle] [clear throat] [cough] [crying] [dramatic] [fear] [gasp] [groan]
# [happy] [laugh] [narration] [sarcastic] [shush] [sigh] [sniff] [surprised]
# [whispering]. Each adds about half a second.
DEFAULT_MOOD_TAGS: dict[str, list[str]] = {
    "tired": ["[sigh]", "[groan]"],
    "sad": ["[sigh]", "[sniff]"],
    "grumpy": ["[groan]", "[sigh]", "[clear throat]"],
    "playful": ["[chuckle]", "[laugh]"],
    "surprised": ["[gasp]", "[surprised]"],
}


class SpeechEngine(_Section):
    """One voice engine Kit can speak with. Swap engines by pointing
    ``speech.engine`` at a different profile; each runs in its own background
    program, so engines with clashing libraries can live in separate Pythons."""

    kind: SpeechKind = Field(
        description="Which engine: kokoro and piper are fast on a CPU; chatterbox is the "
        "most expressive (GPU); chatterbox-turbo is faster but has no emotion dial; tone "
        "beeps, for testing."
    )
    python: str = Field(
        "",
        description="The Python that has this engine installed, e.g. "
        "~/kit-voice/.venv/bin/python. Empty: the Python running Kit.",
    )
    device: Literal["auto", "cpu", "cuda"] = Field(
        "auto", description="Chatterbox only: auto uses the graphics card if there is one."
    )
    voice: str = Field(
        "",
        description="kokoro: a voice name such as af_heart. piper: the voice's .onnx file "
        "(a bare name is looked for in Kit's speech models folder).",
    )
    reference: str = Field(
        "",
        description="chatterbox: a clip of at least 6 seconds whose voice Kit copies. A bare "
        "name is looked for in Kit's speech folder. Empty: Chatterbox's own voice.",
    )
    speed: float = Field(1.0, ge=0.5, le=2, description="kokoro and piper: talking speed.")
    mood_speed: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_MOOD_SPEED),
        description="kokoro and piper: speed change per emotion ('default' for the rest).",
    )
    exaggeration: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_EXAGGERATION),
        description="chatterbox: how strongly each emotion is acted out, 0 to 2 "
        "('default' for the rest).",
    )
    cfg_weight: float = Field(
        0.5, ge=0, le=1, description="chatterbox: lower is slower and more deliberate."
    )
    mood_tags: dict[str, str | list[str]] = Field(
        default_factory=lambda: {m: list(t) for m, t in DEFAULT_MOOD_TAGS.items()},
        description="chatterbox-turbo: sounds that may open a reply in that emotion, such as "
        "[sigh] or [chuckle]; one is picked at random. A single sound works too.",
    )
    mood_tag_chance: float = Field(
        0.6,
        ge=0,
        le=1,
        description="chatterbox-turbo: how often a reply in one of those emotions opens with "
        "a sound (0.6: six in ten); the rest just start.",
    )
    cuda_graph: bool = Field(
        True,
        description="chatterbox-turbo on a graphics card: record its token loop as a CUDA "
        "graph, about 2.4 times faster with the same voice. Off: Chatterbox's own loop.",
    )


DEFAULT_SPEECH_ENGINES: dict[str, dict] = {
    "kokoro": {"kind": "kokoro", "voice": "af_heart"},
    "piper": {"kind": "piper", "voice": "en_US-lessac-medium.onnx"},
    "chatterbox": {"kind": "chatterbox", "reference": "kit_voice.wav"},
    "chatterbox-turbo": {"kind": "chatterbox-turbo", "reference": "kit_voice.wav"},
    "tone": {"kind": "tone"},
}


# The built-in voice engines as a version-1 file holds them. Frozen, like _V1_MODELS.
_V1_SPEECH_ENGINES: dict[str, dict] = {
    "kokoro": {"kind": "kokoro", "voice": "af_heart"},
    "piper": {"kind": "piper", "voice": "en_US-lessac-medium.onnx"},
    "chatterbox": {"kind": "chatterbox", "reference": "kit_voice.wav"},
    "chatterbox-turbo": {"kind": "chatterbox-turbo", "reference": "kit_voice.wav"},
    "tone": {"kind": "tone"},
}


def _default_speech_engines() -> dict[str, SpeechEngine]:
    return {n: SpeechEngine.model_validate(p) for n, p in DEFAULT_SPEECH_ENGINES.items()}


class SpeechSettings(_Section):
    enabled: bool = Field(False, description="Kit speaks his replies aloud in the desk app.")
    engine: str = Field(
        "kokoro", description="Which voice engine profile Kit speaks with (see engines)."
    )
    engines: dict[str, SpeechEngine] = Field(
        default_factory=_default_speech_engines,
        description="Voice engines Kit can use, by name. Built-in profiles are always there; "
        "change their fields or add your own (e.g. a second kokoro voice).",
    )
    port: int = Field(
        8611, ge=1024, le=65535, description="Local port for the voice engine's program."
    )
    load_timeout_s: int = Field(
        240,
        ge=10,
        le=1800,
        description="How long a voice engine may take to load (the first Chatterbox start "
        "downloads its model).",
    )
    sounds: bool = Field(
        False,
        description="Sounds in his voice where a gesture calls for one: a chuckle on the "
        "punchline, a sigh, a gasp. At most one every other sentence. Only Chatterbox Turbo "
        "makes them; other engines leave them out.",
    )

    @field_validator("engines", mode="before")
    @classmethod
    def _keep_built_in_engines(cls, value):
        if not isinstance(value, dict):
            return value
        merged = {name: dict(p) for name, p in DEFAULT_SPEECH_ENGINES.items()}
        for name, profile in value.items():
            if isinstance(profile, BaseModel):
                profile = profile.model_dump()
            if isinstance(profile, dict):
                profile = {**merged.get(name, {}), **profile}
            merged[name] = profile
        return merged

    fallback: str = Field(
        "",
        description="A voice engine to switch to if his usual one can't start or runs out of "
        "graphics card memory (e.g. kokoro, on the CPU). He stays on it until his speech "
        "settings change. Empty: no fallback, his voice just stops.",
    )

    @model_validator(mode="after")
    def _engine_is_known(self) -> SpeechSettings:
        known = ", ".join(sorted(self.engines))
        if self.engine not in self.engines:
            raise ValueError(f"speech.engine is '{self.engine}', which isn't an engine ({known})")
        if self.fallback and self.fallback not in self.engines:
            raise ValueError(
                f"speech.fallback is '{self.fallback}', which isn't an engine ({known})"
            )
        return self

    @property
    def profile(self) -> SpeechEngine:
        return self.engines[self.engine]


class Settings(_Section):
    schema_version: Literal[3] = Field(
        SCHEMA_VERSION,
        description="The settings file's layout. 3: the file holds only what you changed, "
        "and the models are your own list with no prices in it.",
    )
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    models: dict[str, ModelProfile] = Field(
        default_factory=_default_models,
        description="The models Kit can use, by name: your own list. A new Kit starts with "
        "haiku, sonnet and opus; add any model with `kit models add` and take one out with "
        "`kit models remove` (or send it as null). What each costs is fetched daily "
        "(`kit models`), never set here.",
    )
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    nas: NasSettings = Field(default_factory=NasSettings)
    notes: NotesSettings = Field(default_factory=NotesSettings)
    files: FilesSettings = Field(default_factory=FilesSettings)
    pc: PcSettings = Field(default_factory=PcSettings)
    projects: ProjectsSettings = Field(default_factory=ProjectsSettings)
    house: HouseSettings = Field(default_factory=HouseSettings)
    apps: AppsSettings = Field(default_factory=AppsSettings)
    persona: PersonaSettings = Field(default_factory=PersonaSettings)
    brain: BrainSettings = Field(default_factory=BrainSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    life: LifeSettings = Field(default_factory=LifeSettings)
    eyes: EyesSettings = Field(default_factory=EyesSettings)
    hearing: HearingSettings = Field(default_factory=HearingSettings)
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    face: FaceSettings = Field(default_factory=FaceSettings)

    @model_validator(mode="before")
    @classmethod
    def _from_older(cls, data):
        """A version-1 file holds every setting, chosen or not; a version-2 file leans on
        built-in model profiles and holds prices. Either is read as today's layout."""
        if isinstance(data, dict) and data.get("schema_version") == 1:
            data = _without_v1_defaults(data)
        if isinstance(data, dict) and data.get("schema_version") == 2:
            data = _from_version_2(data)
        return data

    @field_validator("models", mode="before")
    @classmethod
    def _models_table(cls, value):
        """The table is the whole list; a model sent as null is taken out, which is how
        a settings page or `kit models remove` drops one."""
        if not isinstance(value, dict):
            return value
        return {name: profile for name, profile in value.items() if profile is not None}

    @model_validator(mode="after")
    def _roles_name_models(self) -> Settings:
        for role in ("chat", "work", "expert"):
            name = getattr(self.routing, role)
            if name not in self.models:
                known = ", ".join(sorted(self.models))
                raise ValueError(f"routing.{role} is '{name}', which isn't a model ({known})")
        return self

    def profile(self, role: str) -> ModelProfile:
        """The model profile a role ("chat", "work" or "expert") points at."""
        return self.models[getattr(self.routing, role)]


LOCAL_STANDS_IN = "2m"  # how long the local model stays loaded when it only stands in


def cloud_background(settings: Settings) -> bool:
    """Kit's background work (thoughts, pipe-ups, fact comparisons) goes to the cloud."""
    return settings.routing.background == "chat"


def local_settings(settings: Settings) -> OllamaSettings:
    """The local model's settings as Ollama should see them: in cloud-only mode with the
    background work in the cloud, the local model only stands in (for what Dan keeps
    local, or when the cloud can't answer), so it leaves the GPU soon after."""
    if local_stands_in(settings):
        return settings.ollama.model_copy(update={"keep_alive": LOCAL_STANDS_IN})
    return settings.ollama


def local_stands_in(settings: Settings) -> bool:
    """The cloud does everything, chat and background alike: the local model only
    stands in for what Dan keeps local, or when the cloud can't answer."""
    return settings.routing.mode == "cloud-only" and cloud_background(settings)


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
    """Every setting as TOML, for reading (``kit config show``). Unset optional values
    are left out (TOML has no null)."""
    return tomli_w.dumps(settings.model_dump(mode="json", exclude_none=True))


def settings_file_toml(settings: Settings) -> str:
    """The settings as the file holds them: only what differs from the defaults, so a
    default that changes in the code reaches the install. A built-in voice engine is
    written field by field the same way; your own engines whole. The models are
    written whole as soon as the list differs from the starters: it's your list."""
    return tomli_w.dumps({"schema_version": SCHEMA_VERSION, **changes(settings, Settings())})


def _dump(value: BaseModel) -> dict:
    return value.model_dump(mode="json", exclude_none=True)


def _profiles(value) -> bool:
    return isinstance(value, dict) and all(isinstance(v, BaseModel) for v in value.values())


def changes(settings: BaseModel, defaults: BaseModel) -> dict:
    """What differs between two settings, field by field, as nested dicts. Plain
    dicts (``nas.read_only_shares``, an engine's ``mood_speed``) count as one value."""
    out: dict = {}
    dump = _dump(settings)
    for name in type(settings).model_fields:
        value, default = getattr(settings, name), getattr(defaults, name)
        if isinstance(value, BaseModel) and isinstance(default, BaseModel):
            sub = changes(value, default)
        elif name == "models" and _profiles(value) and _profiles(default):
            if value != default:  # your own list, kept whole
                out[name] = {key: _dump(profile) for key, profile in value.items()}
            continue
        elif _profiles(value) and _profiles(default):
            sub = {}
            for key, profile in value.items():
                if key not in default:
                    sub[key] = _dump(profile)
                elif diff := changes(profile, default[key]):
                    sub[key] = diff
        elif value != default and name in dump:
            out[name] = dump[name]
            continue
        else:
            continue
        if sub:
            out[name] = sub
    return out


def _without_v1_defaults(raw: dict) -> dict:
    """A version-1 file as version 2: every value that was a default in version 1
    (``_V1_MODELS``, ``_V1_SPEECH_ENGINES``, ``_V1_PERSONA``; today's for the rest)
    is dropped, so today's default is read instead. What the owner changed stays."""
    v1 = _dump(Settings())
    v1["models"] = {n: _v1_profile(p) for n, p in _V1_MODELS.items()}
    v1["speech"]["engines"] = {
        n: _dump(SpeechEngine.model_validate(p)) for n, p in _V1_SPEECH_ENGINES.items()
    }
    out: dict = {"schema_version": 2}  # then _from_version_2 brings it to today's
    for section, value in raw.items():
        if section == "schema_version":
            continue
        if section == "models":
            value = _profiles_without(value, v1["models"])
        elif isinstance(value, dict) and isinstance(v1.get(section), dict):
            if section == "speech" and isinstance(value.get("engines"), dict):
                value = {
                    **value,
                    "engines": _profiles_without(value["engines"], v1["speech"]["engines"]),
                }
            value = {
                k: v
                for k, v in value.items()
                if v != v1[section].get(k)
                and not (section == "persona" and v in _V1_PERSONA.get(k, []))
            }
        out[section] = value
    return out


def _from_version_2(raw: dict) -> dict:
    """A version-2 file as version 3. Its models were the built-ins plus what it
    changed or added; the list becomes the profiles a role uses and the ones the
    file names, whole, with the prices (fetched now) dropped. The budget in US
    dollars becomes Australian dollars."""
    out = {k: v for k, v in raw.items() if k != "schema_version"}
    out["schema_version"] = SCHEMA_VERSION
    named = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    routing = raw.get("routing") if isinstance(raw.get("routing"), dict) else {}
    defaults = RoutingSettings()
    roles = [routing.get(role, getattr(defaults, role)) for role in ("chat", "work", "expert")]
    models = {}
    for name in [*named, *roles]:
        changed = named.get(name)
        if name in models or (name in named and not isinstance(changed, dict)):
            continue
        profile = {**_V2_MODELS.get(name, {}), **(changed or {})}
        if profile:
            models[name] = {k: v for k, v in profile.items() if k not in _PRICE_FIELDS}
    starters = [n for n in STARTER_MODELS if n in models]
    out["models"] = {n: models[n] for n in [*starters, *(n for n in models if n not in starters)]}
    cloud = dict(raw.get("cloud") or {})
    if "monthly_cap_usd" in cloud:
        cloud["monthly_cap_aud"] = float(round(cloud.pop("monthly_cap_usd") * _V2_AUD_PER_USD))
    if "reserve_usd" in cloud:
        cloud["reserve_aud"] = round(cloud.pop("reserve_usd") * _V2_AUD_PER_USD, 1)
    if cloud:
        out["cloud"] = cloud
    return out


def _v1_profile(profile: dict) -> dict:
    """A version-1 built-in profile with every field filled in, prices included."""
    fields = {k: v for k, v in profile.items() if k not in _PRICE_FIELDS}
    prices = {k: v for k, v in profile.items() if k in _PRICE_FIELDS}
    return {**_dump(ModelProfile.model_validate(fields)), **prices}


def _profiles_without(profiles, v1: dict[str, dict]):
    """Built-in profiles with their version-1 fields dropped; others whole."""
    if not isinstance(profiles, dict):
        return profiles
    out = {}
    for name, profile in profiles.items():
        if name in v1 and isinstance(profile, dict):
            profile = {k: v for k, v in profile.items() if v != v1[name].get(k)}
        out[name] = profile
    return out
