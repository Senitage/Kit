"""Kit's two-pass replies: a quick plan in JSON, then his words in plain text."""

import asyncio
import json

import pytest

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, collect, make_cloud, plan, reply
from kit.brain import Brain
from kit.memory import Memory
from kit.prompt import IN_WORDS
from kit.recall import Recall
from kit.reply import (
    Plan,
    Reply,
    SpokenStream,
    early_plan,
    parse_plan,
    reply_json,
    sentences,
    spoken_reply,
)
from kit.settings import Settings


@pytest.fixture
def memory(paths):
    m = Memory(paths.state_dir / "memory.db", Clock())
    yield m
    m.close()


def make(memory, *outputs, **sections):
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}, **sections})
    model = FakeModel(*outputs)
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, FakeAnthropic()), recall)
    return brain, model


def says(events):
    return "".join(e["text"] for e in events if e["type"] == "say")


def test_he_plans_in_json_then_speaks_in_plain_words_livelier(memory):
    brain, model = make(
        memory, reply("Morning.", "Coffee first?", emotion="playful", gesture="wave")
    )
    events = collect(brain.chat("Morning Kit"))
    assert "First answer only with JSON" in model.calls[0][0]["content"]
    speak = model.speak_calls[0]
    assert json.loads(speak[-2]["content"])["gesture"] == "wave"
    # His words answer what Dan just said, said again right there: small models
    # otherwise answer an earlier message in the conversation.
    assert speak[-1]["content"].startswith(
        '[Not from Dan. Dan just said: "Morning Kit". Now say your reply to Dan.'
    )
    assert model.speak_options[0] == {
        "temperature": 0.95,
        "min_p": 0.05,
        "top_k": 64,
        "top_p": 0.95,
        "repeat_penalty": 1.08,
        "repeat_last_n": 64,
    }
    assert says(events) == "Morning. Coffee first?"
    final = events[-1]["reply"]
    assert final["emotion"] == "playful"
    assert [(s["say"], s["gesture"]) for s in final["segments"]] == [
        ("Morning.", "wave"),
        ("Coffee first?", "none"),
    ]
    # His words go into the history as plain words too, so he isn't nudged back into JSON.
    collect(brain.chat("Yes please"))
    assert {"role": "assistant", "content": "Morning. Coffee first?"} in model.calls[1]


def test_he_starts_talking_once_the_plan_is_plainly_nothing_to_do(memory):
    unfinished = '{"emotion": "happy", "gesture": "nod", "action": {"kind": "none", "text": "' + (
        "x" * 40
    )
    brain, model = make(memory, unfinished, "Morning!")
    events = collect(brain.chat("Morning"))
    final = events[-1]["reply"]
    assert final["emotion"] == "happy" and final["segments"][0]["say"] == "Morning!"


def test_a_plan_with_a_look_up_says_a_few_words_first(memory):
    brain, model = make(
        memory,
        reply("Let me think.", action="recall", text="tax returns folder"),
        reply("They're in Finance/Tax."),
    )
    events = collect(brain.chat("Where do I keep my tax stuff?"))
    note = model.speak_calls[0][-1]["content"]
    assert "look back through your memory for 'tax returns folder'" in note
    assert [e["type"] for e in events].count("reply") == 2
    after = model.speak_calls[1][-1]["content"]  # with what he found, still Dan's question
    assert 'Dan just said: "Where do I keep my tax stuff?"' in after
    assert events[-1]["reply"]["segments"][0]["say"] == "They're in Finance/Tax."


def test_words_given_as_a_search_search_for_what_dan_asked(memory):
    brain, model = make(
        memory,
        reply("Hmm.", action="recall", text="Let me think..."),
        reply("No idea, sorry."),
    )
    events = collect(brain.chat("Where's the pump manual?"))
    assert next(e for e in events if e["type"] == "recalled")["query"] == (
        "Where's the pump manual?"
    )


