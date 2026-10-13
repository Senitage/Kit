"""Kit speaking his replies through the desk PC's speakers.

Kit's words stream in from the brain; each sentence goes to the server's voice
engine as soon as it's whole, and plays while the next one is being made. So he
starts talking about one sentence after the brain does, not after the whole reply.

A reply plays through one sound output that stays open while he talks. Sentences
follow each other with no gaps, the speakers are already awake for his first word
(a sound that wakes them loses its start: his first letters went missing when each
sentence was played on its own), and Dan talking stops him straight away.

Each sentence arrives in pieces as the server makes it (the first within a few
hundred milliseconds, the rest while that plays), and every piece joins the sound
output as it comes, so a long sentence starts playing before it's finished being
made and there's no hole after a short one. The chat hears the sentence as its
first piece starts (``heard``) and how long it was as its last piece ends
(``spoke``). His mouth follows the sound itself: the output measures how loud
each bit of his voice is as it plays (``talk``), so it opens on his words,
closes on his pauses and stops exactly when the sound does.

A sound in his voice (``speech.sounds``: a chuckle on the punchline) comes as its
own event before the words it goes with, and is said, never shown.

Each reply has a generation number that goes with every sentence to the server,
so when Dan interrupts, a sentence of the old reply still waiting there is
dropped rather than made, and the new reply's first sentence isn't held behind
one still being fetched: a new fetching thread takes over at once and the old
one's answer is thrown away when it comes.
"""

from __future__ import annotations

import io
import itertools
import logging
import math
import queue
import sys
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from kit.desk.client import BrainError, Sound, SpeechLoading, SpeechOff, SpeechStale
from kit.speech.sentences import SentenceSplitter, without_sounds

log = logging.getLogger(__name__)

# (sentence, emotion, first, generation) -> its sound, in pieces as it's made
Fetch = Callable[[str, str, bool, int], Sound]
Connect = Callable[[], None]  # open the way to the server, so the first sentence needn't
Heard = Callable[[int, str], None]  # (turn, sentence): its turn to be heard has come
Spoke = Callable[[int, str, float], None]  # (turn, sentence, seconds it played for), at its end
Talk = Callable[[float], None]  # how loud his voice is right now, 0..1, as it plays

TICK_S = 0.05  # how often the player looks in when there's nothing new to play
WAIT_S = 20.0  # the output stays open this long for Kit's next sentence to be made
LINGER_S = 3.0  # and this long after he stops, in case he goes on
PRE_ROLL_S = 0.3  # silence ahead of his words while the speakers wake up
STALL_S = 2.0  # the sound card hasn't asked for sound in this long: the output died
LOADING_WAIT_S = 0.5  # the voice engine is still loading: ask again after this
LOADING_TRIES = 6  # and give up on the sentence after this many asks (his words show anyway)
USUAL_FORMAT = (24000, 1, 2)  # rate, channels, bytes a sample: what the engines make
# His mouth from his voice: how loud a bit of sound is (its RMS, 0..1) times this gain is
# how open the mouth is; the level rises in about 20 ms and falls in about 80 ms.
TALK_GAIN = 4.0
TALK_ATTACK_S = 0.02
TALK_RELEASE_S = 0.08


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


@dataclass
class _Piece:
    """A piece of a sentence's sound on its way to the output. The pieces of one
    sentence share ``sid``; the last is followed by one with no clip, carrying how
    many ``seconds`` the sentence was."""

    generation: int
    sid: int
    turn: int
    text: str
    clip: Clip | None
    seconds: float


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
    quick) when a sentence starts playing. ``talk``, if given, is told how loud each
    bit of sound is as it's handed to the card (0..1, smoothed), so his mouth can
    follow his voice; it's told 0 once as the sound ends."""

    def __init__(
        self, sd=None, clock: Callable[[], float] = time.monotonic, talk: Talk | None = None
    ) -> None:
        if sd is None:
            import sounddevice as sd  # its Windows wheel carries PortAudio itself
        self.sd = sd
        self.clock = clock
        self.talk = talk
        self._level = 0.0  # how loud the sound is, smoothed
        self._told = 0.0  # the level last passed on
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
        if self.talk is not None:
            self._measure(chunk, size, frames)

    def _measure(self, chunk: bytes, size: int, frames: int) -> None:
        """How loud this bit of sound is, smoothed, for his mouth."""
        loud = 0.0
        if chunk:
            samples = np.frombuffer(chunk[: len(chunk) - len(chunk) % 2], dtype="<i2")
            if len(samples):
                loud = math.sqrt(float(np.mean(samples.astype(np.float32) ** 2))) / 32768
                loud *= len(chunk) / size  # the rest of the block is silence
        level = min(1.0, loud * TALK_GAIN)
        dt = frames / self._format[0]
        ease = TALK_ATTACK_S if level > self._level else TALK_RELEASE_S
        self._level += (level - self._level) * (1 - math.exp(-dt / ease))
        if not chunk and self._level < 0.02:
            self._level = 0.0  # the sound has ended: his mouth closes now
        told = round(self._level, 2)
        if told != self._told:
            self._told = told
            try:
                self.talk(told)
            except Exception:
                log.exception("telling the face how loud his voice is failed")


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


