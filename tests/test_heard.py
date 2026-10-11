"""What Kit makes of what his ears hear (kit.heard): talk meant for him, a laugh,
his own voice coming back, who's talking and how they sound, and the API the
ears and the desk app use."""

import asyncio
import json
from datetime import timedelta

from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.brain import Brain
from kit.heard import HeardTurns, Hearing, Utterance, calls, echo_of
from kit.memory import Memory
from kit.prompt import history_messages
from kit.recall import Recall
from kit.server import create_app
from kit.settings import HearingSettings, Settings
from kit.settings_store import SettingsStore

AUTH = {"Authorization": "Bearer t"}
NAMES = ["Kit"]


def make(paths, *outputs):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    return brain, memory, model, store


def hear(brain, **said):
    """Kit hears something, and any reply it starts runs to the end."""

    async def run():
        answer = await brain.hear(Utterance(**said))
        if brain._hearing_tasks:
            await asyncio.gather(*brain._hearing_tasks)
        events = []
        if "turn" in answer:
            events = [e async for e in brain.heard_turns.stream(answer["turn"])]
        return answer, events

    return asyncio.run(run())


# --- talking to Kit ----------------------------------------------------------


def test_his_name_at_the_start_or_end_means_he_is_spoken_to():
    for said in (
        "Kit, what's the weather doing?",
        "Hey Kit, you awake?",
        "okay kit what time is it",
        "What do you reckon, Kit?",
        "Thanks Kit.",
        "So, Kit, what now?",
        "Kit?",
    ):
        assert calls(said, NAMES), said
    for said in ("I told Kit about it yesterday", "the kit is in the car", "kitchen's a mess"):
        assert not calls(said, NAMES), said
    assert calls("Kitt, you there?", ["Kit", "Kitt"])


def test_his_name_counts_without_a_comma_and_as_the_ears_mishear_it():
    # How the ears wrote "Kit" in sample sentences, from real speech models.
    names = HearingSettings().names
    for said in (
        "What's the weather doing kitt?",
        "Hey Ki, how are you going?",
        "Okay, Ki, tell me a joke.",
        "Hey, kid, how are you going.",
        "okay so Kit, what's for tea",
        "what do you reckon Kit",
        "I told him, Kit.",
    ):
        assert calls(said, names), said
    for said in (
        "I told Kit",
        "ask Kit",
        "where's the first aid kit?",
        "that's my kid",
        "Kit's been quiet today",
        "did you get it?",
    ):
        assert not calls(said, names), said


def test_words_he_just_said_coming_back_are_an_echo():
    said = ["It's going to rain this afternoon, so bring the washing in."]
    assert echo_of("going to rain this afternoon", said)
    assert not echo_of("what about tomorrow then", said)
    assert not echo_of("", said)


def test_what_kit_makes_of_what_he_hears():
    clock = Clock()
    ears, s = Hearing(clock), HearingSettings()
    assert ears.decide(Utterance(text="what's on the telly"), s).action == "ignore"
    v = ears.decide(Utterance(text="Kit, how are you?"), s)
    assert (v.action, v.called) == ("answer", True)
    # Sounding like Kit only means it's his voice from the speakers while that's playing.
    assert ears.decide(Utterance(text="Kit, hi", own_voice=True), s).why == "his name"
    ears.spoke("The footy starts at seven tonight.", 2.0)
    assert ears.speaking()
    assert ears.decide(Utterance(text="Kit, hi", own_voice=True), s).why == "his own voice"
    echo = ears.decide(Utterance(text="the footy starts at seven"), s)
    assert echo.why == "his own words coming back"
    clock.now += timedelta(seconds=5)  # he stopped 3 s ago: Dan answers without his name
    assert not ears.speaking() and ears.quiet_s() == 3
    assert ears.decide(Utterance(text="good, I'll watch it"), s).action == "answer"
    laugh = ears.decide(Utterance(text="", sound="laughter"), s)
    assert (laugh.action, laugh.laughed) == ("laugh", True)
    clock.now += timedelta(seconds=30)  # long after: talk in the room is let go
    assert ears.decide(Utterance(text="good, I'll watch it"), s).action == "ignore"
    assert ears.decide(Utterance(sound="laughter"), s).action == "ignore"
    assert ears.as_dict()["last"]["why"] == "not talking to him"  # never the words
    never = HearingSettings(follow_up_s=0, laugh_s=0)
    clock.now += timedelta(seconds=1)
    ears.answered()
    assert ears.decide(Utterance(text="and another thing"), never).action == "ignore"
    assert ears.decide(Utterance(sound="laughter"), never).action == "ignore"


def test_talking_over_him_ends_his_voice_early():
    clock = Clock()
    ears = Hearing(clock)
    ears.spoke("One.", 2.0)
    ears.spoke("Two.", 2.0)  # queued after the first
    assert ears.speaking_until == clock.now + timedelta(seconds=4)
    ears.hushed()
    assert not ears.speaking()


