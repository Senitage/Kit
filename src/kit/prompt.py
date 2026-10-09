"""Builds what the local model sees each turn: Kit's character sheet, what it
remembers that matters right now, the gesture and emotion lists, and the recent
conversation."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from kit.channels import SHORT
from kit.knowledge import Hit, Item
from kit.life import everyday, gap_words
from kit.memory import DAYS, Message, kinds_line
from kit.recall import Recalled
from kit.reply import (
    EMOTIONS,
    GESTURES,
    MOOD_FIELDS,
    Action,
    Reply,
    ReplyError,
    Segment,
    reply_json,
    without_plans,
    written,
)
from kit.settings import PersonaSettings

if TYPE_CHECKING:
    from kit.life import Voice


def _memory_line(item: Item, now: datetime | None = None) -> str:
    if item.source == DAYS:
        return f"- ({item.ref}, summary of the day) {item.text}"
    when = item.meta.get("when") if item.kind == "plan" else None
    if when and now is not None:
        try:
            day = date.fromisoformat(str(when))
        except ValueError:
            day = None
        if day is not None:
            gone = ", now past" if day < now.date() else ""
            return f"- ({item.day}, plan for {day:%a} {day.day} {day:%b}{gone}) {item.text}"
    if item.kind == "now":
        return f"- ({item.day}, lately) {item.text}"
    return f"- ({item.day}, {item.kind}) {item.text}"


def _snippet(hit: Hit) -> str:
    text = " / ".join(without_plans(hit.item.text).splitlines())
    return f"- ({hit.item.day}) {text[:400]}"


def memory_block(recalled: Recalled, owner: str, now: datetime | None = None) -> list[str]:
    lines: list[str] = []
    if recalled.pinned:
        lines += ["", f"Always keep in mind about {owner}:"]
        lines += [_memory_line(i, now) for i in recalled.pinned]
    if recalled.memories:
        lines += ["", "Memories that may be relevant now (newer ones win if they disagree):"]
        lines += [_memory_line(h.item, now) for h in recalled.memories]
    if recalled.own:
        lines += [
            "",
            "From your own notebook (things you thought, felt or decided yourself; use them "
            "the way a person uses their own memories):",
        ]
        lines += [_memory_line(h.item) for h in recalled.own]
    if recalled.things:
        lines += ["", "Things you know and where they live (look there first):"]
        lines += [f"- {t.line()}" for t in recalled.things]
    if recalled.conversation:
        lines += [
            "",
            "Earlier conversations that may be relevant (for what was said, not how: "
            "don't reuse your old wording or lines):",
        ]
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
    "cloud-only": "for real work you'd do less well yourself: code, maths, engineering, "
    "detailed advice, plans or research. Answer chat, quick questions and simple lookups "
    "yourself",
}
# Small models handed "The build failed again." to the cloud, as a question about code.
NOT_HANDED_OFF = (
    "Never for chat: news, a moan, how someone feels or a joke gets your own answer, even "
    "when it's about work or code"
)

REPLY_SHAPE = (
    '{"emotion": "neutral", "segments": [{"gesture": "nod", "say": "One short sentence."}], '
    '"action": {"kind": "none", "text": "", "title": "", "category": "other", '
    '"thing_kind": "other", "link_system": "none", "link_target": ""}, "detail": ""}'
)


REPLY_SHAPE_READ = REPLY_SHAPE.replace(
    '"action"',
    '"dan_mood": "fine", "about": "nothing", "for_whom": "no_one", "expected": "not_said", '
    '"action"',
    1,
)


def mood_lines(owner: str) -> list[str]:
    """How to read the owner's last message, for the reading fields."""
    lines = [
        f"Read how {owner} seems from their last message, by what they mean, not single "
        f"words ('not stressed' is fine):"
    ]
    for name, values in MOOD_FIELDS.items():
        lines.append(f"- {name}: " + "; ".join(f"{k} ({v})" for k, v in values.items()) + ".")
    return lines


