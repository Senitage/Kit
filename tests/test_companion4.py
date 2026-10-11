"""Companion stage 4: his voice and eyes carry it. Cloud answers stream in their
mood, sounds in his voice, a backup voice, small moments his eyes feel, keeping
quiet while you're on your phone, and saying later what he held back."""

import asyncio
import json
import random
from datetime import datetime, timedelta

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.life import Life, pipe_up_prompt
from kit.memory import Memory
from kit.noticing import Noticing
from kit.pc_context import PcContext, Snapshot
from kit.recall import Recall
from kit.reply import Reply, StreamedReply, reply_events, voiced
from kit.scene_context import SceneContext, SceneReport
from kit.server import pipe_up_now
from kit.settings import Settings


def snap(idle=40, title="Weekend weather"):
    return Snapshot.model_validate(
        {"focus": {"app": "Firefox", "title": title}, "idle_seconds": idle, "locked": False}
    )


def seen(name=None, expressions=(), gestures=None, actions=(), holding=(), face=True, **more):
    """One person as the eyes report them."""
    return {
        "id": 1,
        "name": name,
        "box": [0.3, 0.1, 0.7, 0.95],
        "face": [0.4, 0.2, 0.55, 0.45] if face else None,
        "looking": "facing the camera",
        "expressions": list(expressions),
        "gestures": gestures or {},
        "actions": list(actions),
        "holding": list(holding),
        **more,
    }


def answer(*segments, emotion="playful", detail=""):
    """A reply's JSON as the model writes it: each segment's gesture before its words."""
    return json.dumps(
        {
            "emotion": emotion,
            "segments": [{"gesture": g, "say": say} for g, say in segments],
            "action": {"kind": "none", "text": ""},
            **({"detail": detail} if detail else {}),
        }
    )


def report(*people, off=False):
    return SceneReport.model_validate({"people": list(people), "off": off})


def setup(when="2026-10-06T10:00:00", **life):
    clock = Clock(when)
    pc = PcContext(clock)
    scene = SceneContext(clock)
    s = Settings.model_validate({"life": life})
    return Life(lambda: s, pc, clock, random.Random(1), scene=scene), pc, clock, scene


def look(life, scene, clock, rep, seconds=1):
    """The eyes reporting once a second, as they do."""
    for _ in range(seconds):
        clock.now += timedelta(seconds=1)
        life.on_scene(scene.update(rep))


def events(life, kind):
    return [e for e in life.events_after(0) if e["type"] == kind]


def keen(life):
    """Bored enough to pipe up, and nothing said lately."""
    life.drives.boredom = 1.0
    life.last_chat -= timedelta(hours=1)


# Cloud answers, as they're written


def test_a_streamed_answer_gives_his_mood_first_then_words_then_spoken_before_detail():
    raw = json.dumps(
        {
            "emotion": "playful",
            "segments": [
                {"say": "Morning!", "gesture": "wave"},
                {"say": "Coffee first?", "gesture": "tilt_head"},
            ],
            "action": {"kind": "none"},
            "detail": "A long written bit.",
        }
    )
    words = StreamedReply("cloud")
    out = []
    for i in range(0, len(raw), 7):
        out += words.feed(raw[i : i + 7])
    kinds = [e["type"] for e in out]
    assert kinds[0] == "mood" and out[0]["emotion"] == "playful"
    assert "".join(e["text"] for e in out if e["type"] == "say") == "Morning! Coffee first?"
    assert all(e["source"] == "cloud" for e in out if e["type"] == "say")
    assert kinds.count("spoken") == 1 and kinds[-1] == "spoken"  # before the detail is done
    assert words.said == "Morning! Coffee first?" and words.mood == "playful"


def test_a_sound_comes_just_before_its_punchline_and_never_twice_running():
    raw = answer(("none", "Right."), ("laugh", "Again?"), ("laugh", "Classic."), ("sigh", "Oh."))
    words = StreamedReply(sounds=True)
    said = ""
    for ch in raw:
        for e in words.feed(ch):
            said += f" [{e['sound']}] " if e["type"] == "sound" else e.get("text", "")
    # A chuckle on "Again?", none on "Classic." (two in a row), a sigh on "Oh.".
    assert said.split() == "Right. [chuckle] Again? Classic. [sigh] Oh.".split()
    quiet = StreamedReply(sounds=False)
    assert not [e for ch in raw for e in quiet.feed(ch) if e["type"] == "sound"]


