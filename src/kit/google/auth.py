"""Signing Kit in to Google, and keeping him signed in.

Dan makes an OAuth client ("Desktop app") in his own Google Cloud project and
saves its JSON as ``google_client.json`` in the secrets folder. ``kit google
connect`` sends him to Google with that client, the scopes his settings allow and
a PKCE challenge; Google sends the browser back to ``http://localhost:PORT``.
On the box there's no browser, so the command listens on that port (an ssh port
forward completes it by itself) and also takes the address of the page the browser
lands on, pasted back. The tokens go in ``google_token.json`` (owner-only). An
access token lasts an hour and is refreshed as needed; a refresh token that Google
no longer honours (revoked, or expired after a week while the Cloud project is in
"Testing") puts the account in ``needs_reconnect`` until ``kit google connect`` is
run again, and Kit says so rather than failing quietly."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from kit.google import SCOPES

CLIENT_FILE = "google_client.json"
TOKEN_FILE = "google_token.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EARLY = timedelta(minutes=2)  # refresh this long before the access token runs out


class GoogleAuthError(Exception):
    """Signing in or refreshing failed, in words for the terminal."""


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    client_secret: str

    @classmethod
    def load(cls, path: Path) -> ClientConfig:
        """The client Dan downloaded from Google Cloud (``installed`` or ``web``)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise GoogleAuthError(f"can't read {path.name}: {e}") from e
        inner = data.get("installed") or data.get("web") or data
        client_id = str(inner.get("client_id", "")).strip()
        if not client_id:
            raise GoogleAuthError(f"{path.name} has no client_id: download it from Google Cloud")
        return cls(client_id, str(inner.get("client_secret", "")).strip())


@dataclass
class Tokens:
    refresh_token: str
    access_token: str = ""
    expires_at: str = ""  # ISO, when the access token runs out
    scopes: list[str] = field(default_factory=list)
    account: str = ""  # the address signed in, once known
    needs_reconnect: bool = False  # Google stopped honouring the refresh token

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)

    @classmethod
    def from_json(cls, text: str) -> Tokens:
        data = json.loads(text)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def fresh(self, now: datetime) -> bool:
        if not self.access_token or not self.expires_at:
            return False
        try:
            return now < datetime.fromisoformat(self.expires_at) - EARLY
        except ValueError:
            return False

    def has(self, part: str) -> bool:
        """Whether the sign-in covered a part (``gmail`` or ``calendar``)."""
        return all(s in self.scopes for s in SCOPES.get(part, ()))


def scopes_for(gmail: bool, calendar: bool) -> list[str]:
    out: list[str] = []
    if gmail:
        out += SCOPES["gmail"]
    if calendar:
        out += SCOPES["calendar"]
    return out


def write_private(path: Path, text: str) -> None:
    """Write a secrets file owner-only (Windows ignores the mode; the data folder's
    own permissions cover it there)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


class TokenStore:
    """The tokens file in the secrets folder."""

    def __init__(self, secrets_dir: Path) -> None:
        self.client_file = secrets_dir / CLIENT_FILE
        self.token_file = secrets_dir / TOKEN_FILE

    def client(self) -> ClientConfig | None:
        return ClientConfig.load(self.client_file) if self.client_file.is_file() else None

    def load(self) -> Tokens | None:
        if not self.token_file.is_file():
            return None
        try:
            tokens = Tokens.from_json(self.token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return tokens if tokens.refresh_token else None

    def save(self, tokens: Tokens) -> None:
        write_private(self.token_file, tokens.to_json() + "\n")

    def forget(self) -> bool:
        if self.token_file.is_file():
            self.token_file.unlink()
            return True
        return False


# Signing in


@dataclass(frozen=True)
class SignIn:
    """A sign-in under way: the address to open, and what the reply must carry."""

    url: str
    state: str
    verifier: str
    redirect_uri: str


def pkce_pair(rng: Callable[[int], str] = secrets.token_urlsafe) -> tuple[str, str]:
    verifier = rng(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def start_sign_in(client: ClientConfig, scopes: list[str], port: int) -> SignIn:
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{port}/"
    query = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # a refresh token, so Kit stays signed in
        "prompt": "consent",  # Google only gives a refresh token when consent is shown
    }
    return SignIn(f"{AUTH_URL}?{urlencode(query)}", state, verifier, redirect_uri)


def code_from_reply(reply: str, state: str) -> str:
    """The authorisation code in the address Google sent the browser to (pasted back
    whole, or just the code itself)."""
    reply = reply.strip()
    if not reply:
        raise GoogleAuthError("nothing pasted")
    if "code=" not in reply and "?" not in reply:
        return reply  # the bare code
    query = parse_qs(urlparse(reply).query)
    if "error" in query:
        raise GoogleAuthError(f"Google said no: {query['error'][0]}")
    if query.get("state", [""])[0] != state:
        raise GoogleAuthError("that reply belongs to another sign-in; start again")
    code = query.get("code", [""])[0]
    if not code:
        raise GoogleAuthError("no code in that address")
    return code


async def exchange_code(
    http: httpx.AsyncClient, client: ClientConfig, sign_in: SignIn, code: str, now: datetime
) -> Tokens:
    data = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "code": code,
        "code_verifier": sign_in.verifier,
        "grant_type": "authorization_code",
        "redirect_uri": sign_in.redirect_uri,
    }
    body = await _token_request(http, data)
    refresh = str(body.get("refresh_token", ""))
    if not refresh:
        raise GoogleAuthError(
            "Google gave no refresh token: remove Kit under your Google account's "
            "third-party access and connect again"
        )
    return Tokens(
        refresh_token=refresh,
        access_token=str(body.get("access_token", "")),
        expires_at=_expiry(body, now),
        scopes=str(body.get("scope", "")).split(),
    )


async def refresh(
    http: httpx.AsyncClient, client: ClientConfig, tokens: Tokens, now: datetime
) -> Tokens:
    """A new access token. ``invalid_grant`` means Google no longer honours the
    refresh token: the tokens come back marked ``needs_reconnect``."""
    data = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "refresh_token": tokens.refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        body = await _token_request(http, data)
    except GoogleAuthError as e:
        if "invalid_grant" in str(e):
            tokens.needs_reconnect = True
            tokens.access_token = ""
            return tokens
        raise
    tokens.access_token = str(body.get("access_token", ""))
    tokens.expires_at = _expiry(body, now)
    tokens.needs_reconnect = False
    if body.get("scope"):
        tokens.scopes = str(body["scope"]).split()
    return tokens


async def revoke(http: httpx.AsyncClient, tokens: Tokens) -> bool:
    """Tell Google to forget the sign-in; False if it wouldn't."""
    try:
        r = await http.post(REVOKE_URL, data={"token": tokens.refresh_token}, timeout=15)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


async def _token_request(http: httpx.AsyncClient, data: dict) -> dict:
    try:
        r = await http.post(TOKEN_URL, data=data, timeout=20)
    except httpx.HTTPError as e:
        raise GoogleAuthError(f"can't reach Google: {e}") from e
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200:
        why = body.get("error_description") or body.get("error") or f"HTTP {r.status_code}"
        raise GoogleAuthError(f"{body.get('error', 'error')}: {why}")
    return body


def _expiry(body: dict, now: datetime) -> str:
    seconds = int(body.get("expires_in") or 3600)
    return (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")
