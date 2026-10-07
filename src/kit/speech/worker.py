"""Kit's speech worker: one voice engine behind a tiny local web server.

Kit runs this file by its path with whichever Python has the engine installed
(each engine can live in its own virtual environment, since Chatterbox and Kokoro
need different numpy versions). So it imports nothing from Kit: only the standard
library, numpy and the engine itself.

    python worker.py --engine kokoro --port 8611 --options '{"voice": "af_heart"}'

GET  /health  -> {"engine", "kind", "sample_rate", "device", "ready"}
POST /speak   {"text": "...", "mood": "happy", "first": true} -> audio/wav (16-bit mono), with
              X-Synth-Ms (time to make it) and X-Audio-Ms (how long it plays)

Engines (``kind``):
  tone              beeps, one per word: for tests and checking the plumbing
  kokoro            kokoro-onnx; fast on a CPU; mood changes the speed
  piper             piper-tts; very fast on a CPU; mood changes the speed
  chatterbox        Chatterbox; expressive, GPU; mood turns the emotion dial
  chatterbox-turbo  Chatterbox Turbo; faster, GPU; no emotion dial, but a sound tag
                    such as [sigh] can open a reply
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import threading
import time
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

KOKORO_FILES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"


def wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """Float audio (-1 to 1) as a 16-bit mono WAV file."""
    pcm = (np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def mood_value(table: dict, mood: str, default: float) -> float:
    """``table[mood]``, else ``table["default"]``, else ``default``."""
    return float(table.get(mood, table.get("default", default)))


class Tone:
    """A short beep per word, so the whole path can be tested without a voice model."""

    sample_rate = 16000
    device = "cpu"

    def __init__(self, options: dict, models_dir: Path) -> None:
        self.options = options

    def speak(self, text: str, mood: str, first: bool = False) -> np.ndarray:
        words = max(1, len(text.split()))
        pitch = 440 * mood_value(self.options.get("mood_speed", {}), mood, 1.0)
        t = np.arange(int(0.08 * self.sample_rate)) / self.sample_rate
        beep = np.sin(2 * math.pi * pitch * t)
        gap = np.zeros(int(0.04 * self.sample_rate))
        return np.concatenate([np.concatenate([0.3 * beep, gap]) for _ in range(words)])


class KokoroEngine:
    device = "cpu"

    def __init__(self, options: dict, models_dir: Path) -> None:
        from kokoro_onnx import Kokoro

        model = Path(options.get("model") or models_dir / "kokoro-v1.0.onnx")
        voices = Path(options.get("voices") or models_dir / "voices-v1.0.bin")
        for path in (model, voices):
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                log(f"downloading {path.name} (once)")
                urllib.request.urlretrieve(KOKORO_FILES + path.name, path)
        self.kokoro = Kokoro(str(model), str(voices))
        self.voice = options.get("voice") or "af_heart"
        self.speed = float(options.get("speed", 1.0))
        self.mood_speed = options.get("mood_speed", {})
        self.sample_rate = 24000

    def speak(self, text: str, mood: str, first: bool = False) -> np.ndarray:
        speed = self.speed * mood_value(self.mood_speed, mood, 1.0)
        audio, self.sample_rate = self.kokoro.create(text, voice=self.voice, speed=speed)
        return audio


class PiperEngine:
    device = "cpu"

    def __init__(self, options: dict, models_dir: Path) -> None:
        from piper import PiperVoice

        model = options.get("voice") or options.get("model") or ""
        path = Path(model)
        if not path.is_absolute():
            path = models_dir / path
        if not model or not path.exists():
            raise RuntimeError(
                "piper needs a voice model: download one with "
                "`python -m piper.download_voices en_US-lessac-medium` and set its .onnx "
                f"file as the voice (looked for {path})"
            )
        self.piper = PiperVoice.load(str(path))
        self.sample_rate = self.piper.config.sample_rate
        self.speed = float(options.get("speed", 1.0))
        self.mood_speed = options.get("mood_speed", {})

    def speak(self, text: str, mood: str, first: bool = False) -> np.ndarray:
        from piper import SynthesisConfig

        speed = self.speed * mood_value(self.mood_speed, mood, 1.0)
        base = getattr(self.piper.config, "length_scale", None) or 1.0
        config = SynthesisConfig(length_scale=base / max(speed, 0.1))
        chunks = [c.audio_float_array for c in self.piper.synthesize(text, syn_config=config)]
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def _torch_device(wanted: str) -> str:
    import torch

    if wanted in ("", "auto"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return wanted


class ChatterboxEngine:
    """Standard Chatterbox: the voice is copied from a reference clip once, and the
    mood turns its emotion dial (``exaggeration``) for each line."""

    def __init__(self, options: dict, models_dir: Path) -> None:
        from chatterbox.tts import ChatterboxTTS

        self.device = _torch_device(options.get("device", "auto"))
        self.tts = ChatterboxTTS.from_pretrained(device=self.device)
        reference = options.get("reference") or ""
        self.exaggeration = options.get("exaggeration", {})
        self.cfg_weight = float(options.get("cfg_weight", 0.5))
        if reference:
            self.tts.prepare_conditionals(reference, exaggeration=0.5)
        self.sample_rate = self.tts.sr

    def speak(self, text: str, mood: str, first: bool = False) -> np.ndarray:
        dial = mood_value(self.exaggeration, mood, 0.5)
        wav = self.tts.generate(text, exaggeration=dial, cfg_weight=self.cfg_weight)
        return wav.squeeze(0).cpu().numpy()


class ChatterboxTurboEngine:
    """Chatterbox Turbo: about two and a half times faster, but no emotion dial."""

    def __init__(self, options: dict, models_dir: Path) -> None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        self.device = _torch_device(options.get("device", "auto"))
        self.tts = ChatterboxTurboTTS.from_pretrained(device=self.device)
        reference = options.get("reference") or ""
        if reference:
            self.tts.prepare_conditionals(reference)
        self.mood_tags = options.get("mood_tags", {})
        self.sample_rate = self.tts.sr

    def speak(self, text: str, mood: str, first: bool = False) -> np.ndarray:
        tag = self.mood_tags.get(mood, "") if first else ""
        return self.tts.generate(f"{tag} {text}".strip()).squeeze(0).cpu().numpy()


ENGINES = {
    "tone": Tone,
    "kokoro": KokoroEngine,
    "piper": PiperEngine,
    "chatterbox": ChatterboxEngine,
    "chatterbox-turbo": ChatterboxTurboEngine,
}


def log(message: str) -> None:
    print(f"[speech] {message}", file=sys.stderr, flush=True)


class Worker:
    def __init__(self, name: str, kind: str, options: dict, models_dir: Path) -> None:
        self.name, self.kind = name, kind
        self.engine = ENGINES[kind](options, models_dir)
        self.lock = threading.Lock()  # one line at a time: the GPU can't share anyway

    def health(self) -> dict:
        return {
            "engine": self.name,
            "kind": self.kind,
            "sample_rate": self.engine.sample_rate,
            "device": getattr(self.engine, "device", "cpu"),
            "ready": True,
        }

    def speak(self, text: str, mood: str, first: bool = False) -> tuple[bytes, float, float]:
        with self.lock:
            start = time.perf_counter()
            audio = self.engine.speak(text, mood, first)
            synth_ms = (time.perf_counter() - start) * 1000
        audio_ms = 1000 * len(np.asarray(audio).reshape(-1)) / self.engine.sample_rate
        return wav_bytes(audio, self.engine.sample_rate), synth_ms, audio_ms


def make_handler(worker: Worker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet: Kit logs what matters
            pass

        def _json(self, code: int, data: dict) -> None:
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            if self.path == "/health":
                self._json(200, worker.health())
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/speak":
                self._json(404, {"error": "not found"})
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                text = str(data.get("text", "")).strip()
                if not text:
                    self._json(400, {"error": "no text"})
                    return
                mood = str(data.get("mood", "neutral"))
                audio, synth_ms, audio_ms = worker.speak(text, mood, bool(data.get("first")))
            except Exception as e:  # the engine failed on this line: say why, keep running
                log(f"failed on {data.get('text', '')!r}: {e}")
                self._json(500, {"error": f"{type(e).__name__}: {e}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("X-Synth-Ms", f"{synth_ms:.0f}")
            self.send_header("X-Audio-Ms", f"{audio_ms:.0f}")
            self.end_headers()
            self.wfile.write(audio)

    return Handler


def watch_parent(parent: int, server: ThreadingHTTPServer) -> None:
    """Stop when Kit does, so a crashed Kit never leaves a model holding the
    graphics card."""
    while os.getppid() == parent:
        time.sleep(2)
    log("Kit has gone, stopping")
    server.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", required=True, help="the profile name, for messages")
    parser.add_argument("--kind", choices=sorted(ENGINES), help="default: the engine name")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--options", default="{}", help="engine options as JSON")
    parser.add_argument("--models-dir", default=".", help="where downloaded model files go")
    parser.add_argument("--warm-up", action="store_true", help="say one line before serving")
    parser.add_argument(
        "--parent", type=int, help="Kit's process id: when it's gone, this stops too"
    )
    args = parser.parse_args(argv)
    kind = args.kind or args.engine
    start = time.perf_counter()
    try:
        worker = Worker(args.engine, kind, json.loads(args.options), Path(args.models_dir))
        if args.warm_up:
            worker.speak("Warming up.", "neutral")
    except Exception as e:
        log(f"{args.engine} couldn't start: {type(e).__name__}: {e}")
        return 1
    took = time.perf_counter() - start
    log(f"{args.engine} ready in {took:.1f} s on {worker.health()['device']}")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(worker))
    if args.parent:
        threading.Thread(target=watch_parent, args=(args.parent, server), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