def test_a_whole_reply_gives_the_same_events_and_a_pipe_up_its_voiced_line():
    whole = Reply.model_validate(
        {
            "emotion": "playful",
            "segments": [
                {"say": "You burnt the toast again?", "gesture": "none"},
                {"say": "Classic.", "gesture": "laugh"},
            ],
            "action": {"kind": "none"},
        }
    )
    got = reply_events(whole, "cloud", sounds=True)
    assert got == [
        {"type": "mood", "emotion": "playful"},
        {"type": "say", "text": "You burnt the toast again?", "source": "cloud"},
        {"type": "sound", "sound": "chuckle"},
        {"type": "say", "text": " Classic.", "source": "cloud"},
    ]
    assert voiced(whole, sounds=True) == "You burnt the toast again? [chuckle] Classic."
    assert voiced(whole) == "You burnt the toast again? Classic."


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock("2026-10-06T10:00:00"))
    yield m
    m.close()


def make(memory, claude=None, outputs=(), **sections):
    s = Settings.model_validate(
        {"memory": {"min_similarity": 0.3}, "routing": {"mode": "cloud-only"}, **sections}
    )
    claude = claude or FakeAnthropic()
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude, key="k"), recall)
    return brain, claude, model


def test_a_cloud_answer_streams_in_its_mood(memory):
    claude = FakeAnthropic(reply("Morning!", "Coffee first, or straight in?", emotion="playful"))
    brain, claude, _ = make(memory, claude)
    out = collect(brain.chat("Morning Kit"))
    kinds = [e["type"] for e in out]
    assert claude.streamed == 1
    assert kinds.index("mood") < kinds.index("say") and kinds.count("say") > 1
    assert next(e for e in out if e["type"] == "mood")["emotion"] == "playful"
    assert kinds.index("spoken") < kinds.index("reply")
    said = "".join(e["text"] for e in out if e["type"] == "say")
    assert said == "Morning! Coffee first, or straight in?"
    # Started coming back: a perk-up as his first words arrive, once.
    reacts = [e for e in brain.life.events_after(0) if e["type"] == "react"]
    assert [r["why"] for r in reacts] == ["the answer started coming back"]


def test_with_streaming_off_a_cloud_answer_comes_whole(memory):
    claude = FakeAnthropic(reply("Morning!", emotion="happy"))
    brain, claude, _ = make(memory, claude, cloud={"stream": False})
    out = collect(brain.chat("Morning Kit"))
    assert claude.streamed == 0
    assert [e["type"] for e in out] == ["mood", "say", "reply"]


def test_a_goodbye_is_still_checked_whole_before_he_says_it(memory):
    claude = FakeAnthropic(reply("Night! Will you be back tomorrow?"))  # a question: not okay
    brain, claude, _ = make(memory, claude)
    out = collect(brain.chat("Night Kit, off to bed"))
    assert claude.streamed == 0 and len(claude.calls) == 2  # asked again, then a stock line
    said = "".join(e["text"] for e in out if e["type"] == "say")
    assert "?" not in said


def test_cloud_sounds_go_with_their_words(memory):
    claude = FakeAnthropic(answer(("none", "You burnt the toast?"), ("laugh", "Classic.")))
    brain, _, _ = make(memory, claude, speech={"sounds": True})
    out = collect(brain.chat("Burnt the toast again"))
    kinds = [e["type"] for e in out]
    sound = kinds.index("sound")
    after = "".join(e["text"] for e in out[sound + 1 :] if e["type"] == "say")
    assert out[sound]["sound"] == "chuckle" and after.strip() == "Classic."


# Busy: on your phone or talking to someone, he keeps quiet and says so


def test_on_your_phone_he_keeps_quiet_and_his_bubble_says_why():
    life, pc, clock, scene = setup(chattiness=0.6)
    pc.update(snap())
    keen(life)
    look(life, scene, clock, report(seen(actions=["using a phone"], holding=["cell phone"])))
    quiet = events(life, "quiet")[-1]
    assert quiet["bubble"] == "keeping quiet, you're on your phone"
    assert life.tick() is None and life.quiet_because == "you're on your phone"
    # Off the phone: his bubble clears, and he's free to pipe up again.
    look(life, scene, clock, report(seen()), seconds=25)
    assert events(life, "quiet")[-1]["bubble"] == ""
    assert life.tick() == "bored"


def test_someone_talking_counts_too_unless_his_manners_are_off():
    life, pc, clock, scene = setup(chattiness=0.6)
    pc.update(snap())
    keen(life)
    look(life, scene, clock, report(seen(actions=["talking"]), {**seen(), "id": 2}))
    assert life.tick() is None and life.quiet_because == "you're talking to someone"
    rude, pc, clock, scene = setup(chattiness=0.6, eyes_manners=False)
    pc.update(snap())
    keen(rude)
    look(rude, scene, clock, report(seen(actions=["talking"])))
    assert rude.tick() == "bored"


