"""The morning brief: once a day, at the desk or in his first answer."""

import asyncio
import random
from datetime import datetime

import pytest
from pydantic import ValidationError

from fakes import Clock, FakeEmbedder, FakeModel, collect, make_cloud, reply
from kit.brain import Brain
from kit.brief import (
    DESK_TRIES,
    Brief,
    Part,
    asked_about,
    brief_aside,
    brief_prompt,
    follow_up_aside,
)
from kit.life import Life
from kit.memory import Memory
from kit.pc_context import PcContext, Snapshot
from kit.recall import Recall
from kit.settings import Settings
from kit.settings_store import SettingsStore

WEATHER = "Weather in Richmond: sunny, top of 27°C."
BILL = "Electricity bill $212 due 2026-10-06."


def sources(**changes):
    async def weather(now):
        return WEATHER

    async def tasks(now):
        return ""  # nothing due: left out

    async def bills(now):
        return BILL

    async def house(now):
        raise ConnectionError("Home Assistant is down")  # left out too

    found = {"weather": weather, "tasks": tasks, "bills": bills, "house": house}
    found.update(changes)
    return found


def setup(paths, when="2026-10-05T08:00:00", **brief):
    paths.ensure()
    clock = Clock(when)
    memory = Memory(paths.state_dir / "memory.db", clock)
    s = Settings.model_validate({"brief": {"enabled": True, **brief}})
    return Brief(memory, lambda: s, sources()), memory, clock


def test_the_parts_that_have_something_are_gathered_in_order(paths):
    b, memory, clock = setup(paths)
    parts = asyncio.run(b.prepare(clock()))
    assert parts == [Part("weather", WEATHER), Part("bills", BILL)]
    assert b.status(clock()) == {"enabled": True, "given": None, "parts": ["weather", "bills"]}
    memory.close()


def test_it_is_only_due_in_its_window_and_only_when_turned_on(paths):
    b, memory, clock = setup(paths, when="2026-10-05T06:59:00")
    assert asyncio.run(b.prepare(clock())) == []  # before brief.after
    clock.now = datetime.fromisoformat("2026-10-05T11:00:00")
    assert asyncio.run(b.prepare(clock())) == []  # brief.until has passed
    clock.now = datetime.fromisoformat("2026-10-05T07:00:00")
    assert asyncio.run(b.prepare(clock()))
    off = Brief(memory, lambda: Settings(), sources())
    assert asyncio.run(off.prepare(clock())) == []  # off unless Dan turns it on
    memory.close()


def test_once_given_it_is_not_given_again_until_tomorrow(paths):
    b, memory, clock = setup(paths)
    asyncio.run(b.prepare(clock()))
    b.mark_given(clock(), "desk")
    assert b.ready(clock()) == [] and b.for_desk(clock()) == []
    assert b.today(clock())[0].text == WEATHER  # kept for "the first one"
    assert b.status(clock())["given"] == "desk"
    clock.now = datetime.fromisoformat("2026-10-06T08:00:00")
    assert b.today(clock()) == []  # a new day
    assert asyncio.run(b.prepare(clock()))
    memory.close()


def test_the_desk_tries_twice_then_leaves_it_for_his_next_answer(paths):
    b, memory, clock = setup(paths)
    asyncio.run(b.prepare(clock()))
    for _ in range(DESK_TRIES):
        assert b.for_desk(clock())
        b.tried(clock())
    assert b.for_desk(clock()) == []
    assert b.ready(clock())  # still there for the reply aside
    memory.close()


def test_with_nothing_to_say_there_is_no_brief(paths):
    b, memory, clock = setup(paths, parts=["tasks", "house"])
    assert asyncio.run(b.prepare(clock())) == []
    memory.close()


def test_stale_parts_are_gathered_again(paths):
    b, memory, clock = setup(paths)
    asyncio.run(b.prepare(clock()))
    calls = []

    async def weather(now):
        calls.append(now)
        return "Weather in Richmond: rain."

    b.sources["weather"] = weather
    asyncio.run(b.prepare(clock()))
    assert calls == []  # fresh enough
    clock.now = datetime.fromisoformat("2026-10-05T08:31:00")
    assert asyncio.run(b.prepare(clock()))[0].text == "Weather in Richmond: rain."
    memory.close()