def test_a_heard_turn_streams_to_readers_from_the_start():
    async def run():
        turns = HeardTurns(keep=2)
        first = turns.start()
        turns.add(first, {"type": "say", "text": "Hi"})
        got = []

        async def read():
            async for e in turns.stream(first):
                got.append(e)

        reader = asyncio.create_task(read())
        await asyncio.sleep(0)
        turns.add(first, {"type": "reply"})
        turns.finish(first)
        await reader
        turns.start(), turns.start()
        return got, first in turns

    got, kept = asyncio.run(run())
    assert [e["type"] for e in got] == ["say", "reply"]
    assert not kept  # only the last two are kept


# --- the brain ---------------------------------------------------------------


def test_talk_meant_for_him_is_answered_on_the_voice_channel(paths):
    brain, memory, model, _ = make(paths, reply("It's sunny out."))
    answer, events = hear(brain, text="Kit, what's it like outside?", tone="neutral")
    assert answer["heard"] == "answer" and answer["why"] == "his name"
    assert "talking to you out loud" in model.calls[0][0]["content"]
    assert any(e["type"] == "reply" for e in events)
    heard = [e for e in brain.life.events_after(0) if e["type"] == "heard"]
    assert heard[0]["text"] == "Kit, what's it like outside?" and heard[0]["who"] == "Dan"
    user = memory.recent(5)[0]
    assert user.channel == "voice" and json.loads(user.meta_json) == {"heard": {"tone": "neutral"}}
    assert brain.hearing.speaking_until is not None  # the follow-up window is open
    memory.close()


def test_overheard_talk_is_let_go(paths):
    brain, memory, model, _ = make(paths)
    answer, _ = hear(brain, text="did you feed the cat")
    assert answer == {"heard": "ignore", "why": "not talking to him"}
    assert model.calls == [] and memory.recent(5) == []
    memory.close()


def test_his_name_wakes_him_but_overheard_talk_does_not(paths):
    brain, memory, _, _ = make(paths, reply("Mm? I'm up."))
    brain.life.asleep = True
    hear(brain, text="pass the remote")
    assert brain.life.asleep
    hear(brain, text="Kit, wake up")
    woke = [e for e in brain.life.events_after(0) if e.get("state") == "awake"]
    assert woke[0]["why"] == "heard his name" and not brain.life.asleep
    memory.close()


def test_a_laugh_at_his_line_makes_him_chuffed(paths):
    brain, memory, _, _ = make(paths)
    brain.hearing.spoke("I'd vote for the cat, honestly.", 1.5)
    answer, _ = hear(brain, sound="laughter")
    assert answer["heard"] == "laugh"
    felt = brain.life.feeling_now()
    assert felt.name == "chuffed" and felt.why.startswith("Dan laughed at what you said")
    assert any(e.get("gesture") == "laugh" for e in brain.life.events_after(0))
    memory.close()


def test_tone_is_a_guess_he_may_ask_about_never_states(paths):
    brain, memory, model, _ = make(paths, reply("Rough day?"))
    hear(brain, text="Kit, I'm home", tone="sad")
    asked = model.calls[0][-1]["content"]  # the asides ride with Dan's message
    assert "Dan's voice sounded down just then" in asked
    assert "never tell Dan how they feel" in asked
    assert brain.life.feeling_now().name == "sympathetic"
    memory.close()


def test_tone_can_be_switched_off(paths):
    brain, memory, model, store = make(paths, reply("Welcome back."))
    store.update({"hearing": {"tone": False}}, "test")
    hear(brain, text="Kit, I'm home", tone="sad")
    assert "sounded down" not in model.calls[0][-1]["content"]
    memory.close()


def test_someone_else_in_the_house_is_answered_as_themselves(paths):
    brain, memory, model, _ = make(paths, reply("Hi Sam!"), reply("Sure."))
    hear(brain, text="Kit, Emma's my cousin", who="Sam")
    assert "said out loud by Sam, not Dan" in model.calls[0][-1]["content"]
    user = memory.recent(5)[0]
    assert json.loads(user.meta_json)["speaker"] == "Sam"
    assert (
        "(Sam, out loud) Kit, Emma's my cousin" in history_messages([user], "voice")[0]["content"]
    )
    # Sam's cousin isn't Dan's: nothing is learned about Dan from it.
    assert not [f for f in memory.facts() if "Emma" in f.text]
    memory.close()


def test_talking_over_him_hushes_bodies_only_while_he_speaks(paths):
    brain, memory, _, _ = make(paths)
    assert brain.hush() is False
    brain.hearing.spoke("A long story about the shed.", 5)
    assert brain.hush() is True
    assert brain.life.events_after(0)[-1]["type"] == "hush"
    assert not brain.hearing.speaking()
    memory.close()


