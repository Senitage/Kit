"""Nudging a phone when Kit pipes up and the app is closed.

Android drops an app's connection to Kit soon after it's closed, so a pipe-up
can't reach a closed app over Tailscale. Instead Kit sends a content-free
nudge through Firebase Cloud Messaging (FCM): no words, only "there's something
new" and the message's number. The phone wakes, fetches the pipe-up from Kit
over Tailscale and shows it. Nothing Kit says leaves the tailnet.

Sending needs a Firebase service account, a JSON file from the Firebase console,
kept in the secrets folder (``kit.credentials.firebase_service_account``).
Without it nudges are off, and the phone falls back to looking for pipe-ups
now and then. Which phones to nudge comes from ``kit.devices`` (each device may
register a push token), and when from the ``phone`` settings.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from kit.devices import Device, Devices

log = logging.getLogger(__name__)

FCM = "fcm"
KINDS = (FCM,)
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
TTL_S = 1800  # a pipe-up older than this isn't news; FCM drops the nudge
# What the nudge says ("kit"): a pipe-up to fetch, or a test from `kit nudge`.
PIPE_UP = "pipe_up"
TEST = "test"

# How posting went: sent, the phone's token is dead (forget it), or it failed.
SENT = "sent"
GONE = "gone"
FAILED = "failed"

# post(url, headers, data_or_json) -> (status, body text). Injected so tests send nothing.
Post = Callable[[str, dict[str, str], dict], Awaitable[tuple[int, str]]]


@dataclass(frozen=True)
class ServiceAccount:
    """What Kit needs from a Firebase service account file."""

    project: str
    email: str
    private_key: str  # PEM
    token_url: str = TOKEN_URL

    @classmethod
    def parse(cls, text: str) -> ServiceAccount | None:
        try:
            raw = json.loads(text)
            return cls(
                raw["project_id"],
                raw["client_email"],
                raw["private_key"],
                raw.get("token_uri") or TOKEN_URL,
            )
        except (ValueError, TypeError, KeyError):
            return None


def nudge_when(notify: str, pc_in_use: bool) -> bool:
    """Should phones be nudged about this pipe-up (``phone.notify``)? ``away``: only
    while no PC is in use, since the desk app shows it there. ``always``. ``never``."""
    if notify == "never":
        return False
    if notify == "always":
        return True
    return not pc_in_use


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_jwt(account: ServiceAccount, now: float, scope: str = SCOPE, lasts_s: int = 3600) -> str:
    """A signed JWT that Google swaps for an access token (RS256, as its OAuth2
    service-account flow wants)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(
        json.dumps(
            {
                "iss": account.email,
                "scope": scope,
                "aud": account.token_url,
                "iat": int(now),
                "exp": int(now) + lasts_s,
            }
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode()
    key = serialization.load_pem_private_key(account.private_key.encode(), password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{claims}.{_b64(signature)}"


async def _post(url: str, headers: dict[str, str], body: dict) -> tuple[int, str]:
    async with httpx.AsyncClient(timeout=15) as http:
        if url.endswith("/token"):
            response = await http.post(url, headers=headers, data=body)
        else:
            response = await http.post(url, headers=headers, json=body)
        return response.status_code, response.text


class Nudger:
    """Sends nudges to the phones registered for them, at most ``per_hour`` each."""

    def __init__(
        self,
        devices: Devices,
        account: ServiceAccount | None,
        post: Post | None = None,
        clock: Callable[[], datetime] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.devices = devices
        self.account = account
        self.post = post or _post
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.now = now
        self._access: tuple[str, float] | None = None  # token, good until (epoch seconds)
        self._sent: dict[str, list[datetime]] = {}

    @property
    def enabled(self) -> bool:
        return self.account is not None

    def targets(self) -> list[Device]:
        return [d for d in self.devices.all() if d.push]

    async def nudge_all(
        self, what: str, extra: dict[str, str] | None = None, per_hour: int = 0
    ) -> dict[str, str]:
        """Nudge every registered phone; how each went, by device name. ``per_hour``
        above 0 skips a phone nudged that often already (a test nudge never is)."""
        out: dict[str, str] = {}
        for device in self.targets():
            if per_hour and self._recent(device.name) >= per_hour:
                out[device.name] = "held"
                continue
            out[device.name] = await self.nudge(device, {"kit": what, **(extra or {})})
        return out

    async def nudge(self, device: Device, data: dict[str, str]) -> str:
        """One nudge to one phone: SENT, GONE (its token is dead, and forgotten) or
        FAILED (logged)."""
        if self.account is None or not device.push:
            return FAILED
        kind, token = device.push.get("kind"), device.push.get("token", "")
        if kind != FCM or not token:
            return FAILED
        try:
            status, text = await self._send_fcm(token, data)
        except (httpx.HTTPError, OSError) as e:
            log.warning("nudging %s failed: %s", device.name, e)
            return FAILED
        if 200 <= status < 300:
            self._sent.setdefault(device.name, []).append(self.clock())
            return SENT
        if status == 404 or "UNREGISTERED" in text:
            log.info("%s's push token is dead; forgetting it", device.name)
            self.devices.clear_push(device.name)
            return GONE
        if status == 401:
            self._access = None  # ask for a fresh access token next time
        log.warning("nudging %s failed: FCM answered %s %s", device.name, status, text[:200])
        return FAILED

    async def _send_fcm(self, token: str, data: dict[str, str]) -> tuple[int, str]:
        assert self.account is not None
        access = await self._access_token()
        message = {
            "message": {
                "token": token,
                "data": data,
                "android": {"priority": "high", "ttl": f"{TTL_S}s"},
            }
        }
        headers = {"Authorization": f"Bearer {access}"}
        return await self.post(SEND_URL.format(project=self.account.project), headers, message)

    async def _access_token(self) -> str:
        assert self.account is not None
        now = self.now()
        if self._access is not None and now < self._access[1]:
            return self._access[0]
        assertion = sign_jwt(self.account, now)
        status, text = await self.post(
            self.account.token_url,
            {},
            {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        if status != 200:
            raise httpx.HTTPError(f"Google wouldn't give an access token: {status} {text[:200]}")
        got = json.loads(text)
        lasts = float(got.get("expires_in", 3600))
        self._access = (got["access_token"], now + lasts - 60)
        return self._access[0]

    def _recent(self, name: str) -> int:
        since = self.clock() - timedelta(hours=1)
        kept = [at for at in self._sent.get(name, []) if at > since]
        self._sent[name] = kept
        return len(kept)
