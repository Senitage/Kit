"""Who can hear Kit (kit.audience): out loud he talks to anyone in the room by name,
on a screen only Dan reads him, and a message can say who sent it."""

import json

import pytest
from fastapi.testclient import TestClient

from fakes import collect, reply
from kit import audience
from kit.scene_context import SceneReport, SeenObject, SeenPerson
from kit.server import create_app
from test_life import make_brain

AUTH = {"Authorization": "Bearer t"}


def person(name=None, x=0.5):
    return SeenPerson(id=1, name=name, box=[x - 0.1, 0.2, x + 0.1, 0.9])


def cat(name=None, x=0.8):
    return SeenObject(id=9, label="cat", name=name, box=[x - 0.05, 0.6, x + 0.05, 0.8])


def see(brain, people=(), objects=()):
    brain.scene.update(SceneReport(people=list(people), objects=list(objects)))


def system(model, call=0):
    return model.calls[call][0]["content"]


def test_out_loud_kit_talks_to_whoever_is_in_the_room():
    line = audience.audience_line("pod", "Dan", room=["Dan", "Sam", "Milo"])
    assert "out loud" in line and "Sam and Milo" in line and "Hi Sam!" in line
    assert "Dan" not in line.split("Also in the room:")[1].split(".")[0]


def test_on_a_screen_others_get_greetings_through_dan():
    line = audience.audience_line("desk", "Dan", room=["Dan", "Sam"])
    assert "Only Dan reads" in line and "pass it on" in line and "With Dan now: Sam" in line
    assert "out loud" not in line


def test_a_message_from_someone_else_says_so():
    assert "from Sam, not Dan" in audience.audience_line("voice", "Dan", "Sam")
    assert "not Dan" not in audience.audience_line("voice", "Dan", "Dan")


@pytest.mark.parametrize(
    "said, who",
    [
        ("Hi Sam! Good to see you.", "Sam"),
        ("Hey there Sam, how's it going?", "Sam"),
        ("Milo, you'd better not eat me.", "Milo"),
        ("You'd better not eat me, Milo!", "Milo"),
        ("Dan, tell Sam I said hello.", "Dan"),
        ("I reckon Sam would like this.", ""),
        ("Nice one. Hi Sam.", ""),  # only the opening sentence counts
    ],
)
def test_who_his_words_are_for(said, who):
    assert audience.addressed(said, ["Dan", "Sam", "Milo"]) == who


def test_a_pet_is_named_when_its_the_only_one_of_its_kind():
    pets = [("Milo", "our grey cat"), ("Rex", "a dog"), ("Bo", "dog, brown")]
    assert audience.pets_by_kind(pets) == {"cat": "Milo"}


def test_the_prompt_says_who_is_in_the_room_and_out_loud(paths):
    brain, memory, model, _ = make_brain(paths, reply("Hi Sam!"), reply("Tell Sam hi."))
    brain.register.add("Milo", "pet", about="the house cat")
    see(brain, [person("Dan", 0.3), person("Sam", 0.7)], [cat()])
    collect(brain.chat("say hi to everyone", "pod"))
    assert "Also in the room: Sam and Milo" in system(model)
    collect(brain.chat("say hi to Sam", "desk"))
    assert "Only Dan reads" in system(model, 1)
    memory.close()


def test_a_message_from_someone_else_is_kept_and_shown_as_theirs(paths):
    brain, memory, model, _ = make_brain(paths, reply("Hi Sam!"), reply("Hey Dan."))
    collect(brain.chat("hello Kit", "voice", speaker="Sam"))
    assert "This message is from Sam, not Dan" in system(model)
    assert json.loads(memory.recent(2)[0].meta_json) == {"speaker": "Sam"}
    collect(brain.chat("who was that?", "voice"))
    past = [m["content"] for m in model.calls[1] if m["role"] == "user"]
    assert any(x.startswith("(Sam said) hello Kit") for x in past)
    memory.close()


def test_out_loud_the_one_person_his_eyes_know_is_who_spoke(paths):
    brain, memory, model, _ = make_brain(paths, reply("Hi Sam!"), reply("Hi."), reply("Hi."))
    see(brain, [person("Sam")])
    collect(brain.chat("hello", "pod"))
    assert "from Sam, not Dan" in system(model)
    collect(brain.chat("hello", "desk"))  # typed on Dan's PC: that's Dan
    assert "This message is from" not in system(model, 1)
    see(brain, [person("Sam"), person()])  # someone else is there too: can't tell
    collect(brain.chat("hello", "pod"))
    assert "This message is from" not in system(model, 2)
    memory.close()


def test_a_body_turns_to_whoever_kit_greets(paths):
    brain, memory, _, store = make_brain(paths, reply("Milo, you'd better not eat me."))
    brain.register.add("Milo", "pet", about="cat")
    see(brain, [person("Dan", 0.5)], [cat(x=0.9)])
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as client:
        last = client.get("/api/body/feed", headers=AUTH).text.split()[-1]
        client.post("/api/chat", json={"text": "the cat's here", "channel": "pod"}, headers=AUTH)
        got = client.get(f"/api/body/feed?after={last}&wait=0", headers=AUTH).text
    turns = [x for x in got.splitlines() if x.startswith("turn_to")]
    assert turns == ["turn_to 0.80 0.26"]  # the cat, off to the right
    memory.close()
