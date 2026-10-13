"""Kit's voice: engines in their own programs, sentence-by-sentence speech."""

import io
import json
import socket
import sys
import threading
import time
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.brain import Brain
from kit.cli import main
from kit.memory import Memory
from kit.recall import Recall
from kit.server import create_app
from kit.settings import Settings, SettingsError, validate_settings
from kit.settings_store import SettingsStore
from kit.speech.bench import gaps, run_bench
from kit.speech.sentences import SentenceSplitter
from kit.speech.service import Loading, SpeechError, SpeechService, Spoken, Stale

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stream(splitter: SentenceSplitter, text: str) -> list[str]:
    """Feed ``text`` a few characters at a time, as the brain streams it."""
    out = []
    for i in range(0, len(text), 3):
        out += splitter.feed(text[i : i + 3])
    return out + splitter.flush()


# Cutting words into speakable pieces


def test_sentences_come_out_as_soon_as_they_end():
    splitter = SentenceSplitter()
    assert splitter.feed("Oh, nice! The flotation model") == ["Oh, nice!"]
    assert splitter.feed(" finally behaved. Told") == ["The flotation model finally behaved."]
    assert splitter.flush() == ["Told"]


def test_abbreviations_and_decimals_dont_end_a_sentence():
    said = stream(SentenceSplitter(), "Right. Check the duty, e.g. at 3.5 bar. Then the cyclone.")
    assert said == ["Right.", "Check the duty, e.g. at 3.5 bar.", "Then the cyclone."]


def test_a_long_first_sentence_is_cut_at_a_comma_so_he_starts_sooner():
    text = "Well, I had a look at the pump curves you sent over, and the duty point sits high."
    said = stream(SentenceSplitter(), text)
    assert said == [
        "Well, I had a look at the pump curves you sent over,",
        "and the duty point sits high.",
    ]
    # Only the first: later long sentences stay whole.
    later = stream(SentenceSplitter(), "Hi. " + text)
    assert later == ["Hi.", text]


def test_the_first_piece_is_never_a_one_word_clause():
    # "Yeah," on its own gets its own falling tune and then a gap: a stammer.
    text = "Yeah, I had a look at that yesterday, and it seemed fine to me."
    assert stream(SentenceSplitter(), text) == [
        "Yeah, I had a look at that yesterday,",
        "and it seemed fine to me.",
    ]
    # The first clause of at least four words is where it's cut, as soon as it's in.
    splitter = SentenceSplitter()
    assert splitter.feed("Well, yes, I had a ") == []
    assert splitter.feed("look, and the") == ["Well, yes, I had a look,"]
    # A sound tag isn't a word, and a short sentence stays whole.
    assert stream(SentenceSplitter(), "[chuckle] Told you, mate, it would pass.") == [
        "[chuckle] Told you, mate, it would pass."
    ]
    assert stream(SentenceSplitter(), "Oh, nice one.") == ["Oh, nice one."]
    assert SentenceSplitter(min_clause_words=0).min_clause_words == 1


def test_a_first_sentence_with_no_comma_is_cut_before_an_and():
    text = "I had a look at the photos from the weekend and the dog looks pretty happy."
    assert stream(SentenceSplitter(), text) == [
        "I had a look at the photos from the weekend",
        "and the dog looks pretty happy.",
    ]
    short = "That sounds like a good plan to me."
    assert stream(SentenceSplitter(), short) == [short]


def test_blank_lines_and_spaces_never_become_pieces():
    assert stream(SentenceSplitter(), "\n\nRight.\n\n  Done.  ") == ["Right.", "Done."]
    assert SentenceSplitter().flush() == []


# Settings


def test_built_in_engines_stay_when_one_is_changed():
    s = Settings.model_validate(
        {"speech": {"engine": "chatterbox-turbo", "engines": {"kokoro": {"voice": "af_bella"}}}}
    )
    assert s.speech.engines["kokoro"].voice == "af_bella"
    assert s.speech.engines["kokoro"].kind == "kokoro"
    assert {"piper", "chatterbox", "chatterbox-turbo", "tone"} <= set(s.speech.engines)
    assert s.speech.profile.kind == "chatterbox-turbo"
    assert s.speech.profile.mood_tags["tired"] == "[sigh]"