def test_a_line_he_just_said_is_asked_for_again_once(memory):
    brain, model = make(
        memory,
        reply("Righto, I'll guard the desk while you're out."),
        reply("Righto, I'll guard the desk while you're gone."),
        "Enjoy lunch. Bring me a chip.",
    )
    collect(brain.chat("Heading out."))
    events = collect(brain.chat("Off for lunch."))
    assert len(model.speak_calls) == 3  # one for the first, two for the second
    retry = model.speak_calls[-1][-1]["content"]
    assert "Not \"Righto, I'll guard the desk while you're gone.\"" in retry
    assert model.speak_options[-1]["temperature"] == pytest.approx(1.05)
    assert "Righto" not in says(events)  # the repeat was never shown
    assert events[-1]["reply"]["segments"][0]["say"] == "Enjoy lunch."


def test_written_detail_comes_after_a_blank_line_and_isnt_spoken(memory):
    brain, model = make(
        memory, plan(), "Here's the plan.\n\n1. Check the pump.\n2. Check the valve."
    )
    events = collect(brain.chat("What should I check?"))
    final = events[-1]["reply"]
    assert says(events) == "Here's the plan."
    assert final["detail"] == "1. Check the pump.\n2. Check the valve."


def test_words_that_come_back_as_json_are_still_read(memory):
    brain, model = make(memory, plan(), reply("Hi there."))
    events = collect(brain.chat("Hello"))
    assert says(events) == "Hi there."
    assert events[-1]["reply"]["segments"][0]["say"] == "Hi there."


def test_a_plan_instead_of_words_is_never_said_and_he_is_asked_for_words(memory):
    brain, model = make(memory, plan(), plan(gesture="wink"), "Fair enough, mate.")
    events = collect(brain.chat("haha"))
    assert says(events) == "Fair enough, mate."
    assert events[-1]["reply"]["segments"][0]["say"] == "Fair enough, mate."
    assert model.speak_calls[1][-1]["content"].endswith(IN_WORDS)


def test_plan_json_already_in_the_chat_isnt_shown_to_him_again(memory):
    # Once one got into the chat, he wrote it above every line after.
    leaked = '{"emotion": "amused", "gesture": "laugh", "action": "none"}\nNot my snacks, I hope.'
    memory.add_message("kit", leaked, reply_json(Reply.plain(leaked)), "local")
    brain, model = make(memory, reply("Ha, fair."))
    collect(brain.chat("well it kinda is"))
    assert {"role": "assistant", "content": "Not my snacks, I hope."} in model.speak_calls[0]
    assert '{"emotion"' not in model.calls[0][0]["content"]  # nor in his last few lines


def test_no_words_twice_is_a_lost_train_of_thought(memory):
    brain, model = make(memory, plan(), "", "")
    events = collect(brain.chat("Hello"))
    assert events[-1] == {"type": "error", "message": "I lost my train of thought. Say again?"}
    brain, model = make(memory, plan(), "", "Hello again.")
    events = collect(brain.chat("Hello?"))
    assert events[-1]["reply"]["segments"][0]["say"] == "Hello again."


def test_a_local_model_thats_down_is_said_plainly(memory):
    brain, model = make(memory)
    model.error = "connection refused"
    events = collect(brain.chat("Hello"))
    assert events[-1]["type"] == "error" and "connection refused" in events[-1]["message"]


def test_one_pass_when_the_speaking_pass_is_off(memory):
    brain, model = make(memory, reply("Hi Dan."), ollama={"speak_pass": False})
    events = collect(brain.chat("Hi"))
    assert model.speak_calls == [] and events[-1]["reply"]["segments"][0]["say"] == "Hi Dan."
    assert "Answer only with JSON: an emotion" in model.calls[0][0]["content"]


def test_a_cloud_model_still_answers_in_one_piece(memory):
    claude = FakeAnthropic(answer=reply("Sonnet here."))
    s = Settings.model_validate({"routing": {"mode": "cloud-first"}})
    model = FakeModel()
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude), recall)
    events = collect(brain.chat("What's a good flotation recovery?"))
    assert events[-1]["reply"]["segments"][0]["say"] == "Sonnet here."
    assert model.speak_calls == []
    assert "First answer only with JSON" not in claude.calls[0]["system"][0]["text"]


