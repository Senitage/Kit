"""Kit's connection to Google: one signed-in account, its access token kept fresh,
and JSON calls to the Gmail and Calendar APIs with the errors turned into words."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from kit.google.auth import GoogleAuthError, Tokens, TokenStore, refresh

log = logging.getLogger(__name__)

API = "https://www.googleapis.com"
NOT_CONNECTED = "Google isn't connected: run `kit google connect` on the server."
RECONNECT = (
    "Google needs reconnecting (the sign-in expired or was revoked): "
    "run `kit google connect` on the server."
)
TIMEOUT_S = 20


class GoogleError(Exception):
    """A call that didn't work, in words. ``reconnect`` marks a sign-in that's gone."""

    def __init__(self, message: str, reconnect: bool = False) -> None:
        super().__init__(message)
        self.reconnect = reconnect


class Google:
    """The signed-in account. ``http`` and ``clock`` are passed in so tests can fake
    Google; ``store`` is the tokens file in the secrets folder."""

    def __init__(
        self,
        store: TokenStore,
        clock: Callable[[], datetime],
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self._own_http = http is None
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=10))
        self.tokens: Tokens | None = store.load()
        self.last_error = ""

    async def close(self) -> None:
        if self._own_http:
            await self.http.aclose()

    # The sign-in

    @property
    def connected(self) -> bool:
        return self.tokens is not None and not self.tokens.needs_reconnect

    @property
    def account(self) -> str:
        return self.tokens.account if self.tokens else ""

    def has(self, part: str) -> bool:
        return self.tokens is not None and self.tokens.has(part)

    def reload(self) -> None:
        """Read the tokens file again (after ``kit google connect`` while Kit runs)."""
        self.tokens = self.store.load()

    def status(self) -> dict:
        """For /api/status and `kit google status`."""
        if self.tokens is None:
            return {"connected": False, "account": "", "gmail": False, "calendar": False}
        return {
            "connected": self.connected,
            "needs_reconnect": self.tokens.needs_reconnect,
            "account": self.tokens.account,
            "gmail": self.tokens.has("gmail"),
            "calendar": self.tokens.has("calendar"),
            "error": self.last_error or None,
        }

    async def access_token(self) -> str:
        if self.tokens is None:
            self.reload()
        if self.tokens is None:
            raise GoogleError(NOT_CONNECTED)
        if self.tokens.needs_reconnect:
            raise GoogleError(RECONNECT, reconnect=True)
        now = self.clock()
        if self.tokens.fresh(now):
            return self.tokens.access_token
        client = self.store.client()
        if client is None:
            raise GoogleError("Google isn't set up: no google_client.json in the secrets folder.")
        try:
            self.tokens = await refresh(self.http, client, self.tokens, now)
        except GoogleAuthError as e:
            self.last_error = str(e)
            raise GoogleError(f"Google is out of reach: {e}") from e
        self.store.save(self.tokens)
        if self.tokens.needs_reconnect:
            self.last_error = "the sign-in expired or was revoked"
            raise GoogleError(RECONNECT, reconnect=True)
        return self.tokens.access_token

    # Calls

    async def call(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict:
        """One JSON call to ``API``/``path``. Errors become ``GoogleError``."""
        token = await self.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = await self.http.request(
                method,
                API + path,
                params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                json=json,
                headers=headers,
                timeout=TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            self.last_error = str(e) or type(e).__name__
            raise GoogleError(f"Google is out of reach: {self.last_error}") from e
        if r.status_code == 401:
            self.tokens.access_token = ""  # stale: refreshed on the next call
            raise GoogleError("Google turned the call away (401): try again.")
        if r.status_code >= 400:
            why = _why(r)
            self.last_error = why
            if r.status_code == 403 and "insufficient" in why.lower():
                raise GoogleError(
                    f"Kit's sign-in doesn't allow that ({why}): run `kit google connect` "
                    "again after turning the part on in settings."
                )
            raise GoogleError(f"Google said no ({r.status_code}): {why}")
        self.last_error = ""
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError as e:
            raise GoogleError("Google sent something that isn't JSON") from e

    async def get(self, path: str, **params: Any) -> dict:
        return await self.call("GET", path, params)

    async def post(self, path: str, json: dict | None = None, **params: Any) -> dict:
        return await self.call("POST", path, params, json)

    async def patch(self, path: str, json: dict, **params: Any) -> dict:
        return await self.call("PATCH", path, params, json)

    async def profile(self) -> str:
        """The address signed in, kept on the tokens."""
        if self.has("gmail"):
            data = await self.get("/gmail/v1/users/me/profile")
            address = str(data.get("emailAddress", ""))
        else:
            data = await self.get("/calendar/v3/calendars/primary")
            address = str(data.get("id", ""))
        if address and self.tokens is not None and self.tokens.account != address:
            self.tokens.account = address
            self.store.save(self.tokens)
        return address


def _why(r: httpx.Response) -> str:
    try:
        err = r.json().get("error")
    except ValueError:
        return r.text[:200] or f"HTTP {r.status_code}"
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or r.status_code)
    return str(err or r.status_code)
