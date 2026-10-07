"""Kit's own thoughts: having them, keeping them, sharing them, and the notebook API."""

import asyncio
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.memory import Memory
from kit.notebook import basis
from kit.pc_context import Snapshot
from kit.recall import Recall
from kit.server import create_app, life_tick
from kit.settings_store import SettingsStore
from kit.thinking import parse_thought, thinking_messages

AUTH = {"Authorization": "Bearer t"}


def thought(text="The pump curve looks off at low flow.", kind="thought", want="", feeling="same"):
    why = "the pump curve" if feeling != "same" else ""
    return json.dumps({"thought": text, "kind": kind, "want": want, "feeling": feeling, "why": why})


def snap():
    return Snapshot.model_validate(
        {"focus": {"app": "VS Code", "title": "pumps.py"}, "idle_seconds": 40}
    )


@pytest.fixture
def kit(paths):
    """A brain with fakes: call it with the local model's outputs."""
    made = []

    def make(*outputs):
        paths.ensure()
        store = SettingsStore(paths)
        memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-07T10:00:00"))
        model = FakeModel(*outputs)
        recall = Recall(memory, FakeEmbedder(), store.current)
        brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
        made.append(memory)
        return brain, model, store

    yield make
    for memory in made:
        memory.close()


def test_a_thought_goes_in_his_notebook_with_a_want_and_a_feeling(kit):
    brain, model, _ = kit(
        thought(
            "Dan's been in pumps.py for an hour. Bet it's the units again.",
            kind="opinion",
            want="Ask Dan if it's the units again.",
            feeling="amused",
        )
    )
    brain.pc.update(snap())
    had = asyncio.run(brain.think(("quiet", "A quiet moment.")))
    assert had.trigger == "quiet" and had.kind == "opinion"
    book = brain.notebook
    assert book.entries("opinion")[0].text.startswith("Dan's been in pumps.py")
    assert book.entries("opinion")[0].meta["trigger"] == "quiet"
    assert book.open_wants()[0].text == "Ask Dan if it's the units again."
    assert brain.life.wanting == pytest.approx(0.7)
    assert brain.life.feeling_now().name == "amused"
    assert any(e.get("gesture") == "look_up" for e in brain.life.events_after(0))
    system, user = model.calls[0][0]["content"], model.calls[0][1]["content"]
    assert "Kit's inner voice" in system and "nobody hears it" in system
    assert "A quiet moment." in user and 'VS Code: "pumps.py"' in user
    assert model.options[0] == {"temperature": 0.95, "min_p": 0.05}  # lively, still JSON
    assert len(brain.life.thoughts) == 1


def test_nothing_coming_to_mind_is_fine(kit):
    brain, _, _ = kit(thought(""))
    had = asyncio.run(brain.think())
    assert had.text == "" and brain.notebook.entries() == []
    assert len(brain.life.thoughts) == 1


def test_a_garbled_thought_or_a_model_thats_down_is_skipped(kit):
    brain, _, _ = kit("not json at all")
    assert asyncio.run(brain.think()) is None and brain.notebook.entries() == []
    brain.model.error = "Ollama isn't running"
    assert asyncio.run(brain.think()) is None
    assert len(brain.life.thoughts) == 2  # tried, so he doesn't hammer a model that's down


def test_his_recent_thoughts_are_in_the_thinking_prompt_so_he_doesnt_repeat_them(kit):
    brain, model, _ = kit(thought("Something new."))
    brain.notebook.write("thought", "Pumps again, always pumps.")
    asyncio.run(brain.think())
    user = model.calls[0][1]["content"]
    assert "On your mind lately (don't just repeat these):" in user
    assert "Pumps again, always pumps." in user


def test_reading_a_thought():
    assert parse_thought("[]", "quiet") is None
    got = parse_thought(json.dumps({"thought": " a  b ", "kind": "rant", "feeling": "x"}), "new")
    assert (got.text, got.kind, got.feeling, got.trigger) == ("a b", "thought", "", "new")


