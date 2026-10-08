"""How Kit learns: adding facts without duplicating or contradicting them, and
turning each finished day into a summary plus facts.

A memory that only ever appends fills up with near-copies and stale facts
("the pump bug is open" next to "the pump bug is fixed"). So each new fact is
compared with the closest existing ones, and the local model decides whether
it's new, already known, or an update. Updates supersede the old fact, which
stays in its history. Who someone is to Dan is caught in his own words too
("Emma's my cousin"), and a changed relation always updates the old fact, so a
small model can't leave Emma both his sister and his cousin.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from kit.knowledge import STOPWORDS
from kit.local_model import LocalModel, LocalModelError
from kit.memory import FACT_KINDS, FACTS, Memory
from kit.recall import Recall

CANDIDATES = 5
RELATIONS = (
    r"partner|wife|husband|girlfriend|boyfriend|fianc[e\u00e9]e?|mum|mom|mother|dad|father|"
    r"step-?(?:mum|dad|sister|brother)|sister|brother|(?:sister|brother)-in-law|cousin|"
    r"aunt(?:ie)?|uncle|nan(?:a)?|grandma|grandmother|pop|grandad|grandpa|grandfather|son|"
    r"daughter|niece|nephew|best (?:mate|friend)|friend|mate|boss|neighbou?r|housemate|"
    r"flatmate|cat|dog|kitten|puppy"
)
# Who someone is to Dan, as he says it: "Emma's my cousin", "my mate Steve", "the
# cat's called Milo". A name is capitalised unless it's plainly a name ("called milo").
_SAID_RELATION = [
    re.compile(
        rf"\b(?P<name>[A-Za-z][a-z]+)(?:'s|\u2019s| is) (?:actually |really )?(?:my|our) "
        rf"(?P<rel>{RELATIONS})\b(?!['\u2019]s)",  # not "Steve is my mate's dad"
        re.I,
    ),
    re.compile(
        rf"\b(?:[Mm]y|[Oo]ur|[Tt]he) (?P<rel>{RELATIONS})(?:'s|\u2019s| is)? "
        rf"(?:(?i:name is|called|named) (?P<lower>[A-Za-z][a-z]+)|(?P<name>[A-Z][a-z]+))\b"
    ),
]
NOT_NAMES = frozenset(
    """she he it that this there who what which one mine they here i you we kit
    also actually really just not still now""".split()
)

# Words a fact may add without Dan having said them: dates and times, and "Dan said".
DATE_WORDS = frozenset(
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday "
    "friday saturday sunday today yesterday tomorrow tonight morning afternoon evening "
    "now currently recently still anymore".split()
)
SAYING = frozenset("said says told tells mentioned mentions remember remembers noted".split())


def _gist(text: str, owner: str) -> set[str]:
    """The words that carry ``text``'s meaning, cut to five letters so "drives" and
    "drive" match."""
    skip = STOPWORDS | DATE_WORDS | SAYING | {owner.lower(), f"{owner.lower()}s"}
    words = re.findall(r"[a-z0-9]+", text.lower().replace("'", "").replace("\u2019", ""))
    return {w[:5] for w in words if len(w) > 2 and not w.isdigit() and w not in skip}


def relations_in(text: str, owner: str) -> list[str]:
    """Who someone is to the owner, in their own words, as facts: "Emma's my cousin"
    is "Emma is Dan's cousin." """
    found = []
    for pattern in _SAID_RELATION:
        for m in pattern.finditer(text):
            name = m.group("name") or m.groupdict().get("lower") or ""
            if not name or name.lower() in NOT_NAMES or name.lower() in DATE_WORDS:
                continue
            if re.fullmatch(RELATIONS, name, re.I):  # "Dad's my best mate"
                continue
            if name.lower() in STOPWORDS or name.lower() == owner.lower():
                continue
            fact = f"{name.capitalize()} is {owner}'s {m.group('rel').lower()}."
            if fact not in found:
                found.append(fact)
    return found


def _relation_of(name: str, text: str, owner: str) -> re.Match | None:
    """Where ``text`` says who ``name`` is to the owner ("Emma, Dan's sister", "Dan's
    sister Emma", "Emma is Dan's sister"): the relation's place, or None. Only the
    owner's: in "Sarah's husband Tom", Tom is nobody to Dan."""
    whose = rf"{re.escape(owner)}['\u2019]s"
    return re.search(
        rf"\b{re.escape(name)}(?:,|\s+is|\s+\()?\s*{whose}\s+(?P<rel>{RELATIONS})\b"
        rf"|{whose}\s+(?P<rel2>{RELATIONS}),?\s+{re.escape(name)}\b",
        text,
        re.I,
    )


def relation_change(fact: str, candidates: list, owner: str) -> tuple[object, str] | None:
    """ "Emma is Dan's cousin" when Kit knew "Emma, Dan's sister, ...": the same
    person with a different relation. Returns (the old fact, it with the relation
    put right), keeping the rest of what Kit knew (her birthday)."""
    for name in set(re.findall(r"\b[A-Z][a-z]+\b", fact)) - {owner}:
        new = _relation_of(name, fact, owner)
        if new is None:
            continue
        rel = (new.group("rel") or new.group("rel2")).lower()
        for old in candidates:
            m = _relation_of(name, old.text, owner)
            if m is None:
                continue
            group = "rel" if m.group("rel") else "rel2"
            if m.group(group).lower() == rel:
                return None  # nothing changed
            fixed = old.text[: m.start(group)] + rel + old.text[m.end(group) :]
            return old, fixed
    return None


def said_so(fact: str, said: list[str], owner: str) -> bool:
    """Did the owner actually say ``fact`` (in ``said``, their latest messages)? At
    least half the words that carry its meaning must be there, so Kit can't keep
    his own lines, jokes or guesses as facts about them."""
    gist = _gist(fact, owner)
    heard = set().union(*(_gist(s, owner) for s in said)) if said else set()
    return bool(gist) and 2 * len(gist & heard) >= len(gist)


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["new", "same", "update"]},
        "which": {"type": "integer", "minimum": 0, "maximum": CANDIDATES},
        "fact": {"type": "string"},
    },
    "required": ["decision", "which", "fact"],
    "additionalProperties": False,
}

