import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.cli import main
from kit.evals import (
    ROUTING_QUESTIONS,
    load_routing_questions,
    run_routing_eval,
    seed_routing_things,
)
from kit.memory import Memory
from kit.prompt import system_prompt
from kit.recall import Recall
from kit.server import create_app
from kit.settings import PersonaSettings, Settings
from kit.settings_store import SettingsStore
from kit.things import THINGS, Link, Register

AUTH = {"Authorization": "Bearer t"}


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def settings():
    return Settings.model_validate({"memory": {"min_similarity": 0.3}})


def thing_reply(name, kind="other", system="none", target="", say="Got it."):
    return json.dumps(
        {
            "emotion": "neutral",
            "segments": [{"say": say, "gesture": "nod"}],
            "action": {
                "kind": "thing",
                "text": name,
                "thing_kind": kind,
                "link_system": system,
                "link_target": target,
            },
        }
    )


def make_brain(memory, *outputs):
    s = settings()
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    return Brain(lambda: s, memory, model, make_cloud(memory, key="k"), recall), model


# The register


def test_add_find_and_mention(memory):
    reg = Register(memory)
    hilux = reg.add("Hilux", "vehicle", ["the ute"], [{"system": "nas", "target": "Cars/Hilux"}])
    assert reg.named("THE UTE").id == hilux
    assert [t.name for t in reg.mentioned_in("When's the ute due?")] == ["Hilux"]
    assert reg.mentioned_in("Hiluxes are great") == []  # whole words only
    assert (
        reg.get(hilux).line() == "Hilux (vehicle; also called the ute). Lives in: NAS: Cars/Hilux"
    )


def test_adding_a_known_name_merges(memory):
    reg = Register(memory)
    first = reg.add("Hilux", "vehicle", links=[{"system": "nas", "target": "Cars"}])
    second = reg.add("hilux", aliases=["ute"], links=[{"system": "home_app", "target": "v/1"}])
    assert second != first and len(reg.all()) == 1
    thing = reg.get(second)
    assert thing.aliases == ["ute"] and len(thing.links) == 2
    assert reg.get(first) is None and len(reg.history(second)) == 2


def test_correction_replaces_the_link_for_that_system(memory):
    reg = Register(memory)
    tax = reg.add("Tax", links=[{"system": "nas", "target": "Finance/Tax"}])
    new = reg.set_link(tax, "nas", "Tax/2023")
    assert reg.get(new).links == [Link("nas", "Tax/2023")]
    assert reg.history(new)[1].links == [Link("nas", "Finance/Tax")]


def test_suggest_confirm_reject(memory):
    reg = Register(memory)
    s = reg.suggest("Biscuit", "pet")
    assert s.suggested and reg.all() == [] and reg.mentioned_in("Biscuit") == []
    again = reg.suggest("biscuit", links=[{"system": "nas", "target": "Photos/Biscuit"}])
    assert len(reg.suggestions()) == 1 and again.links
    entry = reg.confirm(again.id)
    assert reg.suggestions() == [] and reg.get(entry).name == "Biscuit"
    assert reg.confirm(entry) is None  # only suggestions can be confirmed
    other = reg.suggest("Bob")
    assert reg.reject(other.id) and reg.suggestions() == []
    assert reg.forget(entry) and reg.all() == []


def test_unknown_systems_and_kinds_are_tidied(memory):
    reg = Register(memory)
    t = reg.get(reg.add("X", "spaceship", links=[{"system": "dropbox", "target": " a "}]))
    assert t.kind == "other" and t.links == [Link("other", "a")]


# Recall and the prompt


def test_recall_brings_named_things_then_close_ones(memory):
    reg = Register(memory)
    reg.add("Hilux", "vehicle", ["the ute"], [{"system": "nas", "target": "Cars/Hilux"}])
    reg.add("Tax returns", about="receipts and returns", links=[{"system": "nas", "target": "Tax"}])
    recall = Recall(memory, FakeEmbedder(), settings)
    asyncio.run(recall.index_pending())
    got = asyncio.run(recall.for_turn("Is the ute registered?", set()))
    assert got.things[0].name == "Hilux"
    got = asyncio.run(recall.for_turn("where are my receipts", set()))
    assert [t.name for t in got.things] == ["Tax returns"]
    system = system_prompt(PersonaSettings(), got, Clock()())
    assert "Things you know and where they live" in system and "NAS: Tax" in system