def test_a_second_voice_is_its_own_profile_and_unknown_engines_are_refused():
    s = Settings.model_validate(
        {
            "speech": {
                "engine": "bella",
                "engines": {"bella": {"kind": "kokoro", "voice": "af_bella", "speed": 1.1}},
            }
        }
    )
    assert s.speech.profile.voice == "af_bella"
    with pytest.raises(SettingsError, match="isn't an engine"):
        validate_settings({"speech": {"engine": "nope"}})


# The engine's own program


@pytest.fixture
def tone(paths):
    """Settings with the beeping test engine on a free port."""
    paths.ensure()
    box = {"s": Settings.model_validate({"speech": {"engine": "tone", "port": free_port()}})}
    service = SpeechService(lambda: box["s"].speech, paths)
    yield service, box
    service.stop()


def test_the_tone_engine_runs_in_its_own_program_and_says_a_line(tone):
    service, _ = tone
    spoken = service.speak("Oh, nice one", "happy", first=True)
    with wave.open(io.BytesIO(spoken.wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
    assert spoken.audio_ms == pytest.approx(360)  # three words, 120 ms each
    assert service.running()
    assert service.status()["loaded"] == "tone"


def test_engines_without_sounds_leave_them_out(tone):
    service, _ = tone
    assert service.speak("[chuckle] Oh, nice one", "happy").audio_ms == pytest.approx(360)
    assert service.speak("[sigh]", "tired").audio_ms == pytest.approx(150)  # a breath
    assert service.speak("[1] is a footnote", "neutral").audio_ms == pytest.approx(480)


def test_turbo_makes_the_sound_and_skips_the_moods_own_opener(monkeypatch):
    from kit.speech import worker

    made = []

    class Turbo(worker.ChatterboxTurboEngine):
        def __init__(self):
            self.mood_tags, self.sample_rate = {"playful": "[chuckle]"}, 24000
            self.tts, self.turbo, self.graph = self, None, None

        def generate(self, text):
            made.append(text)
            return self

        def squeeze(self, _):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return worker.np.zeros(10)

    turbo = Turbo()
    turbo.speak("[sigh] Fine.", "playful", first=True)
    turbo.speak("Fine.", "playful", first=True)
    turbo.speak("Fine.", "playful")
    assert made == ["[sigh] Fine.", "[chuckle] Fine.", "Fine."]


def test_turbo_uses_the_cuda_graph_loop_when_it_has_one():
    from kit.speech import worker

    made = []

    class Fast:
        @staticmethod
        def generate(tts, graph, line):
            if len(line) > 20:
                raise ValueError("line too long for the token store")
            made.append(("graph", line))
            return worker.np.zeros(10)

    class Turbo(worker.ChatterboxTurboEngine):
        def __init__(self):
            self.mood_tags, self.sample_rate = {"playful": "[chuckle]"}, 24000
            self.tts, self.turbo, self.graph = self, Fast, object()

        def generate(self, text):  # Chatterbox's own loop
            made.append(("own", text))
            return self

        def squeeze(self, _):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return worker.np.zeros(10)

    turbo = Turbo()
    turbo.speak("Fine.", "playful", first=True)
    turbo.speak("That one went on for a while.", "playful")  # too long: its own loop
    assert made == [("graph", "[chuckle] Fine."), ("own", "That one went on for a while.")]


def test_the_worker_drops_a_line_from_a_reply_thats_been_overtaken(tmp_path):
    from kit.speech import worker

    w = worker.Worker("tone", "tone", {}, tmp_path)
    w.speak("One.", "neutral", generation=5)
    w.speak("Older but never numbered.", "neutral")  # an older desk: always made
    w.speak("Seven.", "neutral", generation=7)
    with pytest.raises(worker.Stale):  # from the reply Dan interrupted
        w.speak("Six.", "neutral", generation=6)
    w.speak("Seven again.", "neutral", generation=7)
    # The check is made with the engine's lock held, so a line waiting its turn
    # behind one being made is dropped the moment that one is done.
    dropped = []

    def still_six():
        try:
            w.speak("Still six.", "neutral", generation=6)
        except worker.Stale as e:
            dropped.append(str(e))

    with w.lock:
        waiting = threading.Thread(target=still_six)
        waiting.start()
        w._newest(8)
    waiting.join(5)
    assert dropped == ["reply 6 was interrupted"] and w.generation == 8


def test_the_worker_answers_410_for_a_stale_line_and_the_service_says_so(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "kokoro"}})

    def say(engine):
        return httpx.Response(410, json={"error": "reply 3 was interrupted", "stale": True})

    started, launcher, http = engines_that(say)
    service = SpeechService(lambda: s.speech, paths, launcher, http)
    with pytest.raises(Stale):
        service.speak("Late.", generation=3)
    assert service.in_use() == "kokoro"  # nothing wrong with the engine


