"""``kit speech bench``: the same Kit lines through several voice engines, timed.

For each engine it records how long it takes to load, how soon Kit could start
talking (the first sentence of each line), whether speech keeps up once it has
started (gaps while the next sentence is still being made), and graphics card
memory if ``nvidia-smi`` is there. The clips and a page to compare them go in
Kit's data folder.
"""

from __future__ import annotations

import html
import io
import json
import subprocess
import time
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kit.speech.sentences import SentenceSplitter
from kit.speech.service import SpeechError, SpeechService

LINES: list[tuple[str, str]] = [
    (
        "neutral",
        "The pump curve's ready. The duty point sits at about eighty percent of best efficiency.",
    ),
    ("happy", "Oh, nice! The flotation model finally behaved. Told you it would."),
    ("excited", "Wait, it passed? All forty tests? That's brilliant! Let's ship it!"),
    ("grumpy", "Ugh. The build failed again. Same import error, third time today."),
    ("tired", "It's getting late, Dan. I'll keep the notes, and we can pick it up tomorrow."),
    ("curious", "Hmm. That's odd. Why would the cyclone pressure drop like that?"),
]


@dataclass
class LineResult:
    mood: str
    text: str
    clip: str = ""
    first_ms: float = 0  # time to make the first sentence: how soon Kit starts talking
    synth_ms: float = 0
    audio_ms: float = 0
    gap_ms: float = 0  # silence while waiting for later sentences
    error: str = ""


@dataclass
class EngineResult:
    engine: str
    kind: str = ""
    device: str = ""
    load_s: float = 0
    gpu_before_mib: int | None = None
    gpu_peak_mib: int | None = None
    lines: list[LineResult] = field(default_factory=list)
    error: str = ""

    def median_first_ms(self) -> float | None:
        values = sorted(x.first_ms for x in self.lines if not x.error)
        return values[len(values) // 2] if values else None

    def speed(self) -> float | None:
        """Seconds of speech per second of work (above 1 keeps up)."""
        synth = sum(x.synth_ms for x in self.lines if not x.error)
        audio = sum(x.audio_ms for x in self.lines if not x.error)
        return audio / synth if synth else None


def gpu_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def join_wavs(clips: list[bytes]) -> bytes:
    """Several WAV files of the same format as one."""
    frames, params = [], None
    for clip in clips:
        with wave.open(io.BytesIO(clip)) as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setparams(params)
        out.writeframes(b"".join(frames))
    return buf.getvalue()


def gaps(synth_ms: list[float], audio_ms: list[float]) -> float:
    """Silence while speaking sentence by sentence, each made after the one before."""
    ready = playing_until = 0.0
    silence = 0.0
    for n, (make, length) in enumerate(zip(synth_ms, audio_ms, strict=True)):
        ready += make
        if n and ready > playing_until:
            silence += ready - playing_until
        playing_until = max(ready, playing_until) + length
    return silence


def bench_engine(
    service: SpeechService,
    name: str,
    folder: Path,
    lines: list[tuple[str, str]] = LINES,
    gpu: Callable[[], int | None] = gpu_used_mib,
) -> EngineResult:
    result = EngineResult(engine=name)
    result.gpu_before_mib = gpu()
    peak = result.gpu_before_mib
    try:
        health = service.ensure(name)
    except SpeechError as e:
        result.error = str(e)
        return result
    result.kind, result.device = health.get("kind", ""), health.get("device", "")
    result.load_s = service.load_s or 0
    for n, (mood, text) in enumerate(lines):
        line = LineResult(mood=mood, text=text)
        splitter = SentenceSplitter()
        pieces = splitter.feed(text + " ") + splitter.flush()
        clips, made, lengths = [], [], []
        try:
            for piece in pieces:
                spoken = service.speak(piece, mood, name, first=not clips)
                clips.append(spoken.wav)
                made.append(spoken.synth_ms)
                lengths.append(spoken.audio_ms)
                used = gpu()
                if used is not None:
                    peak = max(peak or 0, used)
        except SpeechError as e:
            line.error = str(e)
        if clips:
            line.clip = f"{name}-{n + 1}-{mood}.wav"
            (folder / line.clip).write_bytes(join_wavs(clips))
            line.first_ms, line.synth_ms, line.audio_ms = made[0], sum(made), sum(lengths)
            line.gap_ms = gaps(made, lengths)
        result.lines.append(line)
    result.gpu_peak_mib = peak
    return result


def run_bench(
    service: SpeechService,
    engines: list[str],
    out_dir: Path,
    lines: list[tuple[str, str]] = LINES,
    gpu: Callable[[], int | None] = gpu_used_mib,
    show: Callable[[str], None] = print,
) -> list[EngineResult]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name in engines:
        show(f"{name}: loading")
        result = bench_engine(service, name, out_dir, lines, gpu)
        service.stop()  # free the memory before the next engine loads
        show(summary_line(result))
        results.append(result)
    (out_dir / "results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
    )
    (out_dir / "index.html").write_text(report(results), encoding="utf-8")
    return results


def summary_line(r: EngineResult) -> str:
    if r.error:
        return f"{r.engine}: couldn't run: {r.error}"
    first, speed = r.median_first_ms(), r.speed()
    gpu = ""
    if r.gpu_before_mib is not None and r.gpu_peak_mib is not None:
        gpu = f", graphics card {r.gpu_before_mib} -> {r.gpu_peak_mib} MiB"
    keeps_up = "keeps up" if all(x.gap_ms < 50 for x in r.lines if not x.error) else "has gaps"
    return (
        f"{r.engine}: loaded in {r.load_s:.1f} s on {r.device}; starts talking after "
        f"{(first or 0) / 1000:.2f} s (median); {speed or 0:.1f}x real time, {keeps_up}{gpu}"
    )


def report(results: list[EngineResult]) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M")
    rows = []
    for r in results:
        if r.error:
            rows.append(
                f"<tr><td>{html.escape(r.engine)}</td><td colspan=6>"
                f"Couldn't run: {html.escape(r.error)}</td></tr>"
            )
            continue
        for x in r.lines:
            audio = f"<audio controls preload=none src='{x.clip}'></audio>" if x.clip else ""
            rows.append(
                f"<tr><td>{html.escape(r.engine)}</td><td>{x.mood}</td>"
                f"<td>{html.escape(x.text)}</td><td>{audio}{html.escape(x.error)}</td>"
                f"<td class=n>{x.first_ms / 1000:.2f} s</td>"
                f"<td class=n>{x.synth_ms / 1000:.1f} / {x.audio_ms / 1000:.1f} s</td>"
                f"<td class=n>{x.gap_ms / 1000:.1f} s</td></tr>"
            )
    summary = "".join(f"<li>{html.escape(summary_line(r))}</li>" for r in results)
    return (
        "<!doctype html><meta charset=utf-8><title>Kit speech bench</title>"
        "<style>body{font:15px system-ui;margin:24px;max-width:1100px}"
        "td,th{padding:6px 10px;border-bottom:1px solid #ddd;text-align:left}"
        ".n{font-variant-numeric:tabular-nums;white-space:nowrap}</style>"
        f"<h1>Kit speech bench</h1><p>{stamp}</p><ul>{summary}</ul>"
        "<table><tr><th>Engine</th><th>Mood</th><th>Line</th><th>Listen</th>"
        "<th>Starts talking after</th><th>Made in / length</th><th>Gaps</th></tr>"
        + "".join(rows)
        + "</table>"
    )