def test_things_can_be_turned_off(memory):
    Register(memory).add("Hilux")
    s = Settings.model_validate({"memory": {"relevant_things": 0}})
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    assert asyncio.run(recall.for_turn("Hilux", set())).things == []


# Chat


def test_new_name_is_suggested_then_confirmed_with_yes(memory):
    brain, model = make_brain(
        memory, thing_reply("Biscuit", "pet", "nas", "Photos/Biscuit", "Cute name.")
    )
    events = collect(brain.chat("We got a puppy called Biscuit"))
    suggested = next(e for e in events if e["type"] == "thing_suggested")
    assert suggested["thing"]["name"] == "Biscuit" and suggested["thing"]["suggested"]
    calls = len(model.calls)
    events = collect(brain.chat("Yes please."))
    assert len(model.calls) == calls  # answered without a model
    assert "Biscuit is in the register" in events[-1]["reply"]["segments"][0]["say"]
    reg = Register(memory)
    assert reg.named("Biscuit").links == [Link("nas", "Photos/Biscuit")]
    # Asked another way later, the entry and its link come back.
    collect(brain.chat("show me photos of Biscuit"))
    assert "NAS: Photos/Biscuit" in model.calls[-1][0]["content"]


def test_no_drops_the_suggestion(memory):
    brain, _ = make_brain(memory, thing_reply("Bob", "person"))
    collect(brain.chat("Bob from work called"))
    events = collect(brain.chat("nah"))
    assert "leave Bob out" in events[-1]["reply"]["segments"][0]["say"]
    assert Register(memory).suggestions() == []


@pytest.mark.parametrize("text", ["ok, open VS Code", "yes it is in the shed", "no idea"])
def test_a_longer_message_is_not_an_answer(memory, text):
    brain, model = make_brain(memory, thing_reply("Bob", "person"), reply("Sure."))
    collect(brain.chat("Bob from work called"))
    collect(brain.chat(text))
    assert len(model.calls) == 2 and len(Register(memory).suggestions()) == 1


def test_anything_else_leaves_the_suggestion_waiting(memory):
    brain, model = make_brain(memory, thing_reply("Bob", "person"), reply("Sure."))
    collect(brain.chat("Bob from work called"))
    collect(brain.chat("what time is it in Perth?"))
    assert len(model.calls) == 2 and len(Register(memory).suggestions()) == 1
    collect(brain.chat("yes"))  # too late: no longer an answer to the suggestion
    assert len(model.calls) == 3 and Register(memory).all() == []


def test_correction_updates_a_known_thing(memory):
    reg = Register(memory)
    reg.add("Tax returns", aliases=["tax"], links=[{"system": "nas", "target": "Finance/Tax"}])
    brain, _ = make_brain(memory, thing_reply("tax", "other", "nas", "Tax/2023", "Noted."))
    events = collect(brain.chat("no, it's in Tax/2023"))
    updated = next(e for e in events if e["type"] == "thing_updated")
    assert updated["thing"]["links"] == [{"system": "nas", "target": "Tax/2023"}]
    assert reg.named("Tax returns").links == [Link("nas", "Tax/2023")]
    assert not reg.suggestions()


# Pages and API


@pytest.fixture
def client(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, None, store.current)  # words only
    brain = Brain(store.current, memory, FakeModel(), make_cloud(memory, key="k"), recall)
    with TestClient(create_app(store, memory, brain, "t", summarise_every_s=None)) as c:
        yield c, memory
    memory.close()


