"""Cut Kit's words into speakable pieces as they stream in.

Speech starts as soon as the first sentence is whole, so Kit is talking while the
brain is still writing the rest. The first sentence is cut short when it can be,
because a voice engine like Chatterbox makes a whole piece before any of it plays:
at its first comma ("Yeah, I reckon...") or, failing that, before an "and", "but"
or "so" once a few words are in. The rest is made while the opening plays.
"""

from __future__ import annotations

import re

ABBREVIATIONS = {"e.g.", "i.e.", "etc.", "vs.", "dr.", "mr.", "mrs.", "ms.", "st.", "approx."}
_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)|\n+")
_CLAUSE = re.compile(r"[,;:–—](?=\s)")
_JOIN = re.compile(r"\s(?=(?:and|but|so|because|though|which|or)\s)", re.IGNORECASE)


class SentenceSplitter:
    """``feed`` streamed text in, get back the pieces that are ready to speak;
    ``flush`` at the end for whatever is left."""

    def __init__(self, first_clause_words: int = 6, min_clause_words: int = 1) -> None:
        self.buffer = ""
        self.started = False
        self.first_clause_words = first_clause_words
        self.min_clause_words = min_clause_words

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
        if not self.started and len(self.buffer.split()) >= self.first_clause_words:
            for match in _CLAUSE.finditer(self.buffer):
                if len(self.buffer[: match.end()].split()) >= self.min_clause_words:
                    return self._take(match.end())
            if len(self.buffer.split()) >= 2 * self.first_clause_words:
                for match in _JOIN.finditer(self.buffer):
                    if len(self.buffer[: match.start()].split()) >= 4:
                        return self._take(match.start())
        return ""