def test_the_service_drops_a_line_from_an_overtaken_reply_before_asking_the_engine(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "kokoro", "fallback": "tone"}})
    asked = []

    def say(engine):
        asked.append(engine)
        return spoke(engine)

    started, launcher, http = engines_that(say)
    service = SpeechService(lambda: s.speech, paths, launcher, http)
    service.speak("Seven.", generation=7)
    with pytest.raises(Stale):
        service.speak("Six.", generation=6)
    service.speak("No number.")
    assert asked == ["kokoro", "kokoro"] and service.in_use() == "kokoro"


def test_without_waiting_an_engine_not_yet_up_loads_in_the_background(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "kokoro", "fallback": "tone"}})
    started, launcher, http = engines_that(spoke)
    service = SpeechService(lambda: s.speech, paths, launcher, http)
    with pytest.raises(Loading, match="still loading"):
        service.speak("Hi.", wait=False)
    service._loader.join(5)
    assert [p.name for p in started] == ["kokoro"]  # loaded, and no switch to the fallback
    assert service.speak("Hi.", wait=False).engine == "kokoro"
    # An engine that failed lately isn't "loading": its failure is the answer, which
    # here hands over to the fallback, loading in the background in its turn.
    service._failed = (service._key_for("kokoro"), service.clock(), "kokoro broke")
    service.stop()
    with pytest.raises(Loading, match=r"\(tone\) is still loading"):
        service.speak("Hi.", wait=False)
    assert service.in_use() == "tone"
    service._loader.join(5)
    assert [p.name for p in started] == ["kokoro", "tone"]
    plain = Settings.model_validate({"speech": {"engine": "kokoro"}})
    started, launcher, http = engines_that(spoke)
    service = SpeechService(lambda: plain.speech, paths, launcher, http)
    service._failed = (service._key_for("kokoro"), service.clock(), "kokoro broke")
    with pytest.raises(SpeechError, match="kokoro broke"):
        service.speak("Hi.", wait=False)
    assert started == []


def test_chatterbox_runs_without_the_perth_watermark(monkeypatch, tmp_path):
    import types

    from kit.speech import worker

    class FakeTTS:
        sr = 24000

        def __init__(self):
            self.watermarker = "perth"
            self.made = []

        @classmethod
        def from_pretrained(cls, device):
            return cls()

        def prepare_conditionals(self, reference, **kw):
            pass

        def generate(self, text, **kw):
            self.made.append(text)
            return self

        def squeeze(self, _):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return worker.np.ones(3)

    turbo = types.ModuleType("chatterbox.tts_turbo")
    turbo.ChatterboxTurboTTS = FakeTTS
    plain = types.ModuleType("chatterbox.tts")
    plain.ChatterboxTTS = FakeTTS
    monkeypatch.setitem(sys.modules, "chatterbox", types.ModuleType("chatterbox"))
    monkeypatch.setitem(sys.modules, "chatterbox.tts_turbo", turbo)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", plain)
    for kind in ("chatterbox-turbo", "chatterbox"):
        engine = worker.ENGINES[kind]({"device": "cpu", "cuda_graph": False}, tmp_path)
        assert isinstance(engine.tts.watermarker, worker.NoWatermark)
        assert list(engine.speak("Hi.", "neutral")) == [1, 1, 1]
    assert worker.NoWatermark().apply_watermark("as is", sample_rate=24000) == "as is"


