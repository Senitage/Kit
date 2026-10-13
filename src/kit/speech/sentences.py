"""Cut Kit's words into speakable pieces as they stream in.

Speech starts as soon as the first sentence is whole, so Kit is talking while the
brain is still writing the rest. The first sentence is cut short when it can be,
because a voice engine like Chatterbox makes a whole piece before any of it plays:
at the first comma after at least four words ("Yeah, I had a look at that,") or,
failing that, before an "and", "but" or "so" once a dozen words are in. A clause
of one or two words ("Yeah,") is never cut off on its own: the engine gives it
its own falling tune and a gap follows, which sounds like a stammer. The rest is
made while the opening plays.
"""

from __future__ import annotations

import re

ABBREVIATIONS = {"e.g.", "i.e.", "etc.", "vs.", "dr.", "mr.", "mrs.", "ms.", "st.", "approx."}
# A sound for his voice to make ("[chuckle]", speech.sounds): said, never shown.
SOUND = re.compile(r"\[[a-z]+(?: [a-z]+)?\]\s*")


def without_sounds(text: str) -> str:
    """His words as shown, with any sounds his voice makes taken out."""
    return SOUND.sub("", text).strip()


_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)|\n+")
_CLAUSE = re.compile(r"[,;:–—](?=\s)")
_JOIN = re.compile(r"\s(?=(?:and|but|so|because|though|which|or)\s)", re.IGNORECASE)


class SentenceSplitter:
    """``feed`` streamed text in, get back the pieces that are ready to speak;
    ``flush`` at the end for whatever is left.

    ``min_clause_words`` is the fewest words the first piece may have when it's cut
    at a comma; the cut before an "and" needs ``long_sentence_words`` in the buffer
    first, so a short sentence stays whole."""

    def __init__(self, min_clause_words: int = 4, long_sentence_words: int = 12) -> None:
        self.buffer = ""
        self.started = False
        self.min_clause_words = max(1, min_clause_words)
        self.long_sentence_words = long_sentence_words

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        ready = []
        while piece := self._next():
            ready.append(piece)
        return ready

    def flush(self) -> list[str]:
        rest = " ".join(self.buffer.split())
        self.buffer = ""
        self.started = self.started or bool(rest)
        return [rest] if rest else []

    def _take(self, end: int) -> str:
        piece = " ".join(self.buffer[:end].split())
        self.buffer = self.buffer[end:].lstrip()
        if piece:
            self.started = True
        return piece

    def _sentence_end(self) -> int | None:
        for match in _END.finditer(self.buffer):
            last_word = self.buffer[: match.end()].split()[-1:] or [""]
            if match.group().strip() == "." and last_word[0].lower() in ABBREVIATIONS:
                continue
            return match.end()
        return None

    def _next(self) -> str:
        while (end := self._sentence_end()) is not None:
            if piece := self._take(end):
                return piece
        if not self.started and self._words(self.buffer) >= self.min_clause_words:
            for match in _CLAUSE.finditer(self.buffer):
                if self._words(self.buffer[: match.end()]) >= self.min_clause_words:
                    return self._take(match.end())
            if self._words(self.buffer) >= self.long_sentence_words:
                for match in _JOIN.finditer(self.buffer):
                    if self._words(self.buffer[: match.start()]) >= self.min_clause_words:
                        return self._take(match.start())
        return ""

    @staticmethod
    def _words(text: str) -> int:
        """Spoken words: a sound tag ("[chuckle]") isn't one."""
        return len(without_sounds(text).split())
