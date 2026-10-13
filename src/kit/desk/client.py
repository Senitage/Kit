"""Talking to Kit's brain from the desk PC.

The desk app only ever connects out to the brain, so nothing on the desk PC
listens on the network and no firewall rule is needed there. Calls block, so
the app makes them from worker threads, never the screen thread.
"""

from __future__ import annotations

import io
import json
import logging
import threading
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

# A cloud answer with web searches can take a minute or two to arrive.
CHAT_TIMEOUT = httpx.Timeout(10.0, read=300.0)
TIMEOUT = httpx.Timeout(5.0)
# A sentence takes the voice engine about a second; one that takes longer than this
# is given up on, so a slow server can't hold a reply for minutes (an engine still
# loading answers 503 at once instead, and the desk asks again in a moment).
SPEAK_TIMEOUT = httpx.Timeout(5.0, read=30.0)
# A connection idles between Kit's sentences and between messages; keeping it a
# minute (httpx's default is 5 s) saves opening a new one before the first word.
KEEP_ALIVE = httpx.Limits(keepalive_expiry=60.0)


def transport_for(url: str) -> httpx.HTTPTransport:
    """How to reach the brain at ``url``: over IPv4, unless it's an IPv6 address.

    The brain listens on IPv4 (``brain.host``). On Windows a name with an IPv6
    address too (``localhost``, a Tailscale name) is tried there first, nothing
    answers, and Windows takes 2 s to give up. Every new connection waited that
    out, which held up the first sentence of every reply by 2 s."""
    if ":" in httpx.URL(url).host:
        return httpx.HTTPTransport(limits=KEEP_ALIVE)
    return httpx.HTTPTransport(local_address="0.0.0.0", limits=KEEP_ALIVE)  # IPv4 sockets only


class BrainError(Exception):
    """The brain couldn't be reached, or said no. The message is fit to show Dan."""


class SpeechOff(BrainError):
    """Kit's speech is turned off on the server."""


class SpeechLoading(BrainError):
    """The voice engine is still loading: not yet, ask again in a moment."""


class SpeechStale(BrainError):
    """The sentence is from a reply that's been overtaken, so it wasn't made."""


@dataclass
class Sound:
    """A sentence of Kit's voice as it arrives: ``pieces`` yields 16-bit samples
    (``width`` bytes each, ``channels`` a frame) at ``rate`` while the server is
    still making the rest, so playing can start on the first."""

    rate: int
    channels: int = 1
    width: int = 2
    pieces: Iterator[bytes] = field(default_factory=lambda: iter(()), repr=False)

    @classmethod
    def from_wav(cls, data: bytes) -> Sound:
        """A whole WAV file (an older server's answer) as one piece."""
        with wave.open(io.BytesIO(data)) as w:
            frames = w.readframes(w.getnframes())
            return cls(w.getframerate(), w.getnchannels(), w.getsampwidth(), iter([frames]))