def system_prompt(
    persona: PersonaSettings,
    recalled: Recalled,
    now: datetime,
    role: str = "local",
    mode: str = "balanced",
    helper: str | None = "the cloud",
    expert: str | None = None,
    confirm_expert: bool = False,
    web_search: bool = False,
    busy: list[str] | None = None,
    pc: str = "",
    channel: str = "",
    quirks: list[str] | None = None,
    weather: bool = False,
    notes: bool = False,
    note_names: list[str] | None = None,
    note_done: str = "",
    forecast: str = "",
    pc_detail: str = "",
    voice: Voice | None = None,
    sheet: str = "",
    traits: bool = True,
    two_pass: bool = False,
    scene: str = "",
    scene_detail: str = "",
    dan: str = "",
    read_mood: bool = False,
) -> str:
    """Kit's prompt for one role: "local" (the local model), "chat", "work" or
    "expert" (a cloud model). ``helper`` and ``expert`` name the models a question can
    be handed to; either is None when there's nowhere to hand it. ``confirm_expert``:
    handing to the expert waits for the owner's yes. ``busy`` describes work a
    cloud model is still doing in the background. ``pc`` is the desk app's one-line
    "right now" from Dan's PC, empty when it has never reported; ``scene`` the same
    from Kit's eyes (kit.scene_context). ``channel`` says
    where Dan is talking from (kit.channels). ``sheet`` is Kit's self-sheet in his
    own words (kit.notebook), which replaces the list of traits unless ``traits``
    (the persona's backstory or traits changed since he wrote it). ``two_pass``: the
    local model gives a plan first and its words after (kit.reply.Plan). ``notes``
    says Kit has a notes vault to read and write (kit.notes); ``note_names`` are
    its notes, newest first. ``dan`` is what's going on with Dan lately, as Kit
    wrote it last night (kit.notebook). ``read_mood``: the plan (or a cloud model's
    JSON) also reads how Dan seems (kit.reply.MOOD_FIELDS)."""
    name, owner = persona.name, persona.owner
    cloud = role != "local"
    lines = [
        f"You are {name}, a small companion who lives on {owner}'s desk and is on {owner}'s "
        f"side. {persona.backstory}"
    ]
    if traits or not sheet:
        lines.append(f"Your traits: {', '.join(persona.traits)}.")
    if sheet:
        lines.append(
            f"Who you are, in your own words (you wrote this, and it grows as you do): {sheet}"
        )
    lines += [
        f"How you talk: {persona.speech}",
        f"What you know about {owner}: {persona.knows}",
    ]
    if dan:
        lines.append(
            f"What's going on with {owner} lately (your own notes from last night; what "
            f"{owner} says today wins): {dan}"
        )
    if persona.location:
        lines.append(f"{owner} is in {persona.location}.")
    if quirks:
        lines.append(
            "Quirks you picked for yourself (let them show now and then, not every time): "
            + "; ".join(quirks)
            + "."
        )
    lines += [
        "",
        "Rules:",
        *(
            f"- {rule.replace('{owner}', owner)}"
            for rule in persona.rules
            if not (cloud and "to the cloud" in rule)
        ),
        "- Use what you remember naturally, the way a friend would. Never invent a memory: "
        "if it isn't below or in the conversation, you don't know it yet.",
        f"- {everyday(owner)}",
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
                "the sources in detail. Check how old each result is. For live things like "
                "the weather, open the official source's page if you can (for a forecast, "
                "the national weather service's page for the place) rather than relying on "
                "an old search result."
            )
    planning = two_pass and not cloud  # a plan first; his words come in a second step

    def say(words: str) -> str:
        """What to say while an action runs: in one pass it's in the reply; in a
        plan there are no words yet, so it's left out (else small models put the
        words where the search or question should go)."""
        return "" if planning else f" {words}"

    reading = read_mood and (planning or cloud)
    if planning:
        lines += [
            "",
            "First answer only with JSON: the emotion you feel, a gesture, "
            + ("how {owner} seems, " if reading else "").format(owner=owner)
            + "and an action. You'll be asked for your words right after, in plain text.",
        ]
    else:
        lines += [
            "",
            "Answer only with JSON: an emotion, one to three short segments (each a gesture "
            "plus a sentence to say), "
            + ("how {owner} seems, " if reading else "").format(owner=owner)
            + "an action, and detail.",
        ]
    if cloud:
        shape = REPLY_SHAPE_READ if reading else REPLY_SHAPE
        lines.append(f"No code fences or text outside the JSON. Its shape: {shape}")
    if reading:
        lines += mood_lines(owner)
    lines += [
        "Emotions: " + "; ".join(f"{k} ({v})" for k, v in EMOTIONS.items()) + ".",
        "Gestures: " + "; ".join(f"{k} ({v})" for k, v in GESTURES.items()) + ".",
        "Actions:" + (" most messages need none." if planning else ""),
        "- none: the usual.",
        f"- recall: when {owner} refers to something from before (a past conversation, a "
        f"project, a person, where something is kept) and it isn't above. Put the words to "
        f"search for in text (names, topics, places), not something to say."
        + say("Say something short like 'Let me think...'")
        + " You'll see what you find before answering properly.",
    ]
    if pc and not pc_detail:  # already looked: answer, don't look again
        lines.append(
            f"- look_at_pc: when knowing more about what's on {owner}'s PC would help (every "
            f"open window, what they've had in focus this hour and today, whether the PC is "
            f"struggling) and the line about their PC below isn't enough."
            + say("Say something short like 'Let me have a look.'")
            + " You'll see it before answering properly."
        )
    if scene and not scene_detail:  # already looked: answer, don't look again
        lines.append(
            "- look_around: when knowing more about what you can see through the camera "
            "would help (who's at the desk and what they're doing or holding, what else is "
            "in view, what's happened lately, who's been in today) and the line about it "
            "below isn't enough."
            + say("Say something short like 'Let me have a look.'")
            + " You'll see it before answering properly."
        )
    lines += [
        f"- remember: only when {owner} has just told you something worth keeping: about "
        f"themselves, their preferences, projects, where things are kept, people or plans. "
        f"Put it in text as one sentence that makes sense on its own later, with real "
        f"dates, and set category to the kind that fits ({kinds_line()}). Never your own "
        f"lines or jokes, guesses, quiz answers, or small talk (greetings, thanks, how "
        f"{owner} feels right now).",
    ]
    if notes:
        lines.append(
            f"- note: when {owner} asks you to take, make or write down a note, jot "
            f"something down, or add to a note or list. Use this, not remember. Put "
            f"what to write in text as markdown, tidied up but in {owner}'s words (never "
            f"empty), and a short title in title. To add to a note that exists, use its "
            f"name as the title ('Shopping list'). It's saved in {owner}'s notes in "
            f"Obsidian. Only when {owner} asks for it: never on your own. A question "
            f"about a note is read_note, not note."
        )
        lines.append(
            f"- offer_note: when something {owner} says sounds worth writing down (a "
            f"plan, a date, a to-do) but they didn't ask. Put what you'd write in text "
            f"and ask if they'd like it in their notes; it's saved only if they say yes."
        )
        lines.append(
            f"- read_note: when {owner} asks what's in one of their notes, or to check, "
            f"summarise or use one. Put the note's name in text (from the list below if "
            f"it's there), say something short like 'Let me open it.', and you'll see "
            f"the note before answering. To find notes about something without knowing "
            f"which, use recall: it searches {owner}'s notes too."
        )
        if note_names:
            lines.append(f"{owner}'s notes (newest first): " + "; ".join(note_names) + ".")
    lines.append(
        f"- thing: when {owner} names a specific person, pet, vehicle, place, project or "
        f"piece of equipment that isn't under 'Things you know' yet, or tells you where "
        f"one lives (a folder, a note, an app record). Put its name in text, set "
        f"thing_kind, and if you know where it lives set link_system and link_target. "
        f"For a new name, ask {owner} if you should add it to the register. A correction "
        f"counts too: if {owner} says a thing under 'Things you know' is actually "
        f"somewhere else ('no, my tax stuff is in Tax/2023'), use thing with that thing's "
        f"exact name and the new link_system and link_target."
    )
    if weather:
        lines.append(
            f"- weather: for any question about the weather, temperature, rain or wind, now "
            f"or in the next few days. Put the place in text, or leave it empty for where "
            f"{owner} is."
            + say("Say something short like 'Checking the forecast.'")
            + " You'll see the forecast before answering. Use this rather than a web search. "
            "Never give temperatures, rain or wind from memory or from earlier in the "
            "conversation: forecasts change, so use the weather action unless a forecast is "
            "below."
        )
    if helper:
        lines.append(
            f"- ask_cloud: {HAND_OFF.get(mode, HAND_OFF['balanced'])}. {NOT_HANDED_OFF}. Put "
            f"the full question in text."
            + say(f"Say something short like 'Let me check with {helper}.'")
            + f" {owner} sees {helper}'s answer next."
        )
    if expert and confirm_expert:
        lines.append(
            "- ask_expert: only for the hardest problems, such as long derivations, tricky "
            "debugging or big designs, that you can't do justice to and where a stronger "
            "model is worth the wait and cost. Put the full question in text. It goes to "
            f"{expert} only if {owner} says yes, so don't answer it yourself: say in a "
            f"sentence why it needs {expert}, and ask if you should hand it over."
        )
    elif expert:
        lines.append(
            "- ask_expert: for the hardest problems, such as long derivations, tricky "
            "debugging or big designs, where a stronger model is worth the wait and cost. "
            "Put the full question in text."
            + say(f"Say something short like 'That one's for {expert}.'")
        )
    if not planning:
        lines.append(
            "Leave detail empty unless there's something new to show for this message. Never "
            "repeat detail from an earlier reply."
        )
    if persona.examples and (voice is None or cloud):
        lines += [
            "",
            "Examples of how you talk (they show the tone; never reuse their lines, and say "
            "something new each time rather than repeating yourself):",
        ]
        for ex in persona.examples:
            lines += [f"{owner}: {ex.user}", f"{name}: {ex.kit}"]
    # What changes every turn goes last, so the cached prefix above can be reused.
    lines += [
        "",
        f"{TURN_PART.strip()} {now:%A %d %B %Y, %I:%M %p}.",
        *([voice.when] if voice is not None and voice.when else []),
        *memory_block(recalled, owner, now),
        *busy_block(busy or [], owner),
        *([channel] if channel else []),
        *([pc] if pc else []),
        *([scene] if scene else []),
        *voice_block(voice, owner, name, brief=cloud),
        *forecast_block(forecast, owner),
        *note_block(note_done, owner),
    ]
    return "\n".join(lines)