def test_kit_knows_whether_he_can_hear(paths):
    brain, memory, _, _ = make(paths)
    assert "your ears aren't on" in brain._about_me("Dan")
    brain.hearing.report("desk")
    assert "You can hear the room through a microphone" in brain._about_me("Dan")
    brain.pause_hearing(True)
    assert "your ears aren't on" in brain._about_me("Dan")
    memory.close()


# --- over the API -------------------------------------------------------------


def test_the_ears_report_hear_and_hush_through_the_api(paths):
    brain, memory, _, store = make(paths, reply("Yes?"))
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as client:
        assert client.post("/api/hearing/report", json={}).status_code == 401
        answer = client.post("/api/hearing/report", json={"mic": "desk"}, headers=AUTH).json()
        assert answer["paused"] is False and answer["settings"]["names"][0] == "Kit"
        assert answer["speech"] == "" and answer["voices_version"] == 0
        status = client.get("/api/status", headers=AUTH).json()
        assert status["hearing"] == "listening (desk)" and status["hearing_paused"] is False
        heard = client.post(
            "/api/hearing/heard", json={"text": "Kit, you there?", "who": "Ghost"}, headers=AUTH
        ).json()
        assert heard["heard"] == "answer"
        lines = client.get(f"/api/hearing/turns/{heard['turn']}", headers=AUTH).text
        events = [json.loads(x) for x in lines.splitlines() if x.strip()]
        assert events[-1]["type"] == "reply"
        assert json.loads(memory.recent(5)[0].meta_json).get("speaker") is None  # not known
        assert client.get("/api/hearing/turns/999", headers=AUTH).status_code == 404
        assert client.post("/api/hearing/hush", headers=AUTH).json()["hushed"] is False
        assert client.get("/api/hearing", headers=AUTH).json()["last"]["why"] == "his name"
        client.post("/api/hearing/pause", json={"paused": True}, headers=AUTH)
        off = client.post("/api/hearing/heard", json={"text": "Kit?"}, headers=AUTH).json()
        assert off["why"] == "his ears are switched off"
        assert client.post("/api/hearing/report", json={}, headers=AUTH).json()["paused"]
    memory.close()


def test_voices_are_enrolled_and_forgotten_through_the_api(paths):
    brain, memory, _, store = make(paths)
    app = create_app(store, memory, brain, "t", summarise_every_s=None, paths=paths)
    with TestClient(app) as client:
        prints = [[0.1] * 512, [0.2] * 512]
        done = client.post(
            "/api/hearing/voices", json={"name": "sam", "embeddings": prints}, headers=AUTH
        ).json()
        assert done == {"name": "Sam", "count": 2, "version": 1}
        short = {"name": "Sam", "embeddings": [[0.1] * 128]}
        assert client.post("/api/hearing/voices", json=short, headers=AUTH).status_code == 422
        assert client.get("/api/hearing", headers=AUTH).json()["voices"] == {"Sam": 2}
        assert (paths.state_dir / "voices.json").is_file()
        gone = client.delete("/api/hearing/voices/sam", headers=AUTH).json()
        assert gone["forgot"] == "Sam"
        assert client.delete("/api/hearing/voices/sam", headers=AUTH).status_code == 404
    memory.close()


def test_his_voice_played_in_the_room_is_tracked_but_a_sample_is_not(paths, monkeypatch):
    from kit.speech.service import Spoken

    brain, memory, _, store = make(paths)
    store.update({"speech": {"enabled": True}}, "test")

    class FakeSpeech:
        quiet_s = staticmethod(lambda: 0.0)

        def speak(self, text, emotion, voice, first):
            return Spoken(b"RIFF", 10.0, 2500.0, "kokoro")

        def close(self):
            pass

    app = create_app(
        store, memory, brain, "t", summarise_every_s=None, life_every_s=None, speech=FakeSpeech()
    )
    with TestClient(app) as client:
        sample = {"text": "Hello, it's me.", "aloud": False}
        assert client.post("/api/speech/say", json=sample, headers=AUTH).status_code == 200
        assert not brain.hearing.speaking()
        said = {"text": "Rain's coming."}
        assert client.post("/api/speech/say", json=said, headers=AUTH).status_code == 200
        assert brain.hearing.speaking() and brain.hearing.last_line() == "Rain's coming."
        answer = client.post("/api/hearing/report", json={}, headers=AUTH).json()
        assert answer["speech"] == "kokoro"
    memory.close()


def test_hearing_settings_need_a_name():
    import pytest

    with pytest.raises(ValueError):
        Settings.model_validate({"hearing": {"names": [" "]}})
    assert Settings.model_validate({"hearing": {"names": [" Kit  "]}}).hearing.names == ["Kit"]
