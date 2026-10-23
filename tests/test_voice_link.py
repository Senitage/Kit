"""Kit's voice made on another computer: the voice link (kit.speech.link), the voice
program that dials in to it (kit.speech.program), and the fallback around them."""

import argparse
import asyncio
import base64
import contextlib
import json
import socket
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.brain import Brain
from kit.cli import cmd_speech, main
from kit.memory import Memory
from kit.paths import KitPaths
from kit.recall import Recall
from kit.server import create_app
from kit.settings import Settings
from kit.settings_store import SettingsStore
from kit.speech import program as voice
from kit.speech import worker
from kit.speech.link import VoiceLink
from kit.speech.service import Loading, Speech, SpeechError, SpeechService, Stale

TOKEN = "test-token"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Now:
    """A loop stand-in that runs what it's handed straight away."""

    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


class Program:
    """The voice program's side of a link, answering as the real one would."""

    def __init__(self, link: VoiceLink, pieces=(b"ab", b"cd"), answer="sound"):
        self.link, self.pieces, self.answer = link, pieces, answer
        self.sent: list[dict] = []
        self.number = link.attach(Now(), self, {"name": "desk-pc"})

    def put_nowait(self, message):  # Kit posting a message to the program
        self.sent.append(message)
        if message.get("type") != "speak":
            return
        n = message["id"]
        if self.answer == "stale":
            self.link.received({"type": "error", "id": n, "error": "overtaken", "stale": True})
            return
        if self.answer == "silent":
            return
        self.link.received({"type": "start", "id": n, "rate": 24000, "synth_ms": 310})
        for piece in self.pieces:
            self.link.received_sound(n.to_bytes(4, "big") + piece)
        if self.answer == "sound":
            self.link.received({"type": "end", "id": n})

    def ready(self, health=None):
        key = self.link.key
        self.link.received({"type": "ready", "key": key, "health": health or {"engine": "pc"}})

    def kinds(self):
        return [m.get("type") for m in self.sent]


def ready_link(**kwargs) -> tuple[VoiceLink, Program]:
    link = VoiceLink()
    program = Program(link, **kwargs)
    link.load("key-1", {"name": "pc", "profile": {}})
    program.ready({"engine": "pc", "device": "cuda", "cuda_graph": True})
    return link, program


# The link


def test_a_line_goes_to_the_voice_program_and_comes_back_in_pieces():
    link, program = ready_link()
    assert link.ready_for("key-1") and not link.ready_for("key-2")
    said = link.speak("Oh, nice.", "happy", True, 4)
    assert (said.rate, said.engine) == (24000, "pc")
    assert list(said.pieces) == [b"ab", b"cd"]
    speak = program.sent[-1]
    assert (speak["text"], speak["mood"], speak["first"], speak["generation"]) == (
        "Oh, nice.",
        "happy",
        True,
        4,
    )
    status = link.status()
    assert status["connected"] and status["name"] == "desk-pc" and status["cuda_graph"]
    assert status["last"]["there_s"] == 0.31  # how long the PC took, beside Kit's own wait


def test_asking_for_the_same_engine_twice_loads_it_once_and_off_unloads_it():
    link, program = ready_link()
    link.load("key-1", {"name": "pc"})
    assert program.kinds() == ["engine"]
    link.unload()
    assert program.sent[-1] == {"type": "engine", "key": "", "name": ""}
    assert not link.ready_for("key-1")
    link.received({"type": "ready", "key": "key-1", "health": {}})  # too late: forgotten
    assert not link.ready_for("key-1")


def test_an_engine_that_fails_there_says_why_and_is_tried_again_a_minute_on():
    now = [0.0]
    link = VoiceLink(clock=lambda: now[0])
    program = Program(link)
    link.load("key-1", {"name": "pc"})
    link.received({"type": "failed", "key": "key-1", "error": "CUDA out of memory"})
    assert link.status()["problem"] == "CUDA out of memory"
    with pytest.raises(Loading):
        link.speak("Hi.", "neutral", False, None)
    link.load("key-1", {"name": "pc"}, retry_s=60)
    assert program.kinds() == ["engine"]  # not straight away
    now[0] = 61
    link.load("key-1", {"name": "pc"}, retry_s=60)
    assert program.kinds() == ["engine", "engine"]


