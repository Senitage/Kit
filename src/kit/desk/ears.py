"""Kit's ears inside the desk app: this PC's mic, with nothing else to install.

The same ears as ``kit hearing`` (kit.hearing.run), on a thread of the desk app
and through its connection to the brain, so a PC with the desk app on it needs
no copy of Kit, no Python and no ``kit hearing connect``. The installer carries
sherpa-onnx; the three models download the first time, into the same folder
``kit hearing`` uses (%APPDATA%\\Kit Hearing), so a PC that had them keeps them.

The ears start again by themselves when something they were built with changes:
the brain's address or token, the mic (This PC page), or a ``[hearing]`` setting
that needs the models built again (``kit.hearing.run.RESTART``). "Listen with
this PC's mic" off on the This PC page, or ``hearing.enabled`` false on the brain,
and they don't run at all. The "Let Kit hear me" switch pauses them as it does
``kit hearing``: the mic is let go.

Introducing a voice (``enrol``) holds the ears while it listens, so the mic is
only open once, then lets them carry on.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from kit.desk.client import BrainClient, BrainError
from kit.desk.config import DeskConfig
from kit.settings import HearingSettings

log = logging.getLogger(__name__)

WAIT_S = 3.0  # not set up, or switched off on this PC: look again this often
RETRY_S = 20.0  # the brain or the mic said no: try again after this long
MIC_NAME = "desk"

Build = Callable[..., object]  # kit.hearing.run.build_ears, or a fake in the tests


def _built_with(settings: HearingSettings) -> dict:
    from kit.hearing.run import RESTART

    return {k: getattr(settings, k) for k in sorted(RESTART)}


class DeskEars:
    """Runs Kit's ears for the desk app and says how they are (``status``)."""

    def __init__(
        self,
        client: Callable[[], BrainClient | None],
        config: Callable[[], DeskConfig],
        stop: threading.Event,
        build: Build | None = None,
        parts: Callable[[HearingSettings], tuple] | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self._stop = stop
        self._build = build
        self._parts = parts  # the enrolling mic, VAD and printer (kit.hearing.enrol)
        self._wake = threading.Event()  # look again now: the This PC page saved
        self._hold = threading.Event()  # enrolling: let the mic go and wait
        self._held = threading.Event()  # the ears have let it go
        self.ears = None
        self.status = "Starting..."
        self.available = True  # False when this build of the app has no ears in it
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="kit-ears-desk", daemon=True)
        self._thread.start()

    def changed(self) -> None:
        """The This PC page saved: start again with what it says now."""
        self._wake.set()

    # The loop

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.once()
            except Exception as e:  # never take the desk app down with them
                log.exception("Kit's ears stopped")
                self.status = f"The ears stopped: {type(e).__name__}: {e}"
                wait = RETRY_S
            if wait is None:
                return
            self._wake.wait(wait)
            self._wake.clear()

    def once(self) -> float | None:
        """Build the ears and run them until something they were built with changes.
        Returns how long to wait before trying again, or None to stop for good."""
        self._held.set()
        client, config = self.client(), self.config()
        if not config.hear_here:
            self.status = 'Off on this PC: tick "Listen with this PC\'s mic" to turn them on.'
            return WAIT_S
        if client is None:
            self.status = "Waiting for Kit's address and token."
            return WAIT_S
        try:
            raw = client.settings()["settings"].get("hearing", {})
            settings = HearingSettings.model_validate(raw)
        except BrainError as e:
            self.status = f"Can't reach Kit's brain ({e})."
            return RETRY_S
        except (KeyError, ValueError) as e:
            self.status = f"Kit's brain gave an answer the ears don't understand ({e})."
            return RETRY_S
        if not settings.enabled:
            self.status = "Kit's hearing is off in his settings (hearing.enabled)."
            return RETRY_S
        if config.mic:
            settings = settings.model_copy(update={"mic": config.mic})
        self.status = "Getting the ears ready (the first time downloads about 200 MB)..."
        try:
            ears = self._make(settings, client)
        except ImportError as e:
            self.available = False
            self.status = f"This copy of the desk app has no ears in it ({e})."
            log.warning("no ears in this desk app: %s", e)
            return None
        except ValueError as e:  # no such mic
            self.status = str(e)
            return RETRY_S
        except Exception as e:  # a model that wouldn't download or load
            self.status = f"The ears couldn't start: {type(e).__name__}: {e}"
            log.exception("the ears couldn't start")
            return RETRY_S
        log.info("Kit's ears are open in the desk app (%s)", settings.mic or "the default mic")
        self.ears = ears
        built = _built_with(settings)
        try:
            while not self._stop.is_set():
                if self._hold.is_set():
                    ears.release()
                    self._held.set()
                    self.status = "Introducing a voice: the mic is in use for that."
                    self._stop.wait(0.2)
                    continue
                self._held.clear()
                ears.step()
                self.status = self._describe(ears, settings)
                if self._restart(client, config, ears, built):
                    log.info("the ears start again with the new settings")
                    return 0.0
        finally:
            ears.close()
            self.ears = None
            self._held.set()
        return None

    def _make(self, settings: HearingSettings, client: BrainClient):
        build = self._build
        if build is None:
            from kit.hearing.run import build_ears

            build = build_ears
        return build(settings, client, mic_name=MIC_NAME)

    def _restart(self, client, config: DeskConfig, ears, built: dict) -> bool:
        """Something the ears were built with has changed."""
        now = self.config()
        return (
            self.client() is not client
            or now.hear_here != config.hear_here
            or now.mic != config.mic
            or not ears.settings.enabled
            or _built_with(ears.settings) != built
        )

    @staticmethod
    def _describe(ears, settings: HearingSettings) -> str:
        mic = settings.mic or "the default mic"
        if ears.error:
            return f"Can't reach Kit's brain ({ears.error}); still trying."
        if ears.paused:
            return 'Paused: "Let Kit hear me" is off, so the mic is let go.'
        if ears.mic is None:
            return f"Waiting for the microphone ({mic})."
        return f"Listening with {mic}. Sound stays on this PC."

    # Introducing a voice

    def enrol(self, who: str, seconds: float = 30.0) -> str:
        """Someone reads the lines in kit.hearing.enrol.LINES; their voice prints go
        to the brain. Holds the ears meanwhile. Returns what to tell them; raises
        RuntimeError when it didn't work."""
        from kit.hearing import enrol

        client = self.client()
        if client is None:
            raise RuntimeError("Kit isn't set up yet: fill in his address and token first.")
        self._hold.set()
        try:
            self._held.wait(5.0)
            try:
                raw = client.settings()["settings"].get("hearing", {})
                settings = HearingSettings.model_validate(raw)
                name = enrol.owner(client, who)
            except (BrainError, KeyError, ValueError) as e:
                raise RuntimeError(f"Can't reach Kit's brain ({e}).") from e
            if self.config().mic:
                settings = settings.model_copy(update={"mic": self.config().mic})
            mic = None
            try:
                open_mic, vad, printer = (self._parts or enrol.real_parts)(settings)
                mic = open_mic()
                stretches = enrol.listen_for(mic.read, vad, seconds)
                prints = enrol.voice_prints(stretches, printer)
            except ImportError as e:
                raise RuntimeError(f"This copy of the desk app has no ears in it ({e}).") from e
            except ValueError as e:  # no such mic
                raise RuntimeError(str(e)) from e
            finally:
                if mic is not None:
                    mic.close()
        finally:
            self._hold.clear()
        if len(prints) < 3:
            raise RuntimeError(
                f"I only heard {len(prints)} good stretch(es) of {name} talking. "
                "Try again, a little closer to the mic."
            )
        try:
            done = client.enrol_voice(name, prints)
        except BrainError as e:
            raise RuntimeError(f"Kit's brain didn't take them ({e}).") from e
        return f"Kit knows {done['name']}'s voice now ({done['count']} voice prints)."


def mics() -> list[str]:
    """This PC's microphones by name, for the This PC page; none without sound."""
    try:
        from kit.hearing.mic import input_devices, mic_names

        return mic_names(input_devices())
    except Exception:  # no sound library, or no sound card
        log.debug("couldn't list the mics", exc_info=True)
        return []
