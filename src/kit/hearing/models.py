"""The ears' three model files, from the sherpa-onnx releases on GitHub, downloaded
the first time into the ears' own folder (kit.hearing.link):

- **SenseVoice-Small** (int8): speech to text in English and four other
  languages, with the tone of voice (happy, sad, angry...) and sounds (a laugh,
  a cough) in the same pass. About 230 MB unpacked; half a second for seven
  seconds of talking on two processor threads.
- **Silero VAD**: tells talking from silence and noise, 32 ms at a time.
- **CAM++** (3D-Speaker, VoxCeleb): a voice print of 512 numbers, for who's
  talking and for knowing Kit's own voice from the speakers.
"""

from __future__ import annotations

import logging
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SENSE_VOICE = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
URLS = {
    "sense_voice": f"{RELEASES}/asr-models/{SENSE_VOICE}.tar.bz2",
    "vad": f"{RELEASES}/asr-models/silero_vad.onnx",
    # The release tag really is spelt this way.
    "voice_print": f"{RELEASES}/speaker-recongition-models/"
    "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
}

Fetcher = Callable[[str, Path], None]


def fetch(url: str, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(path)


def model_file(name: str, folder: Path, fetcher: Fetcher = fetch) -> Path:
    """The local file for the VAD or the voice print model, downloaded the first time."""
    url = URLS[name]
    path = folder / url.rsplit("/", 1)[1]
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        log.info("downloading %s", path.name)
        fetcher(url, path)
    return path


def sense_voice(folder: Path, fetcher: Fetcher = fetch) -> tuple[Path, Path]:
    """SenseVoice's model and tokens files, downloaded and unpacked the first time."""
    here = folder / SENSE_VOICE
    model, tokens = here / "model.int8.onnx", here / "tokens.txt"
    if model.exists() and tokens.exists():
        return model, tokens
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{SENSE_VOICE}.tar.bz2"
    if not archive.exists():
        log.info("downloading %s (about 160 MB, once)", archive.name)
        fetcher(URLS["sense_voice"], archive)
    with tarfile.open(archive, "r:bz2") as tar:
        wanted = [m for m in tar.getmembers() if m.name.endswith(("model.int8.onnx", "tokens.txt"))]
        tar.extractall(folder, members=wanted, filter="data")
    archive.unlink(missing_ok=True)
    return model, tokens
