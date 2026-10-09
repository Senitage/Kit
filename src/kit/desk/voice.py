"""Kit speaking his replies through the desk PC's speakers.

Kit's words stream in from the brain; each sentence goes to the server's voice
engine as soon as it's whole, and plays while the next one is being made. So he
starts talking about one sentence after the brain does, not after the whole reply.

A reply plays through one sound output that stays open while he talks. Sentences
follow each other with no gaps, the speakers are already awake for his first word
(a sound that wakes them loses its start: his first letters went missing when each
sentence was played on its own), and Dan talking stops him straight away.
"""

from __future__ import annotations

import io
import logging
import queue
import sys
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from kit.desk.client import BrainError, SpeechOff
from kit.speech.sentences import SentenceSplitter

log = logging.getLogger(__name__)

Fetch = Callable[[str, str, bool], bytes]  # (sentence, emotion, first) -> WAV
Heard = Callable[[int, str], None]  # (turn, sentence): its turn to be heard has come

TICK_S = 0.05  # how often the player looks in when there's nothing new to play
WAIT_S = 20.0  # the output stays open this long for Kit's next sentence to be made
LINGER_S = 3.0  # and this long after he stops, in case he goes on
PRE_ROLL_S = 0.3  # silence ahead of his words while the speakers wake up
STALL_S = 2.0  # the sound card hasn't asked for sound in this long: the output died
USUAL_FORMAT = (24000, 1, 2)  # rate, channels, bytes a sample: what the engines make


@dataclass
class Clip:
    pcm: bytes
    rate: int
    channels: int
    width: int  # bytes a sample

    @property
    def format(self) -> tuple[int, int, int]:
        return self.rate, self.channels, self.width

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (self.rate * self.channels * self.width)


def read_wav(wav: bytes) -> Clip:
    with wave.open(io.BytesIO(wav)) as w:
        frames = w.readframes(w.getnframes())
        return Clip(frames, w.getframerate(), w.getnchannels(), w.getsampwidth())


def to_wav(clip: Clip) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(clip.channels)
        w.setsampwidth(clip.width)
        w.setframerate(clip.rate)
        w.writeframes(clip.pcm)
    return buf.getvalue()


def silence(fmt: tuple[int, int, int], seconds: float) -> bytes:
    rate, channels, width = fmt
    return bytes(max(0, int(rate * seconds)) * channels * width)


class OutputError(Exception):
    """The sound output wouldn't open."""


def once(call: Callable[[], None]) -> Callable[[], None]:
    """``call``, but only the first time."""
    done = threading.Event()

    def first() -> None:
        if not done.is_set():
            done.set()
            call()

    return first


class Output(Protocol):
    def warm(self) -> None: ...  # he's about to talk: wake the speakers
    def play(self, clip: Clip, started: Callable[[], None] | None = None) -> None: ...
    def mark(self, reached: Callable[[], None]) -> None: ...  # once what's queued has played
    def busy(self) -> bool: ...  # still playing
    def stop(self) -> None: ...  # silence now
    def close(self) -> None: ...  # let the speakers sleep


