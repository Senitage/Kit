"""The faster Chatterbox Turbo token loop does the same sums as Chatterbox's own.

These need torch and chatterbox-tts (the voice's own Python), so they're skipped
where those aren't installed, as in Kit's own test run. The model is built with
random weights: no download, no graphics card.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("chatterbox")

import numpy as np  # noqa: E402
from transformers.generation.logits_process import (  # noqa: E402
    LogitsProcessorList,
    RepetitionPenaltyLogitsProcessor,
    TemperatureLogitsWarper,
    TopKLogitsWarper,
    TopPLogitsWarper,
)

from kit.speech import turbo  # noqa: E402


@pytest.fixture(scope="module")
def t3():
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    from chatterbox.models.t3.modules.t3_config import T3Config

    torch.manual_seed(0)
    hp = T3Config(text_tokens_dict_size=50276)  # Chatterbox Turbo's settings
    hp.llama_config_name = "GPT2_medium"
    hp.speech_tokens_dict_size = 6563
    hp.input_pos_emb = None
    hp.speech_cond_prompt_len = 375
    hp.use_perceiver_resampler = False
    hp.emotion_adv = False
    model = T3(hp)
    del model.tfmr.wte
    model.eval()
    model.cond = T3Cond(
        speaker_emb=torch.randn(1, 256),
        cond_prompt_speech_tokens=torch.randint(0, 6561, (1, 375)),
        emotion_adv=0.5 * torch.ones(1, 1, 1),
    )
    return model


class FakeTTS:
    """Just the parts of ChatterboxTurboTTS the token loop uses."""

    def __init__(self, t3) -> None:
        self.t3, self.device, self.sr = t3, "cpu", 24000
        self.conds = type("Conds", (), {"t3": t3.cond, "gen": {}})()
        self.s3gen = self
        self.watermarker = self
        self.decoded: list[int] = []  # tokens handed to the decoder each time

    def inference(self, speech_tokens, ref_dict, n_cfm_timesteps):
        self.decoded.append(len(speech_tokens))
        return torch.ones(1, 2 * len(speech_tokens)), None

    def apply_watermark(self, wav, sample_rate=None):
        raise AssertionError("Kit's voice isn't watermarked")

    def tokenizer(self, text, return_tensors="pt"):
        ids = torch.tensor([[(ord(c) * 37) % 50000 for c in text[:20]]])
        return type("Ids", (), {"input_ids": ids})()


def test_one_step_gives_the_same_logits_as_chatterbox(t3):
    graph = turbo.GraphTokens(FakeTTS(t3), max_len=500, max_new=50)
    with torch.inference_mode():
        start = t3.hp.start_speech_token * torch.ones(1, 1, dtype=torch.long)
        embeds, _ = t3.prepare_input_embeds(
            t3_cond=t3.cond,
            text_tokens=torch.randint(0, 50000, (1, 10)),
            speech_tokens=start,
            cfg_weight=0.0,
        )
        n = embeds.shape[1]
        out = t3.tfmr(inputs_embeds=embeds, use_cache=True)
        past = out.past_key_values
        for i in range(len(t3.tfmr.h)):
            k, v = turbo._kv(past, i)
            graph.keys[i, :, :, :n].copy_(k)
            graph.values[i, :, :, :n].copy_(v)
        graph.pos.fill_(n)
        for token in (5, 100, 4000, 17):
            t = torch.tensor([[token]])
            graph.token.copy_(t)
            ours = graph.logits()
            o = t3.tfmr(inputs_embeds=t3.speech_emb(t), past_key_values=past, use_cache=True)
            past = o.past_key_values
            theirs = t3.speech_head(o[0])[:, -1, :].float()
            assert torch.allclose(ours, theirs, atol=1e-4)
            graph.pos.add_(1)


def test_choosing_rules_match_transformers():
    procs = LogitsProcessorList(
        [
            TemperatureLogitsWarper(0.8),
            TopKLogitsWarper(1000),
            TopPLogitsWarper(0.95),
            RepetitionPenaltyLogitsProcessor(1.2),
        ]
    )
    torch.manual_seed(1)
    for _ in range(5):
        logits = torch.randn(1, 6563) * 3
        said = torch.randint(0, 6561, (1, 30))
        seen = torch.zeros(1, 6563, dtype=torch.bool).scatter_(1, said, True)
        theirs = procs(said, logits.clone()).softmax(-1)
        ours = turbo.rules(logits.clone(), seen).softmax(-1)
        assert torch.allclose(ours, theirs, atol=1e-6)


def test_picking_follows_the_odds():
    torch.manual_seed(2)
    probs = torch.tensor([[0.5, 0.3, 0.2]])
    seen = torch.zeros(1, 3, dtype=torch.bool)
    logits = probs.log() * 0.8  # undo the temperature
    picks = torch.cat([turbo.pick(logits, seen)[0] for _ in range(4000)])
    share = torch.bincount(picks, minlength=3).float() / 4000
    # top-p 0.95 keeps all three; the shares come out near the odds
    assert torch.allclose(share, probs[0], atol=0.04)


def test_the_loop_yields_tokens_and_stops(t3):
    graph = turbo.GraphTokens(FakeTTS(t3), max_len=500, max_new=12, check_every=4)
    tokens = list(graph("Yeah, I reckon so."))
    assert 1 <= len(tokens) <= 13
    assert all(0 <= t < 6563 for t in tokens)
    assert t3.hp.stop_speech_token not in tokens


def prompt(t3, text_len: int):
    with torch.inference_mode():
        start = t3.hp.start_speech_token * torch.ones(1, 1, dtype=torch.long)
        return t3.prepare_input_embeds(
            t3_cond=t3.cond,
            text_tokens=torch.randint(0, 50000, (1, text_len)),
            speech_tokens=start,
            cfg_weight=0.0,
        )


def test_the_prefill_matches_chatterboxs_own_forward_pass(t3):
    graph = turbo.GraphTokens(FakeTTS(t3), max_len=500, max_new=50)
    embeds, n_cond = prompt(t3, 10)
    with torch.inference_mode():
        out = t3.tfmr(inputs_embeds=embeds, use_cache=True)
        theirs = t3.speech_head(out[0][:, -1:])[:, -1, :].float()
        # In two parts, as a line is run: the conditioning, then its text.
        graph.prefill(embeds[:, :n_cond], 0)
        ours = graph.prefill(embeds[:, n_cond:], int(n_cond))
        assert torch.allclose(ours, theirs, atol=1e-4)
        n = embeds.shape[1]
        for i in range(len(t3.tfmr.h)):
            k, v = turbo._kv(out.past_key_values, i)
            assert torch.allclose(graph.keys[i, :, :, :n], k, atol=1e-4)
            assert torch.allclose(graph.values[i, :, :, :n], v, atol=1e-4)


def test_the_speaker_conditioning_is_worked_out_once_and_kept(t3):
    graph = turbo.GraphTokens(FakeTTS(t3), max_len=500, max_new=8, check_every=4)
    runs = []
    real = graph.prefill

    def counted(embeds, start):
        runs.append((embeds.shape[1], start))
        return real(embeds, start)

    graph.prefill = counted
    list(graph("Yeah, I reckon so."))
    list(graph("Told you."))
    n_cond = int(prompt(t3, 3)[1])
    assert runs[0] == (n_cond + 18 + 1, 0)  # the whole prompt, the first time
    assert runs[1] == (9 + 1, n_cond)  # then only the text and the start token
    # The kept keys and values are the ones a full run gives.
    embeds, _ = prompt(t3, 5)
    with torch.inference_mode():
        graph._cond = None
        graph.prefill(embeds, 0)
        full = graph.keys[:, :, :, :n_cond].clone()
        graph._prompt(embeds, n_cond)
        graph._prompt(embeds, n_cond)
        assert torch.equal(graph.keys[:, :, :, :n_cond], full)
        assert torch.equal(graph._cond[1], full)


def test_generate_hands_back_the_sound_without_a_watermark(t3):
    tts = FakeTTS(t3)
    graph = turbo.GraphTokens(tts, max_len=500, max_new=8, check_every=4)
    wav = np.concatenate(list(turbo.generate(tts, graph, "Yeah.")))
    assert wav.ndim == 1 and wav.dtype.name == "float32" and (wav == 1).all()
    # A short line is one window, ending on three silence tokens.
    assert len(tts.decoded) == 1 and len(wav) == 2 * tts.decoded[0] and tts.decoded[0] >= 3


class _Tokens:
    """Stands in for ``GraphTokens``: hands out tokens already chosen."""

    def __init__(self, tokens):
        self.tokens = tokens

    def __call__(self, text):
        yield from self.tokens


def test_the_sound_comes_a_window_at_a_time_with_the_joins_cross_faded():
    tts = FakeTTS(None)
    tokens = list(range(1, 24))  # 23 tokens: two whole windows and three left over
    pieces = list(turbo.generate(tts, _Tokens(tokens), "ignored", window=10, overlap=3))
    assert len(pieces) == 3
    # Each window is decoded with the three tokens before it; the last with the silence.
    assert tts.decoded == [10, 13, 3 + 3 + 3]
    wav = np.concatenate(pieces)
    # Every token's sound is there once (two samples a token here): the shared tokens
    # are cross-faded into one reading, not doubled.
    assert len(wav) == 2 * (23 + 3) and (wav == 1).all()
    assert [len(p) for p in pieces] == [14, 20, 18]  # the last three tokens' sound held back
    # Tokens that aren't sounds are left out, and a line with none is a breath of silence.
    tts.decoded.clear()
    wav = np.concatenate(list(turbo.generate(tts, _Tokens([turbo.OOV + 1]), "", window=10)))
    assert tts.decoded == [3] and len(wav) == 6
