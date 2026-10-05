"""Builds what the local model sees each turn: Kit's character sheet, what it
remembers that matters right now, the gesture and emotion lists, and the recent
conversation."""

from __future__ import annotations

from datetime import datetime

from kit.knowledge import Hit, Item
from kit.memory import DAYS, Message
from kit.recall import Recalled
from kit.reply import EMOTIONS, GESTURES, Action, Reply, Segment, reply_json
from kit.settings import PersonaSettings


def _memory_line(item: Item) -> str:
    if item.source == DAYS:
        return f"- ({item.ref}, summary of the day) {item.text}"
    return f"- ({item.day}, {item.kind}) {item.text}"


def _snippet(hit: Hit) -> str:
    text = " / ".join(hit.item.text.splitlines())
    return f"- ({hit.item.day}) {text[:400]}"


def memory_block(recalled: Recalled, owner: str) -> list[str]:
    lines: list[str] = []
    if recalled.pinned:
        lines += ["", f"Always keep in mind about {owner}:"]
        lines += [_memory_line(i) for i in recalled.pinned]
    if recalled.memories:
        lines += ["", "Memories that may be relevant now (newer ones win if they disagree):"]
        lines += [_memory_line(h.item) for h in recalled.memories]
    if recalled.conversation:
        lines += ["", "Earlier conversations that may be relevant:"]
        lines += [_snippet(h) for h in recalled.conversation]
    return lines


def system_prompt(persona: PersonaSettings, recalled: Recalled, now: datetime) -> str:
    name, owner = persona.name, persona.owner
    lines = [
        f"You are {name}, {owner}'s personal assistant. {persona.backstory}",
        f"Your traits: {', '.join(persona.traits)}.",
        f"How you talk: {persona.speech}",
        f"What you know about {owner}: {persona.knows}",
        "",
        "Rules:",
        *(f"- {rule}" for rule in persona.rules),
        "- Use what you remember naturally, the way a friend would. Never invent a memory: "
        "if it isn't below or in the conversation, you don't know it yet.",
        "",
        f"It is {now:%A %d %B %Y, %I:%M %p}.",
        *memory_block(recalled, owner),
        "",
        "Answer only with JSON: an emotion, one to three short segments (each a sentence "
        "to say plus a gesture), and an action.",
        "Emotions: " + "; ".join(f"{k} ({v})" for k, v in EMOTIONS.items()) + ".",
        "Gestures: " + "; ".join(f"{k} ({v})" for k, v in GESTURES.items()) + ".",
        "Actions:",
        "- none: the usual.",
        f"- recall: when {owner} refers to something from before (a past conversation, a "
        f"project, a person, where something is kept) and it isn't above. Put a search in "
        f"text, say something short like 'Let me think...', and you'll see what you find "
        f"before answering properly.",
        f"- remember: when {owner} tells you something worth keeping: about themselves, "
        f"their preferences, projects, where things are kept, people or plans. Put it in "
        f"text as one sentence that makes sense on its own later, with real dates, and set "
        f"category.",
        f"- ask_claude: for anything you can't answer well yourself, such as hard maths, "
        f"long code, detailed engineering or facts you're unsure of. Put the full question "
        f"in text and say something short like 'Let me check with Claude.' {owner} sees "
        f"Claude's answer next.",
    ]
    if persona.examples:
        lines += ["", "Examples of how you talk:"]
        for ex in persona.examples:
            lines += [f"{owner}: {ex.user}", f"{name}: {ex.kit}"]
    return "\n".join(lines)


def recall_results(query: str, hits: list[Hit], owner: str) -> str:
    if not hits:
        return (
            f"You searched your memory for '{query}' and found nothing. Tell {owner} "
            f"honestly that you don't remember, and ask if they'd like you to remember it "
            f"now. Answer as JSON with action none."
        )
    found = [_memory_line(h.item) if h.item.source != "conversation" else _snippet(h) for h in hits]
    return "\n".join(
        [
            f"You searched your memory for '{query}' and found:",
            *found,
            f"Now answer {owner}'s last message using this, as JSON with action none. If it "
            f"doesn't answer the question, say what you do know and what you don't.",
        ]
    )


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