class StreamOutput:
    """One sound output (PortAudio, from the sounddevice package) kept open while Kit
    talks: sentences join the end of what's playing, and silence fills the gaps while
    the next one is made. ``started`` is called (from the sound thread, so it must be
    quick) when a sentence starts playing."""

    def __init__(self, sd=None, clock: Callable[[], float] = time.monotonic) -> None:
        if sd is None:
            import sounddevice as sd  # its Windows wheel carries PortAudio itself
        self.sd = sd
        self.clock = clock
        self._life = threading.Lock()  # opening and closing
        self._lock = threading.Lock()  # what's queued; the sound thread takes it too
        self._stream = None
        self._format = USUAL_FORMAT
        self._opened = self._asked = 0.0  # when it opened; when the card last asked
        self._queue = bytearray()
        self._played = 0  # bytes played since the output opened
        self._queued = 0  # bytes queued since it opened
        self._marks: list[tuple[int, Callable[[], None]]] = []  # (byte, when it plays)

    def warm(self) -> None:
        with self._life:
            if self._stream is None:
                self._open(self._format)

    def play(self, clip: Clip, started: Callable[[], None] | None = None) -> None:
        with self._life:
            if self._stream is not None and (clip.format != self._format or self._stalled()):
                self._close()  # another engine's kind of sound, or the output died
            if self._stream is None:
                self._open(clip.format)
            awake = self.clock() - self._opened
            with self._lock:
                if awake < PRE_ROLL_S and not self._queue:
                    self._add(silence(clip.format, PRE_ROLL_S - awake))
                if started is not None:
                    self._marks.append((self._queued, started))
                self._add(clip.pcm)

    def mark(self, reached: Callable[[], None]) -> None:
        with self._lock:
            if self._stream is not None and self._queue:
                self._marks.append((self._queued, reached))
                return
        reached()  # nothing playing: it's reached now

    def busy(self) -> bool:
        with self._lock:
            return bool(self._queue) and not self._stalled()

    def _stalled(self) -> bool:
        """The sound card stopped asking for sound (unplugged, or another device)."""
        return self._stream is not None and self.clock() - self._asked > STALL_S

    def stop(self) -> None:
        with self._lock:
            self._played = self._queued  # what's dropped is as good as played
            self._queue.clear()
            self._marks.clear()

    def close(self) -> None:
        with self._life:
            self._close()

    def _add(self, data: bytes) -> None:
        self._queue += data
        self._queued += len(data)

    def _open(self, fmt: tuple[int, int, int]) -> None:
        rate, channels, width = fmt
        if width != 2:
            raise OutputError(f"can't play {8 * width}-bit sound")
        with self._lock:
            self._queue.clear()
            self._marks.clear()
            self._played = self._queued = 0
        try:
            stream = self.sd.RawOutputStream(
                samplerate=rate, channels=channels, dtype="int16", callback=self._fill
            )
            stream.start()
        except Exception as e:  # no sound device, or PortAudio refused the format
            raise OutputError(f"the sound output wouldn't open: {e}") from e
        self._stream, self._format = stream, fmt
        self._opened = self._asked = self.clock()

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        self.stop()
        try:
            stream.stop()
            stream.close()
        except Exception:
            log.debug("closing the sound output failed", exc_info=True)

    def _fill(self, outdata, frames, time_info, status) -> None:
        """PortAudio wants the next bit of sound: what's queued, else silence."""
        size = len(outdata)
        with self._lock:
            self._asked = self.clock()
            chunk = bytes(self._queue[:size])
            del self._queue[:size]
            self._played += len(chunk)
            due = [started for at, started in self._marks if at <= self._played]
            if due:
                self._marks = [m for m in self._marks if m[0] > self._played]
        outdata[: len(chunk)] = chunk
        if len(chunk) < size:
            outdata[len(chunk) :] = bytes(size - len(chunk))
        for started in due:
            try:
                started()
            except Exception:  # never into PortAudio: it would stop the sound
                log.exception("telling the chat his voice got there failed")


class PlaySoundOutput:
    """Each sentence played on its own (Windows' PlaySound), with silence in front for
    the speakers to wake up on: for when the steady output above won't open."""

    def warm(self) -> None:
        pass

    def play(self, clip: Clip, started: Callable[[], None] | None = None) -> None:
        import winsound

        padded = Clip(silence(clip.format, PRE_ROLL_S) + clip.pcm, *clip.format)
        if started is not None:
            started()
        winsound.PlaySound(to_wav(padded), winsound.SND_MEMORY)  # until it's done

    def mark(self, reached: Callable[[], None]) -> None:
        reached()

    def busy(self) -> bool:
        return False

    def stop(self) -> None:
        pass  # the sentence playing finishes

    def close(self) -> None:
        pass