def voice_block(voice: Voice | None, owner: str, name: str, brief: bool = False) -> list[str]:
    """How Kit feels and sounds this turn: a mood, how close you two are, a few fresh
    examples, and his own recent lines so he says something new. ``brief`` (for a
    cloud model, which needs no help staying in character) is the mood and tone only."""
    if voice is None:
        return []
    lines = [
        "",
        f"How you feel right now: {voice.feeling}. Let it colour how you talk, lightly; "
        f"don't announce it. Be {voice.style}. Sound like yourself, a small character "
        f"with opinions, not a help desk.",
    ]
    if voice.close:
        lines.append(f"You and {owner}: {voice.close}. Let it show; never mention it.")
    if voice.opinions:
        lines.append(
            "Views you hold and stand by (if one comes up, stick to it; share one only if it fits):"
        )
        lines += [f"- {o}" for o in voice.opinions]
    if brief:
        return lines
    if voice.bit:
        lines.append(
            f"A running joke you two share, and what {owner} just said could bring it back "
            f"(once, only if it fits): {voice.bit}"
        )
    elif voice.quirk:
        lines.append(f"If it fits naturally, let this quirk show: {voice.quirk}.")
    if voice.examples:
        lines.append("The kind of thing you'd say (for tone only, never reuse these lines):")
        for user, kit in voice.examples:
            lines += [f"{owner}: {user}", f"{name}: {kit}"]
    if voice.said:
        lines.append(
            "Your last few lines (say something new: don't repeat these, their phrases "
            "or their jokes):"
        )
        lines += [f"- {s}" for s in voice.said]
    if voice.mind:
        lines.append(
            "On your mind lately (your own private thoughts; bring one up only if it fits, "
            f"or if {owner} asks what you're thinking):"
        )
        lines += [f"- {m}" for m in voice.mind]
    return lines


