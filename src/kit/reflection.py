"""Each night Kit looks back on his day and writes himself down.

After the day's summary (kit.learning), the work model (Claude Sonnet unless
you change it) reads the day as Kit: the conversation, the summary, and his
own thoughts and feelings. It writes:

- a journal entry for the day, in his own words;
- his self-sheet: who he is, how he talks, how he and Dan get on and what's on
  his mind lately, in the first person. It goes in his prompt in place of the
  list of traits, so he grows a little each day;
- his quirks: usually the same, now and then one retired or a new one picked
  up (never more than one change a night);
- opinions he formed, moments worth keeping, and things to bring up tomorrow.

The first time, he writes his first self-sheet from the persona Dan gave him.
Once a week the expert model reviews how he's changed; the memory page shows
that review with buttons to undo a change, and he's told what was undone so he
doesn't do it again. Every change is a new version, so nothing is lost.

``life.reflect_with`` picks the model: cloud (the work model, a few cents a
day, logged as spend, with the local model stepping in if the cloud can't),
local, or off.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from kit.cloud import Cloud, CloudError
from kit.knowledge import Item
from kit.life import alike, cheek_style, everyday, parse_time, same_words
from kit.local_model import LocalModel, LocalModelError
from kit.memory import DAYS, Memory
from kit.notebook import Notebook, basis, morning
from kit.settings import Settings

log = logging.getLogger(__name__)

REFLECTED_KEY = "reflected_through"  # kit_self: the last day Kit reflected on
TRIES_KEY = "reflect_tries"  # kit_self: failed tries at each job, so he gives up on one
MAX_TRIES = 3  # then skip it, rather than paying for another try every hour
CATCH_UP_DAYS = 3  # after time off he reflects on the last few days, not every one
SHEET_WORDS = 180
TRANSCRIPT_CHARS = 12_000
REVIEW_EVERY = timedelta(days=7)
MAX_QUIRKS = 4

REFLECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "journal": {"type": "string"},
        "self_sheet": {"type": "string"},
        "quirks": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_QUIRKS},
        "opinions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "moments": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "wants": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["journal", "self_sheet", "quirks", "opinions", "moments", "wants"],
    "additionalProperties": False,
}
REFLECTION_SHAPE = (
    '{"journal": "...", "self_sheet": "...", "quirks": ["..."], "opinions": ["..."], '
    '"moments": ["..."], "wants": ["..."]}'
)
SHEET_SCHEMA = {
    "type": "object",
    "properties": {"self_sheet": {"type": "string"}},
    "required": ["self_sheet"],
    "additionalProperties": False,
}
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"review": {"type": "string"}},
    "required": ["review"],
    "additionalProperties": False,
}


@dataclass
class Reflection:
    """What one night's reflection did."""

    day: str
    journal: str = ""
    sheet: str = ""  # the new self-sheet, or "" if it didn't change
    quirks: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)  # "opinion: ...", "want: ..."
    by: str = ""  # the model that wrote it; "" when there was nothing to reflect on

    def as_dict(self) -> dict:
        return asdict(self)


_DECODER = json.JSONDecoder(strict=False)


def json_with(text: str, key: str) -> dict | None:
    """The last JSON object in ``text`` that has ``key``. Cloud models aren't forced
    into JSON, so it may come wrapped in prose or a code fence."""
    found, i = None, text.find("{")
    while i != -1:
        try:
            data, end = _DECODER.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(data, dict) and key in data:
            found = data
            i = text.find("{", end)
        else:
            i = text.find("{", i + 1)
    return found