class BrainClient:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {token}", "X-Changed-By": "desk app"},
            timeout=TIMEOUT,
            transport=transport or transport_for(self.url),
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            r = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise BrainError(f"Can't reach Kit at {self.url} ({type(e).__name__}).") from e
        _check(r)
        return r

    def check(self) -> dict:
        """Kit's status, which also proves the token works."""
        return self._call("GET", "/api/status").json()

    def health(self) -> dict:
        return self._call("GET", "/api/health").json()

    def face(self) -> dict:
        """Kit's character sheet (kit.face.character): how he looks and moves."""
        return self._call("GET", "/api/face").json()

    def face_presets(self) -> dict:
        """Every character Kit can be (id and name), and which one he is now."""
        return self._call("GET", "/api/face/presets").json()

    def messages(self, limit: int = 40) -> list[dict]:
        return self._call("GET", "/api/messages", params={"limit": limit}).json()

    def life_events(self, after: int, wait: float = 25.0) -> dict:
        """Kit's fidgets and pipe-ups after event ``after``; waits up to ``wait`` s."""
        timeout = httpx.Timeout(10.0, read=wait + 10)
        return self._call(
            "GET", "/api/life/events", params={"after": after, "wait": wait}, timeout=timeout
        ).json()

    def life(self) -> dict:
        return self._call("GET", "/api/life").json()

    def snooze(self, minutes: float) -> dict:
        return self._call("POST", "/api/life/snooze", json={"minutes": minutes}).json()

    def new_chat(self) -> None:
        self._call("POST", "/api/chat/new")

    # Kit's voice (made on the server, played here).

    def speech_status(self) -> dict:
        return self._call("GET", "/api/speech").json()

    def speak(
        self,
        text: str,
        emotion: str = "neutral",
        first: bool = False,
        generation: int | None = None,
    ) -> Sound:
        """One sentence as sound, in pieces as the server makes it. ``generation``
        numbers the reply, so the server drops a sentence from one that's been
        overtaken. Raises SpeechOff if speech is turned off, SpeechLoading while the
        engine loads, SpeechStale if overtaken; a piece that doesn't come (the server
        broke off) ends the sound with a BrainError."""
        body: dict = {"text": text, "emotion": emotion, "first": first}
        if generation is not None:
            body["generation"] = generation
        request = self._http.build_request(
            "POST", "/api/speech/say", json=body, timeout=SPEAK_TIMEOUT
        )
        try:
            r = self._http.send(request, stream=True)
        except httpx.HTTPError as e:
            raise BrainError(f"Kit's voice didn't answer ({type(e).__name__}).") from e
        kind = r.headers.get("content-type", "")
        if r.status_code != 200 or not kind.startswith("audio/L16"):
            try:
                r.read()
            except httpx.HTTPError as e:
                raise BrainError(f"Kit's voice broke off ({type(e).__name__}).") from e
            finally:
                r.close()
            if r.status_code == 409:
                raise SpeechOff(r.text)
            if r.status_code == 503:
                raise SpeechLoading(r.text)
            if r.status_code == 410:
                raise SpeechStale(r.text)
            _check(r)
            try:
                return Sound.from_wav(r.content)  # an older server: the whole sentence
            except (wave.Error, EOFError) as e:
                raise BrainError(f"Kit's voice sent something that isn't sound ({e}).") from e
        try:
            rate = int(r.headers["X-Sample-Rate"])
        except (KeyError, ValueError) as e:
            r.close()
            raise BrainError("Kit's voice didn't say its sample rate.") from e
        return Sound(rate, pieces=_pieces(r))

    # Kit's settings, as on the settings page.

    def settings(self) -> dict:
        return self._call("GET", "/api/settings").json()

    def settings_schema(self) -> dict:
        return self._call("GET", "/api/settings/schema").json()

    def save_settings(self, patch: dict) -> dict:
        return self._call("PATCH", "/api/settings", json=patch).json()

    def undo_settings(self) -> dict:
        return self._call("POST", "/api/settings/undo").json()

    # Kit's memory, as on the memory page.

    def facts(self) -> list[dict]:
        return self._call("GET", "/api/memory/facts").json()

    def search(self, query: str, k: int = 15) -> dict:
        return self._call("GET", "/api/memory/search", params={"q": query, "k": k}).json()

    def remember(self, text: str, pinned: bool = False) -> dict:
        body = {"text": text, "pinned": pinned}
        return self._call("POST", "/api/memory/facts", json=body, timeout=CHAT_TIMEOUT).json()

    def edit_fact(self, fact_id: int, **changes) -> dict:
        return self._call("PATCH", f"/api/memory/facts/{fact_id}", json=changes).json()

    def forget(self, fact_id: int) -> None:
        self._call("DELETE", f"/api/memory/facts/{fact_id}")

    def report(self, snapshot: dict) -> None:
        self._call("POST", "/api/pc/context", json=snapshot)

    # Kit's eyes (kit.eyes): the camera process reports through here too.

    def report_scene(self, report: dict) -> dict:
        """One scene report; the answer says whether the eyes are paused."""
        return self._call("POST", "/api/eyes/scene", json=report).json()

    def eyes(self) -> dict:
        return self._call("GET", "/api/eyes/scene").json()

    def set_eyes(self, on: bool) -> dict:
        """The "Let Kit see me" switch: off releases the camera."""
        return self._call("POST", "/api/eyes/pause", json={"paused": not on}).json()

    def known_faces(self) -> dict:
        """The people Kit's eyes know: names and face numbers (kit.known_faces)."""
        return self._call("GET", "/api/eyes/faces").json()

    def enrol_face(self, name: str, embeddings: list[list[float]]) -> dict:
        return self._call(
            "POST", "/api/eyes/faces", json={"name": name, "embeddings": embeddings}
        ).json()

    def forget_face(self, name: str) -> dict:
        return self._call("DELETE", f"/api/eyes/faces/{quote(name, safe='')}").json()

    def chat(self, text: str) -> Iterator[dict]:
        """Kit's reply events as they arrive (see kit.brain for the kinds)."""
        try:
            with self._http.stream(
                "POST", "/api/chat", json={"text": text, "channel": "desk"}, timeout=CHAT_TIMEOUT
            ) as r:
                if r.status_code >= 400:
                    r.read()
                    _check(r)
                for line in r.iter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.HTTPError as e:
            raise BrainError(f"Lost touch with Kit ({type(e).__name__}).") from e