class NullOutput:
    """No sound: the desk app away from Windows."""

    def warm(self) -> None:
        pass

    def play(self, clip: Clip, started: Callable[[], None] | None = None) -> None:
        if started is not None:
            started()

    def mark(self, reached: Callable[[], None]) -> None:
        reached()

    def busy(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def fallback_output() -> Output:
    return PlaySoundOutput() if sys.platform == "win32" else NullOutput()


def default_output() -> Output:
    if sys.platform != "win32":
        return NullOutput()
    try:
        return StreamOutput()
    except Exception as e:  # sounddevice, or the PortAudio inside it, is missing
        log.warning("no steady sound output (%s): playing sentence by sentence", e)
        return PlaySoundOutput()


class Speaker:
    """Say Kit's reply as it streams in. One reply at a time: a new one, or Dan
    sending a message, stops what he was saying.

    ``heard`` is told (from another thread) as each sentence's turn to be heard
    comes: when it starts playing, or when it couldn't be made, so the chat can show
    his words as he says them. ``live`` says whether his voice is on, as far as the
    server last said."""

    def __init__(
        self,
        fetch: Fetch,
        output: Output | None = None,
        heard: Heard | None = None,
        fallback: Callable[[], Output] = fallback_output,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.fetch = fetch
        self.output = output if output is not None else default_output()
        self.heard = heard
        self.fallback = fallback
        self.clock = clock
        self.enabled = True
        self.live = False
        self._turn = 0
        self._latest = 0  # the newest reply begun: an older one still streaming is ignored
        self._open = False  # a reply has begun and not ended
        self._generation = 0
        self._splitter = SentenceSplitter()
        self._emotion = "neutral"
        self._sent = 0
        self._making = False
        self._warm = False
        self._awake_until = 0.0
        self._lock = threading.Lock()
        self._lines: queue.Queue = queue.Queue()
        self._audio: queue.Queue = queue.Queue()
        threading.Thread(target=self._make, name="kit-voice-make", daemon=True).start()
        threading.Thread(target=self._play, name="kit-voice-play", daemon=True).start()

    def begin(self, turn: int) -> bool:
        """A new reply is coming; anything still queued from the last one is dropped.
        False for an older reply that's still streaming in (Dan asked again)."""
        with self._lock:
            if turn == self._turn:
                return True
            if turn < self._latest:
                return False
            self._generation += 1
            self._turn = self._latest = turn
            self._open = True
            self._splitter = SentenceSplitter()
            self._emotion = "neutral"
            self._sent = 0
            self._warm = self.enabled and self.live  # wake the speakers while he thinks
            self._awake_until = max(self._awake_until, self.clock() + WAIT_S)
            return True

    def mood(self, turn: int, emotion: str) -> None:
        if self.begin(turn):
            self._emotion = emotion or "neutral"

    def say(self, turn: int, text: str) -> None:
        if not self.begin(turn):
            return
        with self._lock:
            self._open = True
            self._queue(self._splitter.feed(text))

    def end(self, turn: int) -> None:
        with self._lock:
            if turn == self._turn and self._open:
                self._queue(self._splitter.flush())
                self._open = False

    def pipe_up(self, turn: int, text: str, emotion: str) -> bool:
        """Say a line Kit came out with by himself, unless he's talking already.
        True if he's going to say it."""
        if not self.enabled or self.talking() or not self.begin(turn):
            return False
        self.mood(turn, emotion)
        self.say(turn, text + " ")
        self.end(turn)
        return True

    def stop(self, turn: int | None = None) -> None:
        """Stop talking, now: Dan is saying something. Replies already on their way
        stay quiet. ``turn`` is the reply Dan's message will get: that one is heard,
        and the speakers wake for it while Kit thinks."""
        with self._lock:
            self._generation += 1
            self._latest = max(self._latest, self._turn + 1)
            self._turn = 0
            self._open = False
            self._splitter = SentenceSplitter()
        self.output.stop()
        if turn is not None:
            self.begin(turn)

    def talking(self) -> bool:
        """A reply is under way: still coming in, being made, or playing."""
        return (
            self._open
            or self._making
            or not self._lines.empty()
            or not self._audio.empty()
            or self.output.busy()
        )

    def _queue(self, pieces: list[str]) -> None:
        if not self.enabled:
            return
        for piece in pieces:
            self._lines.put((self._generation, self._turn, piece, self._emotion, self._sent == 0))
            self._sent += 1
        if pieces:
            self._awake_until = max(self._awake_until, self.clock() + WAIT_S)

    def _current(self, generation: int) -> bool:
        return generation == self._generation

    def _make(self) -> None:
        while True:
            generation, turn, text, emotion, first = self._lines.get()
            if not self._current(generation):
                continue
            self._making = True
            try:
                clip = self._made(text, emotion, first)
                if self._current(generation):  # None: not heard, but his words show in turn
                    self._audio.put((generation, turn, text, clip))
            finally:
                self._making = False

    def _made(self, text: str, emotion: str, first: bool) -> Clip | None:
        try:
            clip = read_wav(self.fetch(text, emotion, first))
        except SpeechOff:
            self.live = False  # speech is off on the server: say nothing
            return None
        except BrainError as e:
            log.warning("couldn't make speech: %s", e)
            return None
        except (wave.Error, EOFError) as e:
            log.warning("the voice engine sent something that isn't sound: %s", e)
            return None
        self.live = True
        return clip

    def _heard(self, generation: int, turn: int, text: str) -> None:
        if self.heard is not None and self._current(generation):
            self.heard(turn, text)

    def _play(self) -> None:
        while True:
            try:
                generation, turn, text, clip = self._audio.get(timeout=TICK_S)
            except queue.Empty:
                self._tick()
                continue
            if not self._current(generation):
                continue
            started = None
            if self.heard is not None:

                @once
                def started(generation=generation, turn=turn, text=text) -> None:
                    self._heard(generation, turn, text)

            if clip is None:
                if started is not None:
                    self._reached(started)
                continue
            self._send(clip, started)
            if not self._current(generation):
                self.output.stop()  # Dan spoke while it was going in

    def _send(self, clip: Clip, started: Callable[[], None] | None) -> None:
        for attempt in range(2):
            try:
                self.output.play(clip, started)
                return
            except OutputError as e:
                if attempt:
                    log.warning("couldn't play speech: %s", e)
                    break
                log.warning("%s: playing sentence by sentence instead", e)
                self.output = self.fallback()
            except Exception:
                log.exception("couldn't play speech")
                break
        if started is not None:
            started()  # not heard, but his words show

    def _reached(self, reached: Callable[[], None]) -> None:
        try:
            self.output.mark(reached)
        except Exception:
            log.exception("couldn't follow the sound output")
            reached()

    def _tick(self) -> None:
        """Between sentences: wake the speakers if he's about to talk, keep the
        output open while he is, and close it a little after he stops."""
        now = self.clock()
        if self._warm:
            self._warm = False
            try:
                self.output.warm()
            except OutputError as e:
                log.warning("%s: playing sentence by sentence instead", e)
                self.output = self.fallback()
            except Exception:
                log.exception("couldn't open the sound output")
        if self.output.busy() or self._making or self._open:
            self._awake_until = max(self._awake_until, now + LINGER_S)
        elif now > self._awake_until:
            self.output.close()