def test_the_prompt_and_asides_carry_the_parts_and_the_shape():
    parts = [Part("weather", WEATHER), Part("bills", BILL)]
    prompt = brief_prompt("Dan", parts, "Short and dry.")
    assert prompt.startswith("[Not from Dan.") and f"1. {WEATHER} 2. {BILL}" in prompt
    assert "two to four sentences" in prompt and "one thing about the day" in prompt
    assert "Short and dry." in prompt
    assert "first chat this morning" in brief_aside("Dan", parts) and BILL in brief_aside(
        "Dan", parts
    )
    assert asked_about("tell me more about the second one", parts) == parts[1]
    assert asked_about("what was the last thing?", parts) == parts[1]
    assert asked_about("number one?", parts) == parts[0]
    assert asked_about("the fifth one", parts) is None
    assert asked_about("what's for lunch", parts) is None
    assert f'Dan means "{BILL}"' in follow_up_aside("Dan", parts, parts[1])


def test_settings_check_the_parts_and_times():
    with pytest.raises(ValidationError):
        Settings.model_validate({"brief": {"parts": ["weather", "horoscope"]}})
    with pytest.raises(ValidationError):
        Settings.model_validate({"brief": {"after": "7am"}})
    assert Settings().brief.enabled is False


# In the brain


def make_brain(paths, *outputs, **brief):
    paths.ensure()
    store = SettingsStore(paths)
    store.update({"brief": {"enabled": True, **brief}}, "test")
    memory = Memory(paths.state_dir / "memory.db", Clock("2026-10-05T08:00:00"))
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), store.current)
    brain = Brain(store.current, memory, model, make_cloud(memory, key="k"), recall)
    brain.brief.sources = sources()
    return brain, memory, model


def test_at_the_desk_it_is_a_pipe_up_given_once(paths):
    brain, memory, model = make_brain(paths, reply("Sunny today, and power's due tomorrow."))
    asyncio.run(brain.brief_tick())
    assert brain.life.brief_ready
    events = collect(brain.pipe_up("brief"))
    assert any(e["type"] == "reply" for e in events)
    prompt = model.calls[0][-1]["content"]
    assert "morning brief" in prompt and WEATHER in prompt
    assert not brain.life.brief_ready
    assert brain.brief.status(memory.clock())["given"] == "desk"
    assert collect(brain.pipe_up("brief")) == []  # not twice
    memory.close()


def test_if_dan_talks_first_it_rides_with_his_answer(paths):
    brain, memory, model = make_brain(paths, reply("Morning! Sunny, and power's due."))
    asyncio.run(brain.brief_tick())
    collect(brain.chat("morning kit"))
    sent = "\n".join(str(m["content"]) for m in model.calls[0])
    assert "first chat this morning" in sent and BILL in sent
    assert brain.brief.status(memory.clock())["given"] == "reply"
    assert not brain.life.brief_ready
    memory.close()


def test_later_the_second_one_means_the_second_part(paths):
    brain, memory, model = make_brain(paths, reply("Morning!"), reply("It's $212."))
    asyncio.run(brain.brief_tick())
    collect(brain.chat("morning kit"))
    collect(brain.chat("tell me more about the second one"))
    sent = "\n".join(str(m["content"]) for m in model.calls[-1])
    assert f'Dan means "{BILL}"' in sent
    memory.close()


def test_turned_off_in_replies_it_waits_for_the_desk(paths):
    brain, memory, model = make_brain(paths, reply("Morning!"), in_reply=False)
    asyncio.run(brain.brief_tick())
    collect(brain.chat("morning kit"))
    sent = "\n".join(str(m["content"]) for m in model.calls[0])
    assert "first chat this morning" not in sent
    assert brain.brief.status(memory.clock())["given"] is None
    memory.close()


def test_his_life_asks_for_it_once_dan_stops_typing():
    clock = Clock("2026-10-05T08:00:00")
    pc = PcContext(clock)
    s = Settings()
    life = Life(lambda: s, pc, clock, random.Random(1))
    life.brief_ready = True
    typing = Snapshot.model_validate({"focus": {"app": "Excel"}, "idle_seconds": 1})
    assert life._urge_now(clock(), typing, s.life)[0] != "brief"
    idle = Snapshot.model_validate({"focus": {"app": "Excel"}, "idle_seconds": 40})
    assert life._urge_now(clock(), idle, s.life) == ("brief", "")
