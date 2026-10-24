"""Kit's end of the voice link: his voice made on another computer's graphics card.

The voice program (``kit voice``, kit.speech.program) runs on the PC with the card
and dials in to Kit over a WebSocket (``/api/speech/link``, Kit's own token), so
nothing on the PC listens on the network. An engine profile with ``remote = true``
is made there: Kit tells the program which engine to load (the profile from his
settings, with his voice clip, so his voice is still changed in one place), hands
it each line and passes the sound on to the desk as it comes.

While the program isn't connected, or is still loading, Kit speaks with
``speech.fallback`` on his own machine, and goes back to the PC's voice as soon as
it's ready again (SpeechService.in_use). A line the link drops before its first
sound is said with the fallback instead, so a closed program costs no line.

The messages (JSON text; sound as binary):

    program -> Kit  {"type": "hello", "name", "version"}
    Kit -> program  {"type": "engine", "key", "name", "profile", "clip_name", "clip"}
                    (clip: the voice clip, base64, or ""; an empty name unloads it)
    program -> Kit  {"type": "ready", "key", "health"} | {"type": "failed", "key", "error"}
    Kit -> program  {"type": "speak", "id", "text", "mood", "first", "generation"}
                    {"type": "cancel", "id"}
    program -> Kit  {"type": "start", "id", "rate", "synth_ms"}, then binary pieces
                    (the line's id as 4 bytes, big-endian, then 16-bit mono samples),
                    then {"type": "end", "id"} | {"type": "error", "id", "error", "stale"}
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator

from kit.speech.service import Loading, NotConnected, Speech, SpeechError, Stale

log = logging.getLogger(__name__)

FIRST_SOUND_S = 15.0  # a line with no sound by then is given up on (and said on the box)
PIECE_GAP_S = 30.0  # the longest wait between two pieces of one line


class VoiceLink:
    """The voice program that's dialled in, if any, and the lines it's making.

    The WebSocket route runs on Kit's event loop; the speech service calls from
    worker threads. Messages to the program go through an ``asyncio.Queue`` the
    route sends from (``post`` never blocks), and what comes back lands in one
    ``queue.Queue`` per line, which the thread asking for that line reads."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        first_sound_s: float = FIRST_SOUND_S,
        piece_gap_s: float = PIECE_GAP_S,
    ) -> None:
        self.clock = clock
        self.first_sound_s, self.piece_gap_s = first_sound_s, piece_gap_s
        self._lock = threading.Lock()
        self._number = 0  # which connection is the current one
        self._outbox: tuple[asyncio.AbstractEventLoop, asyncio.Queue] | None = None
        self.hello: dict = {}
        self.since: float | None = None  # when it connected (time.time)
        self.key: str | None = None  # the engine the program has loaded or is loading
        self.state = ""  # "", "loading", "ready" or "failed"
        self.health: dict = {}
        self.why = ""  # why the engine failed to load there
        self.failed_at = float("-inf")
        self._lines: dict[int, queue.Queue] = {}
        self._next_line = 0
        self.last: dict | None = None  # the latest line's timing

    # The route's side

    def attach(self, loop: asyncio.AbstractEventLoop, outbox: asyncio.Queue, hello: dict) -> int:
        """A program has dialled in; one dialling in again replaces the old one."""
        with self._lock:
            old = self._outbox
            self._number += 1
            self._outbox = (loop, outbox)
            self.hello, self.since = dict(hello), time.time()
            self.key, self.state, self.health, self.why = None, "", {}, ""
            lines, self._lines = self._lines, {}
        if old is not None:
            old[0].call_soon_threadsafe(old[1].put_nowait, None)  # the route closes it
        for line in lines.values():
            line.put(("gone", "the voice program dialled in again"))
        return self._number

    def detach(self, number: int) -> None:
        """The connection ``number`` closed. Its lines end at once, so each is
        said with the fallback or cut short rather than left waiting."""
        with self._lock:
            if number != self._number or self._outbox is None:
                return
            self._outbox = None
            self.key, self.state, self.health = None, "", {}
            lines, self._lines = self._lines, {}
        for line in lines.values():
            line.put(("gone", "the voice program went away"))

    def received(self, message: dict) -> None:
        """A message from the program."""
        kind = message.get("type")
        if kind in ("ready", "failed"):
            with self._lock:
                if message.get("key") != self.key:
                    return  # an answer about an engine since replaced
                if kind == "ready":
                    self.state, self.health, self.why = "ready", message.get("health") or {}, ""
                else:
                    self.state, self.why = "failed", str(message.get("error") or "it failed")
                    self.failed_at = self.clock()
            if kind == "ready":
                log.info("voice link: %s is ready on %s", self.health.get("engine"), self.name)
            else:
                log.warning("voice link: the engine failed to load on %s: %s", self.name, self.why)
            return
        line = self._lines.get(message.get("id"))
        if line is None:
            return
        if kind == "start":
            line.put(("start", int(message.get("rate") or 24000), message.get("synth_ms") or 0))
        elif kind == "end":
            line.put(("end",))
        elif kind == "error":
            line.put(("error", str(message.get("error") or "it failed"), message.get("stale")))

    def received_sound(self, data: bytes) -> None:
        line = self._lines.get(int.from_bytes(data[:4], "big"))
        if line is not None and len(data) > 4:
            line.put(data[4:])

    # The speech service's side

    @property
    def connected(self) -> bool:
        return self._outbox is not None

    @property
    def name(self) -> str:
        return str(self.hello.get("name") or "the PC")

    def ready_for(self, key: str) -> bool:
        return self.connected and self.state == "ready" and self.key == key

    def load(self, key: str, message: dict, retry_s: float | None = None) -> None:
        """Ask the program for this engine (``message`` as an engine message),
        unless it has it or is loading it already, or it failed there less than
        ``retry_s`` ago (it isn't reloaded straight away)."""
        with self._lock:
            again = (
                retry_s is not None
                and self.state == "failed"
                and self.clock() - self.failed_at >= retry_s
            )
            if self._outbox is None or (self.key == key and not again):
                return
            self.key, self.state, self.health, self.why = key, "loading", {}, ""
        log.info("voice link: asking %s to load %s", self.name, message.get("name"))
        self._post({"type": "engine", "key": key, **message})

    def unload(self) -> None:
        """Speech is off, or Kit speaks with another engine: free the PC's card."""
        with self._lock:
            if self._outbox is None or self.key is None:
                return
            self.key, self.state, self.health = None, "", {}
        self._post({"type": "engine", "key": "", "name": ""})

    def speak(self, text: str, mood: str, first: bool, generation: int | None) -> Speech:
        """The line as the program makes it, once its first sound is in."""
        with self._lock:
            if self._outbox is None:
                raise NotConnected("the voice program on the PC isn't connected")
            if self.state != "ready":
                raise Loading(f"Kit's voice is still loading on {self.name}")
            self._next_line += 1
            number = self._next_line
            line: queue.Queue = queue.Queue()
            self._lines[number] = line
            engine = str(self.health.get("engine") or "")
        asked = self.clock()
        self._post(
            {
                "type": "speak",
                "id": number,
                "text": text,
                "mood": mood,
                "first": first,
                "generation": generation,
            }
        )
        try:
            got = line.get(timeout=self.first_sound_s)
        except queue.Empty:
            self._forget(number, cancel=True)
            raise SpeechError(f"{self.name} made no sound in {self.first_sound_s:.0f} s") from None
        if got[0] != "start":
            self._forget(number, cancel=False)
            if got[0] == "error" and got[2]:
                raise Stale(got[1])
            raise SpeechError(f"{self.name}: {got[1]}")
        took_ms = 1000 * (self.clock() - asked)
        self.last = {"first_s": round(took_ms / 1000, 3), "there_s": round(got[2] / 1000, 3)}
        if first:
            log.info(
                "voice link: first sound in %.2f s, %.2f s of it making it on %s",
                took_ms / 1000,
                got[2] / 1000,
                self.name,
            )
        pieces = self._pieces(number, line)
        return Speech(rate=got[1], synth_ms=took_ms, engine=engine, pieces=pieces)

    def _pieces(self, number: int, line: queue.Queue) -> Iterator[bytes]:
        done = False
        try:
            while True:
                try:
                    got = line.get(timeout=self.piece_gap_s)
                except queue.Empty:
                    raise SpeechError(f"{self.name} stopped part way through a line") from None
                if isinstance(got, bytes):
                    yield got
                elif got[0] == "end":
                    done = True
                    return
                else:
                    done = True  # nothing more is coming for it
                    raise SpeechError(f"{self.name} broke off: {got[1]}")
        finally:
            self._forget(number, cancel=not done)  # stopped early: the program stops too

    def _forget(self, number: int, cancel: bool) -> None:
        with self._lock:
            known = self._lines.pop(number, None) is not None
        if cancel and known:
            self._post({"type": "cancel", "id": number})

    def _post(self, message: dict) -> None:
        outbox = self._outbox
        if outbox is not None:
            outbox[0].call_soon_threadsafe(outbox[1].put_nowait, message)

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "name": self.hello.get("name") if self.connected else None,
            "since": self.since if self.connected else None,
            "state": self.state or None,
            "engine": self.health.get("engine"),
            "device": self.health.get("device"),
            "cuda_graph": self.health.get("cuda_graph"),
            "problem": self.why or None,
            "last": self.last,
        }