def test_the_thinking_prompt_keeps_to_what_he_knows():
    from datetime import datetime

    messages = thinking_messages(
        "Kit", "Dan", "I'm Kit.", ["you love puns"], "cheeky", datetime(2026, 10, 7, 9, 5),
        "A quiet moment.", "", "content", [], ["Dan likes metric units."], [],
    )  # fmt: skip
    system, user = messages[0]["content"], messages[1]["content"]
    assert "never invent facts about Dan" in system and "His quirks: you love puns." in system
    assert "You can't see Dan's PC right now." in user
    assert "- Dan likes metric units." in user and "Said today" not in user


def test_asked_what_hes_thinking_he_tells_his_real_thoughts(kit):
    brain, model, _ = kit(reply("Been wondering about that pump curve, actually."))
    note = brain.notebook.write("thought", "The pump curve looks off at low flow.")
    collect(brain.chat("What are you thinking about?"))
    asked = model.calls[0][-1]["content"]
    assert "These are your actual recent thoughts" in asked
    assert "The pump curve looks off at low flow." in asked
    assert brain.notebook.index.get(note).meta["said"]


def test_with_nothing_on_his_mind_he_says_so(kit):
    brain, model, _ = kit(reply("Honestly? Not much. Just watching the cursor."))
    collect(brain.chat("What's on your mind?"))
    assert "Nothing much has been, lately" in model.calls[0][-1]["content"]


async def tick_with(brain, reason):
    brain.life.tick = lambda: reason
    await life_tick(brain)


def test_a_restless_kit_brings_up_what_he_wanted_to_say(kit):
    brain, model, _ = kit(reply("Oi, did the cyclone pump pass its test?"))
    brain.pc.update(snap())
    want = brain.notebook.write("want", "Ask Dan whether the cyclone pump passed its test.")
    brain.life.wanting = brain.notebook.pressing()
    asyncio.run(tick_with(brain, "want"))
    prompt = model.calls[0][-1]["content"]
    assert "You've been wanting to say or ask this" in prompt and "cyclone pump" in prompt
    assert brain.notebook.index.get(want).meta["said"]
    assert brain.life.wanting == 0.0
    assert brain.life.events_after(0)[-1]["reason"] == "want"


def test_asked_to_ask_tomorrow_he_asks_next_morning_and_only_once(kit):
    brain, model, _ = kit(
        reply("Will do. Fingers crossed for it."),
        reply("Morning! So, how did the shutdown go?"),
        reply("Ha. Glad it's over."),
    )
    collect(brain.chat("Ask me tomorrow how the shutdown went."))
    book = brain.notebook
    want = book.unsaid_wants()[0]
    assert want.text == 'Dan said: "Ask me tomorrow how the shutdown went."'
    assert want.meta["after"] == "2026-10-08T07:00:00"
    assert book.open_wants() == []  # not today
    brain.memory.clock.now += timedelta(hours=22)  # 08:00 the next morning
    brain.pc.update(snap())
    asyncio.run(tick_with(brain, "want"))
    prompt = model.calls[1][-1]["content"]
    assert "You've been wanting to say or ask this" in prompt and "shutdown went" in prompt
    assert book.index.get(want.id).meta["said"] and book.open_wants() == []
    collect(brain.chat("It went fine, mostly."))
    assert "(you want to bring this up)" not in model.calls[2][0]["content"]


def test_a_thought_for_tomorrow_waits_till_the_morning(kit):
    brain, _, _ = kit(thought(want="Tomorrow, ask Dan how the shutdown went."))
    asyncio.run(brain.think(("chat_ended", "You and Dan were chatting until just now.")))
    want = brain.notebook.unsaid_wants()[0]
    assert want.meta["after"] == "2026-10-08T07:00:00" and brain.life.wanting == 0.0