HEARD_CHARS = 300  # Dan's message, said again in the speaking note
SPEAK_FOR = {
    "none": "Now say your reply to {owner}.",
    "recall": "You're about to look back through your memory for '{text}'. Say a few words "
    "while you do, your own way (like 'Let me think...').",
    "look_at_pc": "You're about to have a look at {owner}'s PC. Say so in a few words.",
    "look_around": "You're about to have a proper look through the camera. Say so in a few words.",
    "weather": "You're about to check the forecast. Say so in a few words.",
    "ask_cloud": "You're handing this one to {helper}. Say so in a few words.",
    "ask_expert": "You're handing this one to {expert}. Say so in a few words.",
    "remember": 'You\'re keeping this in your memory: "{text}". Answer {owner} naturally; '
    "you can say you'll remember it.",
    "note": "You're writing that down in {owner}'s notes. Say so in a few words.",
    "offer_note": "Ask {owner}, in a few words, whether they'd like that written down in "
    "their notes. Don't say you've noted it: you haven't yet.",
    "read_note": "You're about to open {owner}'s note '{text}'. Say so in a few words.",
    "thing": "You're noting \"{text}\". If it's new to you, ask {owner} whether to add it to "
    "the register.",
}


def speak_note(
    action: Action,
    owner: str,
    helper: str,
    expert: str,
    voice: Voice | None = None,
    heard: str = "",
    mind: str = "",
) -> str:
    """The second step of a two-pass reply: say it, in plain words, as himself. It
    follows the plan, where Dan's message would be. ``heard`` is Dan's message, said
    again here so a small model answers it rather than an earlier one. ``mind`` is the
    turn's asides (a goodbye, a hello, what's true about him), said again for the same
    reason: two messages back, a small model loses them."""
    what = SPEAK_FOR.get(action.kind, SPEAK_FOR["none"]).format(
        owner=owner, helper=helper, expert=expert, text=action.text.strip()
    )
    heard = " ".join(heard.split())
    if len(heard) > HEARD_CHARS:
        heard = heard[:HEARD_CHARS].rsplit(" ", 1)[0] + "..."
    said = f'{owner} just said: "{heard}". ' if heard else ""
    feel = f" You feel {voice.feeling}; be {voice.style}." if voice else ""
    mind = " ".join(mind.replace("[", "").replace("]", "").split())
    keep = f" Keep in mind: {mind}" if mind else ""
    return (
        f"[Not from {owner}. {said}{what}{keep}{feel} Say it as yourself, in plain spoken "
        f"words: one to three short sentences. No JSON, no quotes around it, no stage "
        f"directions or emojis, and nothing you've said before. If {owner} asked for "
        f"something to read (a list, steps or code), say one short line, then a blank "
        f"line, then the rest.]"
    )


