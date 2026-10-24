"""Runs the chosen voice engine as a background program and asks it for speech.

The engine runs in its own process (``worker.py``) with whichever Python has it
installed, so engines with clashing libraries can each have their own virtual
environment. Switching ``speech.engine`` stops the old program, which also frees
the graphics card memory it held, and starts the new one on the next line.

If his usual engine can't start or runs out of graphics card memory, and
``speech.fallback`` names another (Kokoro on the CPU), Kit switches to it and
stays on it until his speech settings change, so his voice carries on.

A line comes back from the engine in pieces as it's made (``stream``: 16-bit
samples, the first within a few hundred milliseconds on Chatterbox Turbo), so
the desk can start playing it before the rest exists. ``speak`` gathers the
pieces into one WAV for callers that want the whole clip (``kit speech say``,
the bench).

A profile with ``remote = true`` is made by the voice program on another computer
(kit.speech.link): nothing is started here for it, and while the program isn't
connected or ready, Kit speaks with ``speech.fallback``, kept loaded here beside it.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol

import httpx

from kit.paths import KitPaths
from kit.settings import SpeechEngine, SpeechSettings

if TYPE_CHECKING:
    from kit.speech.link import VoiceLink

log = logging.getLogger(__name__)

WORKER = Path(__file__).with_name("worker.py")
RETRY_S = 60  # after an engine fails to start, wait this long before trying again
# What a GPU engine says when the card is full (PyTorch, the CUDA driver, cuBLAS). Not
# just "cuda": "no CUDA device" or "cudart not found" is a different kind of trouble.
OUT_OF_MEMORY = re.compile(
    r"(?i:out of memory)|CUDA_ERROR_OUT_OF_MEMORY|cudaErrorMemoryAllocation|"
    r"CUBLAS_STATUS_ALLOC_FAILED"
)


class SpeechError(Exception):
    """The voice engine couldn't start or couldn't say a line."""


class Loading(SpeechError):
    """The voice engine is still loading: ask again in a moment."""


class Stale(SpeechError):
    """The line belongs to a reply that's been overtaken, so it wasn't made."""


class NotConnected(SpeechError):
    """The voice program for a remote engine isn't dialled in."""


class Process(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


def launch(command: list[str], log_file: IO) -> Process:
    return subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)


@dataclass
class Spoken:
    """A whole line as a WAV file."""

    wav: bytes
    synth_ms: float
    audio_ms: float
    engine: str


@dataclass
class Speech:
    """A line as it's made: ``pieces`` yields 16-bit mono samples at ``rate``, the
    first already in hand when the engine answered (``synth_ms`` is its timing)."""

    rate: int
    synth_ms: float
    engine: str
    pieces: Iterator[bytes] = field(repr=False)


