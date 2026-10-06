"""Builds what the local model sees each turn: Kit's character sheet, what it
remembers that matters right now, the gesture and emotion lists, and the recent
conversation."""

from __future__ import annotations

import json
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
    if recalled.things:
        lines += ["", "Things you know and where they live (look there first):"]
        lines += [f"- {t.line()}" for t in recalled.things]
    if recalled.conversation:
        lines += ["", "Earlier conversations that may be relevant:"]
        lines += [_snippet(h) for h in recalled.conversation]
    return lines


# Where the part of the prompt that changes every turn begins. Everything before
# it stays the same between turns, so providers can reuse it from their cache.
TURN_PART = "\n\nIt is"

HAND_OFF = {
    "local-heavy": "for anything you can't answer well yourself, such as hard maths, long "
    "code, detailed engineering, current information (weather, prices, news) or facts you're "
    "unsure of",
    "balanced": "for anything more than small talk or a quick command: real questions, "
    "facts, advice, maths, code, engineering, and anything current such as weather, prices "
    "or news",
    "cloud-first": "for anything more than small talk",
}

REPLY_SHAPE = (
    '{"emotion": "neutral", "segments": [{"gesture": "nod", "say": "One short sentence."}], '
    '"action": {"kind": "none", "text": "", "category": "other", "thing_kind": "other", '
    '"link_system": "none", "link_target": ""}, "detail": ""}'
)


def system_prompt(
    persona: PersonaSettings,
    recalled: Recalled,
    now: datetime,
    role: str = "local",
    mode: str = "balanced",
    helper: str | None = "the cloud",
    expert: str | None = None,
    web_search: bool = False,
) -> str:
    """Kit's prompt for one role: "local" (the local model), "work" or "expert" (a
    cloud model). ``helper`` and ``expert`` name the models a question can be handed
    to; either is None when there's nowhere to hand it."""
    name, owner = persona.name, persona.owner
    cloud = role != "local"
    lines = [
        f"You are {name}, {owner}'s personal assistant. {persona.backstory}",
        f"Your traits: {', '.join(persona.traits)}.",
        f"How you talk: {persona.speech}",
        f"What you know about {owner}: {persona.knows}",
    ]
    if persona.location:
        lines.append(f"{owner} is in {persona.location}.")
    lines += [
        "",
        "Rules:",
        *(f"- {rule}" for rule in persona.rules if not (cloud and "to the cloud" in rule)),
        "- Use what you remember naturally, the way a friend would. Never invent a memory: "
        "if it isn't below or in the conversation, you don't know it yet.",
    ]
    if cloud:
        lines += [
            "- You are the cloud half of " + name + ". Answer properly and correctly; lead "
            "with the answer.",
            "- The segments are spoken aloud: one to three short sentences. Put anything "
            "longer (code, steps, lists, tables, workings, sources) in detail, which is "
            "shown on screen. Keep detail as plain text or simple Markdown.",
        ]
        if web_search:
            lines.append(
                "- You can search the web. Use it for anything current or that you'd "
                "otherwise guess at (weather, prices, products, news, opening hours), and put "
                "the sources in detail."
            )
    lines += [
        "",
        "Answer only with JSON: an emotion, one to three short segments (each a gesture "
        "plus a sentence to say), an action, and detail.",
    ]
    if cloud:
        lines.append(f"No code fences or text outside the JSON. Its shape: {REPLY_SHAPE}")
    lines += [
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
    ]
    lines.append(
        f"- thing: when {owner} names a specific person, pet, vehicle, place, project or "
        f"piece of equipment that isn't under 'Things you know' yet, or tells you where "
        f"one lives (a folder, a note, an app record). Put its name in text, set "
        f"thing_kind, and if you know where it lives set link_system and link_target. "
        f"For a new name, ask {owner} if you should add it to the register."
    )
    if not cloud and helper:
        lines.append(
            f"- ask_cloud: {HAND_OFF.get(mode, HAND_OFF['balanced'])}. Put the full question "
            f"in text and say something short like 'Let me check with {helper}.' {owner} "
            f"sees {helper}'s answer next."
        )
    if expert:
        lines.append(
            f"- ask_expert: for the hardest problems, such as long derivations, tricky "
            f"debugging or big designs, where a stronger model is worth the wait and cost. "
            f"Put the full question in text and say something short like 'That one's for "
            f"{expert}.'"
        )
    lines.append("Leave detail empty unless there's something to show.")
    if persona.examples:
        lines += ["", "Examples of how you talk:"]
        for ex in persona.examples:
            lines += [f"{owner}: {ex.user}", f"{name}: {ex.kit}"]
    # What changes every turn goes last, so the cached prefix above can be reused.
    lines += [
        "",
        f"{TURN_PART.strip()} {now:%A %d %B %Y, %I:%M %p}.",
        *memory_block(recalled, owner),
    ]
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


HISTORY_DETAIL_CHARS = 600


def history_messages(history: list[Message]) -> list[dict]:
    """Past turns in chat form. Kit's turns are shown as the JSON it gave, which
    keeps the model answering in that format. Long written detail (code, lists) is
    cut short so it doesn't crowd the local model's context."""
    out = []
    for m in history:
        if m.role == "user":
            out.append({"role": "user", "content": m.text})
        else:
            out.append({"role": "assistant", "content": _short(m.reply_json) or _as_json(m.text)})
    return out


def _short(reply_json: str | None) -> str | None:
    if not reply_json:
        return None
    try:
        data = json.loads(reply_json)
    except ValueError:
        return reply_json
    detail = data.get("detail") or ""
    if len(detail) > HISTORY_DETAIL_CHARS:
        data["detail"] = detail[:HISTORY_DETAIL_CHARS] + " [...]"
        return json.dumps(data)
    return reply_json


def _as_json(text: str) -> str:
    return reply_json(
        Reply(
            emotion="neutral",
            segments=[Segment(say=text, gesture="none")],
            action=Action(kind="none"),
        )
    )