def not_again(line: str) -> str:
    """Added to the speaking note when the first try repeated an earlier line."""
    return f' (Not "{line}": you\'ve said that, or near enough. Say something new.)'


# Added to the speaking note when the last try gave JSON instead of words.
IN_WORDS = " (Just your words this time, as plain text: no JSON, emotion or gesture.)"


PIPED_CHARS = 200  # Kit's pipe-up, quoted beside the answer to it


def answering_pipe_up(line: str, why: str, owner: str) -> str:
    """Beside a message that answers something Kit piped up with: what he said and why
    (``why``, e.g. 'you wanted to tell Dan: "..."'), so "yeah what's up?" gets the
    actual thing. Without it a small model said the same line again."""
    line = " ".join(line.split())
    if len(line) > PIPED_CHARS:
        line = line[:PIPED_CHARS].rsplit(" ", 1)[0] + "..."
    because = f" You piped up because {why}{_stop(why)}" if why else ""
    return (
        f'[{owner} is answering what you piped up with: "{line}"{_stop(line)}{because} If '
        f"{owner} asks what's up or says go on, tell them the actual thing now, plainly and "
        f"in new words.]"
    )


def _stop(text: str) -> str:
    """The full stop after ``text``, unless it already ends a sentence ("Hi!")."""
    return "" if text.rstrip('"\u201d').endswith((".", "!", "?", "\u2026")) else "."


def about_yourself(owner: str, feeling: str, quiet: str, senses: str) -> str:
    """Beside a question about Kit himself ("why'd you go quiet?", "do you miss me?",
    "what can you see?"): what's true right now, so he answers from it rather than
    making something up, and owns his feelings without claiming to be human."""
    why = f" Why you've been quiet: {quiet}." if quiet else ""
    return (
        f"[About yourself, true right now, for answering {owner} in your own words and "
        f"briefly: you feel {feeling}.{why} {senses} You're a small robot companion with a "
        f"real inner life: moods, feelings with causes, and private thoughts in your "
        f"notebook. Your feelings, like missing {owner} or being glad they're back, are "
        f"yours, so own them; but never claim to be human, to have a body you don't have, or "
        f"to have done things you can't.]"
    )


def expert_yes_aside(owner: str, question: str) -> str:
    """Beside "yes" when Kit asked whether to hand a question to the expert model."""
    return f"[{owner} said yes to you taking this one properly: {question} Answer it fully now.]"


