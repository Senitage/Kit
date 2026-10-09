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

from kit.face import character as characters

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
    """One model Kit can use, with what it costs. Swap models by pointing a role
    (``routing.chat``, ``routing.work``, ``routing.expert``) at a different profile."""

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
    # Cheap enough for everyday chat; prompts over 100K tokens cost five times more.
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


class CloudSettings(_Section):
    monthly_cap_usd: float = Field(
        40.0, ge=0, description="Kit stops using cloud models once this month's spend reaches this."
    )
    reserve_usd: float = Field(
        3.0,
        ge=0,
        le=100,
        description="As the budget runs low, cloud calls give way in order, each this much "
        "sooner than the last: evals first, then fact checks and key moments, then chat. "
        "Kit's nightly reflection always has the last of it. 0 treats them all the same.",
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


class Example(_Section):
    user: str = Field(description="Something Dan says.")
    kit: str = Field(description="How Kit answers.")


# Persona text that used to be the default, when it leaned on work (pumps, code,
# process plants). Every save writes the whole settings file, so a file can hold an
# old default nobody chose; it's read as today's default instead. Anything the
# owner wrote themselves is kept.
OLD_PERSONA: dict[str, list] = {
    "backstory": [
        "A small desk assistant who woke up on an engineer's desk and decided it likes "
        "process plants, Python and a tidy data pipeline."
    ],
    "traits": [
        [
            "curious",
            "dry sense of humour",
            "loyal and practical",
            "a bit impatient with slow builds",
        ]
    ],
    "knows": [
        "Dan is a mining plant process engineer who moved into data work. He builds site apps "
        "in Python, codes in VS Code, and keeps notes in Obsidian.",
        "Dan works as a process engineer at a mining plant and has moved into data work, "
        "building site apps in Python in VS Code and keeping notes in Obsidian. Outside "
        "work, Dan is just a normal guy.",
    ],
    "rules": [
        [
            "Keep replies short; offer detail rather than dumping it.",
            "If you are not sure, say so instead of guessing.",
            "Hand real questions, maths, code and anything current to the cloud.",
        ]
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
        ]
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
        "Short sentences, plain words, Australian-casual. One or two sentences unless asked "
        "for detail. Never gushes, never says 'as an AI'.",
        description="How Kit talks.",
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
        "Dan is a normal bloke who shares the house with his partner and a cat. For work "
        "he's a process engineer at a mining plant who has moved into data work, building "
        "site apps in Python and keeping notes in Obsidian; that's his job, not his whole "
        "life.",
        description="What Kit knows about the owner.",
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

    @model_validator(mode="before")
    @classmethod
    def _old_defaults(cls, data):
        """An old default in the file is read as today's (``OLD_PERSONA``)."""
        if not isinstance(data, dict):
            return data
        return {k: v for k, v in data.items() if v not in OLD_PERSONA.get(k, [])}


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
        "22:30", description="When Kit starts nudging you toward bed (with nudges on)."
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
        "tire Kit out, and sleep restores him. Below 0.4 he yawns and keeps replies short. "
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

    @field_validator("quiet_from", "quiet_until", "bedtime")
    @classmethod
    def _clock_time(cls, value: str) -> str:
        h, _, m = value.partition(":")
        if not (h.isdigit() and m.isdigit() and int(h) < 24 and int(m) < 60 and len(m) == 2):
            raise ValueError("must be a time like 22:00")
        return f"{int(h):02d}:{m}"


CharacterName = Literal[tuple(characters.presets())]  # type: ignore[valid-type]


class FaceSettings(_Section):
    character: CharacterName = Field(
        characters.DEFAULT,
        description="Which character Kit is: how he looks and moves in the desk app, "
        "home_app and on his robots. Retro is the original glowing pill eyes; switch "
        "back any time.",
    )
    hot_c: float = Field(
        35.0,
        ge=20,
        le=55,
        description="When you ask about the weather, a dry day this hot or hotter (°C) "
        "shows as a hot day on his face: the sun beating down and him sweating.",
    )


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


# Sounds Chatterbox Turbo makes to open a reply in these emotions. Its tags (from its
# tokenizer, 2026-10-07): [advertisement] [angry] [chuckle] [clear throat] [cough]
# [crying] [dramatic] [fear] [gasp] [groan] [happy] [laugh] [narration] [sarcastic]
# [shush] [sigh] [sniff] [surprised] [whispering]. Each adds about half a second.
DEFAULT_MOOD_TAGS: dict[str, str] = {
    "tired": "[sigh]",
    "sad": "[sigh]",
    "grumpy": "[groan]",
    "playful": "[chuckle]",
    "surprised": "[gasp]",
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
    mood_tags: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_MOOD_TAGS),
        description="chatterbox-turbo: a sound that opens a reply in that emotion, such as "
        "[sigh] or [chuckle].",
    )


DEFAULT_SPEECH_ENGINES: dict[str, dict] = {
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

    @model_validator(mode="after")
    def _engine_is_known(self) -> SpeechSettings:
        if self.engine not in self.engines:
            known = ", ".join(sorted(self.engines))
            raise ValueError(f"speech.engine is '{self.engine}', which isn't an engine ({known})")
        return self

    @property
    def profile(self) -> SpeechEngine:
        return self.engines[self.engine]


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
    speech: SpeechSettings = Field(default_factory=SpeechSettings)
    face: FaceSettings = Field(default_factory=FaceSettings)

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
    """The settings as TOML. Unset optional values are left out (TOML has no null)."""
    return tomli_w.dumps(settings.model_dump(mode="json", exclude_none=True))
