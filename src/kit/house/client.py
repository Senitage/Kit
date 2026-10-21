"""One WebSocket connection to Home Assistant, as Kit's own user.

``HomeAssistant`` logs in with a long-lived token, keeps one reader that hands each
reply to whoever asked (by ``id``) and each ``state_changed`` event to the
subscribers, and reconnects on its own (1, 2, 4... up to 60 s between tries),
subscribing again. ``connect`` is passed in so tests replay recorded messages
instead of a real Home Assistant. See docs/2 How Kit Works/The House.md."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = 10.0
BACKOFF_S = (1, 2, 4, 8, 15, 30, 60)


class HouseError(Exception):
    """Home Assistant can't be reached, or said no. The message is fit to say."""


class Socket(Protocol):
    async def send(self, text: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


Connect = Callable[[str], Awaitable[Socket]]


async def websocket_connect(url: str) -> Socket:
    import websockets  # the house is optional: only needed once it's turned on

    # The full list of states can be a few MB in a big house.
    return await websockets.connect(url, max_size=2**25, open_timeout=10)


class HomeAssistant:
    def __init__(
        self,
        url: str,
        token: str,
        connect: Connect = websocket_connect,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.url = url
        self.token = token
        self.connect = connect
        self.sleep = sleep
        self.connected = False
        self.last_error = ""
        self.version = ""
        self._socket: Socket | None = None
        self._ids = 0
        self._waiting: dict[int, asyncio.Future] = {}
        self._subscribers: list[Callable[[dict], None]] = []
        self._ready = asyncio.Event()
        self._failed = asyncio.Event()  # set when a try fails, for wait_ready(first_try)
        self._task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        """Connect in the background; ``wait_ready`` waits for the first login."""
        if self._task is None:
            self._closed = False
            self._task = asyncio.create_task(self._run())

    async def wait_ready(self, timeout: float = 10.0, first_try: bool = False) -> bool:
        """Whether it's logged in, waiting up to ``timeout``; with ``first_try``, no
        longer than the first failed try (for ``kit check``)."""
        waiters = {asyncio.ensure_future(self._ready.wait())}
        if first_try:
            waiters.add(asyncio.ensure_future(self._failed.wait()))
        await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for waiter in waiters:
            waiter.cancel()
        return self.connected

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        await self._drop("closed")

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """``callback(data)`` for every ``state_changed`` (entity_id, old_state,
        new_state), from now on and after every reconnect."""
        self._subscribers.append(callback)

    async def _run(self) -> None:
        tries = 0
        while not self._closed:
            try:
                await self._session()
                tries = 0  # it ran, then dropped: try again straight away
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let the house take anything else down
                self.last_error = str(e) or type(e).__name__
                log.info("home assistant: %s", self.last_error)
                self._failed.set()
            await self._drop(self.last_error or "connection lost")
            await self.sleep(BACKOFF_S[min(tries, len(BACKOFF_S) - 1)])
            tries += 1

    async def _session(self) -> None:
        socket = await self.connect(self.url)
        self._socket = socket
        hello = json.loads(await socket.recv())
        if hello.get("type") == "auth_required":
            await socket.send(json.dumps({"type": "auth", "access_token": self.token}))
            hello = json.loads(await socket.recv())
        if hello.get("type") != "auth_ok":
            raise HouseError(
                "Home Assistant didn't accept Kit's token: "
                + str(hello.get("message") or hello.get("type"))
            )
        self.version = str(hello.get("ha_version", ""))
        reader = asyncio.create_task(self._read(socket))
        try:
            self.connected, self.last_error = True, ""
            await self.call("subscribe_events", event_type="state_changed")
            self._ready.set()
            await reader
        finally:
            reader.cancel()

    async def _read(self, socket: Socket) -> None:
        while True:
            message = json.loads(await socket.recv())
            if message.get("type") == "event":
                data = (message.get("event") or {}).get("data") or {}
                for callback in list(self._subscribers):
                    try:
                        callback(data)
                    except Exception:
                        log.exception("a house subscriber failed")
                continue
            future = self._waiting.pop(message.get("id"), None)
            if future is None or future.done():
                continue
            if message.get("success", True):
                future.set_result(message.get("result"))
            else:
                error = message.get("error") or {}
                future.set_exception(HouseError(str(error.get("message") or error)))

    async def _drop(self, why: str) -> None:
        self.connected = False
        socket, self._socket = self._socket, None
        for future in self._waiting.values():
            if not future.done():
                future.set_exception(HouseError(f"Home Assistant went away ({why})"))
        self._waiting.clear()
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()

    async def call(self, kind: str, timeout: float = CALL_TIMEOUT_S, **payload: Any) -> Any:
        """One command; its ``result``. Raises HouseError when it can't be done."""
        socket = self._socket
        if socket is None or not self.connected:
            raise HouseError(
                f"Home Assistant is out of reach ({self.last_error or 'not connected'})"
            )
        self._ids += 1
        call_id = self._ids
        future = asyncio.get_running_loop().create_future()
        self._waiting[call_id] = future
        try:
            await socket.send(json.dumps({"id": call_id, "type": kind, **payload}))
            # asyncio.wait, not wait_for: on Python 3.11 wait_for can swallow a
            # cancel that lands as the answer arrives, and close() would hang.
            done, _ = await asyncio.wait({future}, timeout=timeout)
            if not done:
                raise HouseError("Home Assistant didn't answer in time")
            return future.result()
        finally:
            self._waiting.pop(call_id, None)

    async def states(self) -> list[dict]:
        return await self.call("get_states") or []

    async def areas(self) -> list[dict]:
        return await self.call("config/area_registry/list") or []

    async def entities(self) -> list[dict]:
        return await self.call("config/entity_registry/list") or []

    async def exposed(self, registry: list[dict] | None = None) -> set[str]:
        """The entities exposed to Assist: the only ones Kit may see or touch."""
        try:
            found = await self.call("homeassistant/expose_entity/list")
            exposed = (found or {}).get("exposed_entities", {})
            return {e for e, to in exposed.items() if (to or {}).get("conversation")}
        except HouseError:
            # An older Home Assistant: the entity registry's own flag.
            registry = registry if registry is not None else await self.entities()
            return {
                e["entity_id"]
                for e in registry
                if ((e.get("options") or {}).get("conversation") or {}).get("should_expose")
            }

    async def current_user(self) -> dict:
        return await self.call("auth/current_user") or {}

    async def call_service(
        self, domain: str, service: str, data: dict | None = None, entity: str | None = None
    ) -> Any:
        payload: dict[str, Any] = {"domain": domain, "service": service}
        if data:
            payload["service_data"] = data
        if entity:
            payload["target"] = {"entity_id": entity}
        return await self.call("call_service", **payload)
