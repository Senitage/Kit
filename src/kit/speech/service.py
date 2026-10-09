"""Runs the chosen voice engine as a background program and asks it for speech.

The engine runs in its own process (``worker.py``) with whichever Python has it
installed, so engines with clashing libraries can each have their own virtual
environment. Switching ``speech.engine`` stops the old program, which also frees
the graphics card memory it held, and starts the new one on the next line.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

import httpx

from kit.paths import KitPaths
from kit.settings import SpeechEngine, SpeechSettings

log = logging.getLogger(__name__)

WORKER = Path(__file__).with_name("worker.py")
RETRY_S = 60  # after an engine fails to start, wait this long before trying again


class SpeechError(Exception):
    """The voice engine couldn't start or couldn't say a line."""


class Process(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


def launch(command: list[str], log_file: IO) -> Process:
    return subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)


@dataclass
class Spoken:
    wav: bytes
    synth_ms: float
    audio_ms: float
    engine: str


def speech_dir(paths: KitPaths) -> Path:
    return paths.state_dir / "speech"


def resolve(value: str, folder: Path) -> Path | None:
    """A file setting as a path: ``~`` expanded, a bare name looked for in ``folder``."""
    if not value:
        return None
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else folder / path


class SpeechService:
    def __init__(
        self,
        settings: Callable[[], SpeechSettings],
        paths: KitPaths,
        launcher: Callable[[list[str], IO], Process] = launch,
        http: httpx.Client | None = None,
        port_offset: int = 0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.paths = paths
        self.launcher = launcher
        self.http = http or httpx.Client(timeout=httpx.Timeout(5.0, read=120.0), trust_env=False)
        self.port_offset = port_offset
        self.sleep, self.clock = sleep, clock
        self._lock = threading.RLock()
        self._process: Process | None = None
        self._log: IO | None = None
        self._key: tuple | None = None
        self.health: dict = {}
        self.note = ""  # anything Dan should know about the running engine
        self.load_s: float | None = None
        self._failed: tuple[tuple, float, str] | None = None  # (key, when, why)
        self._making = 0  # sentences being made right now
        self._made_at = float("-inf")  # when the last one was done
        self._making_lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.settings().port + self.port_offset}"

    def options(self, profile: SpeechEngine) -> dict:
        """Engine options for the worker, with file settings made into real paths."""
        options = profile.model_dump(mode="json", exclude={"kind", "python"})
        self.note = ""
        folder = speech_dir(self.paths)
        if profile.kind in ("chatterbox", "chatterbox-turbo"):
            reference = resolve(profile.reference, folder)
            if reference is not None and not reference.exists():
                self.note = f"no voice clip at {reference}, so Chatterbox uses its own voice"
                reference = None
            options["reference"] = str(reference) if reference else ""
        if profile.kind == "piper":
            voice = resolve(profile.voice, folder / "models")
            options["voice"] = str(voice) if voice else ""
        return options

    def command(self, name: str, profile: SpeechEngine, port: int) -> list[str]:
        python = os.path.expanduser(profile.python) if profile.python else sys.executable
        return [
            python,
            str(WORKER),
            "--engine",
            name,
            "--kind",
            profile.kind,
            "--port",
            str(port),
            "--options",
            json.dumps(self.options(profile)),
            "--models-dir",
            str(speech_dir(self.paths) / "models"),
            "--warm-up",
            "--parent",
            str(os.getpid()),
        ]

    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def ensure(self, engine: str | None = None) -> dict:
        """Start the engine (``speech.engine`` unless named) if it isn't already
        running with these settings; returns its health."""
        with self._lock:
            s = self.settings()
            name = engine or s.engine
            if name not in s.engines:
                raise SpeechError(f"there's no voice engine called {name!r}")
            profile = s.engines[name]
            port = s.port + self.port_offset
            # The options include whether the voice clip exists, so adding one restarts.
            key = (name, profile.python, json.dumps(self.options(profile), sort_keys=True), port)
            if self.running() and key == self._key:
                return self.health
            if self._failed and self._failed[0] == key and self.clock() - self._failed[1] < RETRY_S:
                raise SpeechError(self._failed[2])  # don't keep reloading a broken engine
            self.stop()
            try:
                self._start(name, profile, port, s.load_timeout_s)
            except SpeechError as e:
                self._failed = (key, self.clock(), str(e))
                raise
            self._key, self._failed = key, None
            return self.health

    def _start(self, name: str, profile: SpeechEngine, port: int, timeout_s: float) -> None:
        folder = speech_dir(self.paths)
        (folder / "models").mkdir(parents=True, exist_ok=True)
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.paths.logs_dir / "speech.log"
        self._log = log_path.open("a", encoding="utf-8")
        command = self.command(name, profile, port)
        log.info("starting voice engine %s", name)
        start = self.clock()
        try:
            self._process = self.launcher(command, self._log)
        except OSError as e:
            raise SpeechError(f"couldn't start {name} with {command[0]}: {e}") from e
        while self.clock() - start < timeout_s:
            if self._process.poll() is not None:
                self._close_log()
                raise SpeechError(f"{name} stopped while loading: {last_line(log_path)}")
            try:
                self.health = self.http.get(f"http://127.0.0.1:{port}/health").json()
                self.load_s = self.clock() - start
                log.info("voice engine %s ready in %.1f s", name, self.load_s)
                return
            except (httpx.HTTPError, ValueError):
                self.sleep(0.5)
        self.stop()
        raise SpeechError(f"{name} didn't finish loading in {timeout_s:.0f} s; see {log_path}")

    def speak(
        self, text: str, mood: str = "neutral", engine: str | None = None, first: bool = False
    ) -> Spoken:
        """``first``: the opening of a reply, where an engine may add a sound (a sigh)."""
        with self._making_lock:
            self._making += 1
        try:
            return self._speak(text, mood, engine, first)
        finally:
            with self._making_lock:
                self._making -= 1
                self._made_at = self.clock()

    def quiet_s(self) -> float:
        """Seconds since Kit's voice was last being made (0 while it is), so other work
        on the GPU can wait for a quiet moment rather than make him stutter."""
        with self._making_lock:
            return 0.0 if self._making else max(0.0, self.clock() - self._made_at)

    def _speak(self, text: str, mood: str, engine: str | None, first: bool) -> Spoken:
        health = self.ensure(engine)
        payload = {"text": text, "mood": mood, "first": first}
        try:
            r = self.http.post(f"{self._url()}/speak", json=payload)
        except httpx.HTTPError as e:
            raise SpeechError(f"the voice engine didn't answer: {type(e).__name__}") from e
        if r.status_code != 200:
            try:
                message = r.json().get("error", r.text)
            except ValueError:
                message = r.text
            raise SpeechError(f"the voice engine couldn't say that: {message}")
        return Spoken(
            wav=r.content,
            synth_ms=float(r.headers.get("X-Synth-Ms", 0)),
            audio_ms=float(r.headers.get("X-Audio-Ms", 0)),
            engine=health.get("engine", ""),
        )

    def _url(self) -> str:
        return f"http://127.0.0.1:{self._key[-1]}" if self._key else self.url

    def status(self) -> dict:
        s = self.settings()
        return {
            "enabled": s.enabled,
            "engine": s.engine,
            "kind": s.profile.kind,
            "running": self.running(),
            "loaded": self.health.get("engine") if self.running() else None,
            "device": self.health.get("device") if self.running() else None,
            "load_s": self.load_s,
            "note": self.note,
            "engines": {name: e.kind for name, e in s.engines.items()},
        }

    def stop(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    kill = getattr(self._process, "kill", None)
                    if kill:
                        kill()
            self._process, self._key, self.health = None, None, {}
            self._close_log()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None


def last_line(path: Path) -> str:
    try:
        lines = [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x]
    except OSError:
        return "no log"
    return lines[-1] if lines else "no log"