def test_things_api(client):
    c, memory = client
    body = {"name": "Hilux", "kind": "vehicle", "links": [{"system": "nas", "target": "Cars"}]}
    hilux = c.post("/api/things", json=body, headers=AUTH).json()
    assert hilux["line"].startswith("Hilux (vehicle)")
    assert [t["name"] for t in c.get("/api/things", headers=AUTH).json()] == ["Hilux"]
    edited = c.patch(f"/api/things/{hilux['id']}", json={"aliases": ["ute"]}, headers=AUTH).json()
    assert edited["aliases"] == ["ute"] and edited["links"] == body["links"]
    history = c.get(f"/api/things/{edited['id']}/history", headers=AUTH).json()
    assert len(history) == 2
    hits = c.get("/api/memory/search?q=ute", headers=AUTH).json()["hits"]
    assert hits[0]["source"] == THINGS

    s = Register(memory).suggest("Biscuit", "pet")
    assert [t["id"] for t in c.get("/api/things/suggestions", headers=AUTH).json()] == [s.id]
    assert c.post(f"/api/things/{s.id}/confirm", headers=AUTH).json()["name"] == "Biscuit"
    assert c.post(f"/api/things/{s.id}/confirm", headers=AUTH).status_code == 404
    s = Register(memory).suggest("Bob")
    assert c.post(f"/api/things/{s.id}/reject", headers=AUTH).json() == {"ok": True}
    assert c.delete(f"/api/things/{edited['id']}", headers=AUTH).json() == {"ok": True}
    assert c.delete(f"/api/things/{edited['id']}", headers=AUTH).status_code == 404
    assert c.patch("/api/things/999", json={}, headers=AUTH).status_code == 404
    assert c.get("/api/things", headers={}).status_code == 401
    assert "Things and where they live" in c.get("/memory").text


# CLI


def test_things_commands(paths, capsys):
    assert main(["things", "list"]) == 0
    assert "empty" in capsys.readouterr().out
    main(["things", "add", "Hilux", "--kind", "vehicle", "--alias", "ute", "--link", "nas=Cars"])
    out = capsys.readouterr().out
    assert "Hilux (vehicle; also called ute)" in out and "NAS: Cars" in out
    thing_id = int(out.split()[0])
    assert main(["things", "link", str(thing_id), "home_app", "vehicles/1"]) == 0
    new_id = int(capsys.readouterr().out.split()[0])
    main(["things", "history", str(new_id)])
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert main(["things", "link", "999", "nas", "x"]) == 1
    assert main(["things", "confirm", str(new_id)]) == 1
    assert main(["things", "forget", str(new_id)]) == 0
    with pytest.raises(SystemExit):
        main(["things", "add", "X", "--link", "nolink"])


# Routing eval


def test_routing_eval_passes_offline(memory):
    seed_routing_things(Register(memory))
    recall = Recall(memory, None, settings)
    report = asyncio.run(run_routing_eval(recall))
    missed = [r.question for r in report.results if not r.ok]
    assert missed == [] and report.score == len(ROUTING_QUESTIONS)


def test_routing_eval_reports_a_miss(memory):
    recall = Recall(memory, None, settings)
    report = asyncio.run(run_routing_eval(recall, [("Find my tax", "nas", "Tax")]))
    assert not report.passed and report.results[0].got == []


def test_own_routing_questions_file(tmp_path):
    f = tmp_path / "routing-questions.toml"
    f.write_text('[[question]]\ntext = "Find my tax"\nsystem = "nas"\ntarget = "Tax/2023"\n')
    assert load_routing_questions(f) == [("Find my tax", "nas", "Tax/2023")]


def test_eval_routing_command(paths, capsys, monkeypatch):
    import kit.embed

    monkeypatch.setattr(kit.embed, "OllamaEmbedder", lambda settings, client: None)
    paths.ensure()
    Register(Memory(paths.state_dir / "memory.db")).add(
        "Tax returns", aliases=["tax"], links=[{"system": "nas", "target": "Tax/2023"}]
    )
    (paths.config_dir / "routing-questions.toml").write_text(
        '[[question]]\ntext = "Find my tax"\nsystem = "nas"\ntarget = "Tax/2023"\n'
    )
    assert main(["eval", "routing"]) == 0
    out = capsys.readouterr().out
    assert f"knew where to look: {len(ROUTING_QUESTIONS)}/{len(ROUTING_QUESTIONS)}" in out
    assert "your questions" in out and "knew where to look: 1/1" in out
    assert not (paths.state_dir / "routing-eval").exists()
