"""Kit's voice on the desk PC: one steady sound output, each sentence made while the
last one plays, his words shown as he says them, and his pipe-ups said too."""

import json
import threading
import time

import httpx
import pytest

from kit.desk.client import (
    SPEAK_TIMEOUT,
    BrainClient,
    BrainError,
    Sound,
    SpeechLoading,
    SpeechOff,
    SpeechStale,
)
from kit.desk.voice import (
    LOADING_TRIES,
    LOADING_WAIT_S,
    PRE_ROLL_S,
    WAIT_S,
    Clip,
    OutputError,
    Speaker,
    StreamOutput,
    to_wav,
)

RATE = 24000


def wav_bytes(text: str, rate: int = RATE) -> bytes:
    """A WAV whose samples spell ``text``, so tests can tell sentences apart."""
    pcm = text.encode()
    return to_wav(Clip(pcm + b"\0" * (len(pcm) % 2), rate, 1, 2))


def wav(text: str, rate: int = RATE) -> Sound:
    """A sentence's sound, in one piece, whose samples spell ``text``."""
    return Sound.from_wav(wav_bytes(text, rate))


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


def test_his_mouth_follows_how_loud_his_voice_is_and_closes_when_it_ends():
    sd, levels, clock = FakeSoundDevice(), [], Clock()
    out = StreamOutput(sd, clock=clock, talk=levels.append)
    block = RATE // 100  # 10 ms a block, as the sound card asks
    out.play(Clip(bytes(2 * RATE), RATE, 1, 2))  # a second of silence
    stream = sd.streams[0]
    for _ in range(130):
        stream.pull(block)
    assert set(levels) <= {0.0}  # nothing to say: his mouth stays shut
    loud = (b"\x00\x50" * (block // 2) + b"\x00\xb0" * (block // 2)) * 100  # a tone, a second
    clock.now = 1.3  # the speakers are awake
    out.play(Clip(loud, RATE, 1, 2))
    for _ in range(100):
        stream.pull(block)
    assert max(levels) > 0.5  # wide open on his voice
    assert len([x for x in levels if 0 < x < 0.5]) >= 1  # and it opened over a few blocks
    for _ in range(40):  # the sound has ended: shut within a few hundred milliseconds
        stream.pull(block)
    assert levels[-1] == 0.0
    closing = levels[levels.index(max(levels)) :]
    assert closing == sorted(closing, reverse=True)  # falling away, not snapping


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

    def fetch(text, emotion, first, generation):
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

    def fetch(text, emotion, first, generation):
        if text == "Off.":
            raise SpeechOff("speech is off")
        if text == "Broken.":
            raise BrainError("no voice")
        gate.wait(5)
        return wav(text)

    out = FakeOutput(expect=1)
    speaker = Speaker(fetch, out)
    speaker.say(1, "One. Two. Three. ")
    speaker.stop(2)  # Dan sends a message while Kit is mid-reply
    assert out.stopped  # what's playing stops now, not after the sentence
    gate.set()
    speaker.say(2, "Off. Broken. New one.")
    speaker.end(2)
    assert out.done.wait(5)
    time.sleep(0.1)
    assert out.said() == ["New one."]
    assert speaker.live  # the server made a sentence, so his voice is on


def test_an_older_reply_still_streaming_isnt_spoken_over_the_newer_one():
    asked = []
    out = FakeOutput(expect=1)
    speaker = Speaker(lambda text, emotion, first, generation: asked.append(text) or wav(text), out)
    speaker.say(2, "Newer.")
    speaker.say(1, "Older. ")  # Dan asked twice; the first answer arrives late
    speaker.end(1)
    speaker.end(2)
    assert out.done.wait(5)
    time.sleep(0.1)
    assert asked == ["Newer."]


def test_each_sentence_is_heard_in_turn_even_one_that_couldnt_be_voiced():
    heard = []

    def fetch(text, emotion, first, generation):
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


def test_a_sentence_plays_from_its_first_piece_and_is_heard_once_and_spoke_at_its_end():
    heard, spoke, gates = [], [], [threading.Event(), threading.Event()]

    def pieces(text):
        yield b"\x01\x02" * 1200  # 0.1 s
        gates[0].wait(5)  # the server is still making the rest
        yield b"\x03\x04" * 2400
        gates[1].wait(5)
        yield b"\x05\x06" * 3600

    out = FakeOutput(expect=3)
    speaker = Speaker(
        lambda text, emotion, first, generation: Sound(RATE, pieces=pieces(text)),
        out,
        heard=lambda turn, text: heard.append((turn, text)),
        spoke=lambda turn, text, seconds: spoke.append((turn, text, round(seconds, 2))),
    )
    speaker.say(1, "Hello there. ")
    speaker.end(1)
    wait_for(lambda: len(out.clips) == 1)
    assert heard == [(1, "Hello there.")] and spoke == []  # heard on the first piece
    gates[0].set()
    wait_for(lambda: len(out.clips) == 2)
    assert heard == [(1, "Hello there.")] and spoke == []  # and only once
    gates[1].set()
    assert out.done.wait(5)
    wait_for(lambda: spoke)
    assert spoke == [(1, "Hello there.", 0.3)]  # the whole sentence, as it ends
    assert heard == [(1, "Hello there.")]
    # Dan moves on while the rest is still coming: it isn't fetched or played.
    gates[0].clear()
    gates[1].clear()
    speaker.say(2, "Long one. ")
    wait_for(lambda: len(out.clips) == 4)
    speaker.stop(3)
    gates[0].set()
    gates[1].set()
    time.sleep(0.1)
    assert len(out.clips) == 4 and spoke == [(1, "Hello there.", 0.3)]


def test_pieces_of_one_sentence_join_the_output_as_they_come_with_no_gap():
    sd, clock = FakeSoundDevice(), Clock()
    out = StreamOutput(sd, clock=clock)
    started = []
    out.play(Clip(b"\x01\x02" * 5, RATE, 1, 2), lambda: started.append("one"))
    out.play(Clip(b"\x03\x04" * 5, RATE, 1, 2))  # the next piece: no new mark
    stream = sd.streams[0]
    stream.pull(int(RATE * PRE_ROLL_S))
    assert stream.pull(10) == b"\x01\x02" * 5 + b"\x03\x04" * 5 and started == ["one"]
    ended = []
    clock.now = 1.0  # awake: a late piece plays straight away
    out.play(Clip(b"\x05\x06" * 5, RATE, 1, 2))
    out.mark(lambda: ended.append("one"))  # the sentence's end, once it has played
    stream.pull(4)
    assert ended == []
    stream.pull(1)
    assert ended == ["one"]


def test_a_sound_output_that_wont_open_falls_back_to_one_sentence_at_a_time():
    plain = FakeOutput(expect=1)
    broken = FakeOutput(fail=OutputError("no sound device"))
    speaker = Speaker(
        lambda text, emotion, first, generation: wav(text), broken, fallback=lambda: plain
    )
    speaker.say(1, "Still heard. ")
    speaker.end(1)
    assert plain.done.wait(5)
    assert plain.said() == ["Still heard."] and speaker.output is plain


def test_the_way_to_the_server_is_opened_before_the_first_sentence():
    order = []
    out = FakeOutput(expect=1)

    def fetch(text, emotion, first, generation):
        order.append("speak")
        return wav(text)

    def connect():
        order.append("connect")

    speaker = Speaker(fetch, out, connect=connect)
    speaker.stop(1)  # his voice isn't known to be on: nothing to open
    speaker.end(1)
    speaker.live = True
    speaker.stop(2)  # Dan sends a message: the connection opens while Kit thinks
    speaker.say(2, "Hi there. ")
    speaker.end(2)
    assert out.done.wait(5)
    assert order == ["connect", "speak"]


def test_a_failed_warm_up_call_is_only_logged():
    out = FakeOutput(expect=1)

    def connect():
        raise BrainError("Can't reach Kit")

    speaker = Speaker(lambda text, emotion, first, generation: wav(text), out, connect=connect)
    speaker.live = True
    speaker.stop(1)
    speaker.say(1, "Hi there. ")
    speaker.end(1)
    assert out.done.wait(5)
    assert out.said() == ["Hi there."]


def test_the_speakers_wake_while_kit_thinks_and_sleep_after_he_stops():
    clock = Clock()
    out = FakeOutput(expect=1)
    speaker = Speaker(lambda text, emotion, first, generation: wav(text), out, clock=clock)
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

    def fetch(text, emotion, first, generation):
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


def test_a_sentence_stuck_being_made_doesnt_hold_up_the_next_reply():
    gate = threading.Event()
    asked = []

    def fetch(text, emotion, first, generation):
        asked.append(text)
        if text == "Slow one.":
            gate.wait(5)  # the server is stuck on it (an engine restarting, say)
        return wav(text)

    out = FakeOutput(expect=1)
    speaker = Speaker(fetch, out)
    speaker.say(1, "Slow one. ")
    wait_for(lambda: asked == ["Slow one."])
    speaker.stop(2)  # Dan asks something else while that fetch is still out
    speaker.say(2, "Quick answer. ")
    speaker.end(2)
    assert out.done.wait(2)  # said while the old fetch is still stuck
    assert out.said() == ["Quick answer."]
    gate.set()
    time.sleep(0.1)
    assert out.said() == ["Quick answer."]  # the old one's sound is thrown away
    assert asked == ["Slow one.", "Quick answer."]


def test_each_sentence_carries_its_replys_generation_which_goes_up_when_hes_cut_off():
    asked = []
    out = FakeOutput(expect=3)

    def fetch(text, emotion, first, generation):
        asked.append((text, generation))
        return wav(text)

    speaker = Speaker(fetch, out)
    speaker.say(1, "One. Two. ")
    speaker.end(1)
    wait_for(lambda: len(out.clips) == 2)
    speaker.stop(2)
    speaker.say(2, "Three. ")
    speaker.end(2)
    assert out.done.wait(5)
    (_, g1), (_, g2), (_, g3) = asked
    assert g1 == g2 < g3
    assert g1 > 1_000_000_000_000  # from the clock, so bigger than before a restart


def test_an_engine_still_loading_is_asked_again_briefly_then_his_words_just_show():
    asked, slept, heard = [], [], []

    def fetch(text, emotion, first, generation):
        asked.append(text)
        if text == "Stale.":
            raise SpeechStale("that reply was interrupted")
        raise SpeechLoading("Kit's voice is still loading")

    speaker = Speaker(
        fetch,
        FakeOutput(),
        heard=lambda turn, text: heard.append(text),
        sleep=lambda s: slept.append(s),
    )
    speaker.say(1, "First. Second. Stale. ")
    speaker.end(1)
    wait_for(lambda: len(heard) == 3)
    assert heard == ["First.", "Second.", "Stale."]
    # The first sentence is asked for a few times; the rest of the reply once each.
    assert asked == ["First."] * LOADING_TRIES + ["Second.", "Stale."]
    assert slept == [LOADING_WAIT_S] * (LOADING_TRIES - 1)
    # A new reply gets its tries again, but stops asking when Dan moves on.
    asked.clear()
    waiting = threading.Event()
    speaker.sleep = lambda s: waiting.wait(5)
    speaker.say(2, "Again. ")
    wait_for(lambda: asked == ["Again."])
    speaker.stop(3)
    waiting.set()
    time.sleep(0.1)
    assert asked == ["Again."]


def test_the_desk_gives_a_sentence_30_s_and_knows_not_yet_from_dropped():
    assert SPEAK_TIMEOUT.read == 30.0
    streamed = {"Content-Type": "audio/L16; rate=16000", "X-Sample-Rate": "16000"}

    def brain(request):
        body = json.loads(request.content)
        if body["text"] == "Hi.":
            assert body["generation"] == 7
            return httpx.Response(200, content=b"Hi", headers=streamed)
        if body["text"] == "Old server.":
            return httpx.Response(200, content=wav_bytes("Hi"))
        if body["text"] == "Junk.":
            return httpx.Response(200, content=b"not a sound")
        if body["text"] == "Later.":
            assert "generation" not in body
            return httpx.Response(503, text="still loading", headers={"Retry-After": "1"})
        return httpx.Response(410, text="interrupted")

    client = BrainClient("http://kit-server:8600", "t", transport=httpx.MockTransport(brain))
    sound = client.speak("Hi.", "happy", True, 7)  # in pieces as the server makes it
    assert (sound.rate, sound.channels, sound.width) == (16000, 1, 2)
    assert b"".join(sound.pieces) == b"Hi"
    sound = client.speak("Old server.")  # a server from before: the whole WAV at once
    assert (sound.rate, b"".join(sound.pieces)) == (RATE, b"Hi")
    with pytest.raises(BrainError, match="isn't sound"):
        client.speak("Junk.")
    with pytest.raises(SpeechLoading):
        client.speak("Later.")
    with pytest.raises(SpeechStale):
        client.speak("Old.", generation=3)
    client.close()


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

    def sound(self, turn, name):
        self.calls.append(("sound", turn, name))

    def end(self, turn):
        self.calls.append(("end", turn))

    def saying(self, turn):
        return self.enabled and self.live

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


# Sounds in his voice, and his face keeping time with it (companion stage 4)


def test_a_sound_is_said_before_its_words_and_never_shown():
    asked, heard, spoke = [], [], []

    def fetch(text, emotion, first, generation):
        asked.append(text)
        return wav(text)

    out = FakeOutput(expect=2)
    speaker = Speaker(
        fetch,
        out,
        heard=lambda turn, text: heard.append(text),
        spoke=lambda turn, text, seconds: spoke.append((turn, text, seconds)),
    )
    speaker.say(1, "You burnt the toast? ")
    speaker.sound(1, "chuckle")
    speaker.say(1, "Classic.")
    speaker.end(1)
    assert out.done.wait(5)
    wait_for(lambda: len(spoke) == 2)
    assert asked == ["You burnt the toast?", "[chuckle] Classic."]
    assert heard == ["You burnt the toast?", "Classic."]
    # His face hears how long each sentence plays, from the sound itself.
    assert spoke[1][:2] == (1, "Classic.") and spoke[1][2] == pytest.approx(18 / 48000)


def test_the_chat_passes_sounds_to_his_voice(chat):
    chat.on_event(1, {"type": "sound", "sound": "chuckle"})
    assert chat.speaker.calls[-1] == ("sound", 1, "chuckle")


def test_a_pipe_up_with_nobody_to_hear_it_is_only_shown(chat):
    from PySide6.QtWidgets import QApplication

    chat.pipe_up({"segments": [{"say": "Ha."}]}, lead_in_ms=0, aloud=False)
    assert not [c for c in chat.speaker.calls if c[0] == "pipe_up"]
    wait_for(lambda: QApplication.processEvents() or "Ha." in chat.text())
    chat.pipe_up({"segments": [{"say": "Burnt it?"}]}, voice="[chuckle] Burnt it?")
    assert chat.speaker.calls[-1][2] == "[chuckle] Burnt it?"


def test_the_face_hears_whether_his_voice_is_saying_the_reply(chat):
    voicing = []
    chat.replied.connect(lambda reply: voicing.append(chat.voicing))
    chat.on_event(1, {"type": "say", "text": "Hi."})
    chat.on_event(1, {"type": "reply", "reply": {"segments": [{"say": "Hi."}]}})
    chat.heard(1, "Hi.")
    chat.speaker.live = False
    chat.on_event(2, {"type": "say", "text": "Bye."})
    chat.on_event(2, {"type": "reply", "reply": {"segments": [{"say": "Bye."}]}})
    assert voicing == [True, False] and chat.voicing is False


class FakeFace:
    def __init__(self):
        self.calls: list[tuple] = []
        self.state = "idle"
        self.level: float | None = None

    def set_emotion(self, emotion, now, hold_s=0.0):
        self.calls.append(("emotion", emotion))

    def play(self, gesture, now):
        self.calls.append(("gesture", gesture))

    def set_state(self, state):
        self.state = state

    def talk(self, level):
        self.level = level


class Caption:
    def __init__(self):
        self.shown = ""

    def setText(self, text):  # noqa: N802 (Qt's name)
        self.shown = text

    def text(self):
        return self.shown


@pytest.fixture
def performer():
    pytest.importorskip("PySide6")
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from kit.desk.face_preview import Performer

    QApplication.instance() or QApplication([])
    face = FakeFace()
    return Performer(SimpleNamespace(face=face), Caption()), face


def run_qt(seconds):
    from PySide6.QtWidgets import QApplication

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)


REPLY = {
    "emotion": "playful",
    "segments": [
        {"say": "You burnt the toast?", "gesture": "tilt_head"},
        {"say": "Classic.", "gesture": "laugh"},
    ],
}


def test_his_face_talks_exactly_as_long_as_his_voice(performer):
    act, face = performer
    act.perform(REPLY, voiced=True)
    assert face.calls == [("emotion", "playful"), ("gesture", "tilt_head")]
    assert face.state == "idle"  # his mouth waits for his voice
    act.heard(1, "You burnt the toast?")  # his voice starts the first sentence
    assert face.state == "speaking" and act.caption.text() == "You burnt the toast?"
    act.talk(0.6)
    assert face.level == 0.6  # his mouth follows how loud his voice is
    run_qt(0.2)
    act.spoken(1, "You burnt the toast?", 0.3)
    act.heard(1, "Classic.")  # the next sentence: his gesture for it, as it starts
    assert face.calls[-1] == ("gesture", "laugh")
    assert act.caption.text() == "You burnt the toast? Classic."
    run_qt(0.35)
    assert face.state == "speaking"  # the second sentence is still playing
    act.spoken(1, "Classic.", 0.3)
    run_qt(0.3)
    assert face.state == "idle"  # his voice stopped, and so did his mouth
    assert face.level is None


def test_a_streamed_answer_his_voice_started_gets_its_gestures_when_the_reply_lands(performer):
    act, face = performer
    act.spoken(4, "You burnt the toast?", 1.0)
    act.perform(REPLY, voiced=True)
    assert ("gesture", "tilt_head") in face.calls and face.state == "speaking"


def test_a_voice_that_never_comes_falls_back_to_acting_it_out(performer):
    act, face = performer
    act.NO_VOICE_S = 0.1
    act.perform(REPLY, voiced=True)
    run_qt(0.6)
    assert act.caption.text().startswith("You burnt the toast?")