# Reading the words as they stream


def feed(stream, text, size=3):
    out = []
    for i in range(0, len(text), size):
        stream.feed(text[i : i + size])
        if not stream.released and stream.first() is not None:
            stream.release()
        out.append(stream.take())
    out.append(stream.end())
    return "".join(out)


def test_the_opening_waits_until_its_whole_and_long_enough_to_judge():
    stream = SpokenStream("Kit")
    stream.feed("Kit: Morning")
    assert stream.first() is None
    stream.feed(", mate. How")
    assert stream.first() is None  # "Morning, mate." is too short to tell from an old line
    stream.feed("'s the pump going today? I")
    assert stream.first() == "Morning, mate. How's the pump going today?"
    long = SpokenStream()
    long.feed("You got a minute? I think the weather's trying to be a drama queen. And")
    assert long.first() == "You got a minute? I think the weather's trying to be a drama queen."


def test_names_quotes_stage_directions_and_thinking_are_dropped():
    stream = SpokenStream("Kit")
    raw = '<think>hmm</think>**Kit:** "Oh, *grins* look who it is. Back already?"'
    assert feed(stream, raw) == "Oh, look who it is. Back already?"
    assert stream.result() == ("Oh, look who it is. Back already?", "")


def test_detail_after_a_blank_line_and_json_by_mistake():
    stream = SpokenStream()
    assert feed(stream, "Done.\n\n```py\nprint(1)\n```") == "Done."
    assert stream.result() == ("Done.", "```py\nprint(1)\n```")
    json_stream = SpokenStream()
    assert feed(json_stream, reply("From JSON.")) == "From JSON."
    only_detail = SpokenStream()
    only_detail.feed("*grins*\n\nSteps:\n1. Do it.")
    assert only_detail.result() == ("Steps:", "1. Do it.")


def test_a_plan_written_again_with_his_words_is_dropped():
    # A small model put {"emotion": ..., "gesture": ..., "action": ...} above his words.
    words = "So that is it then. You want me to watch your face all day?"
    stream = SpokenStream()
    raw = '{"emotion": "playful", "gesture": "wink", "action": "none"}\n' + words
    assert feed(stream, raw) == words and stream.result() == (words, "")
    fenced = SpokenStream()
    fenced_raw = '```json\n{"emotion": "happy", "gesture": "nod"}\n```\nRighto.'
    assert feed(fenced, fenced_raw) == "Righto."
    after = SpokenStream()
    assert feed(after, 'Righto, done. {"emotion": "happy", "gesture": "nod"}') == "Righto, done."
    only = SpokenStream()
    assert feed(only, plan()) == "" and only.result() == ("", "") and only.wrote_json()


def test_he_says_three_sentences_at_most_and_starts_none_past_thirty_words():
    stream = SpokenStream()
    said = feed(stream, "Ha! Nice one. Told you it'd pass. Now about that pump. And more.")
    assert said == "Ha! Nice one. Told you it'd pass."  # what streamed is what's kept
    assert stream.result() == ("Ha! Nice one. Told you it'd pass.", "")
    first = " ".join(["word"] * 29) + " done."
    wordy = SpokenStream()
    assert feed(wordy, f"{first} Second line here. Third.") == first
    in_json = SpokenStream()
    assert feed(in_json, reply("One.", "Two.", "Three.", "Four.")) == "One. Two. Three."


def test_more_chat_after_a_blank_line_is_dropped_but_things_to_read_are_kept():
    # On screen a second line of chat, often an old one, looked like Kit answering himself.
    chat = SpokenStream()
    feed(chat, "You got a minute?\n\nStill not answered my last line, mate. Watch your back.")
    assert chat.result() == ("You got a minute?", "")
    for detail in [
        "1. Check the pump.\n2. Check the valve.",
        "- pumps.py\n- valves.py",
        "Step 1: fill the tank",
        "Run `kit check` first.",
        "It's in Finance/Tax/2023.",
        "Forecast from https://open-meteo.com",
        "| Pump | kW |",
        "A hydrocyclone " + "spins the slurry so the coarse stuff goes down " * 5,
    ]:
        stream = SpokenStream()
        feed(stream, f"Here you go.\n\n{detail}")
        assert stream.result() == ("Here you go.", detail.strip()), detail


