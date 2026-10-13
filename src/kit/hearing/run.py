"""The ears' loop: sound in, words out.

``Ears`` holds the parts (a way to open the mic, the voice detector, the speech
to text, the voice printer, and calls to the brain) and runs them; every part is
passed in, so the tests run it with fakes and no microphone. ``build_ears``
makes the real parts from Kit's settings.

Each pass reads 32 ms from the mic. While someone talks over Kit, the latest
stretch is voice printed every ``hearing.barge_in_ms``: a voice that isn't his
own (from the speakers) stops him. When a stretch of talking ends, it's turned
into words and sent to the brain with how it sounded and whose voice it was;
the brain decides whether it was meant for Kit (kit.heard). At each short pause
the words so far are worked out on another thread, so when the pause turns out
to be the end of the talking they're ready, and the answer comes sooner.

Every few seconds the ears check in with the brain, which answers with the
"Let Kit hear me" switch, the ``[hearing]`` settings, the voices Kit knows and
his voice engine. Paused ears let the mic go. When the voice engine changes,
the ears ask for a few words in Kit's voice to learn its voice print, so they
know him when he comes back through the mic.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from kit.eyes.recognise import Gallery, normalise, similarity
from kit.hearing.engines import (
    CHUNK,
    RATE,
    Stretch,
    Transcriber,
    Transcript,
    Vad,
    VoicePrinter,
    trim_quiet,
)
from kit.known_voices import VOICE_SIZE
from kit.settings import HearingSettings

log = logging.getLogger(__name__)

CHECK_IN_S = 3.0  # how often the ears tell the brain they're listening
MIC_RETRY_S = 5.0  # the mic went away: try it again after this long
BRAIN_RETRY_S = 5.0
PRINT_S = 1.5  # voice print this much of the latest talking, to check who's talking over him
MIN_PRINT_S = 0.5  # shorter than this, a voice print says little
OWN_LINE = "Hello, it's me, Kit. This is how I sound, so I know my own voice."
# Settings that need the models built again: restart `kit hearing` for them.
RESTART = {"mic", "threshold", "pause_ms", "max_speech_s", "language", "threads"}

Call = Callable[[dict], dict]


class Ears:
    def __init__(
        self,
        open_mic: Callable[[], object | None],
        vad: Vad,
        transcriber: Transcriber,
        printer: VoicePrinter | None,
        check_in: Call,
        heard: Call,
        hush: Callable[[], dict],
        settings: HearingSettings | None = None,
        load_voices: Callable[[], dict] | None = None,
        own_voice: Callable[[], np.ndarray | None] | None = None,
        mic_name: str = "desk",
        words: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or HearingSettings()
        self.open_mic = open_mic
        self.vad = vad
        self.transcriber = transcriber
        self.printer = printer
        self._check_in = check_in
        self._heard = heard
        self._hush = hush
        self.load_voices = load_voices  # the people Kit knows by voice, from the brain
        self.own_voice = own_voice  # a few words in Kit's voice, from the brain
        self.mic_name = mic_name
        self.words = words  # show what was heard in this window (`kit hearing --words`)
        self.clock = clock
        self.sleep = sleep
        self.mic = None
        self.paused = False
        self.error = ""
        self.gallery = Gallery({}, self.settings.match, size=VOICE_SIZE)
        self.voices_version: int | None = None
        self.kit_print: list[float] | None = None  # his own voice, to ignore
        self.engine = ""  # the voice engine kit_print came from
        self.heard_count = 0
        self._recent: deque[np.ndarray] = deque(maxlen=int(PRINT_S * RATE / CHUNK))
        self._talking_for = 0.0  # seconds of talking in the stretch so far
        self._checked_at = 0.0  # into the stretch, when it was last checked for talking over
        self._hushed = False  # this stretch already stopped him
        self._last_check_in = -1e9
        self._mic_failed_at: float | None = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ears-ahead")
        # The stretch under way, and its words being got ready at its last short pause.
        self._ready: tuple[Stretch, Future] | None = None

    # One pass of the loop

    def step(self) -> list[dict]:
        """Listen for 32 ms (or, paused, check in with the brain). Returns what the
        brain made of each stretch of talking that ended."""
        now = self.clock()
        if now - self._last_check_in >= CHECK_IN_S:
            self.check_in(now)
        if self.paused:
            self._release()
            self.sleep(0.2)
            return []
        if self.mic is None and not self._open(now):
            self.sleep(0.5)
            return []
        chunk = self.mic.read()
        if chunk is None:
            return []
        self._recent.append(chunk)
        answers = []
        for stretch in self.vad.accept(chunk):
            if stretch.early:
                self._ahead(stretch)
            else:
                answers.append(self.hear(stretch))
        if self.vad.talking():
            self._talking_for += len(chunk) / RATE
            self._maybe_hush()
        else:
            self._talking_for, self._checked_at, self._hushed = 0.0, 0.0, False
        return [a for a in answers if a]

    def run(self, stop: threading.Event | None = None, max_steps: int | None = None) -> None:
        steps = 0
        try:
            while stop is None or not stop.is_set():
                self.step()
                steps += 1
                if max_steps is not None and steps >= max_steps:
                    break
        finally:
            self._release()
            self._pool.shutdown(wait=False, cancel_futures=True)

    # Talking over him

    def _maybe_hush(self) -> None:
        """Someone has talked for ``barge_in_ms``: if it isn't Kit's own voice, stop
        him. Checked again every ``barge_in_ms`` while the talking goes on, because
        Dan may start over the top of a stretch that began as Kit's voice."""
        s = self.settings
        if not s.barge_in or self._hushed or self.printer is None or self.kit_print is None:
            return  # without his voice print, his own voice would stop him every time
        step = s.barge_in_ms / 1000
        if self._talking_for < step or self._talking_for - self._checked_at < step:
            return
        self._checked_at = self._talking_for
        latest = np.concatenate(list(self._recent))
        if len(latest) < MIN_PRINT_S * RATE:
            return
        if self._likeness(normalise(self.printer.print(latest)))[0]:
            return
        self._hushed = True
        try:
            if self._hush().get("hushed"):
                log.info("talked over Kit: he stops")
        except Exception as e:
            log.warning("couldn't stop Kit talking: %s", e)

    def _likeness(self, voice: list[float]) -> tuple[bool, float, str | None, float]:
        """Is this (normalised) voice print Kit's own voice from the speakers, and how
        alike it is to his voice and to the nearest person he knows. It's his only if
        it's closer to him than to anyone he knows: two voices can both be fairly
        alike to his."""
        who, likeness = self.gallery.match(voice) if self.gallery else (None, 0.0)
        kit = similarity(voice, self.kit_print) if self.kit_print is not None else 0.0
        own = self.kit_print is not None and kit >= self.settings.own_voice and kit > likeness
        return own, kit, who, likeness

    # A stretch of talking

    def _ahead(self, stretch: Stretch) -> None:
        """A short pause in the talking: the words so far, and whose voice, are
        worked out now on the other thread. If the talking goes on, the next pause
        starts over with more of it; if it was the end, ``hear`` finds them ready."""
        if self._ready is not None:
            self._ready[1].cancel()  # not started yet: no need now
        self._ready = (stretch, self._pool.submit(self._work_out, stretch))

    def _work_out(self, stretch: Stretch) -> tuple[Transcript, list[float] | None]:
        said = self.transcriber.transcribe(stretch.samples)
        voice_print = None
        if self.printer is not None and len(stretch.voice) >= MIN_PRINT_S * RATE:
            voice_print = normalise(self.printer.print(stretch.voice))
        return said, voice_print

    def _take_ready(self, stretch: Stretch) -> tuple[Transcript, list[float] | None] | None:
        """The words got ready for this stretch, if it's the one they were made from:
        the same start, and the same end give or take a chunk (an early stretch
        ends at the last talking just as the finished one does)."""
        if self._ready is None:
            return None
        early, job = self._ready
        self._ready = None
        if early.start != stretch.start or abs(early.end - stretch.end) > 2 * CHUNK:
            job.cancel()  # the talking went on past that pause
            return None
        try:
            return job.result()
        except Exception as e:  # the model choked on it: do it again here
            log.warning("couldn't get the words ready early: %s", e)
            return None

    def hear(self, stretch: Stretch) -> dict | None:
        """One finished stretch of talking: words, tone, whose voice, to the brain.
        The words come from the stretch and the moment before it; the voice print
        only from the talking itself. Both were got ready at the last short pause
        when the stretch ended there."""
        s = self.settings
        seconds = len(stretch.voice) / RATE
        if seconds < s.min_speech_s:
            self._take_ready(stretch)
            return None
        started = self.clock()
        ready = self._take_ready(stretch)
        if ready is not None:
            said, voice_print = ready
        else:
            said, voice_print = self.transcriber.transcribe(stretch.samples), None
        if not said.text and said.sound != "laughter":
            return None
        who, likeness, own, kit = None, 0.0, False, 0.0
        if self.printer is not None and seconds >= MIN_PRINT_S:
            # Who it is goes too, even when it sounds like Kit: the brain knows
            # whether his voice was playing just then.
            if voice_print is None:
                voice_print = normalise(self.printer.print(stretch.voice))
            own, kit, who, likeness = self._likeness(voice_print)
        heard = {
            "text": said.text,
            "tone": said.tone,
            "sound": said.sound,
            "who": who,
            "likeness": round(likeness, 3),
            "own_voice": own,
            "seconds": round(seconds, 2),
            "mic": self.mic_name,
        }
        try:
            answer = self._heard(heard)
        except Exception as e:
            log.warning("couldn't tell the brain what was heard: %s", e)
            return None
        self.heard_count += 1
        took = self.clock() - started
        # What Kit made of it, not the words: overheard talk stays off the screen too,
        # unless whoever runs the ears asks to see it (--words, for tuning).
        log.info(
            "heard %.1f s%s: %s (%s, %.2f s%s)%s",
            seconds,
            f" from {who}" if who else "",
            answer.get("heard", "?"),
            answer.get("why", ""),
            took,
            ", words ready early" if ready is not None else "",
            f' [like Kit {kit:.2f}, like {who or "anyone known"} {likeness:.2f}]: "{said.text}"'
            if self.words
            else "",
        )
        return answer

    # The brain

    def check_in(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        self._last_check_in = now
        try:
            answer = self._check_in({"mic": self.mic_name, "listening": not self.paused})
        except Exception as e:  # the brain is down or said no: keep going, say so once
            if self.error != str(e):
                log.warning("can't reach the brain: %s", e)
            self.error = str(e)
            self._last_check_in = now - CHECK_IN_S + BRAIN_RETRY_S
            return
        if self.error:
            log.info("back in touch with the brain")
            self.error = ""
        self.apply(answer or {})

    def apply(self, answer: dict) -> None:
        paused = bool(answer.get("paused", False))
        if paused != self.paused:
            log.info("ears %s", "paused: the mic is off" if paused else "on again")
            self.paused = paused
            if paused:
                self._release()
        raw = answer.get("settings")
        if isinstance(raw, dict):
            try:
                fresh = HearingSettings.model_validate(raw)
            except ValueError:
                fresh = self.settings
            if fresh != self.settings:
                changed = {
                    k
                    for k in HearingSettings.model_fields
                    if getattr(fresh, k) != getattr(self.settings, k)
                }
                if changed & RESTART:
                    log.info(
                        "settings changed (%s); restart `kit hearing` for them",
                        ", ".join(sorted(changed & RESTART)),
                    )
                self.settings = fresh
                self.gallery.threshold = fresh.match
        version = answer.get("voices_version")
        if version is not None and version != self.voices_version:
            self._known_voices(version)
        engine = str(answer.get("speech") or "")
        if engine != self.engine:
            self._learn_own_voice(engine)

    def _known_voices(self, version: int) -> None:
        if self.load_voices is None:
            self.voices_version = version
            return
        try:
            known = self.load_voices()
        except Exception as e:  # try again at the next check-in
            log.warning("can't fetch the voices Kit knows: %s", e)
            return
        self.gallery = Gallery(known.get("people", {}), self.settings.match, size=VOICE_SIZE)
        self.voices_version = version
        names = sorted(self.gallery.people)
        log.info("knows the voices of %s", ", ".join(names) if names else "nobody yet")

    def _learn_own_voice(self, engine: str) -> None:
        """His voice engine changed (or the ears just started): learn how he sounds
        now. With his voice off there's nothing to learn, and nothing to ignore."""
        self.engine = engine
        self.kit_print = None
        if not engine or self.own_voice is None or self.printer is None:
            return
        try:
            sample = self.own_voice()
        except Exception as e:
            log.warning("couldn't hear Kit's own voice to learn it: %s", e)
            self.engine = ""  # try again at the next check-in
            return
        sample = trim_quiet(sample) if sample is not None else None
        if sample is None or len(sample) < MIN_PRINT_S * RATE:
            return
        self.kit_print = normalise(self.printer.print(sample))
        log.info("learned Kit's own voice (%s), so it won't stop him or be answered", engine)

    # The mic

    def _open(self, now: float) -> bool:
        if self._mic_failed_at is not None and now - self._mic_failed_at < MIC_RETRY_S:
            return False
        try:
            self.mic = self.open_mic()
        except Exception as e:
            if self._mic_failed_at is None:
                log.error("can't open the microphone: %s", e)
            self.mic = None
        if self.mic is None:
            self._mic_failed_at = now
            return False
        self._mic_failed_at = None
        return True

    def _release(self) -> None:
        if self.mic is not None:
            self.mic.close()
            self.mic = None


def build_ears(
    settings: HearingSettings, client, mic_name: str = "desk", folder=None, words: bool = False
) -> Ears:
    """The real ears: sounddevice mic, Silero VAD, SenseVoice and CAM++ through
    sherpa-onnx. Imports the libraries here, so only this needs them installed.
    ``client`` is a kit.desk.client.BrainClient."""
    from kit.hearing.engines import CamPlusPlus, SenseVoice, SileroVad, wav_samples
    from kit.hearing.link import models_dir
    from kit.hearing.mic import SoundDeviceMic, input_devices, pick_device

    models = models_dir(folder)
    device = pick_device(settings.mic, input_devices()) if settings.mic else None
    vad = SileroVad(models, settings)
    transcriber = SenseVoice(models, settings)
    printer = CamPlusPlus(models, settings)

    def own_voice() -> np.ndarray | None:
        return wav_samples(client.speak(OWN_LINE, "neutral", aloud=False).wav())

    return Ears(
        lambda: SoundDeviceMic(device),
        vad,
        transcriber,
        printer,
        client.report_hearing,
        client.heard,
        client.hush,
        settings,
        load_voices=client.known_voices,
        own_voice=own_voice,
        mic_name=mic_name,
        words=words,
    )
