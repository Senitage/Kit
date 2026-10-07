"""The register of things: one entry per person, vehicle, room, project or piece
of equipment, like a plant's tag register.

Each entry has a name, other names it goes by, and links to where it lives in
each system: the Home Assistant area, the home_app record, the NAS folder, the
MetTools folder, the Obsidian note. When a message mentions a thing, Kit gets
the entry with its links, so it knows where to look without being told.

Entries are items in the knowledge index (source ``things``), so they're found
by words and by meaning like everything else. Kit suggests an entry when it
meets a new name (source ``thing-suggestions``) and Dan confirms or rejects it;
a change makes a new version that supersedes the old one, so history is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kit.knowledge import STOPWORDS, Item
from kit.memory import Memory

THINGS = "things"
SUGGESTED = "thing-suggestions"

THING_KINDS = {
    "person": "someone in Dan's life",
    "pet": "an animal",
    "vehicle": "a car, ute, bike or boat",
    "place": "a room, building, site or property",
    "project": "something being worked on",
    "equipment": "a machine, device or piece of plant",
    "other": "anything else with a name",
}

SYSTEMS = {
    "home_assistant": "Home Assistant (an area, device or entity)",
    "home_app": "home_app (a record, such as a vehicle or trip)",
    "nas": "the Synology NAS (a folder or file)",
    "mettools": "MetTools (a folder or saved work)",
    "obsidian": "Obsidian (a note)",
    "code": "a code project folder",
    "other": "anywhere else",
}
SYSTEM_NAMES = {
    "home_assistant": "Home Assistant",
    "home_app": "home_app",
    "nas": "NAS",
    "mettools": "MetTools",
    "obsidian": "Obsidian",
    "code": "code",
    "other": "other",
}


@dataclass(frozen=True)
class Link:
    system: str
    target: str

    def __str__(self) -> str:
        return f"{SYSTEM_NAMES.get(self.system, self.system)}: {self.target}"


@dataclass
class Thing:
    id: int
    name: str
    kind: str
    aliases: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    about: str = ""
    suggested: bool = False

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]

    def line(self) -> str:
        """The thing in one line, as the model sees it."""
        also = f"; also called {', '.join(self.aliases)}" if self.aliases else ""
        about = f". {self.about}" if self.about else ""
        where = "; ".join(str(link) for link in self.links) or "nowhere recorded yet"
        return f"{self.name} ({self.kind}{also}){about}. Lives in: {where}"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "aliases": self.aliases,
            "links": [{"system": x.system, "target": x.target} for x in self.links],
            "about": self.about,
            "suggested": self.suggested,
            "line": self.line(),
        }


def _clean_links(links) -> list[Link]:
    out: list[Link] = []
    for link in links or []:
        if isinstance(link, Link):
            system, target = link.system, link.target
        else:
            system, target = link.get("system", ""), link.get("target", "")
        system = system if system in SYSTEMS else "other"
        target = str(target).strip()
        if target and Link(system, target) not in out:
            out.append(Link(system, target))
    return out


def _clean_aliases(name: str, aliases) -> list[str]:
    seen = {name.strip().lower()}
    out = []
    for alias in aliases or []:
        alias = str(alias).strip()
        if alias and alias.lower() not in seen:
            seen.add(alias.lower())
            out.append(alias)
    return out


def _from_item(item: Item) -> Thing:
    meta = item.meta or {}
    return Thing(
        id=item.id,
        name=item.title,
        kind=item.kind,
        aliases=list(meta.get("aliases", [])),
        links=_clean_links(meta.get("links", [])),
        about=meta.get("about", ""),
        suggested=item.source == SUGGESTED,
    )


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", text.lower()) is not None


def named_in(name: str, said: str) -> bool:
    """Did the owner name ``name`` in ``said`` (any word of it will do)? A small model
    asked to put a window title it had seen in the register when Dan only said good
    night."""
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) > 2]
    words = [w for w in words if w not in STOPWORDS]
    if not words:  # "Al", "Jo"
        return bool(name.strip()) and _mentions(said, name.strip())
    return any(w in said.lower() for w in words)


class Register:
    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        self.index = memory.index

    def _write(
        self,
        source: str,
        name: str,
        kind: str,
        aliases: list[str],
        links: list[Link],
        about: str,
    ) -> int:
        thing = Thing(0, name.strip(), kind if kind in THING_KINDS else "other")
        thing.aliases = _clean_aliases(thing.name, aliases)
        thing.links = _clean_links(links)
        thing.about = about.strip()
        return self.index.add(
            source,
            thing.kind,
            thing.line(),
            title=thing.name,
            meta={
                "aliases": thing.aliases,
                "links": [{"system": x.system, "target": x.target} for x in thing.links],
                "about": thing.about,
            },
        )

    # Reading

    def get(self, thing_id: int) -> Thing | None:
        item = self.index.get(thing_id)
        if item is None or item.source not in (THINGS, SUGGESTED) or item.superseded_by:
            return None
        return _from_item(item)

    def all(self) -> list[Thing]:
        return [_from_item(i) for i in self.index.items(THINGS)]

    def suggestions(self) -> list[Thing]:
        return [_from_item(i) for i in self.index.items(SUGGESTED)]

    def named(self, name: str, include_suggested: bool = False) -> Thing | None:
        """The thing with this name or alias, ignoring case."""
        wanted = name.strip().lower()
        pool = self.all() + (self.suggestions() if include_suggested else [])
        return next((t for t in pool if wanted in (n.lower() for n in t.names)), None)

    def mentioned_in(self, text: str) -> list[Thing]:
        """Confirmed things whose name or alias appears in ``text`` as whole words."""
        return [t for t in self.all() if any(_mentions(text, n) for n in t.names)]

    def history(self, thing_id: int) -> list[Thing]:
        return [_from_item(i) for i in self.index.history(thing_id)]

    # Writing

    def add(
        self,
        name: str,
        kind: str = "other",
        aliases: list[str] | None = None,
        links: list | None = None,
        about: str = "",
    ) -> int:
        """Add a confirmed thing. A name already in the register is updated instead."""
        existing = self.named(name)
        if existing:
            return self.change(
                existing.id,
                aliases=existing.aliases + list(aliases or []),
                links=existing.links + _clean_links(links),
                about=about or existing.about,
            )
        return self._write(THINGS, name, kind, aliases or [], _clean_links(links), about)

    def suggest(
        self, name: str, kind: str = "other", links: list | None = None, about: str = ""
    ) -> Thing:
        """Note a new name for Dan to confirm. Returns the suggestion (or the
        existing suggestion for that name, with any new link added)."""
        pending = next((t for t in self.suggestions() if t.name.lower() == name.lower()), None)
        if pending:
            new_id = self._replace(pending, links=pending.links + _clean_links(links))
            return self.get(new_id)  # type: ignore[return-value]
        new_id = self._write(SUGGESTED, name, kind, [], _clean_links(links), about)
        return self.get(new_id)  # type: ignore[return-value]

    def change(
        self,
        thing_id: int,
        name: str | None = None,
        kind: str | None = None,
        aliases: list[str] | None = None,
        links: list | None = None,
        about: str | None = None,
    ) -> int:
        """Change a thing; the old version is kept in its history. Returns the new id."""
        thing = self.get(thing_id)
        if thing is None:
            raise KeyError(thing_id)
        return self._replace(thing, name, kind, aliases, links, about)

    def _replace(self, thing, name=None, kind=None, aliases=None, links=None, about=None) -> int:
        new_id = self._write(
            SUGGESTED if thing.suggested else THINGS,
            name if name is not None else thing.name,
            kind if kind is not None else thing.kind,
            aliases if aliases is not None else thing.aliases,
            _clean_links(links) if links is not None else thing.links,
            about if about is not None else thing.about,
        )
        self.index.supersede(thing.id, new_id)
        return new_id

    def set_link(self, thing_id: int, system: str, target: str) -> int:
        """Where a thing lives in one system. A correction ("no, it's in Tax/2023")
        replaces the old link for that system."""
        thing = self.get(thing_id)
        if thing is None:
            raise KeyError(thing_id)
        links = [x for x in thing.links if x.system != system] + _clean_links(
            [{"system": system, "target": target}]
        )
        return self._replace(thing, links=links)

    def confirm(self, thing_id: int) -> int | None:
        """Turn a suggestion into a register entry. Returns the entry's id."""
        thing = self.get(thing_id)
        if thing is None or not thing.suggested:
            return None
        self.index.delete(thing_id)
        return self.add(thing.name, thing.kind, thing.aliases, thing.links, thing.about)

    def reject(self, thing_id: int) -> bool:
        thing = self.get(thing_id)
        return bool(thing and thing.suggested and self.index.delete(thing_id))

    def forget(self, thing_id: int) -> bool:
        thing = self.get(thing_id)
        return bool(thing and self.index.delete(thing_id))