def test_changing_the_engines_settings_restarts_it_and_off_stops_it(tone):
    service, box = tone
    service.speak("one")
    first = service._process
    service.speak("two")
    assert service._process is first  # same settings: same program
    box["s"] = Settings.model_validate(
        {"speech": {**box["s"].speech.model_dump(), "engines": {"tone": {"speed": 1.2}}}}
    )
    service.speak("three")
    assert service._process is not first
    service.stop()
    assert not service.running()


class DeadProcess:
    def __init__(self):
        self.started = 0

    def __call__(self, command, log_file):
        self.started += 1
        log_file.write("[speech] chatterbox couldn't start: ModuleNotFoundError\n")
        log_file.flush()
        return self

    def poll(self):
        return 1

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 1


def test_an_engine_that_cant_start_says_why_and_isnt_retried_straight_away(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "chatterbox"}})
    now = [100.0]
    launcher = DeadProcess()
    refused = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    service = SpeechService(lambda: s.speech, paths, launcher, refused, clock=lambda: now[0])
    with pytest.raises(SpeechError, match="ModuleNotFoundError"):
        service.speak("hi")
    with pytest.raises(SpeechError, match="ModuleNotFoundError"):
        service.speak("hi again")
    assert launcher.started == 1
    now[0] += 61
    with pytest.raises(SpeechError):
        service.speak("and again")
    assert launcher.started == 2


# A fallback voice (speech.fallback)


class Running:
    """An engine's program that's up, as the service sees it."""

    def __init__(self, name):
        self.name, self.alive = name, True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


def engines_that(say):
    """Engines (fake programs) answering /speak with ``say(engine)``: a response."""
    started: list[Running] = []

    def launcher(command, log_file):
        started.append(Running(command[command.index("--engine") + 1]))
        return started[-1]

    def answer(request):
        engine = started[-1].name
        if request.url.path == "/health":
            return httpx.Response(200, json={"engine": engine, "device": "cuda"})
        return say(engine)

    return started, launcher, httpx.Client(transport=httpx.MockTransport(answer))


def spoke(engine):
    return httpx.Response(200, content=b"RIFFwav", headers={"X-Audio-Ms": "900"})


def test_out_of_graphics_memory_he_switches_to_the_fallback_and_stays(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "chatterbox-turbo", "fallback": "kokoro"}})

    def say(engine):
        if engine == "chatterbox-turbo":
            return httpx.Response(500, json={"error": "CUDA out of memory. Tried to allocate"})
        return spoke(engine)

    started, launcher, http = engines_that(say)
    service = SpeechService(lambda: s.speech, paths, launcher, http)
    assert service.speak("Still here.").engine == "kokoro"
    assert [p.name for p in started] == ["chatterbox-turbo", "kokoro"] and not started[0].alive
    service.speak("And again.")
    assert len(started) == 2  # he stays on it
    status = service.status()
    assert status["using"] == "kokoro" and "out of memory" in status["fell_back"]


def test_other_mistakes_dont_switch_and_without_a_fallback_nothing_does(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "chatterbox-turbo", "fallback": "kokoro"}})
    started, launcher, http = engines_that(lambda e: httpx.Response(500, json={"error": "odd"}))
    service = SpeechService(lambda: s.speech, paths, launcher, http)
    with pytest.raises(SpeechError, match="odd"):
        service.speak("Hm.")
    assert service.in_use() == "chatterbox-turbo"
    plain = Settings.model_validate({"speech": {"engine": "chatterbox-turbo"}})
    oom = httpx.Response(500, json={"error": "CUDA out of memory"})
    started, launcher, http = engines_that(lambda e: oom)
    service = SpeechService(lambda: plain.speech, paths, launcher, http)
    with pytest.raises(SpeechError, match="out of memory"):
        service.speak("Hm.")
    assert [p.name for p in started] == ["chatterbox-turbo"]