def test_what_he_held_back_comes_once_youre_free_with_the_wait_named():
    life, pc, clock, scene = setup(chattiness=0.6, hold_pipe_ups=True)
    pc.update(snap())
    keen(life)
    phone = report(seen(holding=["cell phone"]))
    look(life, scene, clock, phone)
    assert life.tick() is None and life.holding.reason == "bored"
    assert life.hush_line() == "saving something till you're off your phone"
    assert "saving something" in events(life, "quiet")[-1]["bubble"]
    for _ in range(14):  # seven minutes on the phone
        look(life, scene, clock, phone, seconds=30)
        assert life.tick() is None
    look(life, scene, clock, report(seen()), seconds=25)
    assert life.tick() == "bored"
    assert life.held_words("Dan") == "7 minutes, while Dan was on the phone"
    prompt = pipe_up_prompt("bored", "Dan", 0.5, "", 1, held=life.held_words("Dan"))
    assert "held this back for 7 minutes, while Dan was on the phone" in prompt
    life.piped_up("bored")
    assert life.holding is None and life.held_words("Dan") == ""


def test_a_held_pipe_up_goes_stale_after_half_an_hour():
    life, pc, clock, scene = setup(chattiness=0.6, hold_pipe_ups=True)
    pc.update(snap())
    keen(life)
    look(life, scene, clock, report(seen(holding=["cell phone"])))
    life.tick()
    for _ in range(70):  # 35 minutes on the phone
        look(life, scene, clock, report(seen(holding=["cell phone"])), seconds=30)
        life.tick()
    look(life, scene, clock, report(seen()), seconds=25)
    life.drives.boredom = 0.0
    assert life.tick() is None and life.delivering is None


def test_without_holding_nothing_waits_and_talking_to_him_clears_it():
    life, pc, clock, scene = setup(chattiness=0.6)
    pc.update(snap())
    keen(life)
    look(life, scene, clock, report(seen(holding=["cell phone"])))
    life.tick()
    assert life.holding is None
    held, pc, clock, scene = setup(chattiness=0.6, hold_pipe_ups=True)
    pc.update(snap())
    keen(held)
    look(held, scene, clock, report(seen(holding=["cell phone"])))
    held.tick()
    held.note_chat("hey")
    assert held.holding is None


# Moments his eyes catch (life.seen_feelings)


def test_a_smile_held_two_seconds_brightens_him():
    life, _, clock, scene = setup(seen_feelings=True, dials=True)
    valence = life.valence
    look(life, scene, clock, report(seen(expressions=["smiling"])), seconds=2)
    assert not events(life, "react")  # a flicker of a smile isn't a smile at him
    look(life, scene, clock, report(seen(expressions=["smiling"])))
    assert [e["gesture"] for e in events(life, "react")] == ["wiggle"]
    felt = life.feeling_now()
    assert felt.name == "pleased" and felt.why == "Dan smiled at you"
    assert life.valence > valence and events(life, "dials")[-1]["valence"] > valence
    look(life, scene, clock, report(seen(expressions=["smiling"])), seconds=60)
    assert len(events(life, "react")) == 1  # one smile, not sixty


def test_a_smile_looking_away_isnt_at_him():
    life, _, clock, scene = setup(seen_feelings=True)
    look(life, scene, clock, report(seen(expressions=["smiling"], looking="down")), seconds=5)
    assert not events(life, "react")


def test_a_wave_gets_a_wave_back_and_a_thumbs_up_makes_him_proud():
    life, _, clock, scene = setup(seen_feelings=True)
    look(life, scene, clock, report(seen(actions=["waving"])), seconds=3)
    assert [e["gesture"] for e in events(life, "react")] == ["wave"]
    look(life, scene, clock, report(seen(gestures={"right": "thumbs up"})))
    assert len(events(life, "react")) == 1  # a single report could be a twitch
    look(life, scene, clock, report(seen(gestures={"right": "thumbs up"})))
    assert events(life, "react")[-1]["gesture"] == "nod"
    assert life.feeling_now().name == "proud"


def test_a_frown_that_stays_makes_him_sympathetic_and_gives_him_a_thought():
    life, _, clock, scene = setup(seen_feelings=True, thoughts_per_hour=4)
    frown = report(seen(expressions=["frowning"]))
    look(life, scene, clock, frown, seconds=3)
    assert life.feeling_now() is None
    look(life, scene, clock, frown)
    assert life.feeling_now().name == "sympathetic"
    assert ("frowning", "Dan has been frowning for a while.") in life._to_think


