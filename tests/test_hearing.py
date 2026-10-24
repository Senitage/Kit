"""Kit's ears beside the mic (kit.hearing), run with fakes: no microphone, no
models, no sherpa-onnx."""

import io
import tarfile
import wave
from argparse import Namespace

import httpx
import numpy as np
import pytest

from kit.hearing import enrol, link, models
from kit.hearing.engines import (
    CHUNK,
    RATE,
    Lookback,
    Stretch,
    Transcript,
    resample,
    transcript_of,
    trim_quiet,
    wav_samples,
)
from kit.hearing.mic import pick_device
from kit.hearing.run import CHECK_IN_S, Ears
from kit.settings import HearingSettings

KIT = [1.0] + [0.0] * 511  # Kit's own voice print
DAN = [0.0, 1.0] + [0.0] * 510
SAM = [0.0, 0.0, 1.0] + [0.0] * 509


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeMic:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, timeout=0.5):
        return self.chunks.pop(0) if self.chunks else None

    def close(self):
        self.closed = True


class FakeVad:
    """Talking while a chunk is loud; a stretch ends at the first quiet chunk."""

    def __init__(self):
        self.now, self.stretch = False, []

    def accept(self, chunk):
        loud = bool(np.abs(chunk).max() > 0.1)
        done = []
        if loud:
            self.stretch.append(chunk)
        elif self.stretch:
            done.append(Stretch(np.concatenate(self.stretch)))
            self.stretch = []
        self.now = loud
        return done

    def talking(self):
        return self.now


class EarlyVad(FakeVad):
    """Like FakeVad, but hands out the talking so far every ten loud chunks, as the
    real one does at a short pause."""

    def accept(self, chunk):
        done = super().accept(chunk)
        if self.now and len(self.stretch) % 10 == 0:
            done.append(Stretch(np.concatenate(self.stretch), early=True))
        return done


class FakeTranscriber:
    def __init__(self, *said):
        self.said = list(said)

    def transcribe(self, samples):
        return self.said.pop(0) if self.said else Transcript("")


class FakePrinter:
    """Whose voice: the loudness of the sound says (0.5 Kit, 0.8 Dan, 0.9 Sam; 0.6 is
    Dan sounding a bit like Kit)."""

    def print(self, samples):
        level = round(float(np.abs(samples).max()), 1)
        if level == 0.6:
            return [0.6, 0.8] + [0.0] * 510
        return {0.5: KIT, 0.8: DAN, 0.9: SAM}.get(level, DAN)


def talk(level, seconds):
    n = int(seconds * RATE / CHUNK)
    return [np.full(CHUNK, level, dtype=np.float32) for _ in range(n)]


def quiet(seconds=0.1):
    return talk(0.0, seconds)


class Brain:
    def __init__(self, **answer):
        self.answer = {"paused": False, "voices_version": 1, "speech": "kokoro", **answer}
        self.heard, self.hushes, self.check_ins = [], 0, []

    def check_in(self, report):
        self.check_ins.append(report)
        return self.answer

    def hear(self, said):
        self.heard.append(said)
        return {"heard": "answer", "why": "his name"}

    def hush(self):
        self.hushes += 1
        return {"hushed": True}


def ears(chunks, brain, transcriber=None, printer=True, own=True, **settings):
    clock = FakeClock()
    mic = FakeMic(chunks)
    e = Ears(
        lambda: mic,
        FakeVad(),
        transcriber or FakeTranscriber(),
        FakePrinter() if printer else None,
        brain.check_in,
        brain.hear,
        brain.hush,
        HearingSettings(**settings),
        load_voices=lambda: {"people": {"Dan": [DAN], "Sam": [SAM]}},
        own_voice=(lambda: np.full(RATE * 2, 0.5, dtype=np.float32)) if own else None,
        clock=clock,
        sleep=lambda s: None,
    )
    e.mic_obj = mic

    def run():
        while mic.chunks:
            e.step()
            clock.t += CHUNK / RATE

    return e, run


