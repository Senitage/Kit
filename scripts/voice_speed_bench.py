"""Time Chatterbox Turbo the way Kit uses it now, and faster ways to run it.

A one-off test, not part of Kit: run it with the voice's own Python (the one the
speech worker uses), on the PC with the GPU.

    python voice_speed_bench.py --reference /path/to/heart.wav --out ./bench

For each way of making speech it prints how long until the first sound could
play, how long the whole line took, and (streamed) whether playback would have
had to wait for the next piece. Every line is saved as a .wav so you can listen.

Ways (``--modes``):
  now        what the speech worker does today: the whole line, then it plays
  fp16       the same, with the voice model in half precision
  stream     plays the first ~0.5 s while the rest is made
  stream16   streamed and half precision
  parts      today's way split in two: making the speech tokens, then turning
             them into sound (shows which half is slow)
  graph      parts, with the token loop recorded as a CUDA graph and replayed
  stream2    streamed in growing pieces (12, 25, 50... tokens), so the decoder
             runs fewer times
  gstream    streamed in growing pieces with the CUDA graph token loop
"""

from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import time
import wave
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from chatterbox.models.s3gen.const import S3GEN_SIL
from chatterbox.models.s3gen.s3gen import S3Token2Mel
from chatterbox.tts_turbo import ChatterboxTurboTTS, punc_norm
from transformers.generation.logits_process import (
    LogitsProcessorList,
    RepetitionPenaltyLogitsProcessor,
    TemperatureLogitsWarper,
    TopKLogitsWarper,
    TopPLogitsWarper,
)

LINES = [
    "Yeah, I reckon so.",
    "Morning! You were up early, did the coffee machine finally behave itself?",
    "Honestly, I think the cat has decided the printer is hers now, and I'm not "
    "brave enough to tell her otherwise.",
]
OOV = 6561  # speech tokens at or above this aren't sounds
TOKEN_SAMPLES = 960  # 25 speech tokens a second at 24 kHz
LOOKAHEAD = 3  # tokens whose sound isn't settled until the decoder sees what follows
FADE = 480  # 20 ms crossfade where streamed pieces meet


def sync() -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def half(enabled: bool):
    if enabled and torch.cuda.is_available():
        return torch.autocast("cuda", dtype=torch.float16)
    return contextlib.nullcontext()


def speech_tokens(tts: ChatterboxTurboTTS, text: str, fp16: bool):
    """Chatterbox Turbo's token loop (``T3.inference_turbo``), yielding each token
    as it's made instead of returning them all at the end."""
    t3 = tts.t3
    text_tokens = tts.tokenizer(punc_norm(text), return_tensors="pt").input_ids.to(tts.device)
    procs = LogitsProcessorList(
        [
            TemperatureLogitsWarper(0.8),
            TopKLogitsWarper(1000),
            TopPLogitsWarper(0.95),
            RepetitionPenaltyLogitsProcessor(1.2),
        ]
    )
    start = t3.hp.start_speech_token * torch.ones_like(text_tokens[:, :1])
    with torch.inference_mode(), half(fp16):
        embeds, _ = t3.prepare_input_embeds(
            t3_cond=tts.conds.t3, text_tokens=text_tokens, speech_tokens=start, cfg_weight=0.0
        )
        out = t3.tfmr(inputs_embeds=embeds, use_cache=True)
        past, logits = out.past_key_values, t3.speech_head(out[0][:, -1:])
        made: list[torch.Tensor] = []
        for _ in range(1000):
            seen = torch.cat(made, dim=1) if made else start
            scores = procs(seen, logits[:, -1, :].float())
            token = torch.multinomial(F.softmax(scores, dim=-1), num_samples=1)
            if int(token) == t3.hp.stop_speech_token:
                return
            made.append(token)
            yield int(token)
            out = t3.tfmr(inputs_embeds=t3.speech_emb(token), past_key_values=past, use_cache=True)
            past, logits = out.past_key_values, t3.speech_head(out[0])