def test_a_second_line_of_chat_isnt_shown_or_kept_under_his_reply(memory):
    brain, model = make(memory, plan(), "Fair enough.\n\nI think you're ignoring me on purpose.")
    events = collect(brain.chat("yeah whats up?"))
    assert says(events) == "Fair enough." and events[-1]["reply"]["detail"] == ""
    assert memory.recent(1)[0].text == "Fair enough."


def test_reading_a_plan():
    p = parse_plan(plan("curious", "tilt_head", "recall", "pumps"))
    assert (p.emotion, p.gesture, p.action.kind, p.action.text) == (
        "curious",
        "tilt_head",
        "recall",
        "pumps",
    )
    assert early_plan('{"emotion": "happy", "gesture": "nod", "action": {"kind": "none"') == Plan(
        emotion="happy", gesture="nod", action={"kind": "none"}
    )
    assert early_plan('{"emotion": "happy", "gesture": "nod", "action": {"kind": "recall"') is None
    assert early_plan('{"emotion": "elated", "gesture": "nod", "action": {"kind": "none"') is None


def test_spoken_words_become_segments():
    assert sentences("One. Two! Three? Four… Five. Six. Seven.") == [
        "One.",
        "Two!",
        "Three?",
        "Four…",
        "Five.",
        "Six. Seven.",
    ]
    reply_ = spoken_reply(Plan(emotion="happy", gesture="wave", action={"kind": "none"}), "Hi. Yo.")
    assert [(s.say, s.gesture) for s in reply_.segments] == [("Hi.", "wave"), ("Yo.", "none")]


# His voice and the local model's prompt cache


def test_his_words_are_whole_at_a_blank_line_or_at_the_limit_before_the_model_stops():
    stream = SpokenStream("Kit")
    stream.feed("Kit:\n\nRighto, done")
    assert not stream.finished()  # a "Kit:" and a blank line in front isn't the end
    stream.feed(".\n\n1. Check")
    assert stream.finished()  # the rest is written detail
    three = SpokenStream()
    three.feed("One. Two. Three.")
    assert not three.finished()
    three.feed(" And")  # a fourth sentence won't be said
    assert three.finished()
    in_json = SpokenStream()
    in_json.feed('{"emotion": "happy"}\n\n')
    assert not in_json.finished()


def test_his_voice_gets_his_last_sentence_before_the_detail_is_written(memory):
    order = []

    class Watched(FakeModel):
        async def stream(self, messages, schema, model=None, options=None):
            async for piece in super().stream(messages, schema, model, options):
                if schema is None:
                    order.append("written")
                yield piece

    detail = "1. Check the pump.\n2. Check the valve.\n3. Check the motor."
    s = Settings.model_validate({"memory": {"min_similarity": 0.3}})
    model = Watched(plan(), f"Here's the plan.\n\n{detail}", plan(), "Morning.")
    recall = Recall(memory, FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, FakeAnthropic()), recall)
    asked = [{"role": "user", "content": "What should I check?"}]

    async def go():
        async for event in brain._two_pass_reply(asked, "local"):
            order.append(event["type"])

    asyncio.run(go())
    assert order.count("spoken") == 1
    assert order.index("say") < order.index("spoken") < order.index("reply")
    assert "written" in order[order.index("spoken") :]  # the model was still writing
    order.clear()
    asyncio.run(go())  # no detail: his words are whole when the model stops
    assert [e for e in order if e != "written"] == ["mood", "say", "spoken", "reply"]


