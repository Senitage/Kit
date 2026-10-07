import asyncio
from datetime import datetime
from itertools import count

from fakes import FakeModel, reply
from kit.evals import PROMPTS, run_eval
from kit.settings import Settings


def test_there_are_fifty_prompts():
    assert len(PROMPTS) == 50 and len(set(PROMPTS)) == 50


def test_report_counts_valid_replies_and_first_word_time():
    model = FakeModel(reply("Fine."), "broken", reply("Also fine."))
    ticks = count()
    report = asyncio.run(
        run_eval(model, Settings(), ["a", "b", "c"], datetime(2026, 10, 5), lambda: next(ticks))
    )
    assert report.valid == 2
    assert not report.results[1].valid and report.results[1].error
    assert report.latency(0.5) is not None


def test_compare_asks_every_model_every_prompt(paths):
    from fakes import Clock, FakeAnthropic, make_cloud
    from kit.evals import compare_report, run_compare
    from kit.memory import Memory

    memory = Memory(paths.state_dir / "memory.db", Clock())
    claude = FakeAnthropic(answer=reply("Sunny.", text=""))
    cloud = make_cloud(memory, claude)
    ticks = count()
    results = asyncio.run(
        run_compare(
            cloud,
            Settings(),
            ["sonnet", "opus", "gpt-sol"],
            ["weather?", "price?"],
            datetime(2026, 10, 6),
            lambda: next(ticks),
        )
    )
    memory.close()
    assert [(r.prompt, r.model) for r in results][:3] == [
        ("weather?", "sonnet"),
        ("weather?", "opus"),
        ("weather?", "gpt-sol"),
    ]
    assert [c["model"] for c in claude.calls] == ["claude-sonnet-5-5", "claude-opus-5-5"] * 2
    assert results[0].ok and results[0].said == "Sunny." and results[0].cost_usd > 0
    assert not results[2].ok and "openai" in results[2].error  # no GPT adapter in this test
    report = compare_report(results, ["sonnet", "opus", "gpt-sol"])
    assert "**sonnet**: 2/2 answered" in report and "**gpt-sol**: 0/2" in report
    assert "## weather?" in report and "### opus" in report


def test_cutoff_is_suggested_between_right_and_unrelated():
    from kit.evals import MemoryReport

    report = MemoryReport(right=[0.71, 0.64, 0.80], unrelated=[0.52, 0.58])
    assert report.suggested_cutoff() == 0.61
    assert MemoryReport(right=[0.55], unrelated=[0.6]).suggested_cutoff() is None
    assert MemoryReport().suggested_cutoff() is None


def test_fact_similarities_cover_every_fact(paths):
    from fakes import Clock, FakeEmbedder
    from kit.evals import _fact_similarities
    from kit.memory import Memory
    from kit.recall import Recall

    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), lambda: Settings())
    memory.add_fact("Dan drinks his coffee black.", "preference")
    memory.add_fact("Dan drives a Ford Ranger.", "about")
    asyncio.run(recall.index_pending())
    sims = dict(asyncio.run(_fact_similarities(memory, recall, "How does Dan take coffee?")))
    assert sims["Dan drinks his coffee black."] > sims["Dan drives a Ford Ranger."]
    memory.close()


def test_voice_eval_reads_his_lines_thoughts_and_pipe_ups(paths):
    import json

    from fakes import Clock
    from kit.brain import Brain
    from kit.cloud import Cloud
    from kit.evals import VOICE_THOUGHTS, run_voice_eval, seed_voice, voice_report
    from kit.memory import Memory
    from kit.recall import Recall

    memory = Memory(paths.state_dir / "memory.db", Clock())
    s = Settings.model_validate({"ollama": {"speak_pass": False}})
    idea = {
        "thought": "That pump curve looks off.",
        "kind": "opinion",
        "want": "Ask about the curve.",
        "feeling": "amused",
        "why": "the curve",
    }
    model = FakeModel(
        reply("G'day. The flotation model awaits."),
        reply("How can I help you today?"),
        reply("Morning. You look like a man who hasn't had coffee yet."),
        json.dumps(idea),
        reply("Oi, still on pumps.py?"),
    )
    brain = Brain(
        lambda: s, memory, model, Cloud(memory, lambda p: None, {}), Recall(memory, None, lambda: s)
    )
    seed_voice(brain)
    ticks = count()
    report = asyncio.run(
        run_voice_eval(
            brain,
            "fake:1b",
            ["Morning Kit.", "Hi.", "Morning."],
            ["curious"],
            VOICE_THOUGHTS[:1],
            clock=lambda: next(ticks),
        )
    )
    memory.close()
    chat = report.spoken
    assert report.answered == 4 and len(chat) == 4 and not report.two_pass
    assert not chat[0].echo and chat[1].canned and chat[2].echo  # copied an example line
    assert report.thoughts[0].text == "That pump curve looks off."
    assert "wants to say: Ask about the curve." in report.thoughts[0].note
    assert chat[3].kind == "pipe_up" and chat[3].text == "Oi, still on pumps.py?"
    assert report.first_words is not None and 0 < report.variety <= 1
    system = model.calls[0][0]["content"]
    assert "I live on Dan's desk" in system and "Your traits:" not in system  # seeded sheet
    assert "pumps and impeller sizes" in system  # fixed quirks, the same for every model
    assert "pumps.py" in model.calls[-1][-1]["content"]  # curious about what's on screen
    md = voice_report([report])
    assert "**fake:1b** (one pass): 4/4 answered" in md
    assert "## Morning Kit." in md and "## Thinking: chat_ended" in md
    assert "## Piping up: curious" in md and "**[canned]**" in md and "**[echo]**" in md