def test_a_stretch_of_talking_goes_to_the_brain_as_words_with_whose_voice():
    brain = Brain()
    said = Transcript("Kit, what's the time?", "en", "happy", "speech")
    e, run = ears(talk(0.8, 1.0) + quiet(), brain, FakeTranscriber(said))
    run()
    assert brain.check_ins[0] == {"mic": "desk", "listening": True}
    assert e.kit_print is not None and sorted(e.gallery.people) == ["Dan", "Sam"]
    (heard,) = brain.heard
    assert heard["text"] == "Kit, what's the time?" and heard["tone"] == "happy"
    assert heard["who"] == "Dan" and heard["own_voice"] is False
    assert heard["seconds"] == pytest.approx(0.99, abs=0.05)
    assert "audio" not in heard and "samples" not in heard  # words, never sound


def test_the_words_show_in_the_ears_window_only_when_asked(caplog):
    said = Transcript("Kit, what's the time?", "en", "", "speech")
    for words in (False, True):
        caplog.clear()
        e, run = ears(talk(0.8, 1.0) + quiet(), Brain(), FakeTranscriber(said))
        e.words = words
        with caplog.at_level("INFO", logger="kit.hearing.run"):
            run()
        line = next(r.getMessage() for r in caplog.records if "heard" in r.getMessage())
        assert ("what's the time" in line) is words


