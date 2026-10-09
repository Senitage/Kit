"""What Kit does with himself while Dan's out (``life.alone_thoughts_per_hour``).

Away from the desk for a few minutes and Kit isn't asleep yet, so he finds
something to do, the way a pet finds a sunny spot: he watches the weather,
rereads yesterday's journal, thinks about someone or something in the register,
or listens to whatever the PC is playing (only when the desk app's tray switch
shares it). Each pastime feeds one of his drives, so a bored Kit reaches for
the weather or the music and a Kit missing Dan rereads his journal. One lasts
20 to 40 minutes, then rests for a day or more, so the next absence isn't the
same again. The weather is looked up once an absence at most.

What he does is true: the desk face shows it ("watching the rain"), his private
thoughts while alone are about what he really found, and when Dan's back he can
say what he got up to without making anything up.

The readers are passed in (kit.brain wires the forecast, the notebook, the
register and the desk app's report), so tests use fakes.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

log = logging.getLogger(__name__)


class SelfStore(Protocol):
    """Where Kit keeps small things about himself (kit.memory.Memory)."""

    def self_value(self, key: str) -> str | None: ...

    def set_self_value(self, key: str, value: str) -> None: ...


def parse_time(text: str, like: datetime) -> datetime:
    """A saved time, comparable with ``like`` (kit.life.parse_time, which imports this)."""
    when = datetime.fromisoformat(text)
    if (when.tzinfo is None) != (like.tzinfo is None):
        when = when.replace(tzinfo=like.tzinfo)
    return when


PASTIMES_KEY = "pastimes"  # kit_self: {name: when he last did it}
LASTS = (20, 40)  # minutes one pastime holds him


@dataclass(frozen=True)
class Kind:
    feeds: str  # the drive it satisfies: boredom, curiosity or social
    rest: timedelta  # how long before he does it again


KINDS: dict[str, Kind] = {
    "weather": Kind("boredom", timedelta(hours=3)),
    "music": Kind("boredom", timedelta(hours=2)),
    "journal": Kind("social", timedelta(days=1)),
    "thing": Kind("curiosity", timedelta(days=2)),
}


@dataclass
class Pastime:
    """Something Kit is doing on his own, and what he found doing it."""

    name: str
    doing: str  # a few words for the face's bubble: "watching the rain"
    found: str  # a true line for his thoughts and his hello: what he saw or read
    since: datetime
    until: datetime

    @property
    def feeds(self) -> str:
        return KINDS[self.name].feeds

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "doing": self.doing,
            "found": self.found,
            "since": self.since.isoformat(timespec="seconds"),
            "until": self.until.isoformat(timespec="seconds"),
        }

    @classmethod
    def from_dict(cls, data: dict, like: datetime) -> Pastime:
        return cls(
            str(data["name"]),
            str(data["doing"]),
            str(data.get("found", "")),
            parse_time(data["since"], like),
            parse_time(data["until"], like),
        )


# A reader returns (what he's doing, what he found), or None if there's nothing in it.
Found = tuple[str, str] | None


@dataclass
class Readers:
    """Where each pastime looks. Any can be left out."""

    weather: Callable[[], Awaitable[Found]] | None = None
    journal: Callable[[], Found] | None = None
    thing: Callable[[random.Random], Found] | None = None
    music: Callable[[], Found] | None = None


class Pastimes:
    def __init__(
        self,
        readers: Readers,
        clock: Callable[[], datetime],
        store: SelfStore | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.readers = readers
        self.clock = clock
        self.store = store
        self.rng = rng or random.Random()

    def _last(self) -> dict[str, str]:
        raw = self.store.self_value(PASTIMES_KEY) if self.store is not None else None
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _done(self, name: str, now: datetime) -> None:
        if self.store is None:
            return
        last = self._last()
        last[name] = now.isoformat(timespec="seconds")
        self.store.set_self_value(PASTIMES_KEY, json.dumps(last))

    def resting(self, name: str, now: datetime) -> bool:
        when = self._last().get(name)
        if not when:
            return False
        try:
            return now - parse_time(when, now) < KINDS[name].rest
        except ValueError:
            return False

    async def pick(self, drives: dict[str, float], away_since: datetime) -> Pastime | None:
        """Something to do now, fed by his strongest drive first, skipping what's
        resting and the weather if he's looked already this absence. None if nothing
        has anything in it."""
        now = self.clock()
        names = [n for n in KINDS if not self.resting(n, now)]
        if "weather" in names and self._looked_since(away_since):
            names.remove("weather")
        self.rng.shuffle(names)
        names.sort(key=lambda n: -drives.get(KINDS[n].feeds, 0.0))
        for name in names:
            try:
                found = await self._read(name)
            except Exception:  # a pastime is a nice-to-have; a reader failing isn't news
                log.exception("Kit's pastime %s failed", name)
                found = None
            if not found or not found[0].strip():
                continue
            self._done(name, now)
            minutes = self.rng.uniform(*LASTS)
            doing, what = found
            return Pastime(name, doing.strip(), what.strip(), now, now + timedelta(minutes=minutes))
        return None

    def _looked_since(self, since: datetime) -> bool:
        when = self._last().get("weather")
        if not when:
            return False
        try:
            return parse_time(when, since) >= since
        except ValueError:
            return False

    async def _read(self, name: str) -> Found:
        r = self.readers
        if name == "weather":
            return await r.weather() if r.weather else None
        if name == "journal":
            return r.journal() if r.journal else None
        if name == "thing":
            return r.thing(self.rng) if r.thing else None
        if name == "music":
            return r.music() if r.music else None
        return None


def weather_doing(sky: str) -> str:
    """What watching the weather looks like, from the sky ("light rain")."""
    sky = sky.lower()
    if "thunder" in sky:
        return "watching the storm"
    if any(w in sky for w in ("rain", "shower", "drizzle")):
        return "watching the rain"
    if "fog" in sky:
        return "watching the fog"
    if any(w in sky for w in ("cloud", "overcast")):
        return "watching the clouds"
    return "watching the sky"