def test_with_warm_up_what_changes_each_turn_goes_beside_dans_message(memory):
    brain, model = make(memory, reply("Morning."), ollama={"warm_up": True})
    collect(brain.chat("Morning Kit"))
    system, heard = model.calls[0][0]["content"], model.calls[0][-1]["content"]
    assert "\n\nIt is " not in system
    assert heard.startswith("[Not from Dan: how things stand right now, for you to use.\nIt is ")
    assert heard.endswith("]\n\nMorning Kit")
    off, model = make(memory, reply("Morning."))
    collect(off.chat("Morning again"))
    assert "\n\nIt is " in model.calls[0][0]["content"]  # off: as before
    assert model.calls[0][-1]["content"] == "Morning again"
    assert model.warm_calls == []


@pytest.fixture
def quick_warm(monkeypatch):
    import kit.brain

    monkeypatch.setattr(kit.brain, "WARM_AFTER_S", 0.01)
    monkeypatch.setattr(kit.brain, "WARM_POLL_S", 0.01)


def test_the_conversation_is_read_ahead_once_his_voice_is_quiet(memory, quick_warm):
    brain, model = make(memory, reply("Morning."), reply("Not bad."), ollama={"warm_up": True})
    quiet = [0.0]
    brain.voice_quiet = lambda: quiet[0]

    async def go():
        [e async for e in brain.chat("Morning Kit")]
        await asyncio.sleep(0.1)
        assert model.warm_calls == []  # his voice is still being made: it'd stutter
        quiet[0] = 5.0
        await asyncio.sleep(0.1)
        assert len(model.warm_calls) == 1
        [e async for e in brain.chat("How's things?")]

    asyncio.run(go())
    ahead, then = model.warm_calls[0], model.calls[1]
    assert ahead[-1] == {"role": "assistant", "content": "Morning."}
    # The next message's prompt carries straight on from what was read ahead, so the
    # model only has Dan's message left to read.
    assert then[: len(ahead)] == ahead and len(then) == len(ahead) + 1


def test_in_cloud_only_the_local_model_stands_in_without_reading_ahead(memory, quick_warm):
    """There it only answers what Dan keeps local: reading ahead would only load it
    back onto the GPU after every reply."""
    brain, model = make(
        memory, reply("Righto."), ollama={"warm_up": True}, routing={"mode": "cloud-only"}
    )
    brain.voice_quiet = lambda: 5.0

    async def go():
        [e async for e in brain.chat("How's things? Keep it local please")]
        await asyncio.sleep(0.1)

    asyncio.run(go())
    assert "\n\nIt is " in model.calls[0][0]["content"]  # its usual prompt
    assert model.calls[0][-1]["content"].endswith("Keep it local please")
    assert model.warm_calls == []


def test_a_pipe_up_he_keeps_to_himself_leaves_the_read_ahead_be(memory, quick_warm):
    brain, model = make(
        memory, reply("Morning."), ollama={"warm_up": True}, life={"pipe_up_bar": 1.0}
    )
    quiet = [0.0]
    brain.voice_quiet = lambda: quiet[0]

    async def go():
        [e async for e in brain.chat("Morning Kit")]
        assert [e async for e in brain.pipe_up("bored")] == []  # scored under the bar
        quiet[0] = 5.0
        await asyncio.sleep(0.1)

    asyncio.run(go())
    [ahead] = model.warm_calls
    assert ahead[-1] == {"role": "assistant", "content": "Morning."}


def test_a_message_before_the_read_ahead_starts_cancels_it(memory, quick_warm):
    brain, model = make(memory, reply("Morning."), reply("Not bad."), ollama={"warm_up": True})
    quiet = [0.0]
    brain.voice_quiet = lambda: quiet[0]

    async def go():
        [e async for e in brain.chat("Morning Kit")]
        await asyncio.sleep(0.05)
        [e async for e in brain.chat("How's things?")]
        quiet[0] = 5.0
        await asyncio.sleep(0.1)

    asyncio.run(go())
    [ahead] = model.warm_calls  # only the one after the second reply
    assert ahead[-1] == {"role": "assistant", "content": "Not bad."}
