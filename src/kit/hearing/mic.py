"""The microphone, through sounddevice: 16 kHz mono, 32 ms at a time.

The sound card calls back from its own thread; the chunks wait in a queue for
the ears' loop. Nothing is ever written to disk.
"""

from __future__ import annotations

import logging
import queue
from typing import Protocol

import numpy as np

from kit.hearing.engines import CHUNK, RATE

log = logging.getLogger(__name__)


class Mic(Protocol):
    def read(self, timeout: float = 0.5) -> np.ndarray | None: ...
    def close(self) -> None: ...


def input_devices(sd=None) -> list[tuple[int, str]]:
    """(number, name) of each microphone the PC has."""
    if sd is None:
        import sounddevice as sd
    return [
        (i, str(d["name"]))
        for i, d in enumerate(sd.query_devices())
        if int(d.get("max_input_channels", 0)) > 0
    ]


def pick_device(wanted: str, devices: list[tuple[int, str]]) -> int | None:
    """``hearing.mic`` as a device number: a number as is, else the first mic whose
    name has it in; None for the PC's default."""
    wanted = wanted.strip()
    if not wanted:
        return None
    if wanted.isdigit():
        return int(wanted)
    for index, name in devices:
        if wanted.casefold() in name.casefold():
            return index
    raise ValueError(f"no microphone called {wanted!r} (`kit hearing mics` lists them)")


class SoundDeviceMic:
    def __init__(self, device: int | None = None, sd=None) -> None:
        if sd is None:
            import sounddevice as sd
        self._chunks: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stream = sd.InputStream(
            samplerate=RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK,
            device=device,
            callback=self._got,
        )
        self._stream.start()

    def _got(self, indata, frames, time_info, status) -> None:
        try:
            self._chunks.put_nowait(np.array(indata[:, 0], dtype=np.float32))
        except queue.Full:  # the loop fell behind (a slow transcription): drop the oldest
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                pass

    def read(self, timeout: float = 0.5) -> np.ndarray | None:
        try:
            return self._chunks.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # already gone with the device
            log.debug("closing the mic failed", exc_info=True)