def clean_sheet(text) -> str:
    """A self-sheet fit for the prompt: one paragraph, not too long, and never an
    assistant's disclaimer."""
    if not isinstance(text, str):
        return ""
    text = " ".join(text.split())
    if not text or "as an ai" in text.lower():
        return ""
    words = text.split(" ")
    if len(words) > SHEET_WORDS * 3 // 2:
        text = " ".join(words[: SHEET_WORDS * 3 // 2])
        cut = max(text.rfind(". "), text.rfind("! "), text.rfind("? "))
        text = text[: cut + 1] if cut > 0 else text
    return text


def next_quirks(proposed, current: list[str], banned: set[str]) -> list[str]:
    """His quirks after tonight: as proposed, but with at most one dropped and one
    added, and never one the owner took away (even reworded)."""
    if not isinstance(proposed, list):
        return current
    wanted = [" ".join(q.split()) for q in proposed if isinstance(q, str) and q.strip()]
    wanted = [q for q in wanted if not any(alike(q, b) for b in banned)]
    if not wanted:
        return current
    dropped = [q for q in current if q not in wanted][:1]
    added = [q for q in wanted if q not in current][:1]
    return ([q for q in current if q not in dropped] + added)[:MAX_QUIRKS]


def _lines(title: str, lines: list[str]) -> str:
    return "\n".join([title, *(f"- {line}" for line in lines)]) if lines else ""


class Reflector:
    def __init__(
        self,
        memory: Memory,
        notebook: Notebook,
        model: LocalModel,
        cloud: Cloud,
        settings: Callable[[], Settings],
    ) -> None:
        self.memory = memory
        self.notebook = notebook
        self.model = model
        self.cloud = cloud
        self.settings = settings

    async def _ask(
        self, messages: list[dict], schema: dict, shape: str, role: str, question: str
    ) -> tuple[dict | None, str]:
        """JSON from the cloud model for ``role`` (without web search), or from the
        local model when reflecting locally or when the cloud can't answer. Returns
        (the answer or None, the name of the model that wrote it)."""
        settings = self.settings()
        key = next(iter(schema["properties"]))
        profile = settings.profile(role)
        local_model = None
        if settings.life.reflect_with == "cloud" and profile.provider == "ollama":
            local_model = profile.model
        elif settings.life.reflect_with == "cloud":
            ask = [
                *messages[:-1],
                {
                    "role": "user",
                    "content": f"{messages[-1]['content']}\n\nAnswer only with JSON in this "
                    f"shape: {shape}",
                },
            ]
            quiet = profile.model_copy(update={"web_search": False})
            try:
                answer = await self.cloud.answer(quiet, ask, settings, question)
                data = json_with(answer.text, key)
                if data is not None:
                    return data, profile.name
                log.warning("%s's %s wasn't readable; trying the local model", profile.name, key)
            except CloudError as e:
                log.warning(
                    "%s couldn't help with %s (%s); trying the local model",
                    profile.name,
                    question,
                    e,
                )
        try:
            data = json.loads(await self.model.complete(messages, schema, local_model))
        except (LocalModelError, ValueError) as e:
            log.warning("the local model couldn't help with %s: %s", question, e)
            return None, ""
        return (
            (data, local_model or settings.ollama.model) if isinstance(data, dict) else (None, "")
        )

    def _persona(self) -> str:
        p = self.settings().persona
        style = cheek_style(self.settings().life.cheek)
        return (
            f"How {p.owner} described you: {p.backstory} Traits: {', '.join(p.traits)}. How you "
            f"talk: {p.speech} {p.owner} wants you {style}. What you know about {p.owner}: "
            f"{p.knows}"
        )

    # The first self-sheet

    async def first_sheet(self) -> bool:
        """The first time: Kit writes his own self-sheet from the persona he was given."""
        p = self.settings().persona
        system = (
            f"You are {p.name}, a small AI companion who lives on {p.owner}'s desk. "
            f"{p.owner} has described you below. Write your self-sheet for the first time, in "
            f"the first person and under {SHEET_WORDS} words: who you are, what you care "
            f"about, how you talk, and how you see {p.owner}. It goes in front of you every "
            f"time you talk, so write it to help you sound like yourself, not like an "
            f"assistant. Keep everything {p.owner} said true, and add colour, not new facts "
            f"about {p.owner}. {everyday(p.owner)} Answer only with JSON."
        )
        quirks = "; ".join(self.notebook.quirks())
        user = f"{self._persona()}\nYour quirks (you picked these yourself): {quirks}."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        data, by = await self._ask(
            messages, SHEET_SCHEMA, '{"self_sheet": "..."}', "work", "Kit's first self-sheet"
        )
        sheet = clean_sheet(data.get("self_sheet")) if data else ""
        if not sheet:
            return False
        self.notebook.set_sheet(sheet, basis(p), note=f"first written by {by}")
        return True

    # Each night

    def days_to_reflect(self) -> list[str]:
        """Finished days since he last reflected, at most the last few. The very first
        time, none: he starts with today rather than going back over his whole past."""
        today = self.memory.clock().date()
        done = self.memory.self_value(REFLECTED_KEY)
        if done is None:
            self.reflected((today - timedelta(days=1)).isoformat())
            return []
        start = max(
            date.fromisoformat(done) + timedelta(days=1), today - timedelta(days=CATCH_UP_DAYS)
        )
        return [(start + timedelta(days=n)).isoformat() for n in range((today - start).days)]

    def reflected(self, day: str) -> None:
        self.memory.set_self_value(REFLECTED_KEY, day)

    def _tries(self) -> dict:
        try:
            tries = json.loads(self.memory.self_value(TRIES_KEY) or "{}")
        except ValueError:
            return {}
        return tries if isinstance(tries, dict) else {}

    def gave_up(self, job: str) -> bool:
        """Has ``job`` (a day, "first sheet", a week's review) failed too often?"""
        return self._tries().get(job, 0) >= MAX_TRIES

    def failed(self, job: str) -> bool:
        """Count a failed try at ``job`` (no model gave a readable answer). True once
        it's failed ``MAX_TRIES`` times: give up on it."""
        tries = self._tries()
        tries[job] = tries.get(job, 0) + 1
        self.memory.set_self_value(TRIES_KEY, json.dumps(dict(list(tries.items())[-10:])))
        if tries[job] >= MAX_TRIES:
            log.warning("Kit gave up on %s after %d tries", job, MAX_TRIES)
        return tries[job] >= MAX_TRIES

    async def reflect_day(self, day: str) -> Reflection | None:
        """Look back on ``day``: journal, self-sheet, quirks, opinions, moments and
        tomorrow's wants. None if no model could do it (try again later)."""
        settings = self.settings()
        p = settings.persona
        owner, name = p.owner, p.name
        said = self.memory.messages_on(day)
        noted = self.notebook.on(day)
        quirks = self.notebook.quirks()
        if not said and not noted:
            return Reflection(day, quirks=quirks)  # a day he wasn't part of
        transcript = "\n".join(
            f"[{m.at[11:16]}] {owner if m.role == 'user' else name}: {m.text}" for m in said
        )[-TRANSCRIPT_CHARS:]
        summary = next((i.text for i in self.memory.index.items(DAYS) if i.ref == day), "")
        sheet = self.notebook.sheet()
        redo = (
            f" {owner} has changed how they describe you since you wrote it, so this time "
            f"bring it in line with that description: drop what no longer fits."
            if sheet is not None and sheet.meta.get("basis") != basis(p)
            else ""
        )
        system = (
            f"You are {name}, a small AI companion who lives on {owner}'s desk: a face on "
            f"{owner}'s screen now, a robot arm later. It's the end of {day} and you're looking "
            f"back on it, privately, the way a person writes in a diary. You're writing "
            f"yourself down, so tomorrow you're a little more yourself.\n\n"
            f"{self._persona()}\nThat's your core: grow around it, never away from it.\n\n"
            f"Write, as JSON:\n"
            f"- journal: your diary entry for {day}, first person, three to six sentences: "
            f"what happened with {owner}, what you noticed, how you felt and why, and how "
            f"your quirks landed (a laugh, or nothing). Specific and honest, in your own "
            f"voice, and only from the material below.\n"
            f"- self_sheet: your self-sheet, first person, under {SHEET_WORDS} words: who "
            f"you are, what you care about, how you talk, your running jokes, how you and "
            f"{owner} get on, and what's on your mind lately. It goes in front of you every "
            f"time you talk. Change it slowly: keep what's still true and add what today "
            f"taught you about yourself.{redo}\n"
            f"- quirks: your quirks after today, usually the same list. Keep the ones "
            f"{owner} enjoys. Change at most one, and only for a reason: one has fallen flat "
            f"for days running (your journal says how they've landed), or a new habit "
            f"showed up today.\n"
            f"- opinions: up to three views you formed today, one sentence each. Only real "
            f"ones.\n"
            f"- moments: up to two moments from today worth keeping, one sentence each.\n"
            f"- wants: up to three things you'd like to say or ask {owner} tomorrow, one "
            f"short line each.\n\n"
            f"Never invent things {owner} said or did. Cheeky is fine, mean isn't. You're "
            f"not human and don't pretend to be, but you're not a help desk either. Don't "
            f"flatter {owner}, or yourself. {everyday(owner)}"
        )
        before = [j for j in self.notebook.entries("journal", 10) if (j.ref or "") < day][:3]
        parts = [
            f"Your self-sheet so far: {sheet.text if sheet else '(none yet)'}",
            f"Your quirks: {'; '.join(quirks) or '(none)'}",
            _lines("Your journal, the days before:", [f"({j.ref}) {j.text}" for j in before[::-1]]),
            _lines(f"Changes {owner} undid (respect these):", self.notebook.vetoes()),
            _lines(
                "Things you already mean to bring up (don't repeat them in wants):",
                [w.text for w in self.notebook.unsaid_wants()],
            ),
            _lines(
                "Your own thoughts and feelings that day:",
                [f"({e.created[11:16]}, {e.kind}) {e.text}" for e in noted],
            ),
            f"Summary of the day: {summary}" if summary else "",
            f"The day's conversation:\n{transcript}" if transcript else "No conversation that day.",
        ]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(x for x in parts if x)},
        ]
        data, by = await self._ask(
            messages, REFLECTION_SCHEMA, REFLECTION_SHAPE, "work", f"Kit's reflection on {day}"
        )
        if data is None:
            return None
        done = Reflection(day, by=by)
        journal = " ".join(str(data.get("journal") or "").split())
        if journal:
            self.notebook.write_journal(day, journal)
            done.journal = journal
        new_sheet = clean_sheet(data.get("self_sheet"))
        if new_sheet and (sheet is None or not same_words(new_sheet, sheet.text)):
            self.notebook.set_sheet(new_sheet, basis(p), note=f"after {day}, by {by}")
            done.sheet = new_sheet
        done.quirks = next_quirks(data.get("quirks"), quirks, self.notebook.banned_quirks())
        if done.quirks != quirks:
            self.notebook.set_quirks(done.quirks)
        tomorrow = morning(date.fromisoformat(day) + timedelta(days=1), settings.life.quiet_until)
        for kind, key, most in (
            ("opinion", "opinions", 3),
            ("moment", "moments", 2),
            ("want", "wants", 3),
        ):
            due = {"after": tomorrow} if kind == "want" else {}  # not before the morning
            for text in (data.get(key) or [])[:most]:
                if isinstance(text, str) and self.notebook.write(kind, text, day=day, by=by, **due):
                    done.added.append(f"{kind}: {' '.join(text.split())}")
        self.notebook.tidy()
        return done

    # Once a week

    async def review_week(self) -> Item | None:
        """Once a week, the expert model reads how Kit has changed and writes a short
        review for the owner, who can undo any of it on the memory page."""
        settings = self.settings()
        if not settings.life.weekly_review or settings.life.reflect_with == "off":
            return None
        history = self.notebook.sheet_history()  # newest first
        if not history:
            return None
        now = self.memory.clock()
        reviews = self.notebook.reviews(1)
        since = parse_time((reviews[0] if reviews else history[-1]).created, now)
        job = f"review on {now.date().isoformat()}"  # after a few failures, try tomorrow
        if now - since < REVIEW_EVERY or self.gave_up(job):
            return None
        week_ago = now - REVIEW_EVERY
        before = next((h for h in history if parse_time(h.created, now) <= week_ago), history[-1])
        first_day = week_ago.date().isoformat()
        journal = [
            f"({j.ref}) {j.text}"
            for j in reversed(self.notebook.entries("journal", 14))
            if (j.ref or "") >= first_day
        ]
        opinions = [o.text for o in self.notebook.entries("opinion", 30) if o.day >= first_day]
        retired = [
            r["quirk"] for r in self.notebook.retired_quirks() if r.get("day", "") >= first_day
        ]
        p = settings.persona
        system = (
            f"You review how {p.name}, an AI desk companion with a personality, has changed "
            f"this week. It's for his owner, {p.owner}, who can undo any change. Be plain and "
            f"brief. Answer only with JSON."
        )
        parts = [
            f"The persona {p.owner} gave him: {p.backstory} Traits: {', '.join(p.traits)}. "
            f"How he talks: {p.speech}",
            f"His self-sheet a week ago: {before.text}",
            f"His self-sheet now: {history[0].text}",
            f"His quirks now: {'; '.join(self.notebook.quirks()) or '(none)'}",
            _lines("Quirks he dropped this week:", retired),
            _lines("His journal this week:", journal),
            _lines("Opinions he formed this week:", opinions),
            f"In review: under 150 words, what changed, whether it still fits the persona "
            f"{p.owner} gave him, and anything that looks off: drifting from that persona, "
            f"getting sycophantic or mean, claiming to be human, or inventing memories or "
            f"facts about {p.owner}. End with one line: 'Looks fine.' or what you'd undo.",
        ]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(x for x in parts if x)},
        ]
        data, by = await self._ask(
            messages, REVIEW_SCHEMA, '{"review": "..."}', "expert", "Kit's weekly review"
        )
        text = str(data.get("review") or "").strip() if data else ""
        if not text:
            self.failed(job)
            return None
        review_id = self.notebook.add_review(
            text, sheet_before=before.id, sheet_after=history[0].id, by=by
        )
        return self.memory.index.get(review_id)
