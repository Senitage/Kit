"""Who can hear Kit, and who he's talking to.

Kit is one mind with several ways in: the desk app and the chat page only reach
Dan, but when he talks out loud (his voice at the desk, or his robot body) anyone
in the room hears him. So each prompt says which it is, and who his eyes see in the
room, so he can greet a visitor or the cat by name himself out loud, and on a
screen asks Dan to pass it on instead.

A message can also say who sent it (``speaker``), for when someone other than Dan
talks to him; it's kept with the message, so the history shows who said what.

His reply's first words show who it's for ("Hi Sam!"): :func:`addressed` picks
that out, so a body can turn to face them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from kit.scene_context import ANIMALS, join_names

ALOUD = {"voice", "pod"}  # channels where Kit's words are spoken into the room
GREETINGS = ("hi", "hey", "hello", "oi", "morning", "evening", "night", "bye", "g'day")


def aloud(channel: str) -> bool:
    return channel in ALOUD


def pets_by_kind(pets: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Kind of animal ("cat") to the pet's name, from (name, what's known about it)
    pairs, for kinds with exactly one pet, so an animal the eyes see can be named."""
    found: dict[str, list[str]] = {}
    for name, about in pets:
        words = set(re.findall(r"[a-z]+", about.lower()))
        for kind in ANIMALS & words:
            found.setdefault(kind, []).append(name)
    return {kind: names[0] for kind, names in found.items() if len(names) == 1}


def audience_line(
    channel: str, owner: str, speaker: str = "", room: Iterable[str] = (), strangers: int = 0
) -> str:
    """One line for the prompt: who hears Kit's words, and who sent this message."""
    others = [name for name in room if name != owner]
    if aloud(channel):
        line = "You're speaking out loud, so anyone in the room hears you."
        heard = [*others, *(["someone you don't know"] if strangers else [])]
        if heard:
            line += (
                f" Also in the room: {join_names(heard)}. Talk to them directly, by name "
                f'("Hi {others[0] if others else "there"}!"), pets too, rather than through '
                f"{owner}."
            )
    else:
        line = (
            f"Only {owner} reads what you write here. Nobody else can hear you, so to greet "
            f'anyone else ask {owner} to pass it on ("tell them I said hi").'
        )
        if others:
            line += f" With {owner} now: {join_names(others)}."
    if speaker and speaker != owner:
        line += f" This message is from {speaker}, not {owner}: answer {speaker}."
    return line


def speaker_meta(speaker: str, owner: str) -> str | None:
    """What's kept with a message about who sent it (nothing for the owner)."""
    return json.dumps({"speaker": speaker}) if speaker and speaker != owner else None


def speaker_of(meta_json: str | None) -> str:
    """Who sent a stored message, if it wasn't the owner."""
    try:
        return str((json.loads(meta_json or "{}") or {}).get("speaker") or "")
    except (ValueError, AttributeError):
        return ""


def addressed(text: str, names: Iterable[str]) -> str:
    """Who Kit's words are for, if he opens by name: "Hi Sam!", "Sam, ..." or
    "..., Milo." in the first sentence. Empty if he names nobody there."""
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].lower()
    best = ""
    at = len(first) + 1
    for name in names:
        n = re.escape(name.lower())
        greeting = "|".join(re.escape(g) for g in GREETINGS)
        match = re.search(
            rf"^{n}\b|^(?:{greeting})\W+(?:there\W+)?{n}\b|,\s*{n}\W*$|,\s*{n}\s*,", first
        )
        if match and match.start() < at:
            best, at = name, match.start()
    return best