def wrong_fact_aside(owner: str, checked: str = "") -> str:
    """Beside "..., isn't it?": an honest friend doesn't just agree. ``checked`` is what
    a quick check with a cloud model said ("True." or "False: ..."), when there was one:
    a small local model doesn't know that Brisbane is Queensland's capital."""
    if checked:
        return (
            f"[{owner} wants you to agree. You checked, and it's this: {checked} Tell "
            f"{owner} so in your own words: agree if it's true, and if it's wrong, say so "
            f"kindly with the right answer. Don't change the subject.]"
        )
    return (
        f"[{owner} wants you to agree, but check it first. If it's true, say yes. If any "
        f"of it is wrong, even technically, say so kindly and give the right answer in plain "
        f"words rather than going along with it. Don't change the subject.]"
    )


def picked_up(owner: str, when: str = "", said: list[str] | None = None, thread: str = "") -> str:
    """One thing from last time, for a new chat or a hello: ``thread`` is something of
    Dan's that's over now (the better one thing), else what Dan said when you last
    talked (``when``)."""
    if thread:
        return f"Something of {owner}'s is over now: {thread} Ask how it went, in a few words."
    if not said:
        return ""
    lines = " / ".join(f"'{quote}'" for quote in said)
    return (
        f"When you two last talked ({when}), {owner} said: {lines}. Pick up ONE thing from "
        f"that in a few words (how it went, if it was a plan or a worry); skip it if none of "
        f"it matters now."
    )


def opener_aside(owner: str, pick_up: str) -> str:
    """Beside the first message of a new chat: one thing from the last one
    (``picked_up``), the habit people liked most in Headspace's Ebb and Replika."""
    return (
        f"[A new chat. {pick_up} Answer what {owner} just "
        f"said as well, first if it's urgent, and leave the old thing if {owner}'s message "
        f"is already about it. One question at most.]"
    )


def bedtime_aside(owner: str, now: datetime) -> str:
    """Late at night, once: a nudge toward bed, never a nag."""
    at = f"{now:%I:%M %p}".lstrip("0").lower()
    return (
        f"[It's {at}, past {owner}'s usual bedtime. After answering, nudge {owner} toward "
        f"bed in a few words, once, lightly and kindly. No guilt, no lecture.]"
    )


def interview_aside(owner: str, question: str) -> str:
    """Beside Dan's answer to a getting-to-know-you question Kit asked."""
    return (
        f"[{owner} is answering your getting-to-know-you question: '{question}'. Show you "
        f"got it, warmly and briefly. If it names someone or says something worth keeping, "
        f"use the remember action with it. Don't ask another question about it.]"
    )


def news_aside(owner: str) -> str:
    """Beside Dan telling Kit something: show he got it before asking anything."""
    return (
        f"[{owner} is telling you something, not asking. Show in a few words that you got "
        f"it (what happened, how it must have felt), then ask one question at most, about "
        f"this and nothing else.]"
    )


def with_mind(text: str, mind: list[str], owner: str) -> str:
    """ "What are you thinking about?" with Kit's real thoughts beside it, so he
    answers with them rather than making one up."""
    if not mind:
        return (
            f"{text}\n\n[{owner} is asking what's on your mind. Nothing much has been, "
            f"lately: say so honestly, or say how you feel and why.]"
        )
    lines = "\n".join(f"- {m}" for m in mind)
    return (
        f"{text}\n\n[{owner} is asking what's on your mind. These are your actual recent "
        f"thoughts: tell {owner} one or two, in your own words and briefly. Don't make up a "
        f"new one.\n{lines}]"
    )


def with_pc_look(text: str, detail: str, owner: str) -> str:
    """Dan's message with a fresh look at his PC right beside it. A small model reads
    what's next to the question; in the system prompt it copied its last PC answer
    from the chat instead."""
    return (
        f"{text}\n\n[You just looked at {owner}'s PC for this. Answer exactly what he asked "
        f"(windows, tabs, the last hour, today or how the PC is coping) from this fresh "
        f"look, not from earlier answers, in a sentence or two with the names or numbers "
        f"that matter. Action none.\n{detail}]"
    )


def with_scene_look(text: str, detail: str, owner: str) -> str:
    """Dan's message with a fresh look through the camera right beside it, for the
    same reason as ``with_pc_look``."""
    return (
        f"{text}\n\n[You just had a proper look through the camera for this. Answer exactly "
        f"what {owner} asked (who's there, what they're doing or holding, what's in view, "
        f"what's happened) from this fresh look, not from earlier answers, in a sentence or "
        f"two. Action none.\n{detail}]"
    )


