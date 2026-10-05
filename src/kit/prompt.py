"""Builds what the local model sees each turn: Kit's character sheet, what it
remembers, the gesture and emotion lists, and the recent conversation."""

from __future__ import annotations

from datetime import datetime

from kit.memory import Fact, Message
from kit.reply import EMOTIONS, GESTURES, Action, Reply, Segment, reply_json
from kit.settings import PersonaSettings


def system_prompt(persona: PersonaSettings, facts: list[Fact], now: datetime) -> str:
    name, owner = persona.name, persona.owner
    lines = [
        f"You are {name}, {owner}'s personal assistant. {persona.backstory}",
        f"Your traits: {', '.join(persona.traits)}.",
        f"How you talk: {persona.speech}",
        f"What you know about {owner}: {persona.knows}",
        "",
        "Rules:",
        *(f"- {rule}" for rule in persona.rules),
        "",
        f"It is {now:%A %d %B %Y, %I:%M %p}.",
    ]
    if facts:
        lines += ["", f"Things you remember about {owner}:"]
        lines += [f"- ({f.day}) {f.text}" for f in facts]
    lines += [
        "",
        "Answer only with JSON in this shape: an emotion, one to three short segments "
        "(each a sentence to say plus a gesture), and an action.",
        "Emotions: " + "; ".join(f"{k} ({v})" for k, v in EMOTIONS.items()) + ".",
        "Gestures: " + "; ".join(f"{k} ({v})" for k, v in GESTURES.items()) + ".",
        "Actions:",
        "- none: the usual.",
        f"- ask_claude: for anything you can't answer well yourself, such as hard maths, "
        f"long code, detailed engineering or facts you're unsure of. Put the full question "
        f"in text, and say something short like 'Let me check with Claude.' {owner} sees "
        f"Claude's answer next.",
        f"- remember: when {owner} tells you something worth remembering about themselves, their "
        f"work or plans. Put the fact in text as one short sentence.",
    ]
    if persona.examples:
        lines += ["", "Examples of how you talk:"]
        for ex in persona.examples:
            lines += [f"{owner}: {ex.user}", f"{name}: {ex.kit}"]
    return "\n".join(lines)


def history_messages(history: list[Message]) -> list[dict]:
    """Past turns in chat form. Kit's turns are shown as the JSON it gave, which
    keeps the model answering in that format."""
    out = []
    for m in history:
        if m.role == "user":
            out.append({"role": "user", "content": m.text})
        else:
            out.append({"role": "assistant", "content": m.reply_json or _as_json(m.text)})
    return out


def _as_json(text: str) -> str:
    return reply_json(
        Reply(
            emotion="neutral",
            segments=[Segment(say=text, gesture="none")],
            action=Action(kind="none"),
        )
    )
