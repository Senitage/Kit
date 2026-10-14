"""Shared for the tool tests: a brain with the fakes, and small packs to load."""

from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, make_cloud
from kit.brain import Brain
from kit.recall import Recall
from kit.settings import Settings
from kit.tools import EvalCase, Pack, Tool, ToolResult


def make(memory, *outputs, claude=None, settings=None, embedder=None):
    s = settings or Settings.model_validate(
        {"memory": {"min_similarity": 0.3}, "routing": {"mode": "cloud-only"}}
    )
    model = FakeModel(*outputs)
    claude = claude or FakeAnthropic()
    recall = Recall(memory, embedder or FakeEmbedder(), lambda: s)
    brain = Brain(lambda: s, memory, model, make_cloud(memory, claude), recall)
    return brain, model, claude


def shopping_pack(ran: list, private: bool = False) -> Pack:
    """A pack with a read, an act and a change tool, loaded by "shopping" or "list"."""

    async def show(args):
        return ToolResult("Milk, eggs, filament.", private=private)

    async def tick(args):
        ran.append(("tick", args["item"]))
        return ToolResult(f"Ticked {args['item']}.", step="ticked it")

    async def beep(args):
        ran.append(("beep", ""))
        return ToolResult("Beeped.")

    return Pack(
        "shopping",
        "the shopping list",
        [
            Tool("show_list", "Shows the shopping list.", show),
            Tool(
                "tick_item",
                "Ticks an item off.",
                tick,
                {"item": {"type": "string"}},
                ["item"],
                effect="change",
                ask="tick '{item}' off the list",
            ),
            Tool("beep", "Beeps the printer.", beep, effect="act"),
        ],
        words=["shopping", "list"],
        questions=["what do we need from the shops"],
        cases=[EvalCase("What's on the shopping list?", "show_list")],
    )


def house_pack() -> Pack:
    async def lamp(args):
        return ToolResult("The lamp is on.")

    return Pack(
        "house",
        "the house",
        [
            Tool(
                "lamp_on",
                "Turns a lamp on.",
                lamp,
                {"name": {"type": "string"}},
                ["name"],
                effect="act",
            )
        ],
        words=["lamp"],
        questions=["switch the lights on in the lounge"],
        systems=["home_assistant"],
        cases=[EvalCase("Turn the lamp on", "lamp_on", {"name": "lamp"})],
    )


__all__ = ["Clock", "make", "shopping_pack", "house_pack"]
