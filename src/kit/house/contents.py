"""The rooms and things in the house, in Kit's memory: one ``house`` item per room
and per exposed thing, rewritten once a day, so recall and the memory page find
"the study lamp" or "what's in the shed". Their states aren't kept: those change by
the minute, and the house tools ask Home Assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kit.house import HOUSE

if TYPE_CHECKING:
    from kit.house.model import House
    from kit.knowledge import Index

KIND_WORDS = {
    "light": "a light",
    "switch": "a switch",
    "fan": "a fan",
    "climate": "heating or air conditioning",
    "cover": "a garage door, blind or curtain",
    "lock": "a lock",
    "scene": "a scene",
    "script": "a script",
    "sensor": "a sensor",
    "binary_sensor": "a sensor",
    "person": "a person",
    "media_player": "a media player",
    "alarm_control_panel": "an alarm",
}


def write_contents(index: Index, house: House) -> int:
    """Replace the house items with what's there now; how many were written."""
    index.delete_source(HOUSE)
    n = 0
    rooms: dict[str, list[str]] = {}
    for e in sorted(house.entities.values(), key=lambda e: e.name):
        kind = KIND_WORDS.get(e.domain, e.domain.replace("_", " "))
        where = f" in the {e.area}" if e.area else ""
        text = f"{e.name}, {kind}{where} (Home Assistant {e.id})."
        meta = {"entity": e.id, "domain": e.domain, "area": e.area}
        index.add(HOUSE, "entity", text, title=e.name, ref=e.id, meta=meta)
        if e.area:
            rooms.setdefault(e.area, []).append(e.name)
        n += 1
    for area in sorted({a.name for a in house.areas.values()}):
        things = rooms.get(area, [])
        listed = ", ".join(things) if things else "nothing Kit may see"
        text = f"The {area}, a room in the house. In it: {listed}."
        index.add(HOUSE, "area", text, title=area, ref=f"area:{area}", meta={"area": area})
        n += 1
    return n
