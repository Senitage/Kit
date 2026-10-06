import asyncio
import json
from datetime import timedelta

import pytest

from fakes import (
    Clock,
    FakeAnthropic,
    FakeEmbedder,
    FakeModel,
    FakeWeather,
    collect,
    make_cloud,
    reply,
)
from kit.brain import Brain, route
from kit.memory import Memory
from kit.recall import Recall
from kit.settings import Settings


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def memory(paths, clock):
    m = Memory(paths.state_dir / "memory.db", clock)
    yield m
    m.close()


def make(memory, *outputs, settings=None, claude=None, error=None, embedder=None, key="k"):
    model = FakeModel(*outputs, error=error)
    claude = claude or FakeAnthropic()
    s = settings or Settings.model_validate({"memory": {"min_similarity": 0.3}})
    recall = Recall(memory, embedder or FakeEmbedder(), lambda: s)
    cloud = make_cloud(memory, claude, key=key)
    return Brain(lambda: s, memory, model, cloud, recall), model, claude


def settings_with(**sections):
    return Settings.model_validate({"memory": {"min_similarity": 0.3}, **sections})


def decision(what, which=0, fact=""):
    return json.dumps({"decision": what, "which": which, "fact": fact})


def test_reply_streams_words_then_whole_reply(memory):
    brain, model, _ = make(memory, reply("Morning.", "Coffee?", emotion="playful"))
    events = collect(brain.chat("Morning Kit"))
    said = "".join(e["text"] for e in events if e["type"] == "say")
    assert said == "Morning. Coffee?"
    assert len([e for e in events if e["type"] == "say"]) > 1  # streamed, not all at once
    final = events[-1]
    assert final["type"] == "reply" and final["reply"]["emotion"] == "playful"
    assert [m.role for m in memory.recent(5)] == ["user", "kit"]


def test_exchange_is_indexed_for_later(memory):
    brain, _, _ = make(memory, reply("Poor Rex."))
    collect(brain.chat("Rex chewed my boots"))
    item = memory.index.items("conversation")[0]
    assert item.text == "Dan: Rex chewed my boots\nKit: Poor Rex."
    assert memory.index.missing_vectors("fake-embed") == []


def test_relevant_memories_are_in_the_prompt(memory):
    memory.add_fact("Dan's dog is called Rex.", "person")
    memory.add_fact("The thickener is on line 2.", "project")
    memory.add_fact("Dan likes metric units.", "preference", pinned=True)
    s = Settings.model_validate({"persona": {"name": "Kip"}, "memory": {"min_similarity": 0.3}})
    brain, model, _ = make(memory, settings=s)
    collect(brain.chat("How's my dog going?"))
    system = model.calls[0][0]["content"]
    assert "You are Kip" in system and "tilt_head" in system
    assert "Dan's dog is called Rex." in system and "(2026-10-05, person)" in system
    assert "Always keep in mind" in system and "metric" in system
    assert "thickener" not in system
    # What changes each turn (clock, memories) comes after the fixed persona text.
    assert system.index("Rex") > system.index("tilt_head") > system.index("You are Kip")


def test_history_is_in_the_prompt(memory):
    brain, model, _ = make(memory, reply("One."), reply("Two."))
    collect(brain.chat("first"))
    collect(brain.chat("second"))
    roles = [m["role"] for m in model.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]
    assert model.calls[1][-1]["content"] == "second"


def test_old_conversation_is_recalled_but_not_recent(memory):
    brain, model, _ = make(memory, reply("Noted."))
    collect(brain.chat("The Rex vet appointment is Friday"))
    memory.add_message("user", "filler")  # pushes nothing out; still recent
    brain2, model2, _ = make(memory, reply("Friday."))
    collect(brain2.chat("When is the Rex vet appointment?"))
    # Still in the recent history window, so not repeated as a snippet.
    assert "Earlier conversations" not in model2.calls[0][0]["content"]
    s = Settings.model_validate(
        {"brain": {"history_messages": 2}, "memory": {"min_similarity": 0.3}}
    )
    brain3, model3, _ = make(memory, reply("Friday."), settings=s)
    collect(brain3.chat("Rex vet appointment day?"))
    assert "The Rex vet appointment is Friday" in model3.calls[0][0]["content"]


