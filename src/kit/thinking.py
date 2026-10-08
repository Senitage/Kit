"""Kit's own thoughts, between conversations.

Every few minutes while Dan's around, and sooner when something happens (Dan
comes back, opens something new, a build fails or passes, a chat ends), Kit
has a private thought. ``Life.think_now`` says when; ``Brain.think`` asks the
local model, as his inner voice, for one thought or none, from who he is, how
he feels, what Dan's doing, what he remembers and what's been said today.

A thought can turn into something he wants to bring up later, or change how
he feels. It goes in his notebook (kit.notebook), so recall finds it, his next
pipe-up can share it, and "what are you thinking about?" gets a real answer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from kit.life import THOUGHT_FEELINGS, everyday

THOUGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "kind": {"type": "string", "enum": ["thought", "opinion"]},
        "want": {"type": "string"},
        "feeling": {"type": "string", "enum": ["same", *THOUGHT_FEELINGS]},
        "why": {"type": "string"},
    },
    "required": ["thought", "kind", "want", "feeling", "why"],
    "additionalProperties": False,
}


@dataclass
class Thought:
    text: str
    kind: str = "thought"  # or "opinion"
    want: str = ""  # something to say or ask the owner later
    feeling: str = ""  # a kit.life.FEELING_KINDS name, or "" for no change
    why: str = ""
    trigger: str = "quiet"  # what set it off (kit.life.Life.think_now)

    def as_dict(self) -> dict:
        return asdict(self)


def _section(title: str, lines: list[str]) -> list[str]:
    return ["", title, *(f"- {line}" for line in lines)] if lines else []


def thinking_messages(
    name: str,
    owner: str,
    who: str,
    quirks: list[str],
    style: str,
    now: datetime,
    happened: str,
    pc: str,
    feeling: str,
    mind: list[str],
    remembered: list[str],
    said_today: list[str],
) -> list[dict]:
    """The prompt for one private thought. ``who`` is his self-sheet (or the persona
    he was given), ``happened`` what set this thought off."""
    feelings = ", ".join(THOUGHT_FEELINGS)
    system = [
        f"You are {name}'s inner voice. {name} is a small companion who lives on {owner}'s "
        f"desk and helps out. This is {name} thinking to himself: nobody hears it.",
        f"Who {name} is, in his own words: {who}",
    ]
    if quirks:
        system.append(f"His quirks: {'; '.join(quirks)}.")
    system += [
        "",
        f"Think one private thought, in the first person, as {name}: something you noticed, "
        f"a question you're wondering about, an opinion forming, a small worry, a plan, or a "
        f"joke you're saving for {owner}. Base it on what's below and never invent facts "
        f"about {owner} or what's going on. Make it new (not one of your recent thoughts) "
        f"and more than a description of the screen. One or two short sentences, in your "
        f"own voice: {style}. {everyday(owner)}",
        "- kind: opinion if it's a view you've formed, else thought.",
        f"- want: if it's something you'd like to say or ask {owner} when you get the "
        f"chance, write that as one short line in your own words. If it's for tomorrow (or "
        f"{owner} asked you to bring it up tomorrow), start with Tomorrow. Otherwise empty.",
        f"- feeling: if it changes how you feel, one of {feelings}, with why (the cause, in "
        f"a few words). Otherwise same, with why empty.",
        "- If nothing comes to mind, leave thought empty. That's fine too.",
        "Answer only with JSON.",
    ]
    user = [
        f"It's {now:%A %d %B, %I:%M %p}.",
        happened,
        pc or f"You can't see {owner}'s PC right now.",
        f"You feel {feeling}.",
        *_section("On your mind lately (don't just repeat these):", mind),
        *_section("What you remember that may matter:", remembered),
        *_section("Said today, latest last:", said_today),
    ]
    return [
        {"role": "system", "content": "\n".join(system)},
        {"role": "user", "content": "\n".join(user)},
    ]


def parse_thought(raw: str, trigger: str) -> Thought | None:
    """The model's thought, or None if it isn't readable."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    def text(key: str) -> str:
        return " ".join(str(data.get(key) or "").split())

    feeling = text("feeling")
    return Thought(
        text=text("thought"),
        kind="opinion" if data.get("kind") == "opinion" else "thought",
        want=text("want"),
        feeling=feeling if feeling in THOUGHT_FEELINGS else "",
        why=text("why"),
        trigger=trigger,
    )