LIFE_RETRY_S = 10.0  # the brain's life feed broke: wait this long, then twice as long...
LIFE_RETRY_MAX_S = 120.0  # ...up to this, between tries


def life_step(client: BrainClient, after: int | None, emit: Callable[[dict], None]) -> int:
    """One turn of following Kit's inner life: hand each new event to ``emit`` and
    return the id to ask after next. ``after`` None means start from now (the
    desk just started, or the brain did): his current state is emitted first,
    not old fidgets."""
    if after is None:
        state = client.life()
        after = int(state["last_event"])
        if state.get("mood") == "asleep":
            emit({"type": "state", "state": "asleep"})
        if state.get("face"):  # the face he wears between replies
            emit({"type": "mood", "face": state["face"]})
    got = client.life_events(after)
    events = got["events"]
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        raise TypeError("the life events aren't a list of events")
    for event in events:
        emit(event)
    after = int(events[-1]["id"]) if events else max(after, 0)
    if int(got["last"]) < after:  # the brain restarted: its event ids began again
        raise BrainError("Kit's brain restarted")
    return after


def follow_life(
    stop: threading.Event,
    client_of: Callable[[], BrainClient | None],
    emit: Callable[[dict], None],
    retry_s: float = LIFE_RETRY_S,
    retry_max_s: float = LIFE_RETRY_MAX_S,
) -> None:
    """Follow Kit's inner life until ``stop`` is set. Whatever goes wrong (the
    brain away, a malformed answer, a settings change mid-call) is logged once and
    tried again after a wait that doubles while the trouble lasts, so a bad
    answer can't end the feed until the app restarts."""
    after: int | None = None
    delay = retry_s
    trouble = ""
    while not stop.is_set():
        client = client_of()
        if client is None:
            stop.wait(5)
            continue
        try:
            after = life_step(client, after, emit)
            delay, trouble = retry_s, ""
        except Exception as e:  # noqa: BLE001 (anything: the loop must outlive it)
            what = f"{type(e).__name__}: {e}"
            if what != trouble:
                log.warning("can't follow Kit's life (%s); trying again in %.0f s", what, delay)
                trouble = what
            after = None
            stop.wait(delay)
            delay = min(delay * 2, retry_max_s)


def _pieces(r: httpx.Response) -> Iterator[bytes]:
    try:
        for piece in r.iter_bytes():
            if piece:
                yield piece
    except httpx.HTTPError as e:
        raise BrainError(f"Kit's voice broke off ({type(e).__name__}).") from e
    finally:
        r.close()


def _check(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise BrainError("Kit didn't accept the token. Run `kit token` on the server to see it.")
    if r.status_code >= 400:
        raise BrainError(f"Kit answered {r.status_code}: {r.text[:200]}")