def test_persona_change_applies_next_message(memory):
    settings = Settings()
    model = FakeModel()
    recall = Recall(memory, None, lambda: settings)
    brain = Brain(lambda: settings, memory, model, make_cloud(memory, key=None), recall)
    collect(brain.chat("hi"))
    settings = Settings.model_validate({"persona": {"name": "Changed"}})
    collect(brain.chat("hi"))
    assert "You are Changed" in model.calls[1][0]["content"]


def test_recall_action_searches_then_answers(memory):
    memory.add_fact("Dan's tax returns are in Documents/Finance/Tax.", "place")
    brain, model, _ = make(
        memory,
        reply("Let me think.", action="recall", text="tax returns folder"),
        reply("They're in Documents/Finance/Tax."),
    )
    events = collect(brain.chat("Where did I say my returns were?"))
    kinds = [e["type"] for e in events]
    assert kinds.count("reply") == 2 and "recalled" in kinds
    assert next(e for e in events if e["type"] == "recalled")["found"] == 1
    second = model.calls[1]
    assert second[-2]["role"] == "assistant" and "recall" in second[-2]["content"]
    assert "Documents/Finance/Tax" in second[-1]["content"]
    assert "Dan: Where did I say" in memory.index.items("conversation")[0].text
    assert "Let me think. They're in" in memory.index.items("conversation")[0].text
    # Next turn's history shows the answer, not the "Let me think" working step.
    history = memory.recent(10)
    assert [m.text for m in history] == [
        "Where did I say my returns were?",
        "They're in Documents/Finance/Tax.",
    ]


def test_recall_with_nothing_found_says_so(memory):
    brain, model, _ = make(
        memory, reply("Hmm.", action="recall", text="cat name"), reply("I don't know.")
    )
    collect(brain.chat("What's my cat called?"))
    assert "found nothing" in model.calls[1][-1]["content"]


def test_remember_action_learns(memory):
    brain, _, _ = make(
        memory, reply("Got it.", action="remember", text="Emma's birthday is 14 March.")
    )
    events = collect(brain.chat("Remember Emma's birthday is 14 March"))
    got = next(e for e in events if e["type"] == "remembered")
    assert got["decision"] == "new" and got["fact"] == "Emma's birthday is 14 March."
    assert memory.facts()[0].text == "Emma's birthday is 14 March."


def test_remember_action_updates(memory):
    memory.add_fact("Dan drives a Hilux.")
    brain, _, _ = make(
        memory,
        reply("Nice.", action="remember", text="Dan now drives a Ranger."),
        decision("update", 1, "Dan drives a Ford Ranger."),
    )
    events = collect(brain.chat("I traded the Hilux for a Ranger"))
    got = next(e for e in events if e["type"] == "remembered")
    assert got["decision"] == "update" and got["replaced"] == "Dan drives a Hilux."
    assert [f.text for f in memory.facts()] == ["Dan drives a Ford Ranger."]


def test_local_model_hands_off_with_memories(memory):
    memory.add_fact("Dan is studying Kalman filters for the flotation model.", "project")
    brain, _, claude = make(
        memory, reply("Let me check with Sonnet.", action="ask_cloud", text="Kalman maths?")
    )
    events = collect(brain.chat("Explain Kalman filters properly"))
    handing = next(e for e in events if e["type"] == "handing_off")
    assert handing["to"] == "Sonnet" and handing["question"] == "Kalman maths?"
    last = events[-1]
    assert last["source"] == "cloud" and last["cost_usd"] > 0 and last["label"] == "Sonnet"
    call = claude.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["messages"][-1]["content"] == "Explain Kalman filters properly"
    fixed, this_turn = (block["text"] for block in call["system"])
    assert "flotation model" in this_turn and "search the web" in fixed
    system = fixed + this_turn
    assert "ask_cloud" not in system  # nowhere further to hand it but the expert
    assert "ask_expert" in system
    assert memory.recent(1)[0].source == "cloud"


