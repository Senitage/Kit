"""Kit's ears inside the desk app (kit.desk.ears), with fakes: no microphone, no
models, no sherpa-onnx, no Qt."""

import threading
from dataclasses import replace

import numpy as np
import pytest

from kit.desk.client import BrainError
from kit.desk.config import DeskConfig
from kit.desk.ears import RETRY_S, WAIT_S, DeskEars
from kit.hearing.engines import RATE, Stretch
from kit.settings import HearingSettings


class Client:
    def __init__(self, hearing=None, owner="Dan"):
        self.hearing = hearing or {}
        self.owner = owner
        self.enrolled = []

    def settings(self):
        return {"settings": {"hearing": self.hearing, "persona": {"owner": self.owner}}}

    def enrol_voice(self, name, prints):
        self.enrolled.append((name, len(prints)))
        return {"name": name, "count": len(prints)}


class FakeEars:
    def __init__(self, settings, on_step=None):
        self.settings = settings
        self.error, self.paused, self.mic = "", False, object()
        self.steps, self.released, self.closed = 0, 0, False
        self.on_step = on_step

    def step(self):
        self.steps += 1
        if self.on_step:
            self.on_step(self)
        return []

    def release(self):
        self.released += 1

    def close(self):
        self.closed = True


def make(client, config, **kw):
    state = {"client": client, "config": config}
    stop = threading.Event()
    ears = DeskEars(lambda: state["client"], lambda: state["config"], stop, **kw)
    return ears, state, stop


def test_the_ears_wait_while_switched_off_here_or_not_set_up():
    built = []
    ears, state, _ = make(Client(), DeskConfig(hear_here=False), build=lambda *a, **k: built)
    assert ears.once() == WAIT_S and "Off on this PC" in ears.status
    state["config"] = DeskConfig()
    state["client"] = None
    assert ears.once() == WAIT_S and "address and token" in ears.status
    assert built == []


def test_the_ears_follow_hearing_enabled_on_the_brain():
    ears, _, _ = make(Client({"enabled": False}), DeskConfig(), build=lambda *a, **k: None)
    assert ears.once() == RETRY_S and "hearing.enabled" in ears.status


def test_the_ears_say_so_when_the_brain_is_away():
    class Away(Client):
        def settings(self):
            raise BrainError("no route")

    ears, _, _ = make(Away(), DeskConfig(), build=lambda *a, **k: None)
    assert ears.once() == RETRY_S and "no route" in ears.status


def test_the_ears_run_with_this_pcs_mic_and_start_again_when_it_changes():
    built = []

    def build(settings, client, mic_name):
        def on_step(fake):
            if fake.steps == 3:  # Dan picks another mic on the This PC page
                state["config"] = replace(state["config"], mic=state["config"].mic or "Headset")
                if len(built) > 1:  # and then turns the ears off here
                    state["config"] = replace(state["config"], hear_here=False)

        fake = FakeEars(settings, on_step)
        built.append((settings, mic_name, fake))
        return fake

    ears, state, _ = make(Client({"mic": "Realtek", "follow_up_s": 4}), DeskConfig(), build=build)
    assert ears.once() == 0.0  # start again straight away
    settings, mic_name, fake = built[0]
    assert settings.mic == "Realtek" and settings.follow_up_s == 4 and mic_name == "desk"
    assert fake.steps == 3 and fake.closed and ears.ears is None
    ears.once()  # this PC's pick wins over hearing.mic on the brain
    assert built[1][0].mic == "Headset"


def test_the_ears_start_again_for_settings_that_need_the_models_built_again():
    def build(settings, client, mic_name):
        def on_step(fake):
            if fake.steps == 2:  # a check-in brought a new pause_ms
                fake.settings = fake.settings.model_copy(update={"pause_ms": 900})
            if fake.steps == 5:
                raise AssertionError("should have started again")

        return FakeEars(settings, on_step)

    ears, _, _ = make(Client(), DeskConfig(), build=build)
    assert ears.once() == 0.0


