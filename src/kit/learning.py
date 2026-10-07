"""How Kit learns: adding facts without duplicating or contradicting them, and
turning each finished day into a summary plus facts.

A memory that only ever appends fills up with near-copies and stale facts
("the pump bug is open" next to "the pump bug is fixed"). So each new fact is
compared with the closest existing ones, and the local model decides whether
it's new, already known, or an update. Updates supersede the old fact, which
stays in its history.
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
                },
                "required": ["kind", "text"],
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
        self, text: str, kind: str = "other", owner: str = "Dan", source_ref: str | None = None
    ) -> Learned:
        text = " ".join(text.split())
        await self.recall.index_pending()
        candidates = [h.item for h in await self.recall.search(text, [FACTS], CANDIDATES)]
        decision = "new", 0, text
        if candidates:
            decision = await self._decide(text, candidates, owner)
        what, which, wording = decision
        if what == "same" and 1 <= which <= len(candidates):
            learned = Learned("same", candidates[which - 1].id, candidates[which - 1].text)
        elif what == "update" and 1 <= which <= len(candidates):
            old = candidates[which - 1]
            keep_kind = old.kind if kind == "other" else kind
            new_id = self.memory.replace_fact(old.id, wording or text, keep_kind, source_ref)
            learned = Learned("update", new_id, wording or text, replaced=old.text)
        else:
            learned = Learned("new", self.memory.add_fact(text, kind, source_ref=source_ref), text)
        await self.recall.index_pending()
        return learned

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
        """Summarise one finished day and learn its facts. False if the model failed."""
        transcript = "\n".join(
            f"[{m.at[11:16]}] {owner if m.role == 'user' else name}: {m.text}"
            for m in self.memory.messages_on(day)
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
                    f"- facts: up to 15 lasting facts worth remembering about {owner}, each one "
                    f"sentence that makes sense on its own months from now, with dates written "
                    f"out (not 'tomorrow'). Skip small talk and anything only true today. "
                    f"Kinds: {kinds}."
                ),
            },
            {"role": "user", "content": f"Conversation on {day}:\n{transcript[-24000:]}"},
        ]
        try:
            raw = json.loads(await self.model.complete(messages, DAY_SCHEMA))
            summary = str(raw["summary"])
            facts = [(str(f["kind"]), str(f["text"])) for f in raw["facts"]]
        except (LocalModelError, ValueError, KeyError, TypeError):
            return False
        for kind, text in facts:
            if text.strip():
                await self.learn(text, kind, owner, source_ref=day)
        self.memory.save_day(day, summary)
        await self.recall.index_pending()
        return True