def test_eyes_closing_late_is_a_yawn_but_in_the_day_a_blink_is_nothing():
    life, _, clock, scene = setup("2026-10-06T14:00:00", seen_feelings=True)
    look(life, scene, clock, report(seen(expressions=["eyes closed"])), seconds=6)
    assert not events(life, "react") and not life.eyes_closing()
    late, _, clock, scene = setup("2026-10-06T21:45:00", seen_feelings=True)
    look(late, scene, clock, report(seen(expressions=["eyes closed"])), seconds=4)
    assert [e["gesture"] for e in events(late, "react")] == ["yawn"]
    assert late.eyes_closing()


def test_only_dan_counts_and_nothing_while_off_asleep_or_switched_off():
    life, _, clock, scene = setup(seen_feelings=True)
    sam = seen(name="Sam", expressions=["smiling"])
    look(life, scene, clock, report(sam, {**seen(expressions=["smiling"]), "id": 2}), seconds=5)
    assert not events(life, "react")  # someone else, and someone the eyes can't name
    look(life, scene, clock, report(seen(name="Dan", actions=["waving"]), sam))
    assert events(life, "react")[-1]["why"] == "Dan waved"
    off, _, clock, scene = setup()
    look(off, scene, clock, report(seen(actions=["waving"])), seconds=3)
    assert not events(off, "react")
    asleep, _, clock, scene = setup(seen_feelings=True)
    asleep.asleep = True
    look(asleep, scene, clock, report(seen(actions=["waving"])))
    assert not events(asleep, "react")  # his eyes were shut


def test_noticing_waits_before_the_same_moment_again():
    noticing, now = Noticing(), datetime(2026, 10, 6, 10)
    wave = report(seen(actions=["waving"]))
    still = report(seen())
    got = []
    for second in range(100):
        rep = wave if second % 10 < 2 else still  # a wave every ten seconds
        got += noticing.see(rep, "Dan", now + timedelta(seconds=second))
    assert [m.kind for m in got] == ["waved", "waved"]  # once a minute at most


def test_dans_eyes_closing_brings_the_bed_nudge_an_hour_early(memory):
    brain, _, _ = make(memory, life={"seen_feelings": True})
    memory.clock.now = datetime.fromisoformat("2026-10-06T21:40:00")
    brain.pc.update(snap(idle=5))
    assert "sleep" not in brain.offer_wants()  # before bedtime
    for _ in range(5):
        memory.clock.now += timedelta(seconds=1)
        brain.saw(report(seen(expressions=["eyes closed"])))
    assert brain.offer_wants() == ["sleep"]
    want = next(w for w in brain.notebook.open_wants() if w.meta.get("nudge") == "sleep")
    assert want.text == "Tell Dan to get to bed: Dan's eyes keep closing."


# How a pipe-up is said


def test_a_pipe_up_comes_with_its_voiced_line_and_whether_to_say_it_out_loud(memory):
    said = answer(("none", "Burnt toast again?"), ("laugh", "Classic."))
    brain, _, _ = make(
        memory,
        outputs=[said, said],
        routing={"mode": "local-heavy"},
        ollama={"speak_pass": False},
        speech={"sounds": True},
    )
    brain.pc.update(snap())
    asyncio.run(pipe_up_now(brain, "bored"))
    event = next(e for e in brain.life.events_after(0) if e["type"] == "pipe_up")
    assert event["voice"] == "Burnt toast again? [chuckle] Classic." and event["aloud"]
    memory.clock.now += timedelta(minutes=30)
    brain.saw(report())  # his eyes see nobody: nobody to hear it
    brain.life.awaiting_reply = False
    asyncio.run(pipe_up_now(brain, "bored"))
    event = [e for e in brain.life.events_after(0) if e["type"] == "pipe_up"][-1]
    assert event["aloud"] is False


def test_no_nap_while_dan_is_on_his_phone_and_no_pipe_up_while_asleep():
    life, pc, clock, scene = setup(chattiness=0.6, hold_pipe_ups=True)
    pc.update(snap())
    keen(life)
    phone = report(seen(holding=["cell phone"]))
    for _ in range(80):  # forty minutes on the phone, ignoring him
        look(life, scene, clock, phone, seconds=30)
        assert life.tick() is None
    assert not life.asleep and life.holding is not None
    life._fall_asleep(clock.now, beside=True, kind="nap")
    assert life.holding is None  # what he was saving fades as he drifts off
    look(life, scene, clock, report(seen()), seconds=25)
    assert life.tick() is None and life.quiet_because == "asleep"
