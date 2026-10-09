"""Talking to Kit's brain from the desk PC.

The desk app only ever connects out to the brain, so nothing on the desk PC
listens on the network and no firewall rule is needed there. Calls block, so
the app makes them from worker threads, never the screen thread.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

# A cloud answer with web searches can take a minute or two to arrive.
CHAT_TIMEOUT = httpx.Timeout(10.0, read=300.0)
TIMEOUT = httpx.Timeout(5.0)
# A voice engine that's still loading (Chatterbox, the first time) can take minutes.
SPEAK_TIMEOUT = httpx.Timeout(5.0, read=300.0)


class BrainError(Exception):
    """The brain couldn't be reached, or said no. The message is fit to show Dan."""


class SpeechOff(BrainError):
    """Kit's speech is turned off on the server."""


class BrainClient:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {token}", "X-Changed-By": "desk app"},
            timeout=TIMEOUT,
            transport=transport,
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

    def speak(self, text: str, emotion: str = "neutral", first: bool = False) -> bytes:
        """One sentence as a WAV file. Raises SpeechOff if speech is turned off."""
        try:
            r = self._http.post(
                "/api/speech/say",
                json={"text": text, "emotion": emotion, "first": first},
                timeout=SPEAK_TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise BrainError(f"Kit's voice didn't answer ({type(e).__name__}).") from e
        if r.status_code == 409:
            raise SpeechOff(r.text)
        _check(r)
        return r.content

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


def _check(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise BrainError("Kit didn't accept the token. Run `kit token` on the server to see it.")
    if r.status_code >= 400:
        raise BrainError(f"Kit answered {r.status_code}: {r.text[:200]}")