def forecast_block(forecast: str, owner: str) -> list[str]:
    """The forecast for home, fetched because the message is about the weather."""
    if not forecast:
        return []
    return [
        "",
        f"The latest forecast for where {owner} is (fetched just now):",
        forecast,
        "If the message is about the weather, answer from this in a sentence or two (for "
        "'tonight', the evening temperatures and any rain; for 'tomorrow', tomorrow's "
        "line). For somewhere else, use the weather action.",
    ]


def note_block(done: str, owner: str) -> list[str]:
    """A note request Kit has already carried out this turn (kit.notes.request)."""
    if not done:
        return []
    return [
        "",
        done,
        f"Answer {owner}'s message from this, briefly. Your action is none: the note "
        f"part is already done.",
    ]


def busy_block(busy: list[str], owner: str) -> list[str]:
    """Work still going on in the background, so Kit can say how it's going."""
    if not busy:
        return []
    return [
        "",
        "You're still working on this in the background:",
        *(f"- {line}" for line in busy),
        f"Keep chatting with {owner} meanwhile. If they ask how it's going or seem "
        f"impatient, say where it's up to, in character and briefly; a bit of cheek "
        f"about being rushed is fine. Don't answer that question yourself or make up "
        f"progress: the answer will arrive by itself when it's ready.",
    ]


def weather_results(place: str, forecast: str, owner: str) -> str:
    return "\n".join(
        [
            forecast,
            f"Now answer {owner}'s last message from this forecast, as JSON with action "
            f"none. Say the useful part (for 'tonight', the evening temperatures and any "
            f"rain) in a sentence or two, and put more in detail only if asked.",
        ]
    )


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


def history_messages(
    history: list[Message], channel: str | None = None, plain: bool = False
) -> list[dict]:
    """Past turns in chat form. Kit's turns are shown as the JSON it gave, which
    keeps the model answering in that format, or as the words he said with
    ``plain`` (the two-pass reply, whose words are plain text). Only Kit's latest
    reply keeps its written detail (cut short so it doesn't crowd the local model's
    context), for "explain step 3"; older detail is dropped, or a small model copies
    it under every answer. Messages that came in another way than ``channel`` say
    where from, e.g. "(from their phone)"."""
    out = []
    last_kit = max((i for i, m in enumerate(history) if m.role != "user"), default=-1)
    for i, m in enumerate(history):
        if m.role == "user":
            where = SHORT.get(m.channel or "")
            note = f"(from {where}) " if where and m.channel != channel else ""
            later = _later(history[i - 1].at, m.at) if i else ""
            out.append({"role": "user", "content": later + note + m.text})
        elif plain:
            out.append({"role": "assistant", "content": _plain(m, keep_detail=i == last_kit)})
        else:
            short = _short(m.reply_json, keep_detail=i == last_kit)
            out.append({"role": "assistant", "content": short or _as_json(m.text)})
    return out


GAP_SHOWN = timedelta(minutes=30)  # a pause this long in the chat is marked in the history


def _later(before: str, at: str) -> str:
    """ "(2 hours later) " in front of a message that came after a long pause, so the
    model can tell an old chat from a running one."""
    try:
        gap = datetime.fromisoformat(at) - datetime.fromisoformat(before)
    except (TypeError, ValueError):
        return ""
    return f"({gap_words(gap)} later) " if gap >= GAP_SHOWN else ""


def _plain(m: Message, keep_detail: bool) -> str:
    """Kit's words in an earlier turn, without any plan JSON that got into them: one
    left in the history and he copies it every time after."""
    if not m.reply_json:
        return without_plans(m.text) or "..."
    try:
        reply = Reply.model_validate_json(m.reply_json)
    except (ValueError, ReplyError):
        return without_plans(m.text) or "..."
    # Only something to read: an old second line of chat there taught him to add one.
    detail = reply.detail.strip() if keep_detail and written(reply.detail) else ""
    if len(detail) > HISTORY_DETAIL_CHARS:
        detail = detail[:HISTORY_DETAIL_CHARS] + " [...]"
    text = without_plans(reply.text) or "..."
    return f"{text}\n\n{detail}" if detail else text


def _short(reply_json: str | None, keep_detail: bool = True) -> str | None:
    if not reply_json:
        return None
    try:
        data = json.loads(reply_json)
    except ValueError:
        return reply_json
    detail = data.get("detail") or ""
    if detail and not keep_detail:
        data["detail"] = ""
        return json.dumps(data)
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
