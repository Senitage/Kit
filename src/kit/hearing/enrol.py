"""Introducing someone to Kit's ears: ``kit hearing enrol NAME``.

They read a few lines out loud; each stretch of talking is cut into pieces of a
few seconds and voice printed. Only the prints (512 numbers each, from which no
sound can be rebuilt) go to the brain, which keeps them in its data folder
(kit.known_voices). Nothing is recorded to disk.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from kit.hearing.engines import RATE, Vad, VoicePrinter
from kit.settings import HearingSettings

PIECE_S = 3.0  # each voice print is made from this much talking
MIN_PIECE_S = 1.5
MIC_GIVES_UP = 10  # reads in a row with nothing from the mic: it's gone
LINES = [
    "Morning Kit. What's the weather doing today?",
    "I'm heading out for a bit, I'll be back after lunch.",
    "Can you remind me to ring the plumber on Thursday?",
    "That was a good one. Tell me another.",
    "What do you reckon we should have for tea tonight?",
    "Night Kit, see you in the morning.",
]


Parts = tuple[Callable[[], object], Vad, VoicePrinter]  # open the mic, the VAD, the printer


def real_parts(settings: HearingSettings, folder: Path | None = None) -> Parts:
    """The real mic, voice detector and voice printer for enrolling. Imports the
    libraries here, so only this needs them installed."""
    from kit.hearing.engines import CamPlusPlus, SileroVad
    from kit.hearing.link import models_dir
    from kit.hearing.mic import SoundDeviceMic, input_devices, pick_device

    models = models_dir(folder)
    device = pick_device(settings.mic, input_devices()) if settings.mic else None
    return (
        lambda: SoundDeviceMic(device),
        SileroVad(models, settings, ahead=False),
        CamPlusPlus(models, settings),
    )


def owner(client, who: str) -> str:
    """``me`` as Dan's name (persona.owner on the brain); anyone else as given."""
    if who.casefold() != "me":
        return who
    return client.settings()["settings"].get("persona", {}).get("owner", "") or who


def pieces(samples: np.ndarray) -> list[np.ndarray]:
    """A stretch of talking cut into voice-print-sized pieces; a short tail is dropped."""
    size = int(PIECE_S * RATE)
    out = [samples[i : i + size] for i in range(0, len(samples), size)]
    return [p for p in out if len(p) >= MIN_PIECE_S * RATE]


def listen_for(read: Callable[[], np.ndarray | None], vad: Vad, seconds: float) -> list[np.ndarray]:
    """The stretches of talking in the next ``seconds`` from the mic."""
    stretches: list[np.ndarray] = []
    heard, missed = 0.0, 0
    while heard < seconds and missed < MIC_GIVES_UP:
        chunk = read()
        if chunk is None:  # nothing from the mic for a moment
            missed += 1
            continue
        missed = 0
        heard += len(chunk) / RATE
        stretches += [s.voice for s in vad.accept(chunk) if not s.early]
    # Flush whatever is still being said with a little silence.
    stretches += [s.voice for s in vad.accept(np.zeros(int(RATE), dtype=np.float32)) if not s.early]
    return stretches


def voice_prints(stretches: list[np.ndarray], printer: VoicePrinter) -> list[list[float]]:
    return [printer.print(p) for s in stretches for p in pieces(s)]
