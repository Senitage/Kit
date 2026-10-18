"""Which packs a message loads. Every pack's tools in every request would cost
tokens and muddle the model, so each turn loads only the packs it needs, decided
before any model is asked, in this order: packs marked ``always`` (core); a pack
with one of its ``words`` in the message as a whole word; a pack whose ``systems``
include where a register thing named in the message lives ("the Riverbend folder"
is on the NAS: the files pack); then, while there's room under ``tools.max_packs``,
packs whose example ``questions`` are close in meaning to the message
(``tools.match_similarity``), closest first. ``tools.packs`` limits which packs may
ever load. The result holds for the whole turn: a tool's result never loads a new
pack mid-turn. See docs/2 How Kit Works/Tools and Packs.md#Which packs load."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kit.recall import Recall
    from kit.settings import Settings
    from kit.things import Register
    from kit.tools import Registry

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")


def _plain(text: str) -> str:
    """Lower case with curly apostrophes straightened, for whole-word matching."""
    return text.lower().replace("’", "'").replace("‘", "'")


def has_words(text: str, words: list[str]) -> bool:
    """Whether any of ``words`` (each a word or a few) is in ``text`` as whole words."""
    plain = " " + " ".join(_WORD.findall(_plain(text))) + " "
    return any(
        f" {' '.join(_WORD.findall(_plain(w)))} " in plain for w in words if _WORD.search(_plain(w))
    )


def allowed(registry: Registry, settings: Settings) -> list[str]:
    """The packs that may load at all: ``tools.packs``, or every pack for ``all``."""
    wanted = settings.tools.packs
    if "all" in wanted:
        return registry.names()
    return [name for name in registry.names() if name in wanted]


async def match(
    text: str,
    registry: Registry,
    recall: Recall | None,
    register: Register | None,
    settings: Settings,
) -> list[str]:
    """The names of the packs to load for ``text``, core (the ``always`` packs) first."""
    limit = settings.tools.max_packs
    names = allowed(registry, settings)
    packs = [registry.packs[n] for n in names]
    loaded = [p.name for p in packs if p.always]
    # Words and register links load a pack whatever the limit: they're near certain.
    for pack in packs:
        if pack.name not in loaded and pack.words and has_words(text, pack.words):
            loaded.append(pack.name)
    if register is not None and any(p.systems for p in packs if p.name not in loaded):
        systems = {link.system for thing in register.mentioned_in(text) for link in thing.links}
        for pack in packs:
            if pack.name not in loaded and systems & set(pack.systems):
                loaded.append(pack.name)
    # Meaning fills what room is left, closest first.
    rest = [p for p in packs if p.name not in loaded and p.questions]
    if recall is not None and rest and len(loaded) < limit:
        scored = []
        for pack in rest:
            close = await recall.closeness(text, pack.questions)
            if close is not None and close >= settings.tools.match_similarity:
                scored.append((close, pack.name))
        for _, name in sorted(scored, reverse=True)[: limit - len(loaded)]:
            loaded.append(name)
    first = [n for n in loaded if registry.packs[n].always]
    return first + sorted(n for n in loaded if n not in first)
