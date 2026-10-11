"""Which of Kit's bodies are around right now, and what each can do.

There's one Kit and many bodies: the desk app, the phone app, home_app's page, the
Pod. Each body says hello when it starts (``POST /api/bodies/hello``) with what it
can do (a screen, a speaker, a mic, a camera...), and the brain answers with what
it can do: its features, each with a version number. A body only uses a feature
the brain offers, so a new feature lights up in an app that knows it and an old
app carries on without it.

The registry also keeps when each body was last heard from and when Dan last used
it, so later work can pick one body to speak a pipe-up and keep one PC report per
desk. It lives in memory: bodies say hello again after a restart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

API_VERSION = 1  # bumped only if an old body could no longer talk to the brain
ONLINE_FOR = timedelta(seconds=90)  # a body that polls events checks in every ~25 s
# The events bodies hear on /api/life/events (kit.life and kit.server).
LIFE_EVENTS = (
    "mood",
    "fidget",
    "react",
    "state",
    "look",
    "doing",
    "quiet",
    "dials",
    "pipe_up",
)
ABILITIES = (
    "screen",
    "speaker",
    "mic",
    "camera",
    "notify",
    "haptics",
    "touch",
    "place",
    "motion",
    "earbuds",
    "pc",
)


class Hello(BaseModel):
    """A body introducing itself. A paired device's id is its device name."""

    id: str = Field("", max_length=40)
    kind: str = Field("other", max_length=20)  # desk, phone, home_app, robot...
    name: str = Field("", max_length=60)  # how it's shown, e.g. "Dan's phone"
    app: str = Field("", max_length=20)  # the app's version
    api: int = 1
    abilities: list[str] = Field(default_factory=list, max_length=40)
    faces: list[str] = Field(default_factory=list, max_length=10)  # looks it can draw


@dataclass(frozen=True)
class Body:
    id: str
    kind: str
    name: str
    app: str
    api: int
    abilities: tuple[str, ...]
    faces: tuple[str, ...]
    device: str | None  # the paired device it came in on, if any
    first_seen: datetime
    last_seen: datetime
    last_used: datetime | None = None  # when Dan last talked to Kit through it
    unknown: tuple[str, ...] = field(default=())  # abilities the brain doesn't know yet

    def online(self, now: datetime) -> bool:
        return now - self.last_seen < ONLINE_FOR

    def as_dict(self, now: datetime) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "app": self.app,
            "api": self.api,
            "abilities": list(self.abilities),
            "faces": list(self.faces),
            "device": self.device,
            "online": self.online(now),
            "first_seen": self.first_seen.isoformat(timespec="seconds"),
            "last_seen": self.last_seen.isoformat(timespec="seconds"),
            "last_used": self.last_used.isoformat(timespec="seconds") if self.last_used else None,
        }


class BodyRegistry:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._bodies: dict[str, Body] = {}

    def hello(self, hello: Hello, device: str | None = None) -> Body:
        """A body says hello (again): what it is and what it can do. A paired device
        is always known by its device name, whatever id it sends."""
        now = self.clock()
        body_id = device or hello.id.strip() or hello.kind
        old = self._bodies.get(body_id)
        abilities = tuple(dict.fromkeys(a for a in hello.abilities if a in ABILITIES))
        body = Body(
            id=body_id,
            kind=hello.kind,
            name=hello.name or body_id,
            app=hello.app,
            api=hello.api,
            abilities=abilities,
            faces=tuple(hello.faces),
            device=device,
            first_seen=old.first_seen if old else now,
            last_seen=now,
            last_used=old.last_used if old else None,
            unknown=tuple(a for a in hello.abilities if a not in ABILITIES),
        )
        self._bodies[body_id] = body
        return body

    def seen(self, body_id: str | None) -> None:
        """A body checked in (any call from a paired device counts)."""
        body = self._bodies.get(body_id or "")
        if body is not None:
            self._bodies[body.id] = replace(body, last_seen=self.clock())

    def used(self, body_id: str | None) -> None:
        """Dan talked to Kit through this body."""
        body = self._bodies.get(body_id or "")
        if body is not None:
            now = self.clock()
            self._bodies[body.id] = replace(body, last_seen=now, last_used=now)

    def get(self, body_id: str) -> Body | None:
        return self._bodies.get(body_id)

    def all(self) -> list[Body]:
        return sorted(self._bodies.values(), key=lambda b: b.last_seen, reverse=True)

    def online(self) -> list[Body]:
        now = self.clock()
        return [b for b in self.all() if b.online(now)]

    def last_used(self) -> Body | None:
        """The body Dan used most recently and that's still around: where a reply to
        nobody in particular (a pipe-up) should go, once bodies pick one voice."""
        used = [b for b in self.online() if b.last_used is not None]
        return max(used, key=lambda b: b.last_used) if used else None

    def forget(self, body_id: str) -> None:
        self._bodies.pop(body_id, None)

    def listing(self) -> list[dict]:
        now = self.clock()
        return [b.as_dict(now) for b in self.all()]
