"""A faster token loop for Chatterbox Turbo, used by the speech worker.

Chatterbox Turbo makes speech in two halves: a GPT-2 model picks speech tokens
one at a time (25 make a second of speech), then a decoder turns them into
sound. The token loop is about 90% of the time, and on a mid-range card it
barely keeps up with real time, because Python hands the graphics card a few
hundred tiny jobs for every token.

``GraphTokens`` runs one step of that loop (the 24 layers, choosing the token,
moving on a place) on fixed buffers, so it can be recorded once as a CUDA graph
and replayed with a single call per token: about 2.4 times faster on Dan's RTX
2070 Super (32 to 76-80 tokens a second). It does the same sums as Chatterbox's
own loop, so Kit's voice doesn't change.

Like ``worker.py`` this runs inside the voice's own Python, so it imports
nothing from Kit, and torch only when it's used.
"""

from __future__ import annotations

SILENCE = 4299  # Chatterbox's S3GEN_SIL token: a short silence the decoder ends on
OOV = 6561  # speech tokens at or above this aren't sounds


def rules(logits, seen, temperature=0.8, top_k=1000, top_p=0.95, penalty=1.2):
    """Chatterbox Turbo's choosing rules (temperature, top-k, top-p, then the repeat
    penalty, in transformers' order), written with tensors only so a CUDA graph can
    record them. ``seen`` marks the tokens already said."""
    import torch

    s = logits / temperature
    kth = torch.topk(s, min(top_k, s.shape[-1]), dim=-1).values[..., -1:]
    s = s.masked_fill(s < kth, float("-inf"))
    ordered, order = torch.sort(s, dim=-1)
    drop = ordered.softmax(-1).cumsum(-1) <= 1 - top_p
    drop[..., -1:] = False
    s = s.masked_fill(drop.scatter(1, order, drop), float("-inf"))
    return torch.where(seen, torch.where(s < 0, s * penalty, s / penalty), s)


def pick(logits, seen):
    """Choose the next token by ``rules``. The exponential trick (argmax of
    p / Exp(1)) picks each token with probability p and, unlike
    ``torch.multinomial``, is safe to record in a CUDA graph."""
    import torch

    probs = rules(logits, seen).softmax(-1)
    return (probs / torch.empty_like(probs).exponential_(1)).argmax(-1, keepdim=True)


def _kv(past, i):
    if hasattr(past, "layers"):
        return past.layers[i].keys, past.layers[i].values
    return past[i][0], past[i][1]


