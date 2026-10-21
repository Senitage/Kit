"""What Kit notices in the house and may mention: someone getting home or leaving,
a door or the garage opening after dark, a light left on for hours
(``house.long_on_minutes``). Only things in ``house.notice`` count for the first
three. Each becomes ``Life.on_house``: his curiosity, a thought, and a life event;
the life loop's usual manners decide whether he says anything."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from kit.house.model import Entity, House

if TYPE_CHECKING:
    from kit.life import Life
    from kit.settings import Settings

OPENED = {"on", "open", "opening", "unlocked"}
ON = {"on"}


def after_dark(when: datetime) -> bool:
    """Evening and night, as Kit's day parts have it (17:00 to 06:00)."""
    return when.hour >= 17 or when.hour < 6


def _iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


class Watcher:
    def __init__(
        self,
        house: House,
        life: Life,
        settings: Callable[[], Settings],
        clock: Callable[[], datetime],
    ) -> None:
        self.house = house
        self.life = life
        self.settings = settings
        self.clock = clock
        self.told_long_on: set[str] = set()  # lights already mentioned this time they're on
        house.on_change(self.changed)

    def _watched(self, entity_id: str) -> bool:
        return any(fnmatch.fnmatch(entity_id, glob) for glob in self.settings().house.notice)

    def changed(self, old: Entity | None, new: Entity) -> None:
        if old is not None and old.state == new.state:
            return
        if new.state not in ON:
            self.told_long_on.discard(new.id)
        if not self._watched(new.id):
            return
        now = self.clock()
        what = ""
        if new.domain == "person":
            if new.state == "home" and (old is None or old.state != "home"):
                what = f"{new.name} just got home"
            elif old is not None and old.state == "home":
                what = f"{new.name} just left home"
        elif new.state in OPENED and (old is None or old.state not in OPENED):
            if after_dark(now):
                what = f"the {new.name} just opened, after dark"
        if what:
            self.life.on_house(what, new.id)

    def tick(self) -> None:
        """Lights and switches left on: once each time they're on too long."""
        minutes = self.settings().house.long_on_minutes
        if minutes <= 0:
            return
        now = self.clock()
        for e in self.house.entities.values():
            if (
                e.domain not in ("light", "switch")
                or e.state not in ON
                or e.id in self.told_long_on
            ):
                continue
            since = _iso(e.changed)
            if since is None:
                continue
            if since.tzinfo is not None and now.tzinfo is None:
                since = since.astimezone().replace(tzinfo=None)
            elif since.tzinfo is None and now.tzinfo is not None:
                since = since.replace(tzinfo=now.tzinfo)
            on_for = now - since
            if on_for >= timedelta(minutes=minutes):
                self.told_long_on.add(e.id)
                hours = on_for.total_seconds() / 3600
                where = f" in the {e.area}" if e.area else ""
                self.life.on_house(f"the {e.name}{where} has been on for {hours:.0f} hours", e.id)
