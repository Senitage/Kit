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


class BrainError(Exception):
    """The brain couldn't be reached, or said no. The message is fit to show Dan."""


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