def test_local_prompt_offers_hand_off_by_mode(memory):
    brain, model, _ = make(memory, settings=settings_with(routing={"mode": "local-heavy"}))
    collect(brain.chat("hi"))
    heavy = model.calls[0][0]["content"]
    brain, model, _ = make(memory, settings=settings_with(routing={"mode": "balanced"}))
    collect(brain.chat("hi"))
    balanced = model.calls[0][0]["content"]
    assert "ask_cloud: for anything you can't answer well" in heavy
    assert "ask_cloud: for anything more than small talk or a quick command" in balanced
    assert "Let me check with Sonnet" in balanced


def test_saying_ask_claude_skips_the_local_model(memory):
    brain, model, claude = make(memory)
    events = collect(brain.chat("Ask Claude why the sky is blue"))
    assert model.calls == []
    assert events[0] == {"type": "say", "text": "Sure, asking Sonnet."}
    assert claude.calls[0]["messages"][-1]["content"] == "Ask Claude why the sky is blue"
    assert events[-1]["source"] == "cloud"


def test_think_hard_goes_to_the_expert(memory):
    brain, model, claude = make(memory)
    collect(brain.chat("Think hard about the Bond work index for this ore"))
    assert model.calls == [] and claude.calls[0]["model"] == "claude-opus-5-5"