def test_a_want_he_brings_up_in_a_chat_isnt_asked_again(kit):
    brain, model, _ = kit(reply("Morning! How did the shutdown go, by the way?"))
    want = brain.notebook.write("want", "Ask Dan how the shutdown went.")
    collect(brain.chat("Morning Kit"))
    system = model.calls[0][0]["content"]
    assert "(you want to bring this up) Ask Dan how the shutdown went." in system
    assert brain.notebook.index.get(want).meta["said"]


def test_a_bored_kit_shares_a_fresh_thought(kit):
    brain, model, _ = kit(reply("I've decided hydrocyclones are elegant."))
    brain.pc.update(snap())
    brain.notebook.write("opinion", "Not shared: opinions are for when they fit.")
    note = brain.notebook.write("thought", "Hydrocyclones are weirdly elegant.")
    asyncio.run(tick_with(brain, "bored"))
    prompt = model.calls[0][-1]["content"]
    assert 'You were just thinking: "Hydrocyclones are weirdly elegant."' in prompt
    assert brain.notebook.index.get(note).meta["said"]


def test_a_want_dropped_meanwhile_leaves_him_just_bored(kit):
    brain, model, _ = kit(reply("Quiet in here."))
    brain.pc.update(snap())
    asyncio.run(tick_with(brain, "want"))
    prompt = model.calls[0][-1]["content"]
    assert "bored" in prompt and "wanting to say" not in prompt


def test_the_heartbeat_thinks_when_he_wont_pipe_up_but_never_mid_chat(kit):
    brain, model, _ = kit(thought("A heartbeat thought."))
    brain.life.think_now = lambda: ("quiet", "A quiet moment.")
    brain.talking = lambda: True
    asyncio.run(tick_with(brain, None))
    assert model.calls == []
    brain.talking = lambda: False
    asyncio.run(tick_with(brain, None))
    assert brain.notebook.entries("thought")[0].text == "A heartbeat thought."


def test_what_dan_says_changes_how_kit_feels(kit):
    brain, model, _ = kit(reply("Stop it, you'll make me blush.", emotion="shy"))
    collect(brain.chat("You're a legend, Kit"))
    felt = brain.life.feeling_now()
    assert felt.name == "chuffed" and felt.why == 'Dan said "You\'re a legend, Kit"'
    assert "chuffed, because Dan said" in model.calls[0][0]["content"]


def test_a_strong_feeling_in_his_reply_lingers_a_little(kit):
    brain, _, _ = kit(reply("Oh no. I'm sorry about Biscuit.", emotion="sad"))
    collect(brain.chat("Biscuit is at the vet"))
    felt = brain.life.feeling_now()
    assert felt.name == "sad" and felt.strength == pytest.approx(0.4)


def test_his_self_sheet_replaces_the_traits_until_dan_changes_them(kit):
    brain, model, store = kit(reply("Hi."), reply("Hi again."))
    traits = store.current().persona.traits
    brain.notebook.set_sheet("I'm Kit and I love a good pump curve.", basis(traits))
    collect(brain.chat("hi"))
    system = model.calls[0][0]["content"]
    assert "Who you are, in your own words" in system and "good pump curve" in system
    assert "Your traits:" not in system
    store.update({"persona": {"traits": ["grumpy", "loyal", "nosy"]}}, "test")
    collect(brain.chat("hello again"))
    system = model.calls[1][0]["content"]
    assert "Your traits: grumpy, loyal, nosy." in system and "good pump curve" in system


