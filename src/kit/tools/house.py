"""The ``house`` pack: lights, switches, climate, scenes, covers, locks and who's
home, through Home Assistant (kit.house). Kit sees only what Home Assistant exposes
to Assist. Locks and alarms always ask first (``house_secure``); the garage asks
every time and blinds don't (``house_cover``); the aircon or heating asks once a
day per unit (``house.climate_confirm_daily``); unlocking or disarming is refused
from the phone unless ``house.secure_from_phone`` is on. Loaded only once
``house.enabled`` is on with a token. See docs/2 How Kit Works/The House.md."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from kit.house.client import HouseError
from kit.house.model import Entity
from kit.tools import EvalCase, Pack, Tool, ToolResult

if TYPE_CHECKING:
    from kit.brain import Brain
    from kit.settings import Settings

CLIMATE_OK_KEY = "house_climate_ok"  # {entity: the day Dan last said yes to it}
SWITCHABLE = ("light", "switch", "fan", "input_boolean", "media_player", "script", "automation")
SECURE = {"lock": ("lock", "unlock"), "alarm_control_panel": ("arm", "disarm")}
# Things house_set won't touch, and the tool that does them (and may ask first).
ELSEWHERE = {
    "lock": "house_secure",
    "alarm_control_panel": "house_secure",
    "cover": "house_cover",
    "climate": "house_climate",
}
ELSEWHERE_DOMAINS = tuple(ELSEWHERE)
COVER_ACTIONS = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"}
OUT_OF_REACH = "The house is out of reach: Home Assistant isn't answering ({why})."


def _garage(e: Entity) -> bool:
    return (
        "garage" in e.id
        or "garage" in e.name.lower()
        or (e.attributes.get("device_class") == "garage")
    )


def house_pack(brain: Brain) -> Pack:
    def house():
        return brain.house

    def owner() -> str:
        return brain.settings().persona.owner

    def out_of_reach() -> ToolResult:
        why = house().client.last_error or "not connected"
        return ToolResult(OUT_OF_REACH.format(why=why), ok=False)

    def resolve(name: str, domains: tuple[str, ...] = ()) -> tuple[Entity | None, str]:
        """One thing for ``name``, or why not (none, or which of several)."""
        found = house().find(name, brain.register, domains)
        if not found:
            kinds = f" ({', '.join(domains)})" if domains else ""
            return None, (
                f"Nothing{kinds} in the house matches '{name}'. Only what Home Assistant "
                "exposes to Assist is visible; try house_find."
            )
        if len(found) > 1:
            listed = "; ".join(e.line() for e in found[:8])
            return None, f"'{name}' could be several: {listed}. Ask {owner()} which one."
        return found[0], ""

    def climate_ok() -> dict:
        try:
            return json.loads(brain.memory.self_value(CLIMATE_OK_KEY) or "{}")
        except ValueError:
            return {}

    def today() -> str:
        return brain.memory.clock().date().isoformat()

    async def service(domain: str, name: str, entity: Entity, data: dict | None = None) -> str:
        await house().client.call_service(domain, name, data, entity.id)
        return ""

    async def house_find(args: dict) -> ToolResult:
        if not house().reachable and not house().entities:
            return out_of_reach()
        query = str(args.get("query", "")).strip()
        found = house().find(query, brain.register) if query else []
        if not query:
            rooms = sorted({e.area or "no room" for e in house().entities.values()})
            return ToolResult(
                f"{len(house().entities)} things in the house, in: {', '.join(rooms)}."
            )
        if not found:
            return ToolResult(f"Nothing in the house matches '{query}'.", ok=True)
        stale = "" if house().reachable else " (Home Assistant is out of reach: states may be old)"
        return ToolResult(
            "In the house" + stale + ":\n" + "\n".join(f"- {e.line()}" for e in found[:15]),
            step="looked around the house",
        )

    async def house_state(args: dict) -> ToolResult:
        if not house().reachable:
            return out_of_reach()
        entity, why = resolve(str(args.get("entity", "")))
        if entity is None:
            return ToolResult(why, ok=False)
        return ToolResult(entity.line(), step=f"checked the {entity.name}")

    async def house_set(args: dict) -> ToolResult:
        if not house().reachable:
            return out_of_reach()
        entity, why = resolve(str(args.get("entity", "")), SWITCHABLE + ELSEWHERE_DOMAINS)
        if entity is None:
            return ToolResult(why, ok=False)
        if entity.domain in ELSEWHERE:
            return ToolResult(
                f"The {entity.name} isn't switched: use {ELSEWHERE[entity.domain]}.", ok=False
            )
        on = args.get("on")
        on = True if on is None else bool(on)
        data: dict[str, Any] = {}
        if entity.domain == "light" and on:
            if args.get("brightness") is not None:
                data["brightness_pct"] = max(1, min(100, int(args["brightness"])))
            if args.get("colour"):
                data["color_name"] = str(args["colour"]).strip().lower()
        try:
            if entity.domain == "script":
                await service("script", "turn_on", entity)
            elif entity.domain == "automation":
                await service("automation", "trigger" if on else "turn_off", entity)
            else:
                await service(entity.domain, "turn_on" if on else "turn_off", entity, data)
        except HouseError as e:
            return ToolResult(f"It didn't happen: {e}", ok=False)
        done = f"turned the {entity.name} {'on' if on else 'off'}"
        if data.get("brightness_pct"):
            done += f" at {data['brightness_pct']}%"
        return ToolResult(f"Done: {done}.", step=done)

    def climate_asks(args: dict, settings: Settings) -> bool:
        if kind_asks(args, settings, ("climate",)):
            return True
        if not settings.house.climate_confirm_daily or house() is None:
            return False
        found = house().find(str(args.get("entity", "")), brain.register, ("climate",))
        if len(found) != 1:
            return False  # it'll come back asking which one, and run nothing
        return climate_ok().get(found[0].id) != today()

    async def house_climate(args: dict) -> ToolResult:
        if not house().reachable:
            return out_of_reach()
        entity, why = resolve(str(args.get("entity", "")), ("climate",))
        if entity is None:
            return ToolResult(why, ok=False)
        done = []
        try:
            mode = str(args.get("mode") or "").strip().lower()
            if mode:
                await service("climate", "set_hvac_mode", entity, {"hvac_mode": mode})
                done.append(f"set to {mode}")
            if args.get("temperature") is not None:
                temperature = float(args["temperature"])
                await service("climate", "set_temperature", entity, {"temperature": temperature})
                done.append(f"set to {temperature:g}°")
        except (HouseError, ValueError) as e:
            return ToolResult(f"It didn't happen: {e}", ok=False)
        if not done:
            return ToolResult("Give a temperature or a mode (off, cool, heat, auto).", ok=False)
        ok = climate_ok()
        ok[entity.id] = today()
        brain.memory.set_self_value(CLIMATE_OK_KEY, json.dumps(ok))
        line = f"the {entity.name} {' and '.join(done)}"
        return ToolResult(f"Done: {line}.", step=line)

    async def house_scene(args: dict) -> ToolResult:
        if not house().reachable:
            return out_of_reach()
        entity, why = resolve(str(args.get("scene", "")), ("scene",))
        if entity is None:
            return ToolResult(why, ok=False)
        try:
            await service("scene", "turn_on", entity)
        except HouseError as e:
            return ToolResult(f"It didn't happen: {e}", ok=False)
        return ToolResult(f"Done: the {entity.name} scene is on.", step=f"set {entity.name}")

    def kind_asks(args: dict, settings: Settings, domains: tuple[str, ...]) -> bool:
        """Whether the thing meant is a kind ``house.confirm`` says always asks."""
        if house() is None or not settings.house.confirm:
            return False
        found = house().find(str(args.get("entity", "")), brain.register, domains)
        return any(e.domain in settings.house.confirm for e in found)

    def set_asks(args: dict, settings: Settings) -> bool:
        return kind_asks(args, settings, SWITCHABLE)

    def cover_asks(args: dict, settings: Settings) -> bool:
        if house() is None:
            return False
        if kind_asks(args, settings, ("cover",)):
            return True
        found = house().find(str(args.get("entity", "")), brain.register, ("cover",))
        return any(_garage(e) for e in found) or "garage" in str(args.get("entity", "")).lower()

    async def house_cover(args: dict) -> ToolResult:
        if not house().reachable:
            return out_of_reach()
        entity, why = resolve(str(args.get("entity", "")), ("cover",))
        if entity is None:
            return ToolResult(why, ok=False)
        action = str(args.get("action", "")).strip().lower()
        if action not in COVER_ACTIONS:
            return ToolResult("The action is open, close or stop.", ok=False)
        try:
            await service("cover", COVER_ACTIONS[action], entity)
        except HouseError as e:
            return ToolResult(f"It didn't happen: {e}", ok=False)
        verb = {"open": "opening", "close": "closing", "stop": "stopped"}[action]
        return ToolResult(f"Done: the {entity.name} is {verb}.", step=f"{action} the {entity.name}")

    async def house_secure(args: dict) -> ToolResult:
        from kit.brain import CHANNEL

        if not house().reachable:
            return out_of_reach()
        entity, why = resolve(str(args.get("entity", "")), tuple(SECURE))
        if entity is None:
            return ToolResult(why, ok=False)
        action = str(args.get("action", "")).strip().lower()
        if action not in SECURE[entity.domain]:
            return ToolResult(
                f"For the {entity.name} the action is {' or '.join(SECURE[entity.domain])}.",
                ok=False,
            )
        if (
            action in ("unlock", "disarm")
            and CHANNEL.get() == "phone"
            and not brain.settings().house.secure_from_phone
        ):
            return ToolResult(
                f"Not done: {action}ing from the phone is off (house.secure_from_phone). "
                f"Tell {owner()} it has to be done at home.",
                ok=False,
            )
        try:
            if entity.domain == "lock":
                await service("lock", action, entity)
            else:
                code = {"arm": "alarm_arm_away", "disarm": "alarm_disarm"}[action]
                await service("alarm_control_panel", code, entity)
        except HouseError as e:
            return ToolResult(f"It didn't happen: {e}", ok=False)
        done = f"{action}ed the {entity.name}" if action != "arm" else f"armed the {entity.name}"
        return ToolResult(f"Done: {done}.", step=done)

    async def who_is_home(args: dict) -> ToolResult:
        if not house().reachable:
            return out_of_reach()
        people = [e for e in house().entities.values() if e.domain == "person"]
        if not people:
            return ToolResult("Home Assistant shows no people to Kit (none exposed).")
        lines = [
            f"- {e.name}: {'home' if e.state == 'home' else e.state.replace('_', ' ')}"
            for e in people
        ]
        return ToolResult("Who's home:\n" + "\n".join(lines), step="checked who's home")

    def configured() -> bool:
        return brain.house is not None

    def reachable() -> bool:
        return brain.house is not None and brain.house.reachable

    entity_arg = {"entity": {"type": "string", "description": "The thing's name or id."}}
    return Pack(
        "house",
        "the house: lights, switches, climate, scenes, locks, through Home Assistant",
        words=[
            "light",
            "lights",
            "lamp",
            "turn on",
            "turn off",
            "switch on",
            "switch off",
            "aircon",
            "ac",
            "heater",
            "heating",
            "thermostat",
            "temperature inside",
            "lock",
            "unlock",
            "garage",
            "blinds",
            "scene",
            "who's home",
            "is anyone home",
            "home assistant",
        ],  # fmt: skip
        questions=[
            "Turn the study lamp off",
            "Is the AC on?",
            "Set the heater to 21",
            "Lock the front door",
            "Close the garage",
            "Who's home?",
            "Movie scene please",
        ],
        systems=["home_assistant"],
        cases=[
            EvalCase("Turn the study lamp off", "house_set", {"entity": "lamp", "on": False}),
            EvalCase("Is the aircon on?", "house_state", {"entity": "air"}),
            EvalCase("Lock the front door", "house_secure", {"entity": "door", "action": "lock"}),
            EvalCase("Who's home?", "who_is_home"),
        ],
        tools=[
            Tool(
                "house_find",
                "Find things in the house (lights, switches, sensors, climate, covers, locks) "
                "by name, room or kind, with their state. Empty query: how many and which rooms.",
                house_find,
                {"query": {"type": "string", "description": "Words, like 'shed lights'."}},
                offered=configured,
                examples=[{"query": "study lamp"}, {"query": "lights in the lounge"}],
            ),
            Tool(
                "house_state",
                "The state of one thing in the house, with what matters (brightness, room "
                "and set temperature, battery).",
                house_state,
                entity_arg,
                ["entity"],
                offered=reachable,
                examples=[{"entity": "aircon"}],
            ),
            Tool(
                "house_set",
                "Turn a light, switch, fan or script on or off. brightness is 0-100; colour "
                "a colour name. Not for locks, covers or climate.",
                house_set,
                {
                    **entity_arg,
                    "on": {"type": "boolean", "description": "true on, false off."},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
                    "colour": {"type": "string"},
                },
                ["entity", "on"],
                effect="act",
                offered=reachable,
                speak="You're about to switch something in the house. Say so in a few words.",
                ask="switch the {entity}",
                confirm_if=set_asks,
                examples=[{"entity": "study lamp", "on": False}],
            ),
            Tool(
                "house_climate",
                "Set the heating or air conditioning: a temperature, a mode (off, cool, "
                "heat, auto), or both.",
                house_climate,
                {
                    **entity_arg,
                    "temperature": {"type": "number"},
                    "mode": {
                        "type": "string",
                        "enum": ["off", "cool", "heat", "heat_cool", "auto", "dry", "fan_only"],
                    },
                },
                ["entity"],
                effect="act",
                offered=reachable,
                ask="change the {entity}",
                confirm_if=climate_asks,
                examples=[{"entity": "aircon", "temperature": 23}],
            ),
            Tool(
                "house_scene",
                "Turn on a Home Assistant scene by name.",
                house_scene,
                {"scene": {"type": "string", "description": "The scene's name."}},
                ["scene"],
                effect="act",
                offered=reachable,
            ),
            Tool(
                "house_cover",
                "Open, close or stop a garage door, blind or curtain. The garage always "
                "asks first.",
                house_cover,
                {**entity_arg, "action": {"type": "string", "enum": list(COVER_ACTIONS)}},
                ["entity", "action"],
                effect="act",
                offered=reachable,
                ask="{action} the {entity}",
                confirm_if=cover_asks,
            ),
            Tool(
                "house_secure",
                "Lock or unlock a lock, or arm or disarm the alarm. Always asks first.",
                house_secure,
                {
                    **entity_arg,
                    "action": {"type": "string", "enum": ["lock", "unlock", "arm", "disarm"]},
                },
                ["entity", "action"],
                effect="change",
                offered=reachable,
                ask="{action} the {entity}",
            ),
            Tool(
                "who_is_home",
                "Who Home Assistant says is home or away.",
                who_is_home,
                offered=reachable,
            ),
        ],
    )
