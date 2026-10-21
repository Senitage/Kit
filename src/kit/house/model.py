"""The rooms and things in the house, as Kit's Home Assistant user may see them.

Only entities Home Assistant exposes to Assist are kept: the rest don't exist as
far as Kit knows, so he can't see or switch them. ``House.refresh`` reads them all
every ``house.refresh_minutes``; ``state_changed`` events keep the states current in
between. ``find`` turns words ("the study lamp", "the aircon", "the shed lights")
into things, by name, room, kind and the register's Home Assistant links."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from kit.house.client import HomeAssistant, HouseError

if TYPE_CHECKING:
    from kit.things import Register

log = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")
# Words that say nothing about which thing is meant.
FILLER = {
    "a", "an", "the", "in", "on", "off", "of", "to", "my", "our", "is", "it", "turn",
    "switch", "set", "please", "what", "whats", "s", "are", "and", "up", "down", "can",
    "you", "kit", "at", "with", "all", "now", "open", "close", "lock", "unlock",
}  # fmt: skip
# Words that name a kind of thing (a Home Assistant domain).
KINDS = {
    "light": "light", "lights": "light", "lamp": "light", "lamps": "light",
    "fan": "fan", "fans": "fan", "plug": "switch", "switch": "switch",
    "ac": "climate", "aircon": "climate", "air": "climate", "heater": "climate",
    "heating": "climate", "thermostat": "climate", "heatpump": "climate",
    "lock": "lock", "garage": "cover", "blind": "cover", "blinds": "cover",
    "curtains": "cover", "door": "binary_sensor", "scene": "scene", "alarm": "alarm_control_panel",
}  # fmt: skip
USEFUL = (  # the attributes worth telling: the rest is Home Assistant's own bookkeeping
    "brightness", "color_name", "current_temperature", "temperature", "target_temp_low",
    "target_temp_high", "hvac_action", "fan_mode", "preset_mode", "current_position",
    "battery_level", "unit_of_measurement", "device_class",
)  # fmt: skip


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("'", ""))


@dataclass(frozen=True)
class Area:
    id: str
    name: str


@dataclass(frozen=True)
class Entity:
    id: str  # light.study_lamp
    name: str
    area: str = ""  # the room's name
    state: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    changed: str = ""  # when the state last changed (ISO)

    @property
    def domain(self) -> str:
        return self.id.split(".", 1)[0]

    def line(self) -> str:
        """One line for a model: name, room, id and state, with what matters."""
        where = f" in the {self.area}" if self.area else ""
        bits = [f"{self.name}{where} ({self.id}): {self.state or 'unknown'}"]
        a = self.attributes
        if self.domain == "light" and isinstance(a.get("brightness"), int | float):
            bits.append(f"brightness {round(a['brightness'] / 255 * 100)}%")
        if a.get("current_temperature") is not None:
            bits.append(f"room {a['current_temperature']}°")
        if a.get("temperature") is not None and self.domain == "climate":
            bits.append(f"set to {a['temperature']}°")
        if a.get("hvac_action"):
            bits.append(str(a["hvac_action"]))
        if self.domain == "sensor" and a.get("unit_of_measurement"):
            bits[0] += f" {a['unit_of_measurement']}"
        if a.get("current_position") is not None:
            bits.append(f"{a['current_position']}% open")
        if a.get("battery_level") is not None:
            bits.append(f"battery {a['battery_level']}%")
        return ", ".join(bits)


class House:
    """What Kit knows of the house: kept in memory, read from Home Assistant."""

    def __init__(self, client: HomeAssistant, clock: Callable[[], datetime]) -> None:
        self.client = client
        self.clock = clock
        self.entities: dict[str, Entity] = {}
        self.areas: dict[str, Area] = {}
        self.refreshed: datetime | None = None
        self.is_admin: bool | None = None
        self.user = ""
        self._on_change: list[Callable[[Entity | None, Entity], None]] = []
        client.subscribe(self._changed)

    @property
    def reachable(self) -> bool:
        return self.client.connected

    def on_change(self, callback: Callable[[Entity | None, Entity], None]) -> None:
        """``callback(old, new)`` when an exposed thing's state changes."""
        self._on_change.append(callback)

    async def refresh(self) -> int:
        """Re-read the rooms and the exposed things; how many there are."""
        states = await self.client.states()
        areas = await self.client.areas()
        registry = await self.client.entities()
        try:
            devices = await self.client.call("config/device_registry/list") or []
        except HouseError:
            devices = []
        exposed = await self.client.exposed(registry)
        try:
            user = await self.client.current_user()
            self.is_admin, self.user = bool(user.get("is_admin")), str(user.get("name", ""))
        except HouseError:
            pass
        self.areas = {a["area_id"]: Area(a["area_id"], a.get("name", a["area_id"])) for a in areas}
        device_area = {d["id"]: d.get("area_id") for d in devices if d.get("id")}
        by_id = {e["entity_id"]: e for e in registry if e.get("entity_id")}
        found = {}
        for s in states:
            entity_id = s.get("entity_id", "")
            if entity_id not in exposed:
                continue
            reg = by_id.get(entity_id, {})
            area_id = reg.get("area_id") or device_area.get(reg.get("device_id"))
            area = self.areas.get(area_id) if area_id else None
            attributes = s.get("attributes") or {}
            name = attributes.get("friendly_name") or reg.get("name") or entity_id
            found[entity_id] = Entity(
                entity_id,
                str(name),
                area.name if area else "",
                str(s.get("state", "")),
                {k: v for k, v in attributes.items() if k in USEFUL},
                str(s.get("last_changed", "")),
            )
        self.entities = found
        self.refreshed = self.clock()
        return len(found)

    def _changed(self, data: dict) -> None:
        entity_id = data.get("entity_id", "")
        old = self.entities.get(entity_id)
        new_state = data.get("new_state")
        if old is None or not new_state:
            return  # not exposed (or gone): Kit doesn't know it
        attributes = new_state.get("attributes") or {}
        new = replace(
            old,
            state=str(new_state.get("state", "")),
            attributes={k: v for k, v in attributes.items() if k in USEFUL},
            changed=str(new_state.get("last_changed", "")),
        )
        self.entities[entity_id] = new
        for callback in list(self._on_change):
            try:
                callback(old, new)
            except Exception:
                log.exception("a house watcher failed")

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id.strip().lower())

    def find(
        self, text: str, register: Register | None = None, domains: tuple[str, ...] = ()
    ) -> list[Entity]:
        """The exposed things ``text`` means, best first: an id, a name, a room, a
        kind ("lamp", "aircon") or a register thing linked to Home Assistant.
        ``domains`` keeps only those kinds."""
        pool = [e for e in self.entities.values() if not domains or e.domain in domains]
        exact = self.get(text)
        if exact is not None and exact in pool:
            return [exact]
        said = [w for w in words(text) if w not in FILLER]
        kinds = {KINDS[w] for w in words(text) if w in KINDS}
        linked: set[str] = set()
        rooms: set[str] = set()
        if register is not None:
            for thing in register.mentioned_in(text):
                for link in thing.links:
                    if link.system != "home_assistant":
                        continue
                    target = link.target.strip()
                    if target.lower().startswith("area:"):
                        rooms.add(target.split(":", 1)[1].strip().lower())
                    else:
                        linked.add(target.lower())
        scored = []
        for e in pool:
            name, area = set(words(e.name)) - FILLER, set(words(e.area))
            hits = len(name & set(said))
            score = 2 * hits
            if area and area <= set(said):
                score += 3
            if e.area.lower() in rooms or e.id in linked:
                score += 5
            if kinds and e.domain in kinds:
                score += 1
            elif kinds and e.id not in linked:
                if not (name & set(said)) - area:
                    continue  # "the lamp" never means the kettle in the same room
                score -= 2
            if score:
                scored.append((score, e))
        if not scored:
            return []
        scored.sort(key=lambda se: (-se[0], se[1].name))
        best = scored[0][0]
        return [e for s, e in scored if s >= best - 1]