def test_an_engine_that_wont_start_hands_over_until_the_settings_change(paths):
    paths.ensure()
    box = {"s": Settings.model_validate({"speech": {"engine": "chatterbox", "fallback": "tone"}})}
    dead = DeadProcess()
    started, alive, http = engines_that(spoke)

    def launcher(command, log_file):
        if command[command.index("--engine") + 1] == "chatterbox":
            return dead(command, log_file)
        return alive(command, log_file)

    service = SpeechService(lambda: box["s"].speech, paths, launcher, http)
    assert service.speak("Still here.").engine == "tone"
    assert "ModuleNotFoundError" in service.status()["fell_back"]
    service.speak("And again.")
    assert dead.started == 1
    box["s"] = Settings.model_validate({"speech": {**box["s"].speech.model_dump(), "port": 8700}})
    assert service.in_use() == "chatterbox"  # new settings: his usual voice gets another go
    with pytest.raises(SettingsError, match="isn't an engine"):
        validate_settings({"speech": {"fallback": "nope"}})


class LoadingProcess:
    """An engine that's still loading: running, but not answering yet."""

    def __init__(self):
        self.alive = True

    def __call__(self, command, log_file):
        return self

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


def test_shutting_down_stops_a_load_under_way_and_starts_no_more(paths):
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "chatterbox"}})
    engine = LoadingProcess()
    refused = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    service = SpeechService(
        lambda: s.speech, paths, engine, refused, sleep=lambda _: time.sleep(0.01)
    )
    failed = []

    def load():
        try:
            service.ensure()
        except SpeechError as e:
            failed.append(str(e))

    loading = threading.Thread(target=load)
    loading.start()
    time.sleep(0.1)
    service.close()
    loading.join(timeout=2)
    assert not loading.is_alive()
    assert failed and "shutting down" in failed[0]
    assert not engine.alive
    with pytest.raises(SpeechError, match="shutting down"):
        service.ensure()


def test_the_command_uses_the_engines_own_python_and_finds_the_voice_clip(paths):
    paths.ensure()
    clip = paths.state_dir / "speech" / "kit_voice.wav"
    s = Settings.model_validate(
        {"speech": {"engines": {"chatterbox": {"python": "/opt/voice/bin/python"}}}}
    )
    service = SpeechService(lambda: s.speech, paths)
    command = service.command("chatterbox", s.speech.engines["chatterbox"], 8611)
    assert command[0] == "/opt/voice/bin/python"
    assert json.loads(command[command.index("--options") + 1])["reference"] == ""
    assert "no voice clip" in service.note
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"RIFF")
    command = service.command("chatterbox", s.speech.engines["chatterbox"], 8611)
    assert json.loads(command[command.index("--options") + 1])["reference"] == str(clip)
    assert service.command("tone", s.speech.engines["tone"], 1)[0] == sys.executable


# Comparing engines


def test_gaps_count_silence_while_the_next_sentence_is_made():
    assert gaps([500, 300], [1000, 1000]) == 0  # the second is ready before the first ends
    assert gaps([500, 1500], [1000, 1000]) == 500
    assert gaps([200], [800]) == 0


def test_bench_writes_clips_timings_and_a_page(tone):
    service, _ = tone
    out = service.paths.state_dir / "speech" / "bench" / "now"
    lines = [("happy", "Oh, nice! Told you."), ("tired", "Late again.")]
    shown = []
    [result] = run_bench(service, ["tone"], out, lines, gpu=lambda: 1200, show=shown.append)
    assert [x.clip for x in result.lines] == ["tone-1-happy.wav", "tone-2-tired.wav"]
    assert all((out / x.clip).exists() for x in result.lines)
    assert result.lines[0].audio_ms == pytest.approx(480)  # "Oh, nice!" + "Told you."
    assert result.gpu_before_mib == result.gpu_peak_mib == 1200
    assert "tone-1-happy.wav" in (out / "index.html").read_text()
    assert json.loads((out / "results.json").read_text())[0]["engine"] == "tone"
    assert "starts talking after" in shown[-1]
    assert not service.running()  # stopped, so the next engine has the memory