def test_a_dropped_link_ends_its_lines_at_once():
    link, program = ready_link(answer="partial")
    said = link.speak("Hi there.", "neutral", False, None)
    assert next(said.pieces) == b"ab"
    link.detach(program.number)
    assert next(said.pieces) == b"cd"  # what had come already
    with pytest.raises(SpeechError, match="went away"):
        next(said.pieces)
    assert not link.connected
    with pytest.raises(SpeechError, match="isn't connected"):
        link.speak("Hello?", "neutral", False, None)


def test_a_line_stopped_early_stops_on_the_program_too():
    link, program = ready_link(answer="partial")
    said = link.speak("A long line.", "neutral", False, None)
    next(said.pieces)
    said.pieces.close()
    assert program.sent[-1] == {"type": "cancel", "id": program.sent[-2]["id"]}


def test_a_stale_line_says_so_and_a_silent_one_is_given_up_on():
    link, _ = ready_link(answer="stale")
    with pytest.raises(Stale):
        link.speak("Old line.", "neutral", False, 1)
    link, program = ready_link(answer="silent")
    link.first_sound_s = 0.05
    with pytest.raises(SpeechError, match="no sound"):
        link.speak("Hello?", "neutral", False, None)
    assert program.kinds()[-1] == "cancel"


def test_a_second_program_dialling_in_replaces_the_first():
    link, first = ready_link(answer="silent")
    closed = []
    first.put_nowait = closed.append  # the route closes the old one on None
    second = Program(link)
    assert closed == [None] and not link.ready_for("key-1")  # the new one loads afresh
    link.detach(first.number)  # the old one's goodbye doesn't drop the new one
    assert link.connected and second.number > first.number


# The speech service with a remote engine


class Up:
    """A local engine's program that's running."""

    alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False

    def wait(self, timeout=None):
        return 0


def local_engines():
    """Engines on Kit's own machine: fake programs answering with a little sound."""
    started = []

    def launcher(command, log_file):
        started.append(command[command.index("--engine") + 1])
        return Up()

    def answer(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"engine": started[-1], "device": "cpu"})
        return httpx.Response(200, content=bytes(160), headers={"X-Sample-Rate": "8000"})

    return started, launcher, httpx.Client(transport=httpx.MockTransport(answer))


def remote_settings(paths, clip=True, **speech):
    if clip:
        (paths.state_dir / "speech").mkdir(parents=True, exist_ok=True)
        (paths.state_dir / "speech" / "heart.wav").write_bytes(b"RIFF-heart")
    turbo = {"remote": True, "reference": "heart.wav", "python": "~/kit-voice/.venv/bin/python"}
    return Settings.model_validate(
        {
            "speech": {
                "enabled": True,
                "engine": "chatterbox-turbo",
                "fallback": "kokoro",
                "engines": {"chatterbox-turbo": turbo},
                **speech,
            }
        }
    )


def test_until_the_pc_voice_is_ready_kit_speaks_with_the_fallback_kept_loaded_here(paths):
    paths.ensure()
    s = remote_settings(paths)
    started, launcher, http = local_engines()
    link = VoiceLink()
    service = SpeechService(lambda: s.speech, paths, launcher, http, link=link)
    service.keep_ready()  # nothing dialled in: the fallback loads here
    assert started == ["kokoro"] and service.in_use() == "kokoro"
    assert service.speak("Still here.").engine == "kokoro"
    assert service.status()["fell_back"] == "the voice program isn't connected"
    program = Program(link)
    service.keep_ready()
    [engine] = program.sent
    assert engine["name"] == "chatterbox-turbo" and service.in_use() == "kokoro"
    # His voice clip goes with it, since it lives in Kit's data folder.
    assert base64.b64decode(engine["clip"]) == b"RIFF-heart"
    assert engine["profile"]["reference"] == "heart.wav" == engine["clip_name"]
    assert "remote" not in engine["profile"]
    program.ready({"engine": "chatterbox-turbo", "device": "cuda", "cuda_graph": True})
    assert service.in_use() == "chatterbox-turbo"
    said = service.stream("Back on the card.", first=True)
    assert said.engine == "chatterbox-turbo" and b"".join(said.pieces) == b"abcd"
    status = service.status()
    assert status["remote"] and status["device"] == "cuda" and status["fell_back"] is None
    service.keep_ready()
    assert started == ["kokoro"]  # the fallback stays loaded beside it, never reloaded
    link.detach(program.number)
    assert service.in_use() == "kokoro"