def default_output(talk: Talk | None = None) -> Output:
    if sys.platform != "win32":
        return NullOutput()
    try:
        return StreamOutput(talk=talk)
    except Exception as e:  # sounddevice, or the PortAudio inside it, is missing
        log.warning("no steady sound output (%s): playing sentence by sentence", e)
        return PlaySoundOutput()


class Speaker:
    """Say Kit's reply as it streams in. One reply at a time: a new one, or Dan
    sending a message, stops what he was saying.

    ``heard`` is told (from another thread) as each sentence's turn to be heard
    comes: when its first piece starts playing, or when it couldn't be made, so the
    chat can show his words as he says them. ``spoke`` is told as the sentence
    ends how long it played for (0 when it couldn't be made), and ``talk`` how loud
    his voice is as it plays, so his face talks for exactly as long as his voice
    does. ``heard`` and ``spoke`` get the sentence without its sounds. ``live`` says
    whether his voice is on, as far as the server last said. ``connect``, if
    given, is called when a reply is coming, so the way to the server is open
    before the first sentence is asked for.

    ``fetch`` gets each sentence's generation too: a number that goes up with
    every reply begun and every interruption, and is bigger after a restart, so
    the server can tell a sentence from an overtaken reply and drop it."""

    def __init__(
        self,
        fetch: Fetch,
        output: Output | None = None,
        heard: Heard | None = None,
        fallback: Callable[[], Output] = fallback_output,
        clock: Callable[[], float] = time.monotonic,
        spoke: Spoke | None = None,
        connect: Connect | None = None,
        sleep: Callable[[float], None] = time.sleep,
        talk: Talk | None = None,
    ) -> None:
        self.fetch = fetch
        self.connect = connect
        self.output = output if output is not None else default_output(talk)
        self.heard = heard
        self.spoke = spoke
        self.fallback = fallback
        self.clock = clock
        self.sleep = sleep
        self.enabled = True
        self.live = False
        self._turn = 0
        self._latest = 0  # the newest reply begun: an older one still streaming is ignored
        self._open = False  # a reply has begun and not ended
        self._generation = int(time.time() * 1000)  # bigger than any from before a restart
        self._gave_up = None  # a generation whose voice didn't come while the engine loaded
        self._splitter = SentenceSplitter()
        self._emotion = "neutral"
        self._sent = 0
        self._making = 0  # sentences being fetched right now
        self._makers = 0  # fetching threads alive
        self._maker = 0  # the newest of them; an older one stops once its fetch is back
        self._warm = False
        self._awake_until = 0.0
        self._lock = threading.Lock()
        self._lines: queue.Queue = queue.Queue()
        self._audio: queue.Queue = queue.Queue()  # pieces of sound, in order
        self._ids = itertools.count(1)  # one number a sentence, for its pieces
        self._start_maker()
        threading.Thread(target=self._play, name="kit-voice-play", daemon=True).start()

    def _start_maker(self) -> None:
        """A fetching thread. Called again (under the lock) when a reply is overtaken
        while a sentence is being fetched, so the new reply's first sentence doesn't
        wait behind it: the old thread stops once its fetch comes back."""
        self._maker += 1
        self._makers += 1
        threading.Thread(
            target=self._make, args=(self._maker,), name="kit-voice-make", daemon=True
        ).start()

    def _overtaken(self) -> None:
        """A new generation, under the lock: free the way for its first sentence."""
        self._generation += 1
        if self._making and self._making >= self._makers:  # every fetching thread is out
            self._start_maker()

    def begin(self, turn: int) -> bool:
        """A new reply is coming; anything still queued from the last one is dropped.
        False for an older reply that's still streaming in (Dan asked again)."""
        with self._lock:
            if turn == self._turn:
                return True
            if turn < self._latest:
                return False
            self._overtaken()
            self._turn = self._latest = turn
            self._open = True
            self._splitter = SentenceSplitter()
            self._emotion = "neutral"
            self._sent = 0
            self._warm = self.enabled and self.live  # wake the speakers while he thinks
            if self._warm and self.connect is not None:
                self._lines.put((self._generation, turn, None, "", False))  # and the server
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

    def sound(self, turn: int, name: str) -> None:
        """A sound for his voice to make before the words that come next (a chuckle)."""
        if not self.begin(turn) or not name:
            return
        with self._lock:
            self._open = True
            self._queue(self._splitter.feed(f" [{name}] "))

    def end(self, turn: int) -> None:
        with self._lock:
            if turn == self._turn and self._open:
                self._queue(self._splitter.flush())
                self._open = False

    def saying(self, turn: int) -> bool:
        """Is his voice saying the reply for ``turn`` (as far as it knows)?"""
        return self.enabled and self.live and turn != 0 and turn == self._turn

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
            self._overtaken()
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
            or self._making > 0
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

    def _make(self, me: int) -> None:
        try:
            while True:
                generation, turn, text, emotion, first = self._lines.get()
                if not self._current(generation):
                    continue
                if text is None:  # he's about to talk: have the connection open for his words
                    self._connect()
                    continue
                with self._lock:
                    self._making += 1
                try:
                    sound = self._made(text, emotion, first, generation)
                    seconds = self._pieces(sound, generation, turn, text, next(self._ids))
                finally:
                    with self._lock:
                        self._making -= 1
                        superseded = self._maker != me
                if self._current(generation):  # the end of the sentence (its words show in turn)
                    self._audio.put(_Piece(generation, 0, turn, text, None, seconds))
                if superseded:
                    return  # a newer thread took over while this fetch was out
        finally:
            with self._lock:
                self._makers -= 1

    def _connect(self) -> None:
        try:
            self.connect()
        except BrainError as e:
            log.info("couldn't reach Kit ahead of his words: %s", e)
        except Exception:
            log.exception("couldn't reach Kit ahead of his words")

    def _pieces(self, sound: Sound | None, generation: int, turn: int, text: str, sid: int):
        """Queue the sentence's sound to play as its pieces come; how long it was."""
        seconds = 0.0
        if sound is None:
            return seconds
        try:
            for piece in sound.pieces:
                if not self._current(generation):
                    break  # Dan moved on: the rest isn't wanted
                clip = Clip(piece, sound.rate, sound.channels, sound.width)
                seconds += clip.seconds
                self._audio.put(_Piece(generation, sid, turn, text, clip, seconds))
        except BrainError as e:
            log.warning("his voice broke off: %s", e)
        except Exception:
            log.exception("his voice broke off")
        return seconds

    def _made(self, text: str, emotion: str, first: bool, generation: int) -> Sound | None:
        """The sentence as sound (its pieces still to come), or None when it couldn't
        be made. An engine still loading is asked again a few times; once a sentence
        has gone unvoiced for that, the rest of its reply is only asked once each."""
        tries = 1 if self._gave_up == generation else LOADING_TRIES
        for attempt in range(1, tries + 1):
            if attempt > 1:
                self.sleep(LOADING_WAIT_S)
                if not self._current(generation):
                    return None  # Dan moved on while it waited
            try:
                sound = self.fetch(text, emotion, first, generation)
            except SpeechLoading as e:
                if attempt < tries and self._current(generation):
                    continue
                self._gave_up = generation
                log.info("his voice isn't ready yet, so his words only show: %s", e)
                return None
            except SpeechStale:
                return None  # Dan interrupted: the server dropped it, as this will
            except SpeechOff:
                self.live = False  # speech is off on the server: say nothing
                return None
            except BrainError as e:
                log.warning("couldn't make speech: %s", e)
                return None
            self.live = True
            return sound
        return None

    def _heard(self, generation: int, turn: int, text: str) -> None:
        if self._current(generation) and self.heard is not None:
            self.heard(turn, without_sounds(text))

    def _spoke(self, generation: int, turn: int, text: str, seconds: float) -> None:
        if self._current(generation) and self.spoke is not None:
            self.spoke(turn, without_sounds(text), seconds)

    def _play(self) -> None:
        playing: int | None = None  # the sentence whose pieces are going in
        while True:
            try:
                piece = self._audio.get(timeout=TICK_S)
            except queue.Empty:
                self._tick()
                continue
            if not self._current(piece.generation):
                playing = None
                continue
            if piece.clip is None:  # the sentence's end: its words show, and how long it was
                # Nothing of it was voiced: its moment comes in turn, once what's queued has played.
                self._reached(self._ended(piece, heard=playing is None))
                playing = None
                continue
            if piece.sid != playing:  # the first piece of a sentence: heard as it starts
                playing = piece.sid
                self._send(
                    piece.clip, once(lambda p=piece: self._heard(p.generation, p.turn, p.text))
                )
            else:
                self._send(piece.clip, None)
            if not self._current(piece.generation):
                self.output.stop()  # Dan spoke while it was going in

    def _ended(self, piece: _Piece, heard: bool) -> Callable[[], None]:
        @once
        def ended() -> None:
            if heard:
                self._heard(piece.generation, piece.turn, piece.text)
            self._spoke(piece.generation, piece.turn, piece.text, piece.seconds)

        return ended

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