def test_a_stretch_starts_a_little_before_the_vad_noticed_it():
    back = Lookback(1.0)
    sound = np.arange(RATE * 3, dtype=np.float32)
    for i in range(0, len(sound), CHUNK):
        back.add(sound[i : i + CHUNK])
    assert back.fed == RATE * 3
    start = RATE * 2 + RATE // 2
    assert np.array_equal(back.before(start, 0.25), sound[start - RATE // 4 : start])
    assert len(back.before(RATE, 0.5)) == 0  # older than it keeps
    assert len(back.before(RATE * 2 + 10, 0.5)) == 10  # only what it still has
    short = Lookback(1.0)
    short.add(sound[:100])
    assert np.array_equal(short.before(50, 1.0), sound[:50])
    assert np.array_equal(
        back.between(RATE * 2 + 100, RATE * 2 + 300), sound[RATE * 2 + 100 : RATE * 2 + 300]
    )
    assert len(back.between(RATE * 2 + 100, RATE * 9)) == RATE - 100  # only up to what's fed


def test_his_own_voice_from_the_speakers_is_flagged_and_does_not_stop_him():
    brain = Brain()
    e, run = ears(talk(0.5, 2.0) + quiet(), brain, FakeTranscriber(Transcript("Rain later.")))
    run()
    assert brain.hushes == 0
    assert brain.heard[0]["own_voice"] is True and brain.heard[0]["who"] is None


def test_a_voice_more_like_someone_known_than_like_kit_is_theirs():
    brain = Brain()
    e, run = ears(talk(0.6, 2.0) + quiet(), brain, FakeTranscriber(Transcript("Kit, you there?")))
    run()
    assert brain.heard[0]["own_voice"] is False and brain.heard[0]["who"] == "Dan"
    assert brain.hushes == 1  # and it talks over him


def test_words_come_from_the_lead_in_too_but_the_voice_print_does_not():
    heard_lengths, printed_lengths = [], []

    class Hears(FakeTranscriber):
        def transcribe(self, samples):
            heard_lengths.append(len(samples))
            return Transcript("Kit, hi")

    class Prints(FakePrinter):
        def print(self, samples):
            printed_lengths.append(len(samples))
            return DAN

    e = Ears(lambda: None, FakeVad(), Hears(), Prints(), Brain().check_in, Brain().hear, None)
    lead_in, voice = np.zeros(RATE // 2, dtype=np.float32), np.full(RATE, 0.8, dtype=np.float32)
    e.hear(Stretch(voice, lead_in))
    assert heard_lengths == [RATE + RATE // 2] and printed_lengths == [RATE]


def test_words_got_ready_at_a_short_pause_are_used_when_the_talking_ended_there():
    heard, printed = [], []

    class Hears(FakeTranscriber):
        def transcribe(self, samples):
            heard.append(len(samples))
            return Transcript("Kit, hi")

    class Prints(FakePrinter):
        def print(self, samples):
            printed.append(len(samples))
            return DAN

    brain = Brain()
    e = Ears(lambda: None, FakeVad(), Hears(), Prints(), brain.check_in, brain.hear, None)
    loud = lambda seconds: np.full(int(seconds * RATE), 0.8, dtype=np.float32)  # noqa: E731
    e._ahead(Stretch(loud(1.0), start=100, early=True))
    # The finished stretch: the same start, and a chunk longer (the pause's edge).
    e.hear(Stretch(loud(1.0 + CHUNK / RATE), start=100))
    assert heard == [RATE] and printed == [RATE]  # worked out once, at the pause
    assert brain.heard[-1]["seconds"] == pytest.approx(1.03, abs=0.01)
    # The talking went on well past the pause: worked out afresh, from all of it.
    e._ahead(Stretch(loud(1.0), start=5000, early=True))
    e.hear(Stretch(loud(2.0), start=5000))
    assert heard[-1] == RATE * 2 and brain.heard[-1]["seconds"] == 2.0
    # A stretch that began elsewhere isn't the one the words were made from.
    e._ahead(Stretch(loud(1.0), start=9000, early=True))
    e.hear(Stretch(loud(1.0), start=9500))
    assert heard[-1] == RATE and e._ready is None
    e._pool.shutdown(wait=True)


def test_the_loop_gets_the_words_ready_at_each_pause(caplog):
    brain = Brain()
    said = Transcript("Kit, hi")
    e, run = ears(talk(0.8, 1.0) + quiet(), brain, FakeTranscriber(*[said] * 5))
    e.vad = EarlyVad()  # the words are worked out at each pause, from all of it so far
    with caplog.at_level("INFO", logger="kit.hearing.run"):
        run()
    assert brain.heard[-1]["text"] == "Kit, hi" and brain.heard[-1]["who"] == "Dan"
    assert "words ready early" in caplog.text
    # Enrolling only wants finished stretches.
    chunks = talk(0.8, 1.0) + quiet(1.0)
    found = enrol.listen_for(lambda: chunks.pop(0) if chunks else None, EarlyVad(), 2.0)
    assert [len(f) for f in found] == [31 * CHUNK]


def test_kits_voice_sample_is_printed_without_its_silent_padding():
    clip = np.concatenate([np.zeros(800), np.full(1600, 0.3), np.zeros(400)]).astype(np.float32)
    assert len(trim_quiet(clip)) == 1600
    assert len(trim_quiet(np.zeros(100, dtype=np.float32))) == 0


def test_talking_over_him_stops_him_once_a_stretch():
    brain = Brain()
    e, run = ears(talk(0.9, 2.0) + quiet(), brain, FakeTranscriber(Transcript("Hang on.")))
    run()
    assert brain.hushes == 1
    assert brain.heard[0]["who"] == "Sam"


def test_no_talking_over_without_his_voice_print_or_when_switched_off():
    for kwargs in ({"own": False}, {"barge_in": False}, {"printer": False}):
        brain = Brain()
        e, run = ears(talk(0.9, 2.0) + quiet(), brain, **kwargs)
        run()
        assert brain.hushes == 0, kwargs
    brain = Brain(speech="")  # his voice is off: nothing to learn, nothing to talk over
    e, run = ears(talk(0.9, 2.0) + quiet(), brain)
    run()
    assert e.kit_print is None and brain.hushes == 0


def test_short_sounds_and_silence_are_not_sent():
    brain = Brain()
    e, run = ears(talk(0.8, 0.2) + quiet() + talk(0.8, 1.0) + quiet(), brain)
    run()
    assert brain.heard == []  # too short, then nothing said (no words, no laugh)
    laugh = FakeTranscriber(Transcript("", sound="laughter"))
    e, run = ears(talk(0.8, 1.0) + quiet(), brain, laugh)
    run()
    assert brain.heard[0]["sound"] == "laughter"


def test_paused_ears_let_the_mic_go_and_follow_the_settings():
    brain = Brain(paused=True)
    e, run = ears(talk(0.8, 1.0) + quiet(), brain)
    e.step()
    assert e.paused and e.mic is None
    brain.answer = {"paused": False, "settings": {"follow_up_s": 3, "match": 0.7}}
    e.check_in()
    assert not e.paused and e.settings.follow_up_s == 3 and e.gallery.threshold == 0.7


def test_the_ears_keep_going_when_the_brain_is_away():
    brain = Brain()

    def down(report):
        raise httpx.ConnectError("no route")

    e, run = ears(quiet(1.0), brain)
    e._check_in = down
    e.step()
    assert "no route" in e.error
    e._check_in = brain.check_in
    e._last_check_in = -CHECK_IN_S
    e.step()
    assert e.error == ""


def test_sense_voice_tags_become_words():
    t = transcript_of("  hello   there ", "<|en|>", "<|SAD|>", "<|Laughter|>")
    assert (t.text, t.language, t.tone, t.sound) == ("hello there", "en", "sad", "laughter")
    assert transcript_of("hi", "<|en|>", "<|EMO_UNKNOWN|>", "<|Speech|>").tone == ""


def test_kit_voice_from_the_brain_becomes_16k_samples():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes((np.ones(24000) * 8000).astype(np.int16).tobytes())
    samples = wav_samples(buf.getvalue())
    assert len(samples) == RATE and samples.max() == pytest.approx(8000 / 32768, abs=1e-3)
    assert len(resample(np.ones(100, np.float32), 16000)) == 100


def test_the_mic_is_picked_by_number_or_part_of_its_name():
    mics = [(0, "Microphone (Realtek Audio)"), (3, "Headset Mic (USB)")]
    assert pick_device("", mics) is None
    assert pick_device("2", mics) == 2
    assert pick_device("headset", mics) == 3
    with pytest.raises(ValueError):
        pick_device("webcam", mics)


def test_models_are_downloaded_once_and_unpacked(tmp_path):
    fetched = []

    def fetcher(url, path):
        fetched.append(url)
        if url.endswith(".tar.bz2"):
            with tarfile.open(path, "w:bz2") as tar:
                for name in ("model.int8.onnx", "tokens.txt", "README.md"):
                    data = b"x"
                    info = tarfile.TarInfo(f"{models.SENSE_VOICE}/{name}")
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
        else:
            path.write_bytes(b"onnx")

    model, tokens = models.sense_voice(tmp_path, fetcher)
    assert model.is_file() and tokens.is_file()
    assert not (tmp_path / models.SENSE_VOICE / "README.md").exists()
    assert not list(tmp_path.glob("*.tar.bz2"))  # the archive is tidied away
    models.sense_voice(tmp_path, fetcher)
    vad = models.model_file("vad", tmp_path, fetcher)
    models.model_file("vad", tmp_path, fetcher)
    assert vad.name == "silero_vad.onnx" and len(fetched) == 2


def test_enrolling_cuts_talking_into_voice_print_pieces():
    vad = FakeVad()
    chunks = talk(0.8, 7.0) + quiet(0.2) + talk(0.8, 1.0)
    stretches = enrol.listen_for(lambda: chunks.pop(0) if chunks else None, vad, 8.2)
    assert [round(len(s) / RATE) for s in stretches] == [7, 1]
    prints = enrol.voice_prints(stretches, FakePrinter())
    assert len(prints) == 2  # 3 s + 3 s; the 1 s tails are too short


def test_the_ears_find_the_brain_like_the_eyes(tmp_path, monkeypatch, paths):
    monkeypatch.setenv(link.HEARING_DIR_ENV, str(tmp_path / "ears"))
    assert link.hearing_dir() == tmp_path / "ears"
    assert link.models_dir() == tmp_path / "ears" / "models"
    link.save_connection("http://kit-server:8600/", "tok")
    conn = link.find_connection(desk_folder=tmp_path / "none", paths=paths)
    assert (conn.url, conn.token) == ("http://kit-server:8600", "tok")


# --- kit hearing ----------------------------------------------------------------


def _args(action=None, **kw):
    base = {
        "hearing_action": action,
        "brain": "http://brain",
        "token": "t",
        "name": "desk",
        "steps": None,
        "words": False,
    }
    return Namespace(**{**base, **kw})


def _transport(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        if key not in routes:
            return httpx.Response(404, json={"detail": "nope"})
        return httpx.Response(200, json=routes[key])

    return httpx.MockTransport(handler)


def test_kit_hearing_commands(paths, capsys):
    from kit.cli import cmd_hearing

    routes = {
        ("GET", "/api/hearing"): {
            "online": True,
            "paused": False,
            "mic": "desk",
            "last": {"at": "2026-10-11T10:00:00", "action": "ignore", "why": "not talking"},
        },
        ("GET", "/api/hearing/voices"): {"names": {"Dan": 6}},
        ("DELETE", "/api/hearing/voices/Sam"): {"forgot": "Sam"},
        ("POST", "/api/hearing/pause"): {"paused": True},
    }
    t = _transport(routes)
    assert cmd_hearing(paths, _args("show"), transport=t) == 0
    assert "Kit's ears: on, listening (desk)" in capsys.readouterr().out
    assert cmd_hearing(paths, _args("voices"), transport=t) == 0
    assert "Dan: 6 voice prints" in capsys.readouterr().out
    assert cmd_hearing(paths, _args("forget", who="Sam"), transport=t) == 0
    assert "forgotten Sam's voice" in capsys.readouterr().out
    assert cmd_hearing(paths, _args("pause"), transport=t) == 0
    assert "the mic is let go" in capsys.readouterr().out
    assert cmd_hearing(paths, _args("mics"), mics=lambda: [(1, "Headset Mic")]) == 0
    assert "1: Headset Mic" in capsys.readouterr().out


def test_kit_hearing_runs_and_enrols_with_the_brains_settings(paths, capsys):
    from kit.cli import cmd_hearing

    routes = {
        ("GET", "/api/status"): {"name": "Kit"},
        ("GET", "/api/settings"): {"settings": {"hearing": {"follow_up_s": 4}, "persona": {}}},
        ("POST", "/api/hearing/voices"): {"name": "Dan", "count": 2},
    }
    built = {}

    class Ran:
        def run(self, max_steps=None):
            built["ran"] = max_steps

    def build(settings, client, mic_name, words):
        built["settings"] = settings
        return Ran()

    t = _transport(routes)
    assert cmd_hearing(paths, _args(steps=5), transport=t, build=build) == 0
    assert built == {"settings": HearingSettings(follow_up_s=4), "ran": 5}
    chunks = talk(0.8, 7.0) + quiet(0.2)
    mic = FakeMic(chunks)
    parts = (lambda: mic, FakeVad(), FakePrinter())
    args = _args("enrol", who="Dan", seconds=7.3)
    assert cmd_hearing(paths, args, transport=t, parts=parts) == 1  # only two pieces
    assert "only heard 2" in capsys.readouterr().out and mic.closed
    mic = FakeMic(talk(0.8, 10.0) + quiet(0.2))
    parts = (lambda: mic, FakeVad(), FakePrinter())
    args = _args("enrol", who="Dan", seconds=10.3)
    assert cmd_hearing(paths, args, transport=t, parts=parts) == 0
    assert "know Dan's voice now" in capsys.readouterr().out


def test_each_mic_is_listed_once_by_its_shortest_name():
    from kit.hearing.mic import mic_names

    devices = [
        (1, "Microphone (Realtek High Defini"),
        (2, "Headset Mic (USB)"),
        (5, "Microphone (Realtek High Definition Audio)"),
        (7, "Headset Mic (USB)"),
        (9, "  "),
    ]
    assert mic_names(devices) == ["Microphone (Realtek High Defini", "Headset Mic (USB)"]
    assert mic_names(list(reversed(devices))) == [
        "Headset Mic (USB)",
        "Microphone (Realtek High Defini",
    ]