def test_a_line_the_link_drops_before_its_first_sound_is_said_with_the_fallback(paths):
    paths.ensure()
    s = remote_settings(paths)
    started, launcher, http = local_engines()
    link = VoiceLink()
    service = SpeechService(lambda: s.speech, paths, launcher, http, link=link)
    program = Program(link, answer="silent")
    service.keep_ready()
    program.ready()
    program.put_nowait = lambda m: m.get("type") == "speak" and link.detach(program.number)
    said = service.speak("The PC just went off.")
    assert said.engine == "kokoro" and said.audio_ms == 10


def test_without_a_fallback_the_pc_voice_being_away_is_an_error(paths):
    paths.ensure()
    s = remote_settings(paths, fallback="")
    service = SpeechService(lambda: s.speech, paths, *local_engines()[1:], link=VoiceLink())
    service.keep_ready()  # no harm with nothing connected
    with pytest.raises(SpeechError, match="isn't connected"):
        service.speak("Hello?")


def test_speech_off_or_a_local_engine_frees_the_pcs_card(paths):
    paths.ensure()
    box = {"s": remote_settings(paths)}
    link = VoiceLink()
    service = SpeechService(lambda: box["s"].speech, paths, *local_engines()[1:], link=link)
    program = Program(link)
    service.keep_ready()
    program.ready()
    service.idle()
    assert program.sent[-1]["name"] == "" and not service.running()
    service.keep_ready()
    program.ready()
    box["s"] = Settings.model_validate({"speech": {"engine": "kokoro"}})
    service.keep_ready()
    assert program.sent[-1]["name"] == ""


def test_after_a_fallback_the_speech_loop_keeps_the_fallback_loaded(paths):
    """The loop used to load his usual engine every few seconds, which stopped the
    fallback and tried the broken engine again each minute."""
    paths.ensure()
    s = Settings.model_validate({"speech": {"engine": "chatterbox", "fallback": "kokoro"}})
    started, alive, http = local_engines()
    tries = []

    class Dead:
        def poll(self):
            return 1

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 1

    def launcher(command, log_file):
        if command[command.index("--engine") + 1] == "chatterbox":
            tries.append(1)
            log_file.write("ModuleNotFoundError: No module named 'chatterbox'\n")
            log_file.flush()
            return Dead()
        return alive(command, log_file)

    now = [0.0]
    service = SpeechService(lambda: s.speech, paths, launcher, http, clock=lambda: now[0])
    assert service.speak("Still here.").engine == "kokoro"
    for _ in range(5):
        now[0] += 61  # past the minute an engine that failed is left alone
        service.keep_ready()
    assert tries == [1] and started == ["kokoro"] and service.running()


# The voice program


def test_the_program_saves_where_kit_is_and_never_reads_kits_data_folder(tmp_path, paths):
    paths.ensure()  # an old copy of Kit's data folder on the PC is not where Kit is now
    folder = tmp_path / "voice"
    assert voice.find_connection(folder=folder) is None
    voice.save_connection("http://kit-server:8600/", "tok", folder)
    found = voice.find_connection(folder=folder)
    assert (found.url, found.token) == ("http://kit-server:8600", "tok")
    assert voice.find_connection("http://elsewhere:8600", None, folder).token == "tok"


def test_the_link_address_and_ipv4_only():
    assert voice.link_address("http://kit-server:8600") == "ws://kit-server:8600/api/speech/link"
    assert voice.link_address("https://kit.example/") == "wss://kit.example/api/speech/link"
    assert voice.ipv4_only("http://kit-server:8600")
    assert not voice.ipv4_only("http://[fd7a::1]:8600")


def test_the_engine_kit_sends_runs_here_with_its_clip_and_this_pythons_engine(tmp_path):
    program = voice.VoiceProgram("http://kit:8600", "tok", tmp_path, python="/opt/voice/python")
    message = {
        "name": "chatterbox-turbo",
        "profile": {"kind": "chatterbox-turbo", "reference": "heart.wav", "python": "~/x"},
        "clip_name": "../heart.wav",  # only ever a name in this folder
        "clip": base64.b64encode(b"RIFF-heart").decode(),
        "load_timeout_s": 300,
    }
    s = program._settings_for(message)
    profile = s.engines["chatterbox-turbo"]
    assert (s.engine, s.load_timeout_s) == ("chatterbox-turbo", 300)
    assert not profile.remote and profile.python == "/opt/voice/python"
    assert (tmp_path / "state" / "speech" / "heart.wav").read_bytes() == b"RIFF-heart"
    assert profile.reference == "heart.wav"