def rules(logits, seen, temperature=0.8, top_k=1000, top_p=0.95, penalty=1.2):
    """The same choosing rules as the loop above (temperature, top-k, top-p, then
    the repeat penalty), written with tensors only so a CUDA graph can record them.
    ``seen`` marks the tokens already said."""
    s = logits / temperature
    s = s.masked_fill(s < torch.topk(s, top_k, dim=-1).values[..., -1:], float("-inf"))
    ordered, order = torch.sort(s, dim=-1)
    drop = ordered.softmax(-1).cumsum(-1) <= 1 - top_p
    drop[..., -1:] = False
    s = s.masked_fill(drop.scatter(1, order, drop), float("-inf"))
    return torch.where(seen, torch.where(s < 0, s * penalty, s / penalty), s)


def pick(logits, seen):
    """Choose the next token by ``rules``. Sampling uses the exponential trick
    (argmax of p / Exp(1)), which picks each token with probability p and, unlike
    ``torch.multinomial``, is safe to record in a CUDA graph."""
    probs = rules(logits, seen).softmax(-1)
    return (probs / torch.empty_like(probs).exponential_(1)).argmax(-1, keepdim=True)


def _kv(past, i):
    if hasattr(past, "layers"):
        return past.layers[i].keys, past.layers[i].values
    return past[i][0], past[i][1]


