"""The ears' models, wrapped behind small interfaces so the loop (kit.hearing.run)
and the tests never touch sherpa-onnx. Each real one imports it when it's built.

- ``Vad``: give it sound 512 samples at a time; it says whether someone is
  talking right now and hands back each finished ``Stretch`` of talking.
- ``Transcriber``: a stretch of talking -> ``Transcript`` (words, language,
  tone, sound).
- ``VoicePrinter``: a stretch of talking -> 512 numbers for whose voice it is.

All work on 16 kHz mono floats between -1 and 1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from kit.hearing import models
from kit.settings import HearingSettings

RATE = 16000  # samples a second, everywhere in the ears
CHUNK = 512  # the VAD's step: 32 ms

LEAD_IN_S = 0.8  # sound kept from before the VAD noticed talking: "Kit, ..." starts there
# A pause this long (less than ``hearing.pause_ms``) hands out the talking so far as
# an early stretch, so the words can be worked out while waiting to be sure it's over.
EARLY_PAUSE_MS = 200

TONES = {"happy", "sad", "angry", "neutral", "fearful", "disgusted", "surprised"}


@dataclass
class Transcript:
    text: str
    language: str = ""
    tone: str = ""  # one of TONES, or "" when the model couldn't tell
    sound: str = ""  # speech, laughter, applause, cough, sneeze, cry, bgm...


@dataclass
class Stretch:
    """One stretch of talking: what the VAD found, and the moment just before it.
    An ``early`` one is the same stretch at a short pause, before the VAD is sure
    it's over: the words can be got ready from it. ``start`` is the sample number
    it began at, which tells an early stretch and the finished one apart."""

    voice: np.ndarray  # the talking itself: voice prints use only this
    lead_in: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    start: int = 0
    early: bool = False

    @property
    def end(self) -> int:
        return self.start + len(self.voice)

    @property
    def samples(self) -> np.ndarray:
        """Lead-in and talking together, for speech to text: a short first word
        ("Kit, ...") is often in the lead-in."""
        return np.concatenate([self.lead_in, self.voice]) if len(self.lead_in) else self.voice


class Vad(Protocol):
    def accept(self, chunk: np.ndarray) -> list[Stretch]: ...  # finished (and early) stretches
    def talking(self) -> bool: ...  # someone is talking right now


class Transcriber(Protocol):
    def transcribe(self, samples: np.ndarray) -> Transcript: ...


class VoicePrinter(Protocol):
    def print(self, samples: np.ndarray) -> list[float]: ...


def tag(raw: str) -> str:
    """SenseVoice's "<|HAPPY|>" -> "happy"; its "don't know" tags -> ""."""
    word = re.sub(r"[<|>]", "", raw or "").strip().lower()
    return "" if word in ("", "emo_unknown", "unk", "nospeech") else word


def transcript_of(text: str, lang: str, emotion: str, event: str) -> Transcript:
    tone = tag(emotion)
    return Transcript(
        text=" ".join((text or "").split()),
        language=tag(lang),
        tone=tone if tone in TONES else "",
        sound=tag(event),
    )


def resample(samples: np.ndarray, rate: int, to: int = RATE) -> np.ndarray:
    """Plain linear resampling: enough for a voice print of Kit's own voice."""
    if rate == to or len(samples) == 0:
        return samples.astype(np.float32)
    n = int(len(samples) * to / rate)
    x = np.linspace(0, len(samples) - 1, n)
    return np.interp(x, np.arange(len(samples)), samples).astype(np.float32)


def wav_samples(wav: bytes) -> np.ndarray:
    """A WAV file (Kit's voice, from the brain) as 16 kHz mono floats."""
    import io
    import wave

    with wave.open(io.BytesIO(wav)) as w:
        width, channels, rate = w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit sound, got {8 * width}-bit")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return resample(data, rate)


class Lookback:
    """The last few seconds of sound, by sample number, so a stretch of talking can
    start a little before the VAD noticed it. The VAD is slow to notice a short
    first word, and that's where his name usually is."""

    def __init__(self, seconds: float) -> None:
        self.buffer = np.zeros(max(int(seconds * RATE), CHUNK), dtype=np.float32)
        self.fed = 0  # samples heard so far

    def add(self, chunk: np.ndarray) -> None:
        size, n = len(self.buffer), len(chunk)
        kept = chunk[-size:]
        at = (self.fed + n - len(kept)) % size
        first = min(len(kept), size - at)
        self.buffer[at : at + first] = kept[:first]
        self.buffer[: len(kept) - first] = kept[first:]
        self.fed += n

    def between(self, lo: int, hi: int) -> np.ndarray:
        """The sound from sample number ``lo`` up to ``hi``, as much as it still has."""
        lo = max(lo, self.fed - len(self.buffer), 0)
        hi = max(lo, min(hi, self.fed))
        return self.buffer[np.arange(lo, hi) % len(self.buffer)]

    def before(self, start: int, seconds: float) -> np.ndarray:
        """Up to ``seconds`` of the sound just before sample number ``start``."""
        return self.between(start - int(seconds * RATE), start)


