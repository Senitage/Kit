"""Kit's voice on the desk PC: one steady sound output, each sentence made while the
last one plays, his words shown as he says them, and his pipe-ups said too."""

import threading
import time

import pytest

from kit.desk.client import BrainError, SpeechOff
from kit.desk.voice import (
    PRE_ROLL_S,
    WAIT_S,
    Clip,
    OutputError,
    Speaker,
    StreamOutput,
    to_wav,
)

RATE = 24000


def wav(text: str, rate: int = RATE) -> bytes:
    """A WAV whose samples spell ``text``, so tests can tell sentences apart."""
    pcm = text.encode()
    return to_wav(Clip(pcm + b"\0" * (len(pcm) % 2), rate, 1, 2))


def spelled(pcm: bytes) -> str:
    return pcm.strip(b"\0").decode()


def wait_for(condition, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeOutput:
    """Plays each sentence at once: keeps it, and says it started."""

    def __init__(self, expect: int = 0, fail: Exception | None = None):
        self.clips: list[Clip] = []
        self.warmed = self.stopped = self.closed = 0
        self.fail = fail
        self.expect = expect
        self.done = threading.Event()

    def warm(self):
        self.warmed += 1

    def play(self, clip, started=None):
        if self.fail is not None:
            raise self.fail
        self.clips.append(clip)
        if started is not None:
            started()
        if len(self.clips) >= self.expect:
            self.done.set()

    def mark(self, reached):
        reached()

    def busy(self):
        return False

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed += 1

    def said(self) -> list[str]:
        return [spelled(c.pcm) for c in self.clips]


class FakeStream:
    """A sound card: the test pulls sound from it, as the real one would."""

    def __init__(self, rate, channels, callback):
        self.rate, self.channels, self.callback = rate, channels, callback
        self.started = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def pull(self, frames: int) -> bytes:
        buf = bytearray(frames * self.channels * 2)
        self.callback(buf, frames, None, None)
        return bytes(buf)


class FakeSoundDevice:
    def __init__(self, fail: bool = False):
        self.streams: list[FakeStream] = []
        self.fail = fail

    def RawOutputStream(self, samplerate, channels, dtype, callback):  # noqa: N802 (its name)
        assert dtype == "int16"
        if self.fail:
            raise RuntimeError("no sound device")
        self.streams.append(FakeStream(samplerate, channels, callback))
        return self.streams[-1]


# One steady sound output


def test_the_speakers_are_awake_before_his_first_word_and_each_sentence_says_when_it_starts():
    sd, clock = FakeSoundDevice(), Clock()
    out = StreamOutput(sd, clock=clock)
    started = []
    out.play(Clip(b"\x01\x02" * 50, RATE, 1, 2), lambda: started.append("one"))
    stream = sd.streams[0]
    assert stream.started and (stream.rate, stream.channels) == (RATE, 1)
    # Silence first while the speakers wake up: a sound that wakes them loses its start.
    waking = int(RATE * PRE_ROLL_S)
    assert stream.pull(waking - 10) == bytes((waking - 10) * 2) and started == []
    sound = stream.pull(60)
    assert sound == bytes(20) + b"\x01\x02" * 50 and started == ["one"]
    assert not out.busy() and stream.pull(10) == bytes(20)  # silence till the next one
    # Awake now: the next sentence plays straight away, with no silence in front.
    clock.now = 5.0
    stream.pull(10)  # the card keeps asking, and gets silence
    out.play(Clip(b"\x03\x04" * 5, RATE, 1, 2), lambda: started.append("two"))
    assert out.busy() and stream.pull(5) == b"\x03\x04" * 5 and started == ["one", "two"]
    # Dan talks: Kit stops at once, mid-sentence.
    out.play(Clip(b"\x05\x06" * 500, RATE, 1, 2), lambda: started.append("three"))
    out.stop()
    assert stream.pull(10) == bytes(20) and started == ["one", "two"]
    # A sentence that couldn't be voiced still has its moment, once what's queued has played.
    out.play(Clip(b"\x07\x08" * 5, RATE, 1, 2))
    out.mark(lambda: started.append("skipped"))
    assert started == ["one", "two"]
    stream.pull(5)
    assert started == ["one", "two", "skipped"]
    # Another engine's sound: the output reopens to suit it.
    out.play(Clip(b"\x01\x00" * 5, 16000, 1, 2))
    assert stream.closed and sd.streams[-1].rate == 16000
    out.close()
    assert sd.streams[-1].closed


def test_a_sound_output_that_stops_asking_for_sound_is_opened_again():
    sd, clock = FakeSoundDevice(), Clock()
    out = StreamOutput(sd, clock=clock)
    out.play(Clip(b"\x01\x02" * 50, RATE, 1, 2))
    assert out.busy()
    clock.now = 10.0  # the speakers were unplugged: nothing has asked since
    assert not out.busy()  # Kit isn't stuck "talking"
    out.play(Clip(b"\x01\x02" * 5, RATE, 1, 2))
    assert sd.streams[0].closed and len(sd.streams) == 2


def test_a_sound_output_that_wont_open_says_so():
    with pytest.raises(OutputError):
        StreamOutput(FakeSoundDevice(fail=True)).play(Clip(b"\0\0", RATE, 1, 2))
    with pytest.raises(OutputError):
        StreamOutput(FakeSoundDevice()).play(Clip(b"\0", RATE, 1, 1))  # 8-bit


def test_a_mistake_telling_the_chat_never_stops_the_sound():
    sd = FakeSoundDevice()
    out = StreamOutput(sd)

    def broken():
        raise RuntimeError("the chat went away")

    out.play(Clip(b"\x01\x02" * 5, RATE, 1, 2), broken)
    assert b"\x01\x02" * 5 in sd.streams[0].pull(int(RATE * PRE_ROLL_S) + 10)
    assert sd.streams[0].pull(10) == bytes(20)  # still going


# Saying a reply as it streams in


def test_each_sentence_is_said_in_the_mood_with_a_sound_only_first():
    asked = []

    def fetch(text, emotion, first):
        asked.append((text, emotion, first))
        return wav(text)

    out = FakeOutput(expect=3)
    speaker = Speaker(fetch, out)
    speaker.mood(1, "playful")
    for piece in ["Ha! Nice ", "one. Told you it'd ", "pass"]:
        speaker.say(1, piece)
    speaker.end(1)
    assert out.done.wait(5)
    assert asked == [
        ("Ha!", "playful", True),
        ("Nice one.", "playful", False),
        ("Told you it'd pass", "playful", False),
    ]
    assert out.said() == ["Ha!", "Nice one.", "Told you it'd pass"]


def test_dan_talking_stops_kit_at_once_and_speech_off_is_silent():
    gate = threading.Event()

    def fetch(text, emotion, first):
        if text == "Off.":
            raise SpeechOff("speech is off")
        if text == "Broken.":
            raise BrainError("no voice")
        if text == "Junk.":
            return b"not a sound"
        gate.wait(5)
        return wav(text)

    out = FakeOutput(expect=1)
    speaker = Speaker(fetch, out)
    speaker.say(1, "One. Two. Three. ")
    speaker.stop(2)  # Dan sends a message while Kit is mid-reply
    assert out.stopped  # what's playing stops now, not after the sentence
    gate.set()
    speaker.say(2, "Off. Broken. Junk. New one.")
    speaker.end(2)
    assert out.done.wait(5)
    time.sleep(0.1)
    assert out.said() == ["New one."]
    assert speaker.live  # the server made a sentence, so his voice is on


def test_an_older_reply_still_streaming_isnt_spoken_over_the_newer_one():
    asked = []
    out = FakeOutput(expect=1)
    speaker = Speaker(lambda text, emotion, first: asked.append(text) or wav(text), out)
    speaker.say(2, "Newer.")
    speaker.say(1, "Older. ")  # Dan asked twice; the first answer arrives late
    speaker.end(1)
    speaker.end(2)
    assert out.done.wait(5)
    time.sleep(0.1)
    assert asked == ["Newer."]


def test_each_sentence_is_heard_in_turn_even_one_that_couldnt_be_voiced():
    heard = []

    def fetch(text, emotion, first):
        if text == "Broken.":
            raise BrainError("no voice")
        return wav(text)

    out = FakeOutput(expect=2)
    speaker = Speaker(fetch, out, heard=lambda turn, text: heard.append((turn, text)))
    speaker.say(3, "Hello there. Broken. Bye now.")
    speaker.end(3)
    assert out.done.wait(5)
    wait_for(lambda: len(heard) == 3)
    assert heard == [(3, "Hello there."), (3, "Broken."), (3, "Bye now.")]


def test_a_sound_output_that_wont_open_falls_back_to_one_sentence_at_a_time():
    plain = FakeOutput(expect=1)
    broken = FakeOutput(fail=OutputError("no sound device"))
    speaker = Speaker(lambda text, emotion, first: wav(text), broken, fallback=lambda: plain)
    speaker.say(1, "Still heard. ")
    speaker.end(1)
    assert plain.done.wait(5)
    assert plain.said() == ["Still heard."] and speaker.output is plain


def test_the_speakers_wake_while_kit_thinks_and_sleep_after_he_stops():
    clock = Clock()
    out = FakeOutput(expect=1)
    speaker = Speaker(lambda text, emotion, first: wav(text), out, clock=clock)
    speaker.stop(1)  # his voice isn't known to be on: nothing to wake
    time.sleep(0.2)
    assert out.warmed == 0
    speaker.end(1)
    speaker.live = True
    speaker.stop(2)  # Dan sends a message: the speakers wake while Kit thinks
    wait_for(lambda: out.warmed == 1)
    speaker.say(2, "Hi. ")
    speaker.end(2)
    assert out.done.wait(5)
    closed = out.closed
    time.sleep(0.2)
    assert out.closed == closed  # kept open a while, in case he goes on
    clock.now += WAIT_S + 1
    wait_for(lambda: out.closed > closed)


def test_a_pipe_up_is_said_unless_hes_talking_already():
    asked = []
    out = FakeOutput(expect=1)

    def fetch(text, emotion, first):
        asked.append((text, emotion))
        return wav(text)

    speaker = Speaker(fetch, out)
    assert speaker.pipe_up(5, "Oi, lunch?", "playful")
    assert out.done.wait(5)
    assert asked == [("Oi, lunch?", "playful")]
    speaker.say(6, "Talking now, ")  # a reply under way
    assert not speaker.pipe_up(7, "Me too!", "happy")
    speaker.enabled = False
    speaker.end(6)
    assert not speaker.pipe_up(8, "Hello?", "happy")


# His words in the chat, in step with his voice


@pytest.fixture
def chat():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from kit.desk.chat import ChatWindow

    QApplication.instance() or QApplication([])
    window = ChatWindow()
    window.speaker = Voice()
    return window


class Voice:
    """Kit's voice as the chat sees it."""

    def __init__(self, live: bool = True):
        self.live, self.enabled = live, True
        self.busy = True
        self.calls: list[tuple] = []

    def mood(self, turn, emotion):
        self.calls.append(("mood", turn, emotion))

    def say(self, turn, text):
        self.calls.append(("say", turn, text))

    def end(self, turn):
        self.calls.append(("end", turn))

    def stop(self, turn=None):
        self.calls.append(("stop", turn))

    def talking(self):
        return self.busy

    def pipe_up(self, turn, text, emotion):
        self.calls.append(("pipe_up", turn, text, emotion))
        return self.enabled


def test_the_chat_feeds_his_voice_and_stops_it_when_dan_talks(chat):
    chat.on_event(1, {"type": "mood", "emotion": "happy"})
    chat.on_event(1, {"type": "say", "text": "Hi there."})
    chat.on_event(1, {"type": "spoken"})  # his words are complete: the last one is said now
    chat.on_event(1, {"type": "reply", "reply": {"segments": [{"say": "Hi there."}]}})
    chat.send("hello")  # no client: an error line, but Kit stops talking first
    assert chat.speaker.calls[:5] == [
        ("mood", 1, "happy"),
        ("say", 1, "Hi there."),
        ("end", 1),
        ("end", 1),
        ("stop", 1),
    ]


def test_his_words_show_as_his_voice_gets_to_them(chat):
    acted = []
    chat.replied.connect(acted.append)
    chat.on_event(1, {"type": "say", "text": "Hello  there. How's"})
    chat.on_event(1, {"type": "say", "text": " the day going?"})
    assert "Hello" not in chat.text()  # his voice hasn't got there yet
    chat.heard(1, "Hello there.")  # the voice has the spaces tidied
    assert "Hello  there." in chat.text() and "How's" not in chat.text()
    final = {"segments": [{"say": "Hello there. How's the day going?"}], "detail": "1. Coffee"}
    chat.on_event(1, {"type": "reply", "reply": final})
    assert acted == [final]  # he's talking, so his face acts it out now
    assert "Coffee" not in chat.text()
    chat.heard(1, "How's the day going?")
    assert "How's the day going?" in chat.text() and "1. Coffee" in chat.text()


def test_his_face_waits_for_his_voice_too(chat):
    acted = []
    chat.replied.connect(acted.append)
    chat.on_event(1, {"type": "say", "text": "Short one."})
    reply = {"segments": [{"say": "Short one."}]}
    chat.on_event(1, {"type": "reply", "reply": reply})
    assert acted == [] and "Short one." not in chat.text()
    chat.heard(1, "Short one.")
    assert acted == [reply] and "Short one." in chat.text()


def test_a_hand_off_to_the_cloud_keeps_each_part_in_step(chat):
    local = {"segments": [{"say": "Let me check with Claude."}]}
    chat.on_event(1, {"type": "say", "text": "Let me check with Claude."})
    chat.on_event(1, {"type": "reply", "reply": local})
    chat.on_event(1, {"type": "handing_off", "to": "Claude"})
    assert "Let me check with Claude." in chat.text()  # that part's over: it all shows
    chat.on_event(1, {"type": "say", "text": "It's 42.", "source": "cloud"})
    chat.heard(1, "Let me check with Claude.")  # his voice gets there late
    assert "It's 42." not in chat.text()
    chat.heard(1, "It's 42.")
    assert (chat.lines[-1].role, chat.lines[-1].text) == ("claude", "It's 42.")


def test_held_words_show_anyway_when_his_voice_doesnt_come(chat):
    from kit.desk.chat import HOLD_IDLE_S, HOLD_MAX_S

    chat.on_event(1, {"type": "say", "text": "Anyone there?"})
    chat._check_held()
    assert "Anyone" not in chat.text()  # still talking, and not for long
    chat._held[1].since -= HOLD_MAX_S + 0.1
    chat._check_held()
    assert "Anyone there?" in chat.text()  # too long, talking or not
    chat.on_event(2, {"type": "say", "text": "Hello?"})
    chat.speaker.busy = False
    chat._held[2].since -= HOLD_IDLE_S + 0.1
    chat._check_held()
    assert "Hello?" in chat.text()  # his voice went quiet without getting there


def test_with_his_voice_off_or_the_option_off_words_show_as_they_come(chat):
    chat.speaker.live = False
    chat.on_event(1, {"type": "say", "text": "Voice off."})
    assert "Voice off." in chat.text()
    chat.speaker.live, chat.in_step = True, False
    chat.on_event(2, {"type": "say", "text": "Option off."})
    assert "Option off." in chat.text()


def test_dan_talking_shows_the_rest_of_what_kit_was_saying_first(chat):
    chat.on_event(1, {"type": "say", "text": "Long story. Very long."})
    chat.send("stop")
    assert [line.role for line in chat.lines][:2] == ["kit", "you"]
    assert chat.lines[0].text == "Long story. Very long."


def test_a_pipe_up_is_said_and_shown_as_he_says_it(chat):
    from PySide6.QtWidgets import QApplication

    acted = []
    chat.replied.connect(acted.append)
    line = {"emotion": "playful", "segments": [{"say": "Oi."}, {"say": "Lunch?"}]}
    chat.pipe_up(line)
    kind, turn, text, emotion = chat.speaker.calls[-1]
    assert (kind, text, emotion) == ("pipe_up", "Oi. Lunch?", "playful")
    assert "Oi." not in chat.text() and acted == []
    chat.heard(turn, "Oi.")
    assert "Oi." in chat.text() and acted == [line]
    chat.heard(turn, "Lunch?")
    assert chat.lines[-1].text == "Oi. Lunch?"
    # His voice off (or talking already): shown after a moment, as before.
    chat.speaker.enabled = False
    chat.pipe_up({"segments": [{"say": "Quiet one."}]}, lead_in_ms=0)
    wait_for(lambda: QApplication.processEvents() or "Quiet one." in chat.text())
