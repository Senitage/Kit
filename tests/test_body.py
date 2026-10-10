"""Robot bodies (kit.body): the plain-text feed the Pod reads, and pats."""

import pytest
from fastapi.testclient import TestClient

from fakes import reply
from kit import body
from kit.server import create_app
from test_life import make_brain

AUTH = {"Authorization": "Bearer t"}


@pytest.fixture
def setup(paths):
    said = reply("Hi Dan, good to see you.", emotion="happy")
    brain, memory, _, store = make_brain(paths, said)
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as client:
        yield client, brain
    memory.close()


def lines(text):
    return dict(line.split(" ", 1) for line in text.splitlines() if " " in line) | {
        "all": text.splitlines()
    }


def test_a_new_body_gets_kits_state_now_without_old_events(setup):
    client, brain = setup
    brain.life.publish({"type": "fidget", "gesture": "yawn"})
    r = client.get("/api/body/feed", headers=AUTH)
    assert r.headers["content-type"].startswith("text/plain")
    got = lines(r.text)
    assert got["face"] == brain.life.face() and got["asleep"] == "0"
    assert 0 <= float(got["energy"]) <= 1 and got["last"] == "1"
    assert not any(x.startswith("fidget") for x in got["all"])


def test_a_chat_reaches_the_body_as_thinking_an_emotion_and_talking(setup):
    client, brain = setup
    last = lines(client.get("/api/body/feed", headers=AUTH).text)["last"]
    client.post("/api/chat", json={"text": "hi"}, headers=AUTH)
    got = lines(client.get(f"/api/body/feed?after={last}&wait=0", headers=AUTH).text)["all"]
    moments = [x for x in got if x.split()[0] in {"talk", "emotion"}]
    assert moments[0] == "talk thinking" and "emotion happy" in moments
    assert any(x.startswith("talk speaking ") for x in moments) and moments[-1] == "talk done"
    assert got.count("emotion happy") == 1  # said once, though the reply carries it too


def test_fidgets_and_reactions_are_told_apart(setup):
    client, brain = setup
    last = brain.life.publish({"type": "doing", "what": ""})
    brain.life.publish({"type": "fidget", "gesture": "sigh"})
    brain.life.react("perk_up", "Dan's back")
    got = lines(client.get(f"/api/body/feed?after={last}&wait=0", headers=AUTH).text)["all"]
    assert "fidget sigh" in got and "gesture perk_up" in got
    assert not any(x.startswith("doing") for x in got)  # things a body can't show are left out


def test_where_his_eyes_see_you_and_his_pipe_ups_reach_the_body(setup):
    client, brain = setup
    last = brain.life.publish({"type": "doing", "what": ""})
    brain.life.publish({"type": "look", "x": -0.4, "y": 0.125})
    said = {"emotion": "curious", "segments": [{"say": "What are you up to?"}]}
    brain.life.publish({"type": "pipe_up", "reason": "bored", "reply": said})
    got = lines(client.get(f"/api/body/feed?after={last}&wait=0", headers=AUTH).text)["all"]
    assert "look -0.40 0.12" in got
    assert "emotion curious" in got and "talk speaking 1.9" in got


def test_a_pat_makes_kit_feel_warm(setup):
    client, brain = setup
    assert client.post("/api/body/touch", headers=AUTH).json() == {"ok": True}
    assert brain.life.feeling_now().name == "warm"
    assert not [e for e in brain.life.events_after(0) if e.get("gesture")]


def test_feed_needs_the_token(setup):
    client, _ = setup
    assert client.get("/api/body/feed?wait=0").status_code == 401


def test_talk_time_follows_the_words():
    assert body.talk_seconds("hi") == body.TALK_MIN_S
    assert body.talk_seconds("word " * 13) == 5.0
    assert body.talk_seconds("word " * 500) == body.TALK_MAX_S