def test_his_own_notes_are_recalled_like_memories(kit):
    brain, model, store = kit(reply("I reckon hydrocyclones are elegant."), reply("Still do."))
    store.update({"memory": {"min_similarity": 0.3}}, "test")
    brain.notebook.write("opinion", "Hydrocyclones are the most elegant machines ever made.")
    brain.memory.clock.now += timedelta(hours=13)  # yesterday's: no longer on his mind
    asyncio.run(brain.recall.index_pending())
    collect(brain.chat("What do you think of hydrocyclones?"))
    system = model.calls[0][0]["content"]
    assert "From your own notebook" in system and "most elegant machines" in system
    brain.notebook.write("opinion", "Hydrocyclones beat pumps, honestly.")
    asyncio.run(brain.recall.index_pending())
    collect(brain.chat("Hydrocyclones again?"))
    system = model.calls[1][0]["content"]
    assert system.count("Hydrocyclones beat pumps") == 1  # on his mind, so not recalled too


def test_the_notebook_api(kit):
    brain, model, store = kit(thought("A thought on demand."))
    app = create_app(store, brain.memory, brain, "t", summarise_every_s=None, life_every_s=None)
    book = brain.notebook
    first = book.set_sheet("I'm Kit.", "b")
    book.set_sheet("I'm Kit, cheekier.", "b")
    want = book.write("want", "Ask Dan about lunch.")
    book.write("opinion", "Pumps are underrated.")
    book.set_quirks(["you love puns", "you count tabs"])
    with TestClient(app) as client:
        got = client.get("/api/life/notebook", headers=AUTH).json()
        assert got["sheet"]["text"] == "I'm Kit, cheekier."
        assert got["sheet_history"][0]["id"] == first
        assert got["wants"][0]["pressure"] == 0.7 and got["opinions"][0]["text"]
        state = client.get("/api/life", headers=AUTH).json()
        assert state["wants"] == ["Ask Dan about lunch."] and "wanting" in state
        back = client.post("/api/life/sheet/restore", json={"id": first}, headers=AUTH)
        assert back.json()["text"] == "I'm Kit." and book.sheet().text == "I'm Kit."
        missing = client.post("/api/life/sheet/restore", json={"id": 999}, headers=AUTH)
        assert missing.status_code == 404
        quirks = client.post(
            "/api/life/quirks/retire", json={"quirk": "you count tabs"}, headers=AUTH
        )
        assert quirks.json()["quirks"] == ["you love puns"]
        assert quirks.json()["retired_quirks"][-1]["by"] == "owner"
        nope = client.post("/api/life/quirks/retire", json={"quirk": "nope"}, headers=AUTH)
        assert nope.status_code == 404
        again = client.post(
            "/api/life/quirks/restore", json={"quirk": "you count tabs"}, headers=AUTH
        )
        assert "you count tabs" in again.json()["quirks"]
        assert client.delete(f"/api/life/notebook/{want}", headers=AUTH).json() == {"ok": True}
        assert client.delete(f"/api/life/notebook/{want}", headers=AUTH).status_code == 404
        had = client.post("/api/life/think", headers=AUTH).json()["thought"]
        assert had["text"] == "A thought on demand."
        hits = client.get("/api/memory/search?q=pumps underrated", headers=AUTH).json()["hits"]
        assert any(h["source"] == "self" for h in hits)
        store.update({"life": {"reflect_with": "off"}}, "test")
        assert client.post("/api/life/reflect", headers=AUTH).status_code == 409


def test_reflecting_now_from_the_api(kit):
    reflection = json.dumps(
        {
            "journal": "Dan and I talked pumps.",
            "self_sheet": "I'm Kit. Pumps are my thing.",
            "quirks": [],
            "opinions": [],
            "moments": [],
            "wants": [],
        }
    )
    sheet = json.dumps({"self_sheet": "I'm Kit."})
    brain, _, store = kit(reply("Morning!"), sheet, reflection)
    store.update({"life": {"reflect_with": "local"}}, "test")
    collect(brain.chat("Morning"))
    app = create_app(store, brain.memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as client:
        done = client.post("/api/life/reflect", headers=AUTH).json()
    assert done["first_sheet"] and done["journal"] == "Dan and I talked pumps."
    assert done["sheet"] == "I'm Kit. Pumps are my thing."
    assert brain.notebook.journal("2026-10-07").text == "Dan and I talked pumps."