def test_the_bench_says_whether_an_engine_fits_the_graphics_card(tone):
    service, _ = tone
    out = service.paths.state_dir / "speech" / "bench" / "gpu"
    lines = [("playful", "You burnt the toast? [chuckle] Classic.")]
    shown = []
    [roomy] = run_bench(
        service, ["tone"], out, lines, gpu=lambda: 6200, show=shown.append, total=lambda: 8192
    )
    assert roomy.fits() and "fits the graphics card (6.1 of 8.0 GB at the peak)" in shown[-1]
    [tight] = run_bench(
        service, ["tone"], out, lines, gpu=lambda: 7900, show=shown.append, total=lambda: 8192
    )
    assert tight.fits() is False and "too tight" in shown[-1] and "speech.fallback" in shown[-1]
    [unknown] = run_bench(service, ["tone"], out, lines, gpu=lambda: None, total=lambda: None)
    assert unknown.fits() is None


# The server


class FakeSpeech:
    def __init__(self):
        self.said = []
        self.on = False

    def speak(self, text, mood="neutral", engine=None, first=False, generation=None, wait=True):
        if not wait and not self.on:
            self.on = True  # loading in the background: ready next time
            raise Loading("Kit's voice (tone) is still loading; ask again in a moment")
        if generation == 1:
            raise Stale("reply 1 was interrupted, so that line wasn't made")
        self.said.append((text, mood, first, generation))
        return Spoken(wav=b"RIFFwav", synth_ms=420, audio_ms=900, engine="tone")

    def status(self):
        return {"engine": "tone", "running": self.on}

    def ensure(self, engine=None):
        self.on = True

    def running(self):
        return self.on

    def stop(self):
        self.on = False

    close = stop

    def quiet_s(self):
        return 99.0


@pytest.fixture
def server(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, FakeModel(reply("Hi.")), make_cloud(memory), recall)
    speech = FakeSpeech()
    app = create_app(
        store, memory, brain, TOKEN, summarise_every_s=None, speech=speech, speech_check_s=0.01
    )
    with TestClient(app) as client:
        yield client, store, speech
    memory.close()


def test_the_server_says_a_sentence_only_when_speech_is_on(server):
    client, store, speech = server
    body = {"text": "Oh, nice!", "emotion": "excited", "first": True}
    assert client.post("/api/speech/say", json=body, headers=AUTH).status_code == 409
    store.update({"speech": {"enabled": True}}, "test")
    speech.on = True
    r = client.post("/api/speech/say", json=body, headers=AUTH)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.headers["x-synth-ms"] == "420"
    assert r.content == b"RIFFwav"
    assert speech.said == [("Oh, nice!", "excited", True, None)]
    assert client.get("/api/speech", headers=AUTH).json()["available"] is True


def test_the_server_says_not_yet_while_the_engine_loads_and_drops_an_overtaken_line(server):
    client, store, speech = server
    store.update({"speech": {"enabled": True}}, "test")
    body = {"text": "Oh, nice!", "emotion": "excited", "first": True, "generation": 2}
    r = client.post("/api/speech/say", json=body, headers=AUTH)  # not loaded yet: at once
    assert r.status_code == 503 and r.headers["retry-after"] == "1"
    assert "still loading" in r.json()["detail"]
    assert client.post("/api/speech/say", json=body, headers=AUTH).status_code == 200
    assert speech.said == [("Oh, nice!", "excited", True, 2)]
    stale = {"text": "Old news.", "emotion": "neutral", "generation": 1}
    r = client.post("/api/speech/say", json=stale, headers=AUTH)
    assert r.status_code == 410 and "interrupted" in r.json()["detail"]
    assert len(speech.said) == 1