class GraphTokens:
    """The token loop with each step recorded once as a CUDA graph and replayed.

    The loop above is slow because Python hands the GPU a few hundred tiny jobs
    for every token. Here one step (the 24 GPT-2 layers, choosing the token, and
    moving on a place) works on fixed buffers: a key/value store sized for the
    longest line, the current token and its position. So it can be recorded once
    and replayed with a single call per token. Python only looks at the result
    every ``check_every`` tokens, to hand them on and spot the end. Without a GPU
    the same step just runs normally (for checking it gives the same answers)."""

    def __init__(self, tts: ChatterboxTurboTTS, max_len=1600, max_new=1000, check_every=4):
        t3, tf = tts.t3, tts.t3.tfmr
        self.tts, self.max_len, self.max_new, self.check_every = tts, max_len, max_new, check_every
        self.width = tf.config.n_embd
        self.heads = tf.config.n_head
        dev, dtype = tts.device, next(tf.parameters()).dtype
        shape = (len(tf.h), 1, self.heads, max_len, self.width // self.heads)
        with torch.inference_mode():
            self.keys = torch.zeros(shape, device=dev, dtype=dtype)
            self.values = torch.zeros(shape, device=dev, dtype=dtype)
            self.token = torch.zeros(1, 1, dtype=torch.long, device=dev)
            self.pos = torch.zeros(1, dtype=torch.long, device=dev)
            self.step = torch.zeros(1, dtype=torch.long, device=dev)
            self.seen = torch.zeros(1, t3.speech_head.out_features, dtype=torch.bool, device=dev)
            self.out = torch.zeros(1, max_new + check_every, dtype=torch.long, device=dev)
            self.places = torch.arange(max_len, device=dev)
        self.graph = None
        if str(dev).startswith("cuda"):
            self._record()

    def logits(self):
        """One token through the model, using and filling the key/value store."""
        t3, tf = self.tts.t3, self.tts.t3.tfmr
        heads, size = self.heads, self.width // self.heads
        x = t3.speech_emb(self.token) + tf.wpe(self.pos.view(1, 1))
        mask = (self.places <= self.pos).view(1, 1, 1, -1)
        for i, block in enumerate(tf.h):
            q, k, v = block.attn.c_attn(block.ln_1(x)).split(self.width, dim=2)
            q, k, v = (t.view(1, 1, heads, size).transpose(1, 2) for t in (q, k, v))
            self.keys[i].index_copy_(2, self.pos, k)
            self.values[i].index_copy_(2, self.pos, v)
            a = F.scaled_dot_product_attention(q, self.keys[i], self.values[i], attn_mask=mask)
            x = x + block.attn.c_proj(a.transpose(1, 2).reshape(1, 1, self.width))
            x = x + block.mlp(block.ln_2(x))
        return t3.speech_head(tf.ln_f(x))[:, -1, :].float()

    def _step(self) -> None:
        token = pick(self.logits(), self.seen)
        self.seen.scatter_(1, token, True)
        self.out.index_copy_(1, self.step, token)
        self.token.copy_(token)
        self.pos.add_(1)
        self.step.add_(1)

    def _record(self) -> None:
        with torch.inference_mode():
            side = torch.cuda.Stream()
            side.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(side):
                for _ in range(3):  # warm up before recording, as CUDA graphs need
                    self._step()
            torch.cuda.current_stream().wait_stream(side)
            self.graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(self.graph):
                self._step()

    def __call__(self, text: str):
        """Speech tokens for ``text``, yielded a few at a time as they're made."""
        tts, t3 = self.tts, self.tts.t3
        stop = t3.hp.stop_speech_token
        ids = tts.tokenizer(punc_norm(text), return_tensors="pt").input_ids.to(tts.device)
        start = t3.hp.start_speech_token * torch.ones_like(ids[:, :1])
        with torch.inference_mode():
            embeds, _ = t3.prepare_input_embeds(
                t3_cond=tts.conds.t3, text_tokens=ids, speech_tokens=start, cfg_weight=0.0
            )
            n = embeds.shape[1]
            if n + self.max_new + self.check_every > self.max_len:
                raise ValueError(f"line too long for the graph's store ({n} prompt tokens)")
            out = t3.tfmr(inputs_embeds=embeds, use_cache=True)
            for i in range(len(t3.tfmr.h)):
                k, v = _kv(out.past_key_values, i)
                self.keys[i, :, :, :n].copy_(k)
                self.values[i, :, :, :n].copy_(v)
            # The first token is chosen with only the start token counted as seen,
            # as Chatterbox's own loop does; after that, only spoken tokens count.
            self.seen.zero_()
            self.seen[0, t3.hp.start_speech_token] = True
            first = pick(t3.speech_head(out[0][:, -1:])[:, -1, :].float(), self.seen)
            if int(first) == stop:
                return
            self.seen.zero_()
            self.seen.scatter_(1, first, True)
            self.token.copy_(first)
            self.pos.fill_(n)
            self.step.zero_()
        yield int(first)
        done = 0
        while done < self.max_new:
            with torch.inference_mode():
                for _ in range(self.check_every):
                    if self.graph is not None:
                        self.graph.replay()
                    else:
                        self._step()
                made = self.out[0, done : done + self.check_every].tolist()
            done += self.check_every
            for token in made:
                if token == stop:
                    return
                yield token


def to_audio(tts: ChatterboxTurboTTS, tokens: list[int], final: bool, noise, fp16: bool):
    """Speech tokens so far -> audio, as Chatterbox's own decoder does it. The
    decoder's own not-final mode doesn't work in this version (its mask keeps the
    tokens it drops), so it always decodes everything and the caller holds back the
    end until what follows is known."""
    s3 = tts.s3gen
    toks = [t for t in tokens if t < OOV]
    if final:
        toks += [S3GEN_SIL] * 3
    t = torch.tensor([toks], dtype=torch.long, device=tts.device)
    frames = 2 * len(toks)
    with torch.inference_mode(), half(fp16):
        mels = S3Token2Mel.forward(
            s3,
            t,
            ref_wav=None,
            ref_sr=None,
            ref_dict=tts.conds.gen,
            n_cfm_timesteps=2,
            finalize=True,
            noised_mels=noise[:, :, :frames],
        )
        wav, _ = s3.hift_inference(mels.to(s3.dtype), None)
        wav[:, : len(s3.trim_fade)] *= s3.trim_fade
    return wav[0].float().cpu().numpy()


def whole(tts: ChatterboxTurboTTS, text: str, fp16: bool) -> dict:
    """Today's way: make the whole line, then play it."""
    sync()
    t0 = time.perf_counter()
    with torch.inference_mode(), half(fp16):
        wav = tts.generate(text)
    sync()
    took = time.perf_counter() - t0
    audio = wav.squeeze(0).float().cpu().numpy()
    return {"first": took, "total": took, "stalls": 0.0, "audio": audio}


def parts(tts: ChatterboxTurboTTS, text: str, loop=None) -> dict:
    """Today's way, timed in its two halves: the token loop, then the decoder.
    ``loop`` swaps in another token loop (``GraphTokens``)."""
    noise = torch.randn(1, 80, 2 * 1100, device=tts.device, dtype=tts.s3gen.dtype)
    sync()
    t0 = time.perf_counter()
    tokens = list(loop(text) if loop else speech_tokens(tts, text, False))
    sync()
    t1 = time.perf_counter()
    audio = to_audio(tts, tokens, True, noise, False)
    sync()
    t2 = time.perf_counter()
    return {
        "first": t2 - t0,
        "total": t2 - t0,
        "stalls": 0.0,
        "audio": audio,
        "tokens_s": t1 - t0,
        "decode_s": t2 - t1,
        "tokens": len(tokens),
    }


def streamed(
    tts: ChatterboxTurboTTS,
    text: str,
    fp16: bool,
    first: int,
    chunk: int,
    loop=None,
    grow: float = 1.0,
) -> dict:
    """Make audio every ``first`` then ``chunk`` tokens and hand each piece over as
    soon as it's ready, crossfading where pieces meet. Each piece after the first is
    ``grow`` times bigger, so the decoder runs fewer times once playback is ahead.
    ``loop`` swaps in another token loop (``GraphTokens``)."""
    noise = torch.randn(1, 80, 2 * 1100, device=tts.device, dtype=tts.s3gen.dtype)
    ramp = np.linspace(0.0, 1.0, FADE, dtype=np.float32)
    pieces, arrivals = [], []
    tokens: list[int] = []
    out_at, tail, due = 0, None, first + LOOKAHEAD
    sync()
    t0 = time.perf_counter()

    def emit(wav: np.ndarray, final: bool) -> None:
        nonlocal out_at, tail
        end = len(wav) if final else len(wav) - (LOOKAHEAD + 1) * TOKEN_SAMPLES
        seg = wav[out_at:end].copy()
        if len(seg) <= 2 * FADE and not final:
            return
        if tail is not None:
            n = min(FADE, len(seg))
            seg[:n] = tail[:n] * (1 - ramp[:n]) + seg[:n] * ramp[:n]
        if final:
            ready, tail = seg, None
        else:
            ready, tail, out_at = seg[:-FADE], seg[-FADE:], end - FADE
        # Chatterbox marks its audio as made by AI; each piece gets the same mark.
        pieces.append(tts.watermarker.apply_watermark(ready, sample_rate=tts.sr))
        arrivals.append(time.perf_counter() - t0)

    for token in loop(text) if loop else speech_tokens(tts, text, fp16):
        tokens.append(token)
        if len(tokens) >= due:
            emit(to_audio(tts, tokens, False, noise, fp16), False)
            due = len(tokens) + chunk
            chunk = min(int(chunk * grow), 200)
    emit(to_audio(tts, tokens, True, noise, fp16), True)
    sync()
    total = time.perf_counter() - t0
    audio = np.concatenate(pieces)
    # Would the speaker have run dry waiting for a piece?
    stalls, playing_until = 0.0, arrivals[0]
    for piece, arrived in zip(pieces, arrivals, strict=True):
        if arrived > playing_until:
            stalls += arrived - playing_until
            playing_until = arrived
        playing_until += len(piece) / tts.sr
    return {"first": arrivals[0], "total": total, "stalls": stalls, "audio": audio}


def save(path: Path, audio: np.ndarray, rate: int) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--reference", default="", help="Kit's voice clip (the engine's 'reference')")
    p.add_argument("--out", default="voice_bench", help="folder for the .wav files and results")
    p.add_argument("--modes", default="now,parts,graph,stream2,gstream")
    p.add_argument("--runs", type=int, default=3, help="tries per line (the median is shown)")
    p.add_argument("--first", type=int, default=12, help="streamed: tokens in the first piece")
    p.add_argument("--chunk", type=int, default=25, help="streamed: tokens in later pieces")
    args = p.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(
        f"loading Chatterbox Turbo on {device}"
        + (f" ({torch.cuda.get_device_name(0)})" if device == "cuda" else "")
    )
    tts = ChatterboxTurboTTS.from_pretrained(device=device)
    if args.reference:
        tts.prepare_conditionals(args.reference)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    graph = None
    if {"graph", "gstream"} & set(modes):
        t0 = time.perf_counter()
        try:
            graph = GraphTokens(tts)
            print(f"recorded the token step as a CUDA graph in {time.perf_counter() - t0:.1f}s")
        except Exception as e:  # report it and carry on with the other ways
            print(f"couldn't record the CUDA graph, skipping graph and gstream: {e!r}")
            modes = [m for m in modes if m not in ("graph", "gstream")]
    run = {
        "now": lambda text: whole(tts, text, False),
        "fp16": lambda text: whole(tts, text, True),
        "stream": lambda text: streamed(tts, text, False, args.first, args.chunk),
        "stream16": lambda text: streamed(tts, text, True, args.first, args.chunk),
        "parts": lambda text: parts(tts, text),
        "graph": lambda text: parts(tts, text, graph),
        "stream2": lambda text: streamed(tts, text, False, args.first, args.chunk, grow=2.0),
        "gstream": lambda text: streamed(
            tts, text, False, args.first, args.chunk, loop=graph, grow=2.0
        ),
    }
    for mode in modes:  # warm each way up once so the first timing isn't a cold start
        run[mode]("Warming up.")

    results = []
    for i, text in enumerate(LINES, 1):
        print(f"\nline {i}: {text}")
        for mode in modes:
            tries = []
            for r in range(args.runs):
                torch.manual_seed(r)
                if device == "cuda":
                    torch.cuda.reset_peak_memory_stats()
                tries.append(run[mode](text))
            seconds = len(tries[0]["audio"]) / tts.sr
            row = {
                "line": i,
                "mode": mode,
                "first_sound_s": round(statistics.median(t["first"] for t in tries), 3),
                "total_s": round(statistics.median(t["total"] for t in tries), 3),
                "stalls_s": round(statistics.median(t["stalls"] for t in tries), 3),
                "audio_s": round(seconds, 2),
                "vram_peak_mb": round(torch.cuda.max_memory_allocated() / 2**20)
                if device == "cuda"
                else None,
            }
            row["made_vs_played"] = round(seconds / row["total_s"], 2)
            if mode in ("parts", "graph"):
                row["token_loop_s"] = round(statistics.median(t["tokens_s"] for t in tries), 3)
                row["decode_s"] = round(statistics.median(t["decode_s"] for t in tries), 3)
                row["tokens_per_s"] = round(
                    statistics.median(t["tokens"] / t["tokens_s"] for t in tries), 1
                )
            results.append(row)
            save(out / f"line{i}_{mode}.wav", tries[0]["audio"], tts.sr)
            print(
                f"  {mode:9} first sound {row['first_sound_s']:.2f}s  "
                f"whole line {row['total_s']:.2f}s  gaps {row['stalls_s']:.2f}s  "
                f"({row['audio_s']:.1f}s of speech, made at {row['made_vs_played']:.2f}x "
                "the speed it plays)"
            )
            if mode in ("parts", "graph"):
                print(
                    f"            token loop {row['token_loop_s']:.2f}s "
                    f"({row['tokens_per_s']:.0f} tokens/s; 25 plays in real time), "
                    f"decoder {row['decode_s']:.2f}s"
                )
    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nsaved the clips and results.json in {out.resolve()}")


if __name__ == "__main__":
    main()