def test_the_status_says_how_the_ears_are():
    states = []

    def build(settings, client, mic_name):
        def on_step(fake):
            states.append(ears.status)
            if fake.steps == 1:
                fake.paused = True
            elif fake.steps == 2:
                fake.paused, fake.mic = False, None
            elif fake.steps == 3:
                fake.mic = object()
                state["config"] = replace(state["config"], hear_here=False)

        return FakeEars(settings, on_step)

    ears, state, _ = make(Client(), DeskConfig(), build=build)
    assert ears.once() == 0.0
    assert states[0].startswith("Getting the ears ready")
    assert states[1].startswith("Paused")
    assert states[2].startswith("Waiting for the microphone")
    assert ears.status.startswith("Listening with the default mic")


def test_a_desk_app_without_the_ears_libraries_says_so_and_stops_trying():
    def build(*a, **k):
        raise ImportError("No module named 'sherpa_onnx'")

    ears, _, _ = make(Client(), DeskConfig(), build=build)
    assert ears.once() is None and not ears.available and "no ears" in ears.status


def test_a_mic_that_isnt_there_is_shown_and_tried_again():
    def build(*a, **k):
        raise ValueError("no microphone called 'Headset'")

    ears, _, _ = make(Client(), DeskConfig(mic="Headset"), build=build)
    assert ears.once() == RETRY_S and "Headset" in ears.status


def test_the_loop_keeps_going_when_the_ears_break():
    calls = []

    def build(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("model file is broken")
        stop.set()
        return FakeEars(HearingSettings())

    ears, _, stop = make(Client(), DeskConfig(), build=build)
    ears._wake.set = lambda: None
    ears._wake.wait = lambda timeout: None  # no real waiting in the test
    ears.run()
    assert len(calls) == 2


class FakeMic:
    def __init__(self, chunks):
        self.chunks, self.closed = list(chunks), False

    def read(self, timeout=0.5):
        return self.chunks.pop(0) if self.chunks else None

    def close(self):
        self.closed = True


class FakeVad:
    """Each loud chunk is a finished stretch of talking."""

    def accept(self, chunk):
        return [Stretch(chunk)] if chunk.max() > 0.1 else []


class FakePrinter:
    def print(self, samples):
        return [1.0] + [0.0] * 511


def talking(seconds):
    return [np.full(int(RATE * 3), 0.5, dtype=np.float32) for _ in range(int(seconds / 3))]


def test_introducing_a_voice_holds_the_ears_and_sends_the_prints():
    mic = FakeMic(talking(12))
    client = Client()
    ears, _, _ = make(client, DeskConfig(), parts=lambda s: (lambda: mic, FakeVad(), FakePrinter()))
    ears._held.set()  # the ears have let the mic go
    said = ears.enrol("me", seconds=12)
    assert "Dan's voice" in said and client.enrolled == [("Dan", 4)]
    assert mic.closed and not ears._hold.is_set()


def test_introducing_a_voice_with_too_little_talking_says_try_again():
    mic = FakeMic(talking(6))
    client = Client()
    ears, _, _ = make(client, DeskConfig(), parts=lambda s: (lambda: mic, FakeVad(), FakePrinter()))
    ears._held.set()
    with pytest.raises(RuntimeError, match="only heard 2"):
        ears.enrol("Sam", seconds=6)
    assert client.enrolled == [] and mic.closed and not ears._hold.is_set()


def test_running_ears_let_the_mic_go_while_a_voice_is_introduced():
    def build(settings, client, mic_name):
        def on_step(fake):
            if fake.steps == 1:
                ears._hold.set()
                threading.Timer(0.3, ears._hold.clear).start()
            elif fake.steps == 2:
                assert fake.released and "Introducing" in seen[0]
                state["config"] = replace(state["config"], hear_here=False)

        return FakeEars(settings, on_step)

    seen = []
    ears, state, stop = make(Client(), DeskConfig(), build=build)
    real_wait = stop.wait

    def wait(timeout):
        seen.append(ears.status)
        return real_wait(timeout)

    stop.wait = wait
    assert ears.once() == 0.0
