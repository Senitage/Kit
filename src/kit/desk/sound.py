"""Kit's little noises: a "boop" when he says something, so it isn't missed.

The sounds are made here from sine waves (no sound files in the repo) and saved
once into the desk app's folder as small WAV files. Windows plays them with
``winsound``, which needs nothing extra; elsewhere there's no sound. Turn them off
on the Look page or from the tray (``DeskConfig.boop``), for example once Kit
talks out loud.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import sys
import wave
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("kit.desk")

RATE = 22_050
# Each sound is a few notes: (start Hz, end Hz, seconds). The pitch slides within
# a note, which is what makes it sound like a cartoon "boop" rather than a beep.
SOUNDS: dict[str, list[tuple[float, float, float]]] = {
    "boop": [(660.0, 440.0, 0.13)],  # he answered
    "bip_boop": [(620.0, 880.0, 0.08), (700.0, 470.0, 0.12)],  # he piped up by himself
}
VOLUME = 0.32
SOUND_VERSION = 1  # bump when the notes change, so the saved files are made again


def tone(notes: list[tuple[float, float, float]], rate: int = RATE) -> bytes:
    """The notes as a mono 16-bit WAV, each with a soft start and a rounded end."""
    frames = bytearray()
    for start, end, seconds in notes:
        n = int(rate * seconds)
        phase = 0.0
        for i in range(n):
            t = i / n
            freq = start + (end - start) * t
            phase += 2 * math.pi * freq / rate
            envelope = min(1.0, t / 0.08) * (1 - t) ** 1.6  # quick in, rounded out
            # A touch of the octave makes it rounder than a plain sine.
            sample = math.sin(phase) + 0.18 * math.sin(2 * phase)
            frames += struct.pack("<h", int(sample * envelope * VOLUME * 32767 / 1.18))
        frames += b"\0\0" * int(rate * 0.02)  # a breath between notes
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return out.getvalue()


def _winsound(path: Path) -> None:
    import winsound  # Windows only

    winsound.PlaySound(
        str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
    )


class Sounds:
    """Plays Kit's noises. ``player`` is passed in so tests can listen."""

    def __init__(self, folder: Path, player: Callable[[Path], None] | None = None) -> None:
        self.folder = folder
        if player is None and sys.platform == "win32":
            player = _winsound
        self.player = player

    def path(self, name: str) -> Path:
        """The sound's file, written the first time it's wanted."""
        path = self.folder / f"{name}-{SOUND_VERSION}.wav"
        if not path.is_file():
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tone(SOUNDS[name]))
        return path

    def play(self, name: str) -> None:
        if self.player is None:
            return
        try:
            self.player(self.path(name))
        except Exception:  # a missing sound must never stop Kit talking
            log.exception("couldn't play %s", name)