class FakeService:
    """The voice program's engine, as a stand-in."""

    def __init__(self, error=None):
        self.error, self.loaded, self.stopped = error, [], 0
        self.load_s = 1.5

    def ensure(self, name):
        if self.error:
            raise SpeechError(self.error)
        self.loaded.append(name)
        return {"engine": name, "device": "cuda", "cuda_graph": True}

    def stream(self, text, mood, engine, first, generation):
        if text == "old":
            raise Stale("reply 1 was interrupted")
        return Speech(rate=24000, synth_ms=420, engine=engine, pieces=(p for p in [b"ab", b"cd"]))

    def stop(self):
        self.stopped += 1

    close = stop


def test_the_program_loads_what_kit_asks_and_answers_each_line_in_pieces(tmp_path):
    service = FakeService()
    program = voice.VoiceProgram("http://kit:8600", "tok", tmp_path, service=service)
    sent = []
    program.load({"key": "k", "name": "pc", "profile": {"kind": "tone"}}, sent.append)
    health = {"engine": "pc", "device": "cuda", "cuda_graph": True}
    assert sent == [{"type": "ready", "key": "k", "health": health}]
    sent.clear()
    program.make({"id": 7, "text": "Hi.", "mood": "happy"}, sent.append, threading.Event())
    head = (7).to_bytes(4, "big")
    assert sent == [
        {"type": "start", "id": 7, "rate": 24000, "synth_ms": 420},
        head + b"ab",
        head + b"cd",
        {"type": "end", "id": 7},
    ]
    sent.clear()
    program.make({"id": 8, "text": "old"}, sent.append, threading.Event())
    assert sent[0]["stale"] is True
    sent.clear()
    stop = threading.Event()
    stop.set()  # Kit stopped it: nothing after the start
    program.make({"id": 9, "text": "Hi."}, sent.append, stop)
    assert [m["type"] for m in sent] == ["start"]
    program.load({"key": "", "name": ""}, sent.append)
    assert service.stopped == 1


def test_an_engine_that_cant_load_on_the_pc_tells_kit_why(tmp_path):
    program = voice.VoiceProgram("http://k", "t", tmp_path, service=FakeService("no CUDA"))
    sent = []
    program.load({"key": "k", "name": "pc", "profile": {"kind": "tone"}}, sent.append)
    assert sent == [{"type": "failed", "key": "k", "error": "no CUDA"}]


def test_the_program_dials_again_after_a_drop(tmp_path):
    attempts, waits = [], []

    class Refused:
        async def __aenter__(self):
            attempts.append(1)
            if len(attempts) == 3:
                program.stopping = True
            raise OSError("connection refused")

        async def __aexit__(self, *exc):
            return False

    async def sleep(s):
        waits.append(s)

    program = voice.VoiceProgram(
        "http://kit:8600",
        "tok",
        tmp_path,
        connect=lambda url, token: Refused(),
        service=FakeService(),
        sleep=sleep,
    )
    asyncio.run(program.run())
    assert len(attempts) == 3 and waits == [1, 2]  # a second, then longer


def test_kit_voice_connect_and_run_without_an_address(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KIT_VOICE_DIR", str(tmp_path / "voice"))
    assert main(["voice"]) == 1
    assert "kit voice connect" in capsys.readouterr().out
    assert main(["voice", "connect", "http://kit-server:8600", "tok"]) == 0
    assert voice.find_connection().url == "http://kit-server:8600"


def test_the_worker_sends_each_piece_at_once():
    """Nagle's algorithm held the first piece, written just after the headers, until
    Kit acknowledged them: 40 ms before every line's first sound."""
    handler = worker.make_handler(object())
    assert handler.disable_nagle_algorithm


# Through Kit's server


def kit_app(paths, speech_settings):
    paths.ensure()
    store = SettingsStore(paths)
    store.update({"speech": speech_settings}, "test")
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, FakeModel(reply("Hi.")), make_cloud(memory), recall)
    speech = SpeechService(lambda: store.current().speech, paths)
    app = create_app(
        store,
        memory,
        brain,
        TOKEN,
        summarise_every_s=None,
        speech=speech,
        speech_check_s=0.1,
        life_every_s=None,
        notes_every_s=None,
        files_every_s=None,
    )
    return app, store, memory, speech


