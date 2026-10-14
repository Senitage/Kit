"""The ``core`` pack: the look-ups Kit has always been able to do mid-answer, as
tools. Search his memory, look at what's on the PC, look around through his eyes,
fetch the forecast, open one of Dan's notes. Each wraps what the brain did for the
matching ``action``, so a cloud model calling the tool and the local model picking
the action end up in the same place (kit.brain, the tool loop)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from kit.memory import CONVERSATION, DAYS, FACTS, SELF
from kit.prompt import recall_results, weather_results
from kit.tools import Pack, Tool, ToolResult
from kit.weather import WeatherError

if TYPE_CHECKING:
    from kit.brain import Brain

NOTES = "notes"
SEEN = "seen"
THINGS = "things"
DEEP_RECALL = 10

# The reply actions these tools replace, and the argument the action's text fills.
ACTION_ARGS = {
    "recall": "query",
    "look_at_pc": None,
    "look_around": None,
    "weather": "place",
    "read_note": "name",
}


def core_pack(brain: Brain) -> Pack:
    """The core pack for ``brain``. Looks are offered only where there's something to
    look at and it hasn't been looked at this turn (``brain.tool_context``)."""

    def owner() -> str:
        return brain.settings().persona.owner

    async def recall(args: dict) -> ToolResult:
        query = str(args.get("query", "")).strip()
        hits = await brain.recall.search(
            query, [FACTS, DAYS, CONVERSATION, THINGS, SELF, NOTES, SEEN], DEEP_RECALL
        )
        return ToolResult(
            recall_results(query, hits, owner()),
            event={"type": "recalled", "query": query, "found": len(hits)},
            step=f"looked through your memory for '{query}'",
        )

    async def look_at_pc(args: dict) -> ToolResult:
        return ToolResult(
            f"What you can see on {owner()}'s PC:\n{brain.pc.detail(owner())}",
            event={"type": "looked_at_pc", "online": brain.pc.online()},
            step="looked at what's open on your PC",
        )

    async def look_around(args: dict) -> ToolResult:
        return ToolResult(
            f"What you can see:\n{brain.scene.detail(owner())}",
            event={"type": "looked_around", "in_view": brain.scene.in_view()},
            step="had a look around",
        )

    async def weather(args: dict) -> ToolResult:
        settings = brain.settings()
        place = str(args.get("place", "")).strip() or settings.persona.location
        if brain.weather is None:
            return ToolResult("There's no forecast source set up.", ok=False)
        try:
            forecast = await brain.weather.forecast(place, settings.persona.country)
        except WeatherError as e:
            forecast = f"The forecast lookup failed: {e}"
        brain.forecast_fetched()
        return ToolResult(
            weather_results(place, forecast, owner()),
            event={"type": "weather", "place": place},
            step=f"checked the forecast for {place}",
        )

    async def read_note(args: dict) -> ToolResult:
        name = str(args.get("name", "")).strip()
        text = await asyncio.to_thread(brain._read_note, name, brain.settings())
        return ToolResult(
            text,
            event={"type": "reading_note", "note": name},
            step=f"read your note '{name}'",
        )

    def ctx():
        return brain.tool_context

    return Pack(
        "core",
        "your memory, the PC, the room, the forecast, one of the owner's notes",
        [
            Tool(
                "recall",
                "Search your memory: past conversations, facts you were told, the owner's "
                "notes, the register of things, your own notebook. Use it when the owner "
                "refers to something from before (a project, a person, where something is "
                "kept) that isn't already in front of you. Put the words to search for "
                "(names, topics, places), not a sentence to say.",
                recall,
                {"query": {"type": "string", "description": "What to search for."}},
                ["query"],
                examples=[{"query": "tax returns folder"}, {"query": "Pod neck servo"}],
                speak="You're about to look back through your memory for '{query}'. Say a "
                "few words while you do, your own way (like 'Let me think...').",
            ),
            Tool(
                "look_at_pc",
                "See everything on the owner's PC right now: every open window, what has had "
                "focus this hour and today, and how the PC is coping. Use it when the one "
                "line about the PC isn't enough to answer.",
                look_at_pc,
                offered=lambda: ctx().pc and not ctx().pc_detail,
                speak="You're about to have a look at {owner}'s PC. Say so in a few words.",
            ),
            Tool(
                "look_around",
                "See everything your eyes can see: who's at the desk and what they're doing "
                "or holding, what else is in view, what's happened lately, who's been in "
                "today. Use it when the one line about the room isn't enough.",
                look_around,
                offered=lambda: ctx().scene and not ctx().scene_detail and not ctx().pc_detail,
                speak="You're about to have a proper look around. Say so in a few words.",
            ),
            Tool(
                "weather",
                "The forecast for a place: now and the next few days, from the weather "
                "service, never from memory. Use it for any question about the weather, "
                "temperature, rain or wind. Leave place empty for where the owner is.",
                weather,
                {"place": {"type": "string", "description": "A town or city, or empty for home."}},
                examples=[{"place": ""}, {"place": "Richmond"}],
                offered=lambda: ctx().weather and not ctx().forecast,
                speak="You're about to check the forecast. Say so in a few words.",
            ),
            Tool(
                "read_note",
                "Open one of the owner's notes by name and read it whole. Use it when they "
                "ask what's in a note, or to check, summarise or use one. To find notes about "
                "something without knowing which, use recall instead.",
                read_note,
                {"name": {"type": "string", "description": "The note's name or path."}},
                ["name"],
                examples=[{"name": "Holiday planner"}],
                offered=lambda: ctx().notes and not ctx().note_done,
                speak="You're about to open {owner}'s note '{name}'. Say so in a few words.",
            ),
        ],
    )