def test_his_voice_says_how_long_its_been_quiet_for_the_brain_to_wait_on(paths):
    clock = [100.0]
    service = SpeechService(lambda: Settings().speech, paths, clock=lambda: clock[0])
    assert service.quiet_s() == float("inf")  # never spoken
    inside, gate = threading.Event(), threading.Event()

    def slow(text, mood, engine, first, generation, wait):
        inside.set()
        gate.wait(5)
        return Spoken(wav=b"RIFF", synth_ms=1, audio_ms=1, engine="tone")

    service._speak = slow
    worker = threading.Thread(target=service.speak, args=("Hi.",))
    worker.start()
    assert inside.wait(5)
    assert service.quiet_s() == 0.0  # a sentence is being made
    gate.set()
    worker.join(5)
    clock[0] = 102.5
    assert service.quiet_s() == 2.5
    # The brain reads ahead only once his voice is quiet (ollama.warm_up).
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), lambda: Settings())
    brain = Brain(lambda: Settings(), memory, FakeModel(), make_cloud(memory), recall)
    create_app(SettingsStore(paths), memory, brain, TOKEN, speech=FakeSpeech())
    assert brain.voice_quiet() == 99.0
    memory.close()


def test_the_server_loads_the_engine_when_speech_is_on_and_frees_it_when_off(server):
    client, store, speech = server
    store.update({"speech": {"enabled": True}}, "test")
    deadline = time.monotonic() + 5
    while not speech.on and time.monotonic() < deadline:
        time.sleep(0.02)
    assert speech.on
    store.update({"speech": {"enabled": False}}, "test")
    while speech.on and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not speech.on


# The brain and the command line


def test_the_brain_says_how_he_feels_before_his_words(paths):
    paths.ensure()
    memory = Memory(paths.state_dir / "memory.db", Clock())
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}})
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    model = FakeModel(reply("Oh, nice.", emotion="happy"))
    brain = Brain(lambda: s, memory, model, make_cloud(memory), recall)
    from fakes import collect

    events = collect(brain.chat("It passed!"))
    kinds = [e["type"] for e in events]
    assert kinds.index("mood") < kinds.index("say")
    assert events[kinds.index("mood")]["emotion"] == "happy"
    memory.close()


def test_kit_speech_switches_engines_and_turns_speech_on_and_off(paths, capsys):
    assert main(["speech", "use", "chatterbox-turbo"]) == 0
    assert main(["speech", "on"]) == 0
    s = SettingsStore(paths).current().speech
    assert (s.engine, s.enabled) == ("chatterbox-turbo", True)
    assert main(["speech", "use", "nope"]) == 1
    assert main(["speech", "off"]) == 0
    assert main(["speech"]) == 0
    out = capsys.readouterr().out
    assert "* chatterbox-turbo" in out
    assert "speech: off" in out


def test_kit_speech_say_saves_the_line_and_shows_the_timing(paths, capsys, monkeypatch):
    paths.ensure()
    SettingsStore(paths).update({"speech": {"engine": "tone", "port": free_port()}}, "test")
    assert main(["speech", "say", "Oh, nice! Told you."]) == 0
    out = capsys.readouterr().out
    assert "to make" in out and "Oh, nice!" in out
    [saved] = (paths.state_dir / "speech" / "said").glob("*-tone.wav")
    with wave.open(str(saved)) as w:
        assert w.getnframes() == int(0.48 * 16000)


def test_the_worker_stops_when_kit_does(tmp_path):
    import subprocess

    from kit.speech.service import WORKER

    port = free_port()
    # A stand-in for Kit that starts the worker and exits at once.
    script = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, {str(WORKER)!r}, '--engine', 'tone', "
        f"'--port', '{port}', '--parent', str(__import__('os').getpid())]); "
        "import time; time.sleep(1.5)"
    )
    subprocess.run([sys.executable, "-c", script], check=True, timeout=20)
    deadline = time.monotonic() + 10
    alive = True
    while alive and time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5, trust_env=False)
            time.sleep(0.3)
        except httpx.HTTPError:
            alive = False
    assert not alive