class GraphTokens:
    """Chatterbox Turbo's token loop with each step recorded as a CUDA graph.

    One step works on fixed buffers: a key/value store sized for the longest line,
    the current token and its place. Python only looks at the result every
    ``check_every`` tokens, to hand them on and spot the end. Without a graphics
    card the same step just runs normally, which is how the tests check it.

    Every line starts with the same speaker conditioning (the voice clip as 375
    tokens and a speaker embedding), so its keys and values are worked out once
    and kept (``_cond``); each line then only runs its own text through the model
    before the loop starts. If the conditioning ever differs, the whole prompt is
    run again and the cache replaced."""

    def __init__(self, tts, max_len=1600, max_new=1000, check_every=4) -> None:
        import torch

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
        self._cond = None  # (conditioning embeds, their keys, their values)
        if str(dev).startswith("cuda"):
            self._record()

    def logits(self):
        """One token through the model, using and filling the key/value store."""
        import torch.nn.functional as F

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

    def prefill(self, embeds, start: int):
        """A run of prompt embeddings at places ``start`` on, through the model at
        once, filling the key/value store: the logits for the last of them. The same
        sums as ``logits`` for a run of tokens, so Chatterbox's own forward pass
        isn't needed and the store can be filled part by part."""
        import torch.nn.functional as F

        t3, tf = self.tts.t3, self.tts.t3.tfmr
        heads, size = self.heads, self.width // self.heads
        n = embeds.shape[1]
        places = self.places[start : start + n]
        x = embeds + tf.wpe(places).unsqueeze(0)
        mask = (self.places.view(1, -1) <= places.view(-1, 1)).view(1, 1, n, -1)
        for i, block in enumerate(tf.h):
            q, k, v = block.attn.c_attn(block.ln_1(x)).split(self.width, dim=2)
            q, k, v = (t.view(1, n, heads, size).transpose(1, 2) for t in (q, k, v))
            self.keys[i][:, :, start : start + n].copy_(k)
            self.values[i][:, :, start : start + n].copy_(v)
            a = F.scaled_dot_product_attention(q, self.keys[i], self.values[i], attn_mask=mask)
            x = x + block.attn.c_proj(a.transpose(1, 2).reshape(1, n, self.width))
            x = x + block.mlp(block.ln_2(x))
        return t3.speech_head(tf.ln_f(x[:, -1:]))[:, -1, :].float()

    def _prompt(self, embeds, n_cond: int):
        """Fill the store for the prompt: the kept conditioning when it's the same
        as last time, and only the text after it through the model."""
        import torch

        cond = embeds[:, :n_cond]
        kept = self._cond
        if kept is not None and kept[0].shape == cond.shape and torch.equal(kept[0], cond):
            for i in range(len(self.tts.t3.tfmr.h)):
                self.keys[i][:, :, :n_cond].copy_(kept[1][i])
                self.values[i][:, :, :n_cond].copy_(kept[2][i])
            return self.prefill(embeds[:, n_cond:], n_cond)
        logits = self.prefill(embeds, 0)
        self._cond = (
            cond.clone(),
            self.keys[:, :, :, :n_cond].clone(),
            self.values[:, :, :, :n_cond].clone(),
        )
        return logits

    def _step(self) -> None:
        token = pick(self.logits(), self.seen)
        self.seen.scatter_(1, token, True)
        self.out.index_copy_(1, self.step, token)
        self.token.copy_(token)
        self.pos.add_(1)
        self.step.add_(1)

    def _record(self) -> None:
        import torch

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
        import torch
        from chatterbox.tts_turbo import punc_norm

        tts, t3 = self.tts, self.tts.t3
        stop = t3.hp.stop_speech_token
        ids = tts.tokenizer(punc_norm(text), return_tensors="pt").input_ids.to(tts.device)
        start = t3.hp.start_speech_token * torch.ones_like(ids[:, :1])
        with torch.inference_mode():
            embeds, n_cond = t3.prepare_input_embeds(
                t3_cond=tts.conds.t3, text_tokens=ids, speech_tokens=start, cfg_weight=0.0
            )
            n = embeds.shape[1]
            if n + self.max_new + self.check_every > self.max_len:
                raise ValueError(f"line too long for the token store ({n} prompt tokens)")
            logits = self._prompt(embeds, int(n_cond))
            # The first token is chosen with only the start token counted as seen,
            # as Chatterbox's own loop does; after that, only spoken tokens count.
            self.seen.zero_()
            self.seen[0, t3.hp.start_speech_token] = True
            first = pick(logits, self.seen)
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


def generate(tts, graph: GraphTokens, text: str):
    """``ChatterboxTurboTTS.generate`` with the faster token loop: the same decoder
    and settings, as a float numpy array. Without Chatterbox's watermark, which
    cost 30 to 80 ms of processor time a clip and marked sound that never leaves
    the house."""
    import torch

    tokens = [t for t in graph(text) if t < OOV] + [SILENCE] * 3
    with torch.inference_mode():
        speech = torch.tensor(tokens, dtype=torch.long, device=tts.device)
        wav, _ = tts.s3gen.inference(
            speech_tokens=speech, ref_dict=tts.conds.gen, n_cfm_timesteps=2
        )
    return wav.squeeze(0).detach().float().cpu().numpy()