def pcm_wav(pcm: bytes, rate: int) -> bytes:
    """16-bit mono samples as a WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


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
        link: VoiceLink | None = None,
    ) -> None:
        from kit.speech.link import VoiceLink

        self.settings = settings
        self.link = link or VoiceLink()
        self.paths = paths
        self.launcher = launcher
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(5.0, read=120.0),
            limits=httpx.Limits(keepalive_expiry=60.0),  # the worker's socket stays open
            trust_env=False,
        )
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
        self._closing = False  # Kit is shutting down: no more starting engines
        self._loader: threading.Thread | None = None  # an engine loading in the background
        self.generation: int | None = None  # the newest reply a line has come from
        # On the fallback engine: (the speech settings it happened under, why).
        self.fell_back: tuple[str, str] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.settings().port + self.port_offset}"

    def options(self, profile: SpeechEngine) -> dict:
        """Engine options for the worker, with file settings made into real paths."""
        options = profile.model_dump(mode="json", exclude={"kind", "python", "remote"})
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

    def _key_for(self, name: str) -> tuple:
        s = self.settings()
        if name not in s.engines:
            raise SpeechError(f"there's no voice engine called {name!r}")
        profile = s.engines[name]
        # The options include whether the voice clip exists, so adding one restarts.
        return (
            name,
            profile.python,
            json.dumps(self.options(profile), sort_keys=True),
            s.port + self.port_offset,
        )

    def _failed_lately(self, key: tuple) -> str | None:
        """Why this engine failed, if it did within the last ``RETRY_S``: it isn't
        reloaded straight away."""
        if self._failed and self._failed[0] == key and self.clock() - self._failed[1] < RETRY_S:
            return self._failed[2]
        return None

    def ready(self, engine: str | None = None) -> bool:
        """Is the engine up with the current settings? Doesn't wait on a load."""
        return self.running() and self._key == self._key_for(engine or self.settings().engine)

    def load_soon(self, engine: str | None = None) -> None:
        """Start loading the engine in the background, unless one is loading already."""
        with self._making_lock:
            if self._loader is not None and self._loader.is_alive():
                return

            def load() -> None:
                try:
                    self.ensure(engine)
                except SpeechError as e:
                    log.warning("voice engine: %s", e)

            self._loader = threading.Thread(target=load, name="kit-voice-load", daemon=True)
            self._loader.start()

    def ensure(self, engine: str | None = None) -> dict:
        """Start the engine (``speech.engine`` unless named) if it isn't already
        running with these settings; returns its health. Waits for the load."""
        with self._lock:
            if self._closing:
                raise SpeechError("Kit is shutting down")
            s = self.settings()
            name = engine or s.engine
            if name in s.engines and s.engines[name].remote:
                return self._ensure_remote(name)
            key = self._key_for(name)
            profile, port = s.engines[name], key[-1]
            if self.running() and key == self._key:
                return self.health
            if (why := self._failed_lately(key)) is not None:
                raise SpeechError(why)  # don't keep reloading a broken engine
            self.stop()
            try:
                self._start(name, profile, port, s.load_timeout_s)
            except SpeechError as e:
                self._failed = (key, self.clock(), str(e))
                raise
            self._key, self._failed = key, None
            return self.health

    def keep_ready(self) -> None:
        """Have loaded what Kit speaks with now, for the speech loop: the fallback
        once it has taken over (not his usual engine, which would stop the fallback
        to try again every minute). With a remote engine, ask the voice program to
        load it and keep a fallback loaded here beside it, so a dropped link carries
        straight on."""
        s = self.settings()
        if not s.engines[s.engine].remote:
            self.link.unload()  # frees the other computer's graphics card
            self.ensure(self.in_use())
            return
        self.offer_link()
        if s.fallback and s.fallback != s.engine and not s.engines[s.fallback].remote:
            self.ensure(s.fallback)
        elif self.running():
            self.stop()
        if self.link.state == "failed":
            self._ensure_remote(s.engine)  # says why, once, in the loop's log

    def offer_link(self) -> None:
        """Ask a connected voice program for the remote engine Kit speaks with, if
        it hasn't been asked already. Doesn't wait: it says when it's ready."""
        s = self.settings()
        if s.engines[s.engine].remote:
            with contextlib.suppress(Loading, NotConnected):
                self._ensure_remote(s.engine)

    def idle(self) -> None:
        """Speech is off: stop the engine here and free the other computer's card."""
        if self.running():
            self.stop()
        self.link.unload()

    def _remote_message(self, name: str) -> dict:
        """The engine message for a remote engine's voice program: the profile from
        Kit's settings, with the voice clip itself, since that lives in his data
        folder and not on the other computer."""
        s = self.settings()
        profile = s.engines[name]
        data = profile.model_dump(mode="json", exclude={"remote"})
        clip, clip_name = "", ""
        if profile.kind in ("chatterbox", "chatterbox-turbo"):
            reference = resolve(profile.reference, speech_dir(self.paths))
            self.note = ""
            if reference is not None and reference.is_file():
                clip_name = reference.name
                clip = base64.b64encode(reference.read_bytes()).decode("ascii")
            elif reference is not None:
                self.note = f"no voice clip at {reference}, so Chatterbox uses its own voice"
                log.warning("voice link: %s (it must be on this machine)", self.note)
        data["reference"] = clip_name
        return {
            "name": name,
            "profile": data,
            "clip_name": clip_name,
            "clip": clip,
            "load_timeout_s": s.load_timeout_s,
        }

    def _remote_key(self, name: str) -> str:
        """What a remote engine is loaded with: a change to any of it (the clip
        too) has the voice program load it again."""
        s = self.settings()
        profile = s.engines[name]
        reference = resolve(profile.reference, speech_dir(self.paths))
        try:
            clip = reference.stat() if reference is not None else None
            clip_key = [clip.st_size, clip.st_mtime_ns] if clip else None
        except OSError:
            clip_key = None
        data = profile.model_dump(mode="json", exclude={"remote"})
        return json.dumps([name, data, clip_key, s.load_timeout_s], sort_keys=True)

    def _ensure_remote(self, name: str) -> dict:
        """Ask the voice program for a remote engine; its health once it's ready."""
        key = self._remote_key(name)
        link = self.link
        if not link.connected:
            raise NotConnected(f"the voice program for {name} isn't connected (kit voice)")
        if link.key != key or link.state == "failed":
            link.load(key, self._remote_message(name), retry_s=RETRY_S)
        if link.ready_for(key):
            return link.health
        if link.state == "failed" and link.key == key:
            raise SpeechError(f"{name} couldn't load on {link.name}: {link.why}")
        raise Loading(f"Kit's voice ({name}) is still loading on {link.name}")

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
            if self._closing:
                self.stop()
                raise SpeechError(f"Kit is shutting down, so {name} wasn't loaded")
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
        self,
        text: str,
        mood: str = "neutral",
        engine: str | None = None,
        first: bool = False,
        generation: int | None = None,
        wait: bool = True,
    ) -> Spoken:
        """The whole line as a WAV file (``stream`` gathered up), for callers that
        want it in one piece: ``kit speech say``, the bench, older desks."""
        said = self.stream(text, mood, engine, first, generation, wait)
        start = self.clock()
        pcm = b"".join(said.pieces)
        return Spoken(
            wav=pcm_wav(pcm, said.rate),
            synth_ms=said.synth_ms + 1000 * (self.clock() - start),
            audio_ms=1000 * len(pcm) / (2 * said.rate),
            engine=said.engine,
        )

    def stream(
        self,
        text: str,
        mood: str = "neutral",
        engine: str | None = None,
        first: bool = False,
        generation: int | None = None,
        wait: bool = True,
    ) -> Speech:
        """The line as the engine makes it: ``Speech`` whose pieces are 16-bit samples,
        the first already made. ``first``: the opening of a reply, where an engine may
        add a sound (a sigh). ``generation`` numbers the reply: once a higher number
        has been seen, lines from a lower one are stale (``Stale``) and aren't made,
        and a line under way stops at its next piece. With ``wait`` off, an engine
        that isn't up is started in the background and ``Loading`` raised, so a
        caller isn't held for the minutes a load can take. His voice counts as being
        made (``quiet_s``) until the last piece has been taken."""
        if generation is not None and self._stale(generation):
            raise Stale(f"reply {generation} was interrupted, so that line wasn't made")
        with self._making_lock:
            self._making += 1
        done = False

        def finish() -> None:
            nonlocal done
            if not done:
                done = True
                with self._making_lock:
                    self._making -= 1
                    self._made_at = self.clock()

        try:
            said = self._speak(text, mood, engine, first, generation, wait)
        except BaseException:
            finish()
            raise
        pieces = said.pieces

        def counted() -> Iterator[bytes]:
            try:
                yield from pieces
            finally:
                finish()

        said.pieces = counted()
        return said

    def quiet_s(self) -> float:
        """Seconds since Kit's voice was last being made (0 while it is), so other work
        on the GPU can wait for a quiet moment rather than make him stutter."""
        with self._making_lock:
            return 0.0 if self._making else max(0.0, self.clock() - self._made_at)

    def _speak(
        self,
        text: str,
        mood: str,
        engine: str | None,
        first: bool,
        generation: int | None,
        wait: bool,
    ) -> Speech:
        name = engine or self.in_use()
        try:
            return self._say(text, mood, name, first, generation, wait)
        except Stale:
            raise  # nothing wrong with the engine
        except SpeechError as e:
            s = self.settings()
            if engine is None and s.engines[name].remote and s.fallback not in ("", name):
                # The link dropped, or the line failed there: this line in the fallback.
                if not isinstance(e, Loading):
                    log.warning("voice link: %s; saying the line with %s", e, s.fallback)
                return self._say(text, mood, s.fallback, first, generation, wait)
            if isinstance(e, Loading) or engine is not None or not self._fall_back(e):
                raise
            return self._say(text, mood, self.in_use(), first, generation, wait)

    def _stale(self, generation: int) -> bool:
        """Note the newest reply seen; is this line from an older one?"""
        with self._making_lock:
            if self.generation is None or generation > self.generation:
                self.generation = generation
            return generation < self.generation

    def _overtaken(self, generation: int | None) -> bool:
        """Has a newer reply been seen since this line began?"""
        with self._making_lock:
            return (
                generation is not None
                and self.generation is not None
                and generation < self.generation
            )

    def in_use(self) -> str:
        """The engine Kit speaks with: ``speech.engine``, or ``speech.fallback`` once
        that has had to take over (until his speech settings change)."""
        s = self.settings()
        if s.engines[s.engine].remote:
            # The other computer's voice while its program is up and ready; the
            # fallback here meanwhile, and his usual voice again the moment it's back.
            if s.fallback in ("", s.engine) or self.link.ready_for(self._remote_key(s.engine)):
                return s.engine
            return s.fallback
        if self.fell_back is not None:
            if self.fell_back[0] == self._settings_key(s) and s.fallback:
                return s.fallback
            self.fell_back = None  # the settings changed: his usual engine gets another go
        return s.engine

    def _fall_back(self, error: SpeechError) -> bool:
        """His usual engine failed: switch to the fallback, if there is one and the
        failure is one it can help with (couldn't start, or out of memory)."""
        s = self.settings()
        why = str(error)
        started = self.running() and self._key is not None and self._key[0] == s.engine
        if (
            s.engines[s.engine].remote
            or self.fell_back is not None
            or not s.fallback
            or s.fallback == s.engine
            or (started and not OUT_OF_MEMORY.search(why))
        ):
            return False
        log.warning("voice engine %s failed (%s): switching to %s", s.engine, why, s.fallback)
        self.stop()  # frees the graphics card memory it held
        self.fell_back = (self._settings_key(s), why)
        return True

    @staticmethod
    def _settings_key(s: SpeechSettings) -> str:
        return json.dumps(s.model_dump(mode="json"), sort_keys=True)

    def _say(
        self, text: str, mood: str, engine: str, first: bool, generation: int | None, wait: bool
    ) -> Speech:
        if self.settings().engines[engine].remote:
            self._ensure_remote(engine)
            said = self.link.speak(text, mood, first, generation)
            said.pieces = self._overtakable(said.pieces, generation)
            return said
        if not wait and not self.ready(engine):
            if (why := self._failed_lately(self._key_for(engine))) is not None:
                raise SpeechError(why)
            self.load_soon(engine)
            raise Loading(f"Kit's voice ({engine}) is still loading; ask again in a moment")
        health = self.ensure(engine)
        payload = {"text": text, "mood": mood, "first": first, "generation": generation}
        try:
            request = self.http.build_request("POST", f"{self._url()}/speak", json=payload)
            r = self.http.send(request, stream=True)
        except httpx.HTTPError as e:
            raise SpeechError(f"the voice engine didn't answer: {type(e).__name__}") from e
        if r.status_code != 200:
            r.read()
            r.close()
            if r.status_code == 410:
                raise Stale(f"reply {generation} was interrupted, so that line wasn't made")
            try:
                message = r.json().get("error", r.text)
            except ValueError:
                message = r.text
            raise SpeechError(f"the voice engine couldn't say that: {message}")
        rate = int(r.headers.get("X-Sample-Rate") or health.get("sample_rate") or 24000)
        return Speech(
            rate=rate,
            synth_ms=float(r.headers.get("X-Synth-Ms", 0)),
            engine=health.get("engine", ""),
            pieces=self._pieces(r, generation),
        )

    def _overtakable(self, pieces: Iterator[bytes], generation: int | None) -> Iterator[bytes]:
        """A remote line's pieces, stopping once the reply is overtaken (closing them
        tells the voice program to stop making it)."""
        try:
            for piece in pieces:
                if self._overtaken(generation):
                    log.info("reply %s was interrupted: dropping the rest of the line", generation)
                    return
                yield piece
        finally:
            pieces.close()

    def _pieces(self, r: httpx.Response, generation: int | None) -> Iterator[bytes]:
        """The engine's answer as it comes, stopping once the reply is overtaken."""
        try:
            for piece in r.iter_bytes():
                if self._overtaken(generation):
                    log.info("reply %s was interrupted: dropping the rest of the line", generation)
                    return
                if piece:
                    yield piece
        except httpx.HTTPError as e:
            raise SpeechError(f"the voice engine broke off: {type(e).__name__}") from e
        finally:
            r.close()

    def _url(self) -> str:
        return f"http://127.0.0.1:{self._key[-1]}" if self._key else self.url

    def status(self) -> dict:
        s = self.settings()
        using = self.in_use()
        remote = s.engines[using].remote
        up = self.link.ready_for(self._remote_key(using)) if remote else self.running()
        health = self.link.health if remote else self.health
        fell_back = self.fell_back[1] if self.fell_back and using != s.engine else None
        if s.engines[s.engine].remote and using != s.engine:
            link = self.link
            fell_back = (
                link.why
                or (f"it's still loading on {link.name}" if link.connected else "")
                or "the voice program isn't connected"
            )
        return {
            "enabled": s.enabled,
            "engine": s.engine,
            "using": using,
            "fell_back": fell_back,
            "kind": s.engines[using].kind,
            "remote": remote,
            "running": up,
            "loaded": health.get("engine") if up else None,
            "device": health.get("device") if up else None,
            "cuda_graph": bool(health.get("cuda_graph")) if up else None,
            "load_s": self.load_s,
            "note": self.note,
            "engines": {name: e.kind for name, e in s.engines.items()},
            "link": self.link.status(),
        }

    def close(self) -> None:
        """Kit is shutting down: stop the engine and don't start it again. An engine
        still loading gives up at once, so a restart isn't held up by a load that
        began after the stop (the service manager stops the engine with Kit)."""
        self._closing = True
        self.stop()

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