class SileroVad:
    """Two Silero detectors hear the same sound: one ends a stretch after
    ``hearing.pause_ms`` of quiet, the other after ``EARLY_PAUSE_MS``. The early one
    hands out the talking so far at each short pause, so the words can be worked
    out while the first is still waiting to be sure the talking is over. A segment
    carries no trailing quiet, so both end a stretch at the same sample (give or
    take a chunk) and start it at the same one."""

    def __init__(self, folder: Path, settings: HearingSettings, ahead: bool = True) -> None:
        self._model = str(models.model_file("vad", folder))
        self._vad = self._detector(settings, settings.pause_ms)
        self._early = None
        if ahead and settings.pause_ms > EARLY_PAUSE_MS + 100:
            self._early = self._detector(settings, EARLY_PAUSE_MS)
        self._since: int | None = None  # where the stretch under way began
        self._lookback = Lookback(settings.max_speech_s + settings.pause_ms / 1000 + 3)

    def _detector(self, settings: HearingSettings, pause_ms: int):
        import sherpa_onnx

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = self._model
        config.silero_vad.threshold = settings.threshold
        config.silero_vad.min_silence_duration = pause_ms / 1000
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.max_speech_duration = settings.max_speech_s
        config.sample_rate = RATE
        config.num_threads = 1
        return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)

    def accept(self, chunk: np.ndarray) -> list[Stretch]:
        self._lookback.add(chunk)
        done = []
        if self._early is not None:
            self._early.accept_waveform(chunk)
            while not self._early.empty():
                found = self._early.front
                if self._since is None:
                    self._since = found.start
                # The talking so far, from where the stretch under way began: the
                # early detector may have cut it at an earlier short pause.
                end = found.start + len(found.samples)
                voice = self._lookback.between(self._since, end)
                lead_in = self._lookback.before(self._since, LEAD_IN_S)
                done.append(Stretch(voice, lead_in, start=self._since, early=True))
                self._early.pop()
        self._vad.accept_waveform(chunk)
        while not self._vad.empty():
            found = self._vad.front
            voice = np.asarray(found.samples, dtype=np.float32)
            lead_in = self._lookback.before(found.start, LEAD_IN_S)
            done.append(Stretch(voice, lead_in, start=found.start))
            self._vad.pop()
            self._since = None
        return done

    def talking(self) -> bool:
        return bool(self._vad.is_speech_detected())


def trim_quiet(samples: np.ndarray, floor: float = 0.01) -> np.ndarray:
    """Without the near-silence at either end (a voice clip's padding), so a voice
    print is of the voice, not the gaps."""
    loud = np.flatnonzero(np.abs(samples) >= floor)
    return samples[loud[0] : loud[-1] + 1] if len(loud) else samples[:0]


class SenseVoice:
    def __init__(self, folder: Path, settings: HearingSettings) -> None:
        import sherpa_onnx

        model, tokens = models.sense_voice(folder)
        self._recogniser = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model),
            tokens=str(tokens),
            use_itn=True,  # numbers and punctuation written properly
            language=settings.language,
            num_threads=settings.threads,
        )

    def transcribe(self, samples: np.ndarray) -> Transcript:
        stream = self._recogniser.create_stream()
        stream.accept_waveform(RATE, samples)
        self._recogniser.decode_stream(stream)
        r = stream.result
        return transcript_of(r.text, r.lang, r.emotion, r.event)


class CamPlusPlus:
    def __init__(self, folder: Path, settings: HearingSettings) -> None:
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(models.model_file("voice_print", folder)), num_threads=settings.threads
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.size = self._extractor.dim

    def print(self, samples: np.ndarray) -> list[float]:
        stream = self._extractor.create_stream()
        stream.accept_waveform(RATE, samples)
        stream.input_finished()
        return [float(x) for x in self._extractor.compute(stream)]
