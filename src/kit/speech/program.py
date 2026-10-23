"""The voice program (``kit voice``): Kit's voice made on this computer's graphics
card while his brain runs on another machine.

It runs on the PC with the card (in WSL, as its own small service, never as Kit's
server) and dials out to Kit over a WebSocket, so nothing here listens on the
network. Kit says which engine to load, the profile from his settings with his
voice clip, and the program starts it with the speech worker (worker.py) on this
machine, just as Kit's server would, CUDA graph and all. Then it makes each line
Kit hands it and sends the sound back in pieces as they're made. The messages are
in kit.speech.link.

If the connection drops it dials again after a second, then longer, up to 30 s.
The engine stays loaded meanwhile, so when Kit is back the voice is too.

Its few files live in ``~/.config/kit-voice`` (``%APPDATA%\\Kit Voice`` on Windows,
or wherever ``KIT_VOICE_DIR`` points): Kit's address and token (``kit voice
connect URL TOKEN``), the voice clip Kit sent, and the engine's log. It never
reads Kit's data folder, since on the PC that may be an old copy of it.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import json
import logging
import os
import socket
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import kit
from kit.eyes import link as eyes_link
from kit.paths import KitPaths
from kit.settings import SpeechSettings
from kit.speech.service import SpeechError, SpeechService, Stale, speech_dir

log = logging.getLogger(__name__)

VOICE_DIR_ENV = "KIT_VOICE_DIR"
PORT = 8611  # the engine's own port on this machine (127.0.0.1 only)
LINK_PATH = "/api/speech/link"
RETRY_S = (1, 2, 5, 10, 30)  # waits between dialling attempts, the last repeating
WRONG_TOKEN_S = 60  # Kit said no: the token won't change by itself, so wait longer
MAX_MESSAGE = 64 * 1024 * 1024  # an engine message carries the voice clip


def voice_dir() -> Path:
    override = os.environ.get(VOICE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Kit Voice"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kit-voice"


def save_connection(url: str, token: str, folder: Path | None = None) -> Path:
    return eyes_link.save_connection(url, token, folder or voice_dir())


@dataclass
class Connection:
    url: str
    token: str


def find_connection(
    url: str | None = None, token: str | None = None, folder: Path | None = None
) -> Connection | None:
    """Kit's address and token: from the command line, else this program's folder."""
    folder = folder or voice_dir()
    try:
        saved = tomllib.loads((folder / eyes_link.CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        saved = {}
    try:
        saved_token = (folder / eyes_link.TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        saved_token = ""
    url = (url or str(saved.get("brain_url", ""))).rstrip("/")
    token = (token or saved_token).strip()
    return Connection(url, token) if url and token else None


def link_address(url: str) -> str:
    """Kit's address as the link's WebSocket address: http -> ws, https -> wss."""
    scheme, rest = url.rstrip("/").split("://", 1) if "://" in url else ("http", url)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}{LINK_PATH}"


def ipv4_only(url: str) -> bool:
    """Dial over IPv4 unless the address is an IPv6 one. Kit listens on IPv4, and a
    name with an IPv6 address too (a Tailscale name) is otherwise tried over IPv6
    first, which can hold every new connection up by 2 s (as kit.desk.client says)."""
    host = url.split("://", 1)[-1].split("/", 1)[0]
    return not host.startswith("[")


class VoiceProgram:
    """Dials in to Kit and makes his lines with an engine on this machine.

    ``connect`` opens the WebSocket (websockets' own, or a fake in tests) and
    ``service`` runs the engine (a SpeechService on this machine's folder)."""

    def __init__(
        self,
        url: str,
        token: str,
        folder: Path | None = None,
        python: str = "",
        port: int = PORT,
        connect: Callable | None = None,
        service: SpeechService | None = None,
        name: str | None = None,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self.url, self.token = url, token
        self.folder = folder or voice_dir()
        self.python, self.port = python, port
        self.connect = connect
        self.paths = KitPaths(self.folder)
        self._settings: SpeechSettings | None = None
        self.service = service or SpeechService(self._current, self.paths)
        self.name = name or socket.gethostname()
        self.sleep = sleep
        self.engine = ""  # the engine loaded for Kit, by its name in his settings
        self.stopping = False

    def _current(self) -> SpeechSettings:
        if self._settings is None:
            raise SpeechError("Kit hasn't said which engine to load yet")
        return self._settings

    async def run(self) -> None:
        """Dial in, and dial again whenever the link drops, until stopped."""
        tries = 0
        while not self.stopping:
            wait = RETRY_S[min(tries, len(RETRY_S) - 1)]
            try:
                async with self._open() as ws:
                    tries = 0
                    log.info("connected to Kit at %s", self.url)
                    await self.session(ws)
                    log.info("Kit closed the link")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # can't reach him, or the link broke
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (401, 403):
                    wait = WRONG_TOKEN_S
                    log.warning(
                        "Kit said no to the token: check it with `kit token` on his server "
                        "and save it with `kit voice connect URL TOKEN`"
                    )
                else:
                    log.warning("can't reach Kit at %s (%s: %s)", self.url, type(e).__name__, e)
                tries += 1
            if not self.stopping:
                await self.sleep(wait)

    def _open(self):
        if self.connect is not None:
            return self.connect(self.url, self.token)
        from websockets.asyncio.client import connect

        options = {"family": socket.AF_INET} if ipv4_only(self.url) else {}
        return connect(
            link_address(self.url),
            additional_headers={"Authorization": f"Bearer {self.token}"},
            ping_interval=5,
            ping_timeout=10,
            max_size=MAX_MESSAGE,
            open_timeout=10,
            **options,
        )

    async def session(self, ws) -> None:
        """One connection: say hello, then answer Kit until it closes."""
        loop = asyncio.get_running_loop()
        outbox: asyncio.Queue = asyncio.Queue()

        def post(message) -> None:  # from any thread
            loop.call_soon_threadsafe(outbox.put_nowait, message)

        async def send() -> None:
            while True:
                message = await outbox.get()
                await ws.send(message if isinstance(message, bytes) else _json(message))

        await ws.send(_json({"type": "hello", "name": self.name, "version": kit.__version__}))
        sender = asyncio.create_task(send())
        lines: dict[int, threading.Event] = {}
        work: set[asyncio.Task] = set()
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                message = _parse(raw)
                kind = message.get("type")
                if kind == "engine":
                    task = asyncio.create_task(asyncio.to_thread(self.load, message, post))
                elif kind == "speak":
                    number = int(message.get("id", 0))
                    stop = lines.setdefault(number, threading.Event())
                    task = asyncio.create_task(asyncio.to_thread(self.make, message, post, stop))
                    task.add_done_callback(functools.partial(_drop, lines, number))
                elif kind == "cancel" and message.get("id") in lines:
                    lines[message["id"]].set()
                    continue
                else:
                    continue
                work.add(task)
                task.add_done_callback(work.discard)
        finally:
            for stop in lines.values():
                stop.set()  # Kit's gone: no one to send the rest to
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender

    def load(self, message: dict, post: Callable) -> None:
        """Load the engine Kit asked for (or none), then say whether it's ready."""
        key = message.get("key", "")
        name = str(message.get("name") or "")
        if not name:
            self.engine, self._settings = "", None
            self.service.stop()
            log.info("Kit's speech is off here: the engine is stopped")
            return
        try:
            settings = self._settings_for(message)
        except Exception as e:
            post({"type": "failed", "key": key, "error": f"{type(e).__name__}: {e}"})
            return
        self._settings, self.engine = settings, name
        log.info("loading %s for Kit...", name)
        try:
            health = self.service.ensure(name)
        except SpeechError as e:
            log.warning("%s couldn't load: %s", name, e)
            post({"type": "failed", "key": key, "error": str(e)})
            return
        if self.service.load_s is not None:
            log.info("%s is ready on %s", name, health.get("device"))
        post({"type": "ready", "key": key, "health": health})

    def _settings_for(self, message: dict) -> SpeechSettings:
        """Speech settings with just this engine, the clip saved in this folder."""
        name = message["name"]
        profile = dict(message.get("profile") or {})
        profile["remote"] = False  # it's made right here
        if self.python:
            profile["python"] = self.python
        clip_name = Path(str(message.get("clip_name") or "")).name
        if clip_name and message.get("clip"):
            folder = speech_dir(self.paths)
            folder.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(message["clip"])
            clip = folder / clip_name
            if not clip.is_file() or clip.read_bytes() != data:
                clip.write_bytes(data)
            profile["reference"] = clip_name
        else:
            profile["reference"] = ""
        return SpeechSettings.model_validate(
            {
                "enabled": True,
                "engine": name,
                "engines": {name: profile},
                "port": self.port,
                "load_timeout_s": message.get("load_timeout_s") or 240,
            }
        )

    def make(self, message: dict, post: Callable, stop: threading.Event) -> None:
        """Make one line and send it back in pieces, unless Kit stops it."""
        number = int(message.get("id", 0))
        start = time.perf_counter()
        try:
            said = self.service.stream(
                str(message.get("text", "")),
                str(message.get("mood", "neutral")),
                self.engine or None,
                bool(message.get("first")),
                message.get("generation"),
            )
        except Stale as e:
            post({"type": "error", "id": number, "error": str(e), "stale": True})
            return
        except SpeechError as e:
            post({"type": "error", "id": number, "error": str(e), "stale": False})
            return
        post({"type": "start", "id": number, "rate": said.rate, "synth_ms": said.synth_ms})
        head = number.to_bytes(4, "big")
        samples = 0
        pieces = said.pieces
        try:
            for piece in pieces:
                if stop.is_set():
                    return
                samples += len(piece) // 2
                post(head + piece)
            post({"type": "end", "id": number})
        except SpeechError as e:
            post({"type": "error", "id": number, "error": str(e), "stale": False})
        finally:
            pieces.close()
            took = time.perf_counter() - start
            log.info(
                "line: first sound %.2f s, %.2f s for %.1f s of speech%s",
                said.synth_ms / 1000,
                took,
                samples / max(said.rate, 1),
                " (stopped by Kit)" if stop.is_set() else "",
            )

    def close(self) -> None:
        self.stopping = True
        self.service.close()


def _drop(lines: dict, number: int, _task) -> None:
    lines.pop(number, None)


def _json(message: dict) -> str:
    return json.dumps(message)


def _parse(raw: str) -> dict:
    try:
        message = json.loads(raw)
    except ValueError:
        return {}
    return message if isinstance(message, dict) else {}