def test_the_link_wants_kits_own_token(paths):
    app, _, memory, _ = kit_app(paths, {"enabled": False})
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(
                "/api/speech/link", headers={"Authorization": "Bearer nope"}
            ) as ws:
                ws.receive_text()
        assert e.value.code == 1008
    memory.close()


def test_the_link_through_kits_server_hands_over_lines_and_takes_the_sound(paths):
    app, store, memory, speech = kit_app(paths, {"enabled": True})
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as client:
        with client.websocket_connect("/api/speech/link", headers=headers) as ws:
            ws.send_text(json.dumps({"type": "hello", "name": "desk-pc"}))
            deadline = time.monotonic() + 5
            while not speech.link.connected and time.monotonic() < deadline:
                time.sleep(0.01)
            assert client.get("/api/speech", headers=headers).json()["link"]["name"] == "desk-pc"
    deadline = time.monotonic() + 5
    while speech.link.connected and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not speech.link.connected  # gone the moment it closes
    memory.close()


def _wait_for(check, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_end_to_end_the_pc_voice_speaks_falls_back_and_comes_back(paths, tmp_path):
    """A real server, a real voice program over a real WebSocket, and the beeping
    test engine in its own program on each side."""
    import uvicorn

    app, store, memory, speech = kit_app(
        paths,
        {
            "enabled": True,
            "engine": "pc",
            "fallback": "tone",
            "port": free_port(),
            "engines": {"pc": {"kind": "tone", "remote": True}},
        },
    )
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    http = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {TOKEN}"})

    def start_program():
        program = voice.VoiceProgram(url, TOKEN, tmp_path / "pc", port=free_port())
        loop = asyncio.new_event_loop()
        task = loop.create_task(program.run())

        def run():
            with contextlib.suppress(asyncio.CancelledError):
                loop.run_until_complete(task)

        threading.Thread(target=run, daemon=True).start()
        return program, loop, task

    def using():
        try:
            return http.get("/api/speech").json()["using"]
        except httpx.HTTPError:
            return None

    def say(text):
        r = http.post("/api/speech/say", json={"text": text, "first": True})
        return r.headers.get("x-engine"), len(r.content)

    program, loop, task = start_program()
    try:
        assert _wait_for(lambda: using() == "pc")
        assert say("Oh nice one") == ("pc", int(0.36 * 16000) * 2)
        assert http.get("/api/speech").json()["link"]["last"]["first_s"] < 1
        loop.call_soon_threadsafe(task.cancel)  # the PC's voice program stops
        assert _wait_for(lambda: using() == "tone")
        assert say("Still here") == ("tone", int(0.24 * 16000) * 2)
        program.service.close()
        program, loop, task = start_program()  # and starts again
        assert _wait_for(lambda: using() == "pc")
        assert say("Back again")[0] == "pc"
    finally:
        loop.call_soon_threadsafe(task.cancel)
        program.service.close()
        server.should_exit = True
        speech.close()
        memory.close()


def test_kit_speech_say_with_the_pc_voice_goes_through_kits_server(paths, capsys):
    paths.ensure()
    SettingsStore(paths).update(
        {"speech": {"engine": "pc", "engines": {"pc": {"kind": "tone", "remote": True}}}}, "t"
    )
    seen = []

    def answer(request):
        if request.url.path == "/api/speech":
            link = {"connected": True, "name": "desk-pc", "state": "ready", "device": "cuda"}
            return httpx.Response(200, json={"using": "pc", "link": link})
        seen.append(json.loads(request.content))
        headers = {"X-Engine": "pc", "X-Sample-Rate": "16000"}
        return httpx.Response(200, content=bytes(3200), headers=headers)

    transport = httpx.MockTransport(answer)
    args = argparse.Namespace(action="say", text="Hello there. Told you.", engine=None)
    args.mood = "neutral"
    assert cmd_speech(paths, args, transport=transport) == 0
    out = capsys.readouterr().out
    assert "to first sound" in out and "made by pc" in out
    assert [s["first"] for s in seen] == [True, False] and not seen[0]["aloud"]
    args = argparse.Namespace(action="show")
    assert cmd_speech(paths, args, transport=transport) == 0
    assert "voice link: desk-pc (cuda), ready" in capsys.readouterr().out


def test_kits_paths_on_the_pc_are_the_programs_own_folder(tmp_path):
    program = voice.VoiceProgram("http://k", "t", tmp_path / "v", service=FakeService())
    assert program.paths == KitPaths(tmp_path / "v")