def test_cloud_context_alternates(memory):
    brain, _, claude = make(memory, reply("a"), reply("b"))
    collect(brain.chat("one"))
    collect(brain.chat("two"))
    collect(brain.chat("ask claude three"))
    roles = [m["role"] for m in claude.calls[0]["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]


def test_cloud_first_skips_the_local_model(memory):
    brain, model, claude = make(memory, settings=settings_with(routing={"mode": "cloud-first"}))
    events = collect(brain.chat("Morning"))
    assert model.calls == [] and len(claude.calls) == 1
    assert [e["type"] for e in events] == ["say", "reply"]
    assert events[-1]["reply"]["segments"][0]["say"] == "The answer is 42."


def test_keep_it_local_wins_over_cloud_first(memory):
    brain, model, claude = make(
        memory, reply("Sure."), settings=settings_with(routing={"mode": "cloud-first"})
    )
    collect(brain.chat("Keep it local: what's 2 and 2?"))
    assert claude.calls == [] and len(model.calls) == 1
    assert "ask_cloud" not in model.calls[0][0]["content"]


def test_cloud_down_falls_back_to_local(memory):
    s = settings_with(routing={"mode": "cloud-first"})
    brain, model, _ = make(memory, reply("Morning."), settings=s, key=None)
    events = collect(brain.chat("Morning"))
    notice = next(e for e in events if e["type"] == "notice")
    assert "API key" in notice["message"] and "answer myself" in notice["message"]
    assert events[-1]["source"] == "local" and len(model.calls) == 1


def test_cloud_down_without_fallback_says_why(memory):
    s = settings_with(routing={"mode": "cloud-first", "fallback_to_local": False})
    brain, model, _ = make(memory, settings=s, key=None)
    events = collect(brain.chat("Morning"))
    assert model.calls == [] and "API key" in events[-1]["reply"]["segments"][0]["say"]


def test_asked_by_name_and_down_says_why(memory):
    brain, model, _ = make(memory, key=None)
    events = collect(brain.chat("ask claude about pumps"))
    assert model.calls == [] and "API key" in events[-1]["reply"]["segments"][0]["say"]


def test_cloud_reply_json_is_used_and_can_remember(memory):
    answer = reply(
        "Noted, Emma's on the 14th.", action="remember", text="Emma's birthday is 14 March."
    )
    s = settings_with(routing={"mode": "cloud-first"})
    brain, _, _ = make(memory, settings=s, claude=FakeAnthropic(answer=answer))
    events = collect(brain.chat("Remember Emma's birthday is 14 March"))
    assert next(e for e in events if e["type"] == "remembered")["decision"] == "new"
    assert memory.facts()[0].text == "Emma's birthday is 14 March."


def test_cloud_detail_is_shown_and_indexed(memory):
    answer = json.dumps(
        {
            "emotion": "proud",
            "segments": [{"gesture": "nod", "say": "Here's the function."}],
            "action": {"kind": "none"},
            "detail": "def flag(df): ...",
        }
    )
    s = settings_with(routing={"mode": "cloud-first"})
    brain, _, _ = make(memory, settings=s, claude=FakeAnthropic(answer=answer))
    events = collect(brain.chat("Write the pump flag function"))
    assert events[-1]["reply"]["detail"] == "def flag(df): ..."
    assert "def flag" in memory.index.items("conversation")[0].text


def test_work_model_can_ask_the_expert(memory):
    first = reply("That one's for Opus.", action="ask_expert", text="Derive it")
    claude = FakeAnthropic(answer=[first, "Here's the derivation."])
    s = settings_with(routing={"mode": "cloud-first"})
    brain, _, _ = make(memory, settings=s, claude=claude)
    events = collect(brain.chat("Derive the Bond equation"))
    assert [c["model"] for c in claude.calls] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert next(e for e in events if e["type"] == "handing_off")["to"] == "Opus"
    assert "ask_expert" not in claude.calls[1]["system"][0]["text"]


def test_a_local_profile_can_do_the_work(memory):
    s = settings_with(
        routing={"mode": "cloud-first", "work": "big"},
        models={"big": {"provider": "ollama", "model": "qwen3.8:27b"}},
    )
    brain, model, claude = make(memory, reply("Sure."), settings=s)
    collect(brain.chat("hi"))
    assert claude.calls == [] and model.models == ["qwen3.8:27b"]


def test_routing_phrases():
    s = Settings()
    assert route("keep it local please", s) == ("local", True)
    assert route("ask Gemini what it thinks", s) == ("work", True)
    assert route("think carefully about this", s) == ("expert", True)
    assert route("morning", s) == ("local", False)
    cloud_first = Settings.model_validate({"routing": {"mode": "cloud-first"}})
    assert route("morning", cloud_first) == ("work", False)


def test_broken_json_keeps_the_words(memory):
    brain, _, _ = make(memory, '{"emotion": "happy", "segments": [{"say": "Half a thou')
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "reply"
    assert events[-1]["reply"]["segments"][0]["say"] == "Half a thou"


def test_bad_escape_in_the_stream_keeps_the_words(memory):
    brain, _, _ = make(memory, '{"segments": [{"say": "Hi\\uZZZZ there')  # bad escape, cut off
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "reply" and events[-1]["reply"]["segments"][0]["say"] == "Hi there"


def test_garbage_is_an_error_and_not_indexed(memory):
    brain, _, _ = make(memory, "nonsense")
    assert collect(brain.chat("hi"))[-1]["type"] == "error"
    assert memory.index.items("conversation") == []


def test_ollama_down_is_an_error(memory):
    brain, _, _ = make(memory, error="connection refused")
    events = collect(brain.chat("hi"))
    assert events[-1]["type"] == "error" and "local brain" in events[-1]["message"]


def test_embeddings_down_still_chats(memory):
    memory.add_fact("Rex is the dog.")
    brain, model, _ = make(memory, reply("Rex!"), embedder=FakeEmbedder(fail=True))
    assert collect(brain.chat("How is Rex?"))[-1]["type"] == "reply"
    assert "Rex is the dog." in model.calls[0][0]["content"]


def test_blank_message_does_nothing(memory):
    brain, model, _ = make(memory)
    assert collect(brain.chat("   ")) == [] and model.calls == []


def test_yesterday_is_remembered_after_restart(paths, memory, clock):
    day = json.dumps(
        {
            "summary": "Dan talked about his dog Rex.",
            "facts": [{"kind": "person", "text": "Dan has a dog called Rex."}],
        }
    )
    brain, _, _ = make(memory, reply("Nice."), day)
    collect(brain.chat("My dog is called Rex"))
    clock.now += timedelta(days=1)
    assert asyncio.run(brain.summarise_past_days()) == ["2026-10-05"]
    assert asyncio.run(brain.summarise_past_days()) == []
    memory.close()

    fresh = Memory(paths.state_dir / "memory.db", clock)  # as if Kit restarted
    brain2, model2, _ = make(fresh, reply("Rex, right?"))
    collect(brain2.chat("What's my dog's name?"))
    system = model2.calls[0][0]["content"]
    assert "Dan has a dog called Rex." in system
    fresh.close()


# Chatting while a slow answer works


async def _until(check):
    for _ in range(200):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never happened")


def test_local_model_chats_while_the_cloud_works(memory):
    async def run():
        claude = FakeAnthropic(answer=reply("Pumps push fluid.", emotion="neutral"))
        claude.gate = asyncio.Event()
        brain, model, _ = make(memory, reply("Geez, relax, I'm thinking."), claude=claude)
        slow = asyncio.create_task(_collect(brain.chat("ask Claude how pumps work")))
        await _until(lambda: brain.jobs)
        assert brain.busy()[0]["question"] == "ask Claude how pumps work"

        quick = await _collect(brain.chat("how are you going?"))
        assert quick[-1]["reply"]["segments"][0]["say"] == "Geez, relax, I'm thinking."
        system = model.calls[-1][0]["content"]
        assert "still working on this in the background" in system
        assert '"ask Claude how pumps work": you asked Sonnet' in system
        assert len(claude.calls) == 1  # the quick one didn't go to the cloud

        claude.gate.set()
        events = await slow
        final = events[-1]
        assert final["source"] == "cloud" and final["question"] == "ask Claude how pumps work"
        assert brain.jobs == {}
        # Afterwards, the prompt no longer says Kit is busy.
        await _collect(brain.chat("thanks"))
        assert "in the background" not in model.calls[-1][0]["content"]

    asyncio.run(run())


def test_slow_answer_is_kept_if_nobody_waits(memory):
    async def run():
        claude = FakeAnthropic(answer=reply("Found it.", emotion="neutral"))
        claude.gate = asyncio.Event()
        brain, _, _ = make(memory, claude=claude)
        events = brain.chat("ask Claude where the pump curve is")
        await events.__anext__()  # "Sure, asking..."
        await events.aclose()  # the page was closed
        await _until(lambda: brain.jobs)
        claude.gate.set()
        await _until(lambda: not brain._turns)
        assert memory.recent(5)[-1].text == "Found it."

    asyncio.run(run())


def test_job_line_lists_progress():
    from kit.brain import Job

    job = Job(1, "find pump curves", "Sonnet", steps=["searched the web for 'x'"])
    assert job.line().startswith('"find pump curves": you asked Sonnet 0 seconds ago.')
    assert "So far you've searched the web for 'x'." in job.line()


async def _collect(agen):
    return [e async for e in agen]


PERTH = {"memory": {"min_similarity": 0.3}, "persona": {"location": "Perth, WA", "country": "AU"}}


def test_weather_question_is_answered_locally_from_the_forecast(memory):
    brain, model, claude = make(
        memory, reply("Mild tonight, about 14 and clear."), settings=Settings.model_validate(PERTH)
    )
    brain.weather = FakeWeather()
    events = collect(brain.chat("What's the weather like tonight?"))
    assert [e["type"] for e in events].count("reply") == 1
    assert next(e for e in events if e["type"] == "weather")["place"] == "Perth, WA"
    assert brain.weather.asked == [("Perth, WA", "AU")]
    system = model.calls[0][0]["content"]
    assert "Forecast for Perth, WA" in system
    assert "ask_cloud" not in system  # no handing a weather question to the cloud
    assert not claude.calls


def test_engineering_temperatures_are_not_weather(memory):
    brain, model, _ = make(memory, reply("Hi."), settings=Settings.model_validate(PERTH))
    brain.weather = FakeWeather()
    collect(brain.chat("What temperature does the leach tank run at?"))
    assert brain.weather.asked == []


def test_weather_action_for_somewhere_else(memory):
    brain, model, _ = make(
        memory,
        reply("Checking.", action="weather", text="Broome"),
        reply("Hot and dry up there."),
    )
    brain.weather = FakeWeather()
    events = collect(brain.chat("Is it nice in Broome at the moment?"))
    assert brain.weather.asked == [("Broome", "")]
    assert [e["type"] for e in events].count("reply") == 2
    assert "Forecast for Broome" in model.calls[1][-1]["content"]


def test_weather_failure_is_told_to_the_model(memory):
    brain, model, _ = make(memory, reply("I can't get the forecast right now."))
    brain.weather = FakeWeather(fail=True)
    collect(brain.chat("Will it rain tomorrow?"))
    assert "forecast lookup for home failed" in model.calls[0][0]["content"]


def test_no_weather_action_without_a_forecast_source(memory):
    brain, model, _ = make(memory, reply("Hi."))
    collect(brain.chat("Hi"))
    assert "- weather:" not in model.calls[0][0]["content"]


def test_weather_follow_up_gets_a_fresh_forecast(memory, clock):
    brain, model, _ = make(
        memory,
        reply("Clear tonight."),
        reply("Drizzle early."),
        reply("Ok."),
        settings=Settings.model_validate(PERTH),
    )
    brain.weather = FakeWeather()
    collect(brain.chat("What's the weather like tonight?"))
    clock.now += timedelta(minutes=2)
    collect(brain.chat("whats it going to be like tomorrow?"))
    assert len(brain.weather.asked) == 2
    follow_up = model.calls[1][0]["content"]
    assert "Forecast for Perth" in follow_up
    assert "ask_cloud" in follow_up  # not plainly weather, so it can still be handed on
    clock.now += timedelta(minutes=30)
    collect(brain.chat("what's on tomorrow?"))
    assert len(brain.weather.asked) == 2  # long after, "tomorrow" isn't about the weather


def test_checking_in_while_busy_names_the_work(memory):
    from kit.brain import Job

    brain, model, _ = make(memory, reply("Still on the thickener, give me a sec."))
    brain.jobs[1] = Job(1, "size a thickener", "Opus")
    collect(brain.chat("how are you going?"))
    last = model.calls[0][-1]["content"]
    assert last.startswith("how are you going?") and '"size a thickener"' in last
    assert memory.recent(10)[0].text == "how are you going?"  # the note isn't saved


def test_other_messages_while_busy_get_a_light_note(memory):
    from kit.brain import Job

    brain, model, _ = make(memory, reply("It's Tuesday."))
    brain.jobs[1] = Job(1, "size a thickener", "Opus")
    collect(brain.chat("what day is it today again?"))
    last = model.calls[0][-1]["content"]
    assert "Answer this message normally" in last and '"size a thickener"' in last


def test_no_note_when_not_busy(memory):
    brain, model, _ = make(memory, reply("Hi."))
    collect(brain.chat("hey"))
    assert model.calls[0][-1]["content"] == "hey"


@pytest.mark.parametrize(
    "text", ["hello?", "anything?", "?", "hey", "kit", "any update?", "you there"]
)
def test_nudges_while_busy_count_as_checking_in(memory, text):
    from kit.brain import Job

    brain, model, _ = make(memory, reply("Still on it."))
    brain.jobs[1] = Job(1, "pump cavitation", "Opus")
    collect(brain.chat(text))
    assert '"pump cavitation"' in model.calls[0][-1]["content"]