DAY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "facts": {
            "type": "array",
            "maxItems": 15,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(FACT_KINDS)},
                    "text": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["kind", "text", "importance"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "facts"],
    "additionalProperties": False,
}


@dataclass
class Learned:
    decision: Literal["new", "same", "update"]
    item_id: int
    text: str
    replaced: str | None = None


class Learner:
    def __init__(self, memory: Memory, recall: Recall, model: LocalModel) -> None:
        self.memory = memory
        self.recall = recall
        self.model = model

    async def learn(
        self,
        text: str,
        kind: str = "other",
        owner: str = "Dan",
        source_ref: str | None = None,
        importance: float | None = None,
        private: bool = False,
    ) -> Learned:
        """Keep ``text`` as a fact: new, the same as one Kit has, or an update to one.
        ``private`` when it came from what Dan kept local (kit.memory.KEEP_LOCAL)."""
        text = " ".join(text.split())
        await self.recall.index_pending()
        candidates = [h.item for h in await self.recall.search(text, [FACTS], CANDIDATES)]
        decision = "new", 0, text
        if candidates:
            decision = await self._decide(text, candidates, owner)
        what, which, wording = decision
        changed = relation_change(text, candidates + self._naming(text, candidates, owner), owner)
        if changed is not None:  # the same person, a different relation: always an update
            old, fixed = changed
            if old not in candidates:
                candidates.append(old)
            what, which, wording = "update", candidates.index(old) + 1, fixed
        lasting = 1 <= which <= len(candidates) and candidates[which - 1].kind != "now"
        if what == "update" and kind == "now" and lasting:
            what = "new"  # "been sleeping badly" fades; what Kit knew for good stays
        if what == "same" and 1 <= which <= len(candidates):
            learned = Learned("same", candidates[which - 1].id, candidates[which - 1].text)
        elif what == "update" and 1 <= which <= len(candidates):
            old = candidates[which - 1]
            keep_kind = old.kind if kind == "other" else kind
            new_id = self.memory.replace_fact(
                old.id, wording or text, keep_kind, source_ref, private=private
            )
            learned = Learned("update", new_id, wording or text, replaced=old.text)
        else:
            new_id = self.memory.add_fact(
                text, kind, source_ref=source_ref, importance=importance, private=private
            )
            learned = Learned("new", new_id, text)
        await self.recall.index_pending()
        return learned

    def _naming(self, text: str, candidates: list, owner: str) -> list:
        """When ``text`` says who someone is to the owner, the facts naming them that
        the search missed, so "Emma is Dan's cousin" finds "Emma, Dan's sister"
        however little else they share."""
        names = {
            n
            for n in set(re.findall(r"\b[A-Z][a-z]+\b", text)) - {owner}
            if _relation_of(n, text, owner)
        }
        if not names:
            return []
        seen = {c.id for c in candidates}
        return [
            f
            for f in self.memory.facts()
            if f.id not in seen and any(re.search(rf"\b{n}\b", f.text) for n in names)
        ]

    async def _decide(self, text: str, candidates, owner: str) -> tuple[str, int, str]:
        listing = "\n".join(f"{n}. ({c.day}) {c.text}" for n, c in enumerate(candidates, start=1))
        messages = [
            {
                "role": "system",
                "content": (
                    f"You maintain a memory of facts about {owner}. Compare the new information "
                    "with the existing facts and answer as JSON.\n"
                    "- same: an existing fact already says this. which = its number.\n"
                    "- update: the new information changes, corrects or adds detail to existing "
                    "fact number `which`. fact = one sentence combining both, as it is now.\n"
                    "- new: none of them is about the same thing. which = 0, fact = the new "
                    "information as one clear sentence that makes sense on its own."
                ),
            },
            {"role": "user", "content": f"Existing facts:\n{listing}\n\nNew information: {text}"},
        ]
        try:
            raw = json.loads(await self.model.complete(messages, DECISION_SCHEMA))
            return raw["decision"], int(raw["which"]), str(raw["fact"]).strip()
        except (LocalModelError, ValueError, KeyError, TypeError):
            return "new", 0, text

    async def summarise_day(self, day: str, owner: str, name: str) -> bool:
        """Summarise one finished day and learn its facts. False if the model failed.
        On a day Dan kept something local, the summary and facts are private."""
        said = self.memory.messages_on(day)
        private = len(self.memory.shared(said)) < len(said)
        transcript = "\n".join(
            f"[{m.at[11:16]}] {owner if m.role == 'user' else name}: {m.text}" for m in said
        )
        kinds = "; ".join(f"{k}: {v}" for k, v in FACT_KINDS.items())
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are {name}'s memory. Read the day's conversation between {owner} and "
                    f"{name} and answer as JSON with:\n"
                    f"- summary: a short paragraph of what happened and was discussed, with "
                    f"names of projects, files and people, so it can be found later.\n"
                    f"- facts: up to 15 facts worth remembering about {owner}, each one "
                    f"sentence that makes sense on its own months from now, with dates written "
                    f"out (not 'tomorrow'). Skip small talk and anything only true today. How "
                    f"{owner} has been lately (flat out, crook, a visitor staying) is kind "
                    f"'now', kept for two weeks. Kinds: {kinds}. importance: 1 (trivia) to 5 "
                    f"(a big thing in {owner}'s life, or someone close)."
                ),
            },
            {"role": "user", "content": f"Conversation on {day}:\n{transcript[-24000:]}"},
        ]
        try:
            raw = json.loads(await self.model.complete(messages, DAY_SCHEMA))
            summary = str(raw["summary"])
            facts = [
                (str(f["kind"]), str(f["text"]), _importance(f.get("importance")))
                for f in raw["facts"]
            ]
        except (LocalModelError, ValueError, KeyError, TypeError, AttributeError):
            return False
        for kind, text, importance in facts:
            if text.strip():
                await self.learn(
                    text, kind, owner, source_ref=day, importance=importance, private=private
                )
        self.memory.save_day(day, summary, private=private)
        await self.recall.index_pending()
        return True


def _importance(value) -> float | None:
    """The summary's 1 to 5 as 0.2 to 1, or None if it didn't say."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return max(1, min(5, int(value))) / 5
