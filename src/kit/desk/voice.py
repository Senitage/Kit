"""Kit speaking his replies through the desk PC's speakers.

Kit's words stream in from the brain; each sentence goes to the server's voice
engine as soon as it's whole, and plays while the next one is being made. So he
starts talking about one sentence after the brain does, not after the whole reply.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from collections.abc import Callable

from kit.desk.client import BrainError, SpeechOff
from kit.speech.sentences import SentenceSplitter

log = logging.getLogger(__name__)

Fetch = Callable[[str, str, bool], bytes]  # (sentence, emotion, first) -> WAV


def play_wav(wav: bytes) -> None:
    """Play a WAV file and return when it's done (Windows; elsewhere, silence)."""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(wav, winsound.SND_MEMORY)


class Speaker:
    """Say Kit's reply as it streams in. One reply at a time: a new one, or Dan
    sending a message, stops what he was saying (after the sentence playing now)."""

    def __init__(self, fetch: Fetch, play: Callable[[bytes], None] = play_wav) -> None:
        self.fetch = fetch
        self.play = play
        self.enabled = True
        self._turn = 0
        self._latest = 0  # the newest reply begun: an older one still streaming is ignored
        self._generation = 0
        self._splitter = SentenceSplitter()
        self._emotion = "neutral"
        self._sent = 0
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
            self._splitter = SentenceSplitter()
            self._emotion = "neutral"
            self._sent = 0
            return True

    def mood(self, turn: int, emotion: str) -> None:
        if self.begin(turn):
            self._emotion = emotion or "neutral"

    def say(self, turn: int, text: str) -> None:
        if not self.begin(turn):
            return
        with self._lock:
            self._queue(self._splitter.feed(text))

    def end(self, turn: int) -> None:
        with self._lock:
            if turn == self._turn:
                self._queue(self._splitter.flush())

    def stop(self) -> None:
        """Stop talking: Dan is saying something. Replies already on their way stay
        quiet; the next one is heard."""
        with self._lock:
            self._generation += 1
            self._turn = 0
            self._latest += 1
            self._splitter = SentenceSplitter()

    def _queue(self, pieces: list[str]) -> None:
        if not self.enabled:
            return
        for piece in pieces:
            self._lines.put((self._generation, piece, self._emotion, self._sent == 0))
            self._sent += 1

    def _current(self, generation: int) -> bool:
        return generation == self._generation

    def _make(self) -> None:
        while True:
            generation, text, emotion, first = self._lines.get()
            if not self._current(generation):
                continue
            try:
                wav = self.fetch(text, emotion, first)
            except SpeechOff:
                continue  # speech is off on the server: say nothing
            except BrainError as e:
                log.warning("couldn't make speech: %s", e)
                continue
            if self._current(generation):
                self._audio.put((generation, wav))

    def _play(self) -> None:
        while True:
            generation, wav = self._audio.get()
            if not self._current(generation):
                continue
            try:
                self.play(wav)
            except Exception:
                log.exception("couldn't play speech")
