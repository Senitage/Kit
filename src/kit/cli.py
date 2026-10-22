"""The ``kit`` command."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import time
import tomllib
from datetime import datetime
from importlib import resources
from pathlib import Path

import httpx

from kit import checks, docs_check
from kit.checks import CheckResult, Status
from kit.credentials import api_token, app_token, cloud_api_key, home_assistant_token
from kit.memory import FACT_KINDS
from kit.paths import KitPaths
from kit.prices import PRICES_FILE, Prices
from kit.settings import (
    Settings,
    SettingsError,
    load_settings,
    local_settings,
    settings_to_toml,
)
from kit.settings_store import SettingsStore
from kit.things import SYSTEMS, THING_KINDS

CHECK_NAMES = ["data", "gpu", "ollama", "tailscale", "nas", "files", "house", "apps"]
CHECK_NAMES += ["cloud", "prices", "eyes"]


def cmd_paths(paths: KitPaths) -> int:
    print(f"data folder:   {paths.root}")
    print(f"settings file: {paths.settings_file}")
    print(f"secrets:       {paths.secrets_dir}")
    print(f"state:         {paths.state_dir}")
    print(f"logs:          {paths.logs_dir}")
    return 0


def cmd_init(paths: KitPaths) -> int:
    paths.ensure()
    if paths.settings_file.exists():
        print(f"kept existing {paths.settings_file}")
    else:
        example = resources.files("kit").joinpath("settings.example.toml")
        with resources.as_file(example) as src:
            shutil.copyfile(src, paths.settings_file)
        print(f"wrote {paths.settings_file}; edit it to add your NAS shares")
    print(f"Kit's data folder is ready at {paths.root}")
    return 0


def run_checks(paths: KitPaths, skip: set[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        settings = load_settings(paths.settings_file)
    except SettingsError as e:
        return [CheckResult("settings", Status.FAIL, str(e))]
    if "data" not in skip:
        results.append(checks.check_data_dir(paths))
    if "gpu" not in skip:
        results.append(checks.check_gpu())
    if "ollama" not in skip:
        with httpx.Client() as client:
            results.append(checks.check_ollama(settings, client))
    if "tailscale" not in skip:
        results.append(checks.check_tailscale())
    if "nas" not in skip:
        results.extend(checks.check_nas(settings))
    if "files" not in skip:
        results.extend(checks.check_files(settings))
    if "house" not in skip:
        results.append(checks.check_house(settings, home_assistant_token(paths)))
    if "apps" not in skip:
        results.extend(checks.check_apps(settings, lambda n, s: app_token(paths, n, s)))
    if "cloud" not in skip:
        results.extend(checks.check_cloud(settings, lambda p: cloud_api_key(paths, p)))
    if "prices" not in skip:
        results.append(checks.check_prices(settings, Prices(paths.state_dir / PRICES_FILE)))
    if "eyes" not in skip:
        results.append(checks.check_eyes(settings))
    return results


def print_report(results: list[CheckResult]) -> None:
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"[{r.status.value}] {r.name.ljust(width)}  {r.detail}")
    failed = sum(r.status is Status.FAIL for r in results)
    print()
    print("All checks passed." if not failed else f"{failed} check(s) failed.")


def parse_value(text: str):
    """A TOML value if it reads as one (42, true, ['a', 'b']), else plain text."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


def nested_patch(settings: Settings, keys: list[str], value) -> dict:
    """A change to one setting, however deep (models.sonnet.effort). Deeper tables
    are sent whole, with the one value changed, because a change replaces a
    section's fields whole."""
    section = keys[0]
    if len(keys) == 2:
        return {section: {keys[1]: value}}
    current = settings.model_dump(mode="json").get(section)
    if not isinstance(current, dict):
        current = {}
    table = current.get(keys[1])
    table = dict(table) if isinstance(table, dict) else {}
    node = table
    for key in keys[2:-1]:
        node[key] = dict(node[key]) if isinstance(node.get(key), dict) else {}
        node = node[key]
    node[keys[-1]] = value
    return {section: {keys[1]: table}}


async def _weather(paths: KitPaths, place: str | None) -> int:
    """Print the forecast exactly as Kit is given it."""
    from kit.weather import Weather, WeatherError

    persona = SettingsStore(paths).current().persona
    async with httpx.AsyncClient() as client:
        try:
            print(await Weather(client).forecast(place or persona.location, persona.country))
        except WeatherError as e:
            print(e)
            return 1
    return 0


def cmd_models(paths: KitPaths, args: argparse.Namespace) -> int:
    """Show the models Kit can use, with today's prices, and which one does what;
    switch a role; add or remove a model; or fetch the prices now."""
    store = SettingsStore(paths)
    prices = Prices(paths.state_dir / PRICES_FILE)
    action = args.action
    try:
        if action in ("chat", "work", "expert"):
            if args.name is None:
                print(f"give a model name too, for example: kit models {action} sonnet")
                return 2
            store.update({"routing": {action: args.name}}, "cli")
            print(f"{action} now uses {args.name}; Kit uses it from the next message")
            return 0
        if action == "add":
            return _add_model(store, prices, args)
        if action == "remove":
            return _remove_model(store, args.name)
    except SettingsError as e:
        print(e)
        return 1
    if action == "prices":
        return asyncio.run(_fetch_prices(prices))
    s = store.current()
    roles: dict[str, list[str]] = {}
    in_use = (["chat"] if s.routing.mode == "cloud-only" else []) + ["work", "expert"]
    for role in in_use:
        roles.setdefault(getattr(s.routing, role), []).append(role)
    print(f"routing: {s.routing.mode}   local model: {s.ollama.model}")
    print(f"cloud budget: A${s.cloud.monthly_cap_aud:.2f} a month")
    print(f"{prices.table.line()}\n")
    print(
        f"  {'name':<14} {'role':<13} {'provider':<10} {'model':<20} {'effort':<7}"
        f" {'A$ in/out per M':<17} {'search/1k'}"
    )
    rate = prices.table.aud_per_usd
    for name, m in s.models.items():
        price = prices.price_of(m.model, m.provider)
        if m.provider == "ollama":
            cost, search = "free (local)", "off"
        elif price is None:
            cost, search = "no price yet", "?"
        else:
            cost = f"{price.input_per_mtok * rate:.2f}/{price.output_per_mtok * rate:.2f}"
            search = f"A${price.search_per_k * rate:.2f}" if m.web_search else "off"
        print(
            f"  {name:<14} {', '.join(roles.get(name, [])):<13} {m.provider:<10} {m.model:<20}"
            f" {m.effort:<7} {cost:<17} {search}"
        )
    print(
        "\nSwitch:  kit models work <name>"
        "\nAdd:     kit models add <name> --provider anthropic --model <id>"
        "\nRemove:  kit models remove <name>"
        "\nPrices:  kit models prices   (fetched daily while Kit runs)"
    )
    return 0


def _add_model(store: SettingsStore, prices: Prices, args: argparse.Namespace) -> int:
    """``kit models add NAME --provider P --model ID [...]``: only what's given is
    written, so the rest takes the profile's defaults."""
    if not (args.name and args.provider and args.model):
        print("give a name, --provider and --model, for example:")
        print("  kit models add sonnet-6 --provider anthropic --model claude-sonnet-6")
        return 2
    if args.name in store.current().models:
        print(f"there's a model called {args.name} already; remove it first, or pick a name")
        return 1
    profile: dict = {"provider": args.provider, "model": args.model}
    for field in ("label", "effort", "max_tokens"):
        if getattr(args, field) is not None:
            profile[field] = getattr(args, field)
    if args.no_thinking:
        profile["thinking"] = False
    if args.no_search:
        profile["web_search"] = False
    store.update({"models": {args.name: profile}}, "cli")
    print(f"added {args.name} ({args.provider} {args.model})")
    if args.provider != "ollama" and prices.price_of(args.model, args.provider) is None:
        print(
            f"no price known for {args.model} yet: its calls count as free in the budget until "
            "the price list has it (kit models prices fetches today's)"
        )
    print(f"use it with: kit models work {args.name}")
    return 0


def _remove_model(store: SettingsStore, name: str | None) -> int:
    if not name:
        print("say which model to remove, for example: kit models remove gpt-sol")
        return 2
    s = store.current()
    if name not in s.models:
        print(f"there's no model called {name} ({', '.join(s.models)})")
        return 1
    using = [role for role in ("chat", "work", "expert") if getattr(s.routing, role) == name]
    if using:
        print(f"{name} is the {' and '.join(using)} model; point that at another model first")
        return 1
    store.update({"models": {name: None}}, "cli")
    print(f"removed {name}")
    return 0


async def _fetch_prices(prices: Prices) -> int:
    """``kit models prices``: fetch today's price list and exchange rate now."""
    async with httpx.AsyncClient() as client:
        prices.client = client
        problems = await prices.refresh()
    for problem in problems:
        print(problem)
    print(prices.table.line())
    return 1 if problems else 0


def cmd_speech(paths: KitPaths, args: argparse.Namespace, launcher=None) -> int:
    """Kit's voice: show the engines, switch one, turn speech on or off, try a line,
    or compare engines side by side."""
    from kit.speech.service import SpeechError, SpeechService

    store = SettingsStore(paths)
    action = args.action or "show"
    try:
        if action == "use":
            store.update({"speech": {"engine": args.engine}}, "cli")
            print(f"Kit now speaks with {args.engine}; it loads in the background")
            return 0
        if action in ("on", "off"):
            store.update({"speech": {"enabled": action == "on"}}, "cli")
            print(f"speech is {action}")
            return 0
    except SettingsError as e:
        print(e)
        return 1
    s = store.current().speech
    if action == "show":
        fallback = f"   fallback: {s.fallback}" if s.fallback else ""
        print(f"speech: {'on' if s.enabled else 'off'}   engine: {s.engine}{fallback}\n")
        print(f"  {'name':<18} {'kind':<17} {'python':<28} voice")
        for name, e in s.engines.items():
            mark = "*" if name == s.engine else " "
            voice = e.voice or e.reference or "-"
            python = e.python or "(Kit's own)"
            print(f"{mark} {name:<18} {e.kind:<17} {python:<28} {voice}")
        print("\nSwitch with: kit speech use <name>")
        print('Try one:     kit speech say "Hello" --engine <name> --mood happy')
        print("Compare:     kit speech bench --engines chatterbox-turbo kokoro")
        return 0
    # A separate port, so this doesn't disturb the engine Kit's server is running.
    kwargs = {"launcher": launcher} if launcher else {}
    service = SpeechService(lambda: store.current().speech, paths, port_offset=1, **kwargs)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        if action == "say":
            return _speech_say(paths, service, args, stamp)
        from kit.speech.bench import run_bench

        out_dir = paths.state_dir / "speech" / "bench" / stamp
        run_bench(service, args.engines or [s.engine], out_dir)
        print(f"\nListen and compare: {out_dir / 'index.html'}")
        return 0
    except SpeechError as e:
        print(e)
        return 1
    finally:
        service.stop()


def _speech_say(paths: KitPaths, service, args: argparse.Namespace, stamp: str) -> int:
    from kit.speech.bench import join_wavs
    from kit.speech.sentences import SentenceSplitter

    engine = args.engine or service.settings().engine
    print(f"loading {engine}...")
    service.ensure(engine)
    print(f"  ready in {service.load_s:.1f} s on {service.health.get('device')}")
    if service.note:
        print(f"  note: {service.note}")
    splitter = SentenceSplitter()
    clips = []
    for n, piece in enumerate(splitter.feed(args.text + " ") + splitter.flush()):
        spoken = service.speak(piece, args.mood, engine, first=n == 0)
        clips.append(spoken.wav)
        print(f"  {spoken.synth_ms / 1000:5.2f} s to make {spoken.audio_ms / 1000:4.1f} s: {piece}")
    folder = paths.state_dir / "speech" / "said"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{stamp}-{engine}.wav"
    out.write_bytes(join_wavs(clips))
    print(f"saved {out}")
    return 0


def cmd_config(paths: KitPaths, args: argparse.Namespace) -> int:
    store = SettingsStore(paths)
    try:
        if args.action == "show":
            print(settings_to_toml(store.current()), end="")
        elif args.action == "schema":
            print(json.dumps(Settings.model_json_schema(), indent=2))
        elif args.action == "set":
            keys = args.key.split(".")
            if len(keys) < 2 or not all(keys):
                print("use section.field, for example persona.name or models.sonnet.effort")
                return 2
            store.update(nested_patch(store.current(), keys, parse_value(args.value)), "cli")
            print(f"set {args.key}; Kit uses it from the next message")
        elif args.action == "undo":
            store.undo()
            print("went back to the previous settings")
        elif args.action == "reset":
            store.replace(Settings(), "cli reset")
            print("settings are back to the defaults; `kit config undo` brings yours back")
        elif args.action == "history":
            versions = store.history()
            if not versions:
                print("no earlier versions yet")
            for v in versions:
                print(f"{v.id}  (before a change by {v.changed_by})")
        elif args.action == "restore":
            store.restore(args.version, "cli")
            print(f"restored {args.version}")
        elif args.action == "check":
            load_settings(paths.settings_file)
            print(f"{paths.settings_file} is valid")
    except SettingsError as e:
        print(e)
        return 1
    if store.problem and args.action != "check":
        print(f"\nwarning: {store.problem}")
    return 0


def cmd_token(paths: KitPaths) -> int:
    paths.ensure()
    print(api_token(paths))
    return 0


def setup_logging(paths: KitPaths) -> None:
    """Warnings and errors go to logs/kit.log (rotated), so a bad night is visible later."""
    import logging
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(
        paths.logs_dir / "kit.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _runtime(paths: KitPaths, client: httpx.AsyncClient):
    from kit.brain import Brain
    from kit.embed import OllamaEmbedder
    from kit.local_model import OllamaModel
    from kit.memory import Memory
    from kit.recall import Recall
    from kit.weather import Weather

    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db")
    model = OllamaModel(lambda: local_settings(store.current()), client)
    cloud = make_cloud(paths, memory, client)
    recall = Recall(memory, OllamaEmbedder(store.current, client), store.current)
    weather = Weather(client)
    return store, memory, Brain(store.current, memory, model, cloud, recall, weather)


def make_cloud(paths: KitPaths, memory, client: httpx.AsyncClient):
    from kit.cloud import AnthropicProvider, Cloud, GoogleProvider, OpenAIProvider

    providers = {
        "anthropic": AnthropicProvider(),
        "openai": OpenAIProvider(client),
        "google": GoogleProvider(client),
    }
    prices = Prices(paths.state_dir / PRICES_FILE, client)
    return Cloud(memory, lambda provider: cloud_api_key(paths, provider), providers, prices)


def cmd_serve(paths: KitPaths, args: argparse.Namespace) -> int:
    import uvicorn

    from kit.server import create_app

    paths.ensure()
    setup_logging(paths)
    client = httpx.AsyncClient()
    store, memory, brain = _runtime(paths, client)
    settings = store.current()
    if store.problem:
        print(f"warning: {store.problem}\n")
    host = args.host or settings.brain.host
    port = args.port or settings.brain.port
    token = api_token(paths)
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"{settings.persona.name} is listening.")
    print(f"  chat:     http://{shown}:{port}/#token={token}")
    print(f"  settings: http://{shown}:{port}/settings#token={token}")
    from kit.speech.service import SpeechService

    speech = SpeechService(lambda: store.current().speech, paths)
    app = create_app(store, memory, brain, token, paths=paths, speech=speech)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


async def _chat_loop(paths: KitPaths) -> int:
    async with httpx.AsyncClient() as client:
        store, memory, brain = _runtime(paths, client)
        name = store.current().persona.name
        if store.problem:
            print(f"warning: {store.problem}\n")
        print(f"Talking to {name}. Ctrl+C or an empty line to stop.")
        print("You can keep typing while a slow answer is on its way.")
        me = name.lower()
        turns: set[asyncio.Task] = set()

        async def turn(text: str) -> None:
            print(f"{me}> ", end="", flush=True)
            since = brain.life.state()["last_event"]
            async for event in brain.chat(text, "terminal"):
                _print_event(event, me)
            await brain.settle()  # what he learned once the reply was out
            for event in brain.life.events_after(since):
                if event["type"] == "remembered":
                    _print_event(event, me)

        while True:
            try:
                text = await asyncio.to_thread(input, "you> ")
            except (EOFError, KeyboardInterrupt):
                break
            if not text.strip():
                break
            before = set(brain.jobs)
            task = asyncio.create_task(turn(text))
            turns.add(task)
            task.add_done_callback(turns.discard)
            # Wait for the answer, or until it's gone off to a cloud model.
            await asyncio.sleep(0.05)
            while not task.done() and set(brain.jobs) <= before:
                await asyncio.sleep(0.05)
        if turns:
            print("(finishing what I was working on...)")
            await asyncio.gather(*turns, return_exceptions=True)
        memory.close()
    return 0


def _print_event(event: dict, me: str) -> None:
    kind = event["type"]
    if kind == "say":
        print(event["text"], end="", flush=True)
    elif kind == "reply":
        r = event["reply"]
        tags = [r["emotion"], *(s["gesture"] for s in r["segments"])]
        if event["source"] == "cloud":
            tags += [event["model"], f"${event['cost_usd']:.3f}"]
            if event["searches"]:
                tags.append(f"{event['searches']} search(es)")
        print(f"  [{' · '.join(t for t in tags if t != 'none')}]")
        if r.get("detail"):
            print(f"\n{r['detail']}\n")
    elif kind == "handing_off":
        print(f"\n{me}> (asking {event['to']}; keep chatting if you like)\n{me}> ", end="")
    elif kind == "notice":
        print(f"\n  ({event['message']})\n{me}> ", end="", flush=True)
    elif kind == "remembered":
        print(f"  (remembered: {event['fact']})")
    elif kind == "weather":
        print("  (checking the forecast)")
    elif kind == "thing_suggested":
        print(f"  (add to the register? {event['thing']['line']}  yes/no)")
    elif kind == "thing_updated" and event["thing"]:
        print(f"  (register: {event['thing']['line']})")
    elif kind == "error":
        print(f"\n  ! {event['message']}")


def _show_item(item) -> str:
    pin = "*" if item.pinned else " "
    return f"{item.id:>5}{pin} {item.day}  {item.kind:<10}  {item.text}"


def cmd_life(paths: KitPaths, action: str, transport: httpx.BaseTransport | None = None) -> int:
    """Kit's inner life lives in the running brain, so ask it over the API."""
    s = SettingsStore(paths).current().brain
    host = "127.0.0.1" if s.host in ("0.0.0.0", "::") else s.host
    headers = {"Authorization": f"Bearer {api_token(paths)}"}
    with httpx.Client(
        base_url=f"http://{host}:{s.port}", headers=headers, timeout=300, transport=transport
    ) as client:
        try:
            if action == "poke":
                r = client.post("/api/life/poke")
                r.raise_for_status()
                reply = r.json().get("reply")
                said = " ".join(seg["say"] for seg in reply["segments"]) if reply else None
                print(
                    f"Kit: {said}"
                    if said
                    else "Kit didn't say anything: the local model isn't answering, or all he "
                    "came up with was something he'd said lately (logs/kit.log says which)."
                )
                return 0
            if action == "think":
                r = client.post("/api/life/think")
                r.raise_for_status()
                _print_thought(r.json().get("thought"))
                return 0
            if action == "reflect":
                print("Kit is looking back on today so far...")
                r = client.post("/api/life/reflect")
                if r.status_code in (409, 503):
                    print(r.json().get("detail", r.text))
                    return 1
                r.raise_for_status()
                _print_reflection(r.json())
                return 0
            if action == "notebook":
                r = client.get("/api/life/notebook")
                r.raise_for_status()
                _print_notebook(r.json())
                return 0
            r = client.get("/api/life")
            r.raise_for_status()
        except httpx.HTTPError as e:
            print(f"can't reach Kit's brain at {client.base_url} ({e}). Is it running?")
            return 1
    state = r.json()
    print(f"mood:     {state['mood']}")
    if state.get("presence") and state["presence"] != "here":
        doing = f", {state['doing']}" if state.get("doing") else ""
        print(f"where:    {state['presence']}{doing}")
    if state.get("sleep"):
        wakes = state.get("wakes_at") or ""
        print(f"sleep:    {state['sleep']}, wakes by himself about {wakes[11:16] or 'soon'}")
    elif state.get("groggy"):
        print("sleep:    just woken up, still groggy")
    for line in state.get("slept_lately", [])[-6:]:
        print(f"slept:    {line}")
    felt = state.get("feeling")
    if felt:
        print(f"feeling:  {felt['name']}, because {felt['why']} (since {felt['since'][11:16]})")
    also = state.get("also_feeling")
    if also:
        print(f"also:     {also['name']}, because {also['why']}")
    if state.get("bad_night"):
        print("care:     you're having a rough time, so no cheek for now")
    print("drives:   " + ", ".join(f"{k} {v}" for k, v in state["drives"].items()))
    if state.get("thinking"):
        print(f"thinking: {state['thinking']}")
    for want in state.get("wants", [])[:3]:
        print(f"wants to: {want}")
    for want in state.get("later", [])[:3]:
        print(f"later:    {want['text']} (from {want['after'][:16].replace('T', ' ')})")
    for thread in state.get("threads", [])[:3]:
        when = "now" if thread["due"] else f"from {thread['after'][:16].replace('T', ' ')}"
        print(f"follows:  {thread['text']} (asks how it went {when})")
    print(f"quiet:    {state.get('quiet_because') or 'ready to pipe up'}")
    if state.get("closeness"):
        print(f"you two:  {state['closeness']}")
    if state.get("away_since") and state.get("presence") != "here":
        print(f"away:     since {state['away_since'][11:16]} (as far as Kit can tell)")
    if state.get("hello_owed"):
        print(f"hello:    owed ({state['hello_owed']}), said at the next chance")
    if state.get("goodbye"):
        print(f'goodbye:  "{state["goodbye"]}" (he\'ll ask how it went)')
    if state.get("did_today"):
        print("on his own today: " + "; ".join(state["did_today"]))
    if state.get("dials"):
        d = state["dials"]
        print(f"dials:    lively {d['arousal']}, happy {d['valence']}")
    if state.get("taken_up"):
        print("taken up: " + ", ".join(f"{k} {v}" for k, v in state["taken_up"].items()))
    if state.get("mood_reading"):
        print(f"reads you by: {state['mood_reading']}")
    print(f"last pipe-up: {state['last_piped_up'] or 'not yet'}")
    if "thoughts_this_hour" in state:
        print(
            f"thoughts: {state['thoughts_this_hour']} this hour, next one around "
            f"{state.get('next_thought', '')[11:16]} (sooner if something happens)"
        )
    print("quirks:   " + "; ".join(state.get("quirks", [])))
    return 0


def _print_thought(thought: dict | None) -> None:
    if not thought or not (thought.get("text") or thought.get("want")):
        print("Nothing came to mind (or the local model isn't answering).")
        return
    if thought.get("text"):
        kind = " (an opinion)" if thought.get("kind") == "opinion" else ""
        print(f"Kit thought{kind}: {thought['text']}")
    if thought.get("want"):
        print(f"He wants to: {thought['want']}")
    if thought.get("feeling"):
        print(f"He feels {thought['feeling']}: {thought.get('why', '')}")


def _print_reflection(done: dict) -> None:
    if done.get("first_sheet"):
        print("(he wrote his first self-sheet too)")
    if not done.get("by"):
        print("Nothing happened today for him to reflect on yet.")
        return
    print(f"\nJournal, {done['day']}:\n  {done['journal'] or '(none)'}")
    if done.get("sheet"):
        print(f"\nHis self-sheet changed:\n  {done['sheet']}")
    else:
        print("\nHis self-sheet stays as it was.")
    print("\nQuirks: " + "; ".join(done.get("quirks", [])))
    for line in done.get("added", []):
        print(f"  + {line}")
    print(f"\n(written by {done['by']})")


def _print_notebook(book: dict) -> None:
    sheet = book.get("sheet")
    print("Who Kit thinks he is" + (f" ({sheet['day']}):" if sheet else ":"))
    print(f"  {sheet['text']}" if sheet else "  (not written yet: he writes it on first start)")
    if book.get("reviews"):
        latest = book["reviews"][0]
        print(f"\nLatest weekly review ({latest['day']}):\n  {latest['text']}")
    print("\nQuirks: " + ("; ".join(book.get("quirks", [])) or "(none)"))
    dan = book.get("dan")
    if dan:
        print(f"\nWhat's going on with you ({dan['day']}):\n  {dan['text']}")
    for title, key in [
        ("Things he'll ask about", "threads"),
        ("Running jokes", "bits"),
        ("Wants to bring up", "wants"),
        ("Thoughts", "thoughts"),
        ("Opinions", "opinions"),
        ("Moments", "moments"),
        ("Journal", "journal"),
    ]:
        entries = book.get(key, [])
        if entries:
            print(f"\n{title}:")
            for e in entries[:8]:
                meta = e.get("meta", {})
                said = f"  (you said: {meta['outcome']})" if meta.get("outcome") else ""
                said = said or ("  (said)" if meta.get("said") else "")
                print(f"{e['id']:>6}  {e['day']}  {e['text']}{said}")
    print("\nForget an entry on the memory page (Kit's notebook tab).")


def _enrol(client, args: argparse.Namespace, settings, enroller=None) -> int:
    """``kit eyes enrol``: a couple of dozen looks at someone, sent to the brain as
    face numbers. Stop ``kit eyes`` first on Windows: one camera, one user."""
    from kit.desk.client import BrainError
    from kit.eyes import enrol

    who = args.who
    if who.casefold() == "me":
        who = client.settings()["settings"].get("persona", {}).get("owner", "") or who
    photos = None
    if args.photos is not None:
        if not args.photos.is_dir():
            print(f"{args.photos} isn't a folder")
            return 1
        photos = enrol.photos_in(args.photos)
        if not photos:
            print(f"no photos (jpg, png, bmp, webp) in {args.photos}")
            return 1
    camera = None
    try:
        if enroller is None:
            from kit.eyes.link import models_dir

            enroller = enrol.build_enroller(models_dir(), photos=photos is not None)
        if photos is not None:
            print(f"looking for {who}'s face in {len(photos)} photo(s)...")
            looks = enrol.from_photos(enroller, photos)
        else:
            from kit.eyes.camera import open_camera

            index = settings.camera if args.camera is None else args.camera
            camera = open_camera(index, settings.width, settings.height)
            if camera is None:
                print(f"can't open camera {index} (is `kit eyes` still running? close it first)")
                return 1
            print(
                f"{who}: sit in front of the camera and look at it, then turn your head slowly "
                "a little left, right, up and down."
            )
            looks = enrol.from_camera(enroller, camera.read, shots=args.shots)
    except ImportError as e:
        print(f'introducing someone needs the eye libraries: pip install "kit[eyes]" ({e})')
        return 1
    finally:
        if camera is not None:
            camera.release()
    if len(looks) < 3:
        print(f"only got {len(looks)} good look(s) at {who}'s face; try again in better light")
        return 1
    try:
        done = client.enrol_face(who, looks)
    except BrainError as e:
        print(f"Kit's brain didn't take them ({e})")
        return 1
    print(
        f"Kit's eyes know {done['name']} now ({done['count']} looks). Running eyes pick this up "
        "by themselves; `kit eyes forget` undoes it."
    )
    return 0


def cmd_eyes(
    paths: KitPaths,
    args: argparse.Namespace,
    transport: httpx.BaseTransport | None = None,
    cameras=None,
    build=None,
    enroller=None,
) -> int:
    """Kit's eyes (kit.eyes): run them beside the camera, list cameras, save where
    the brain is, show what Kit sees, switch them off and on, or introduce people
    to them (enrol, faces, forget)."""
    from kit.desk.client import BrainClient, BrainError
    from kit.eyes import link
    from kit.eyes.camera import camera_line
    from kit.settings import EyesSettings

    action = args.eyes_action or "run"
    if action == "cameras":
        try:
            found = (cameras or checks.cameras_here)()
        except ImportError:
            print('the camera libraries aren\'t installed here: pip install "kit[eyes]"')
            return 1
        if not found:
            print("No cameras found.")
            return 1
        for cam in found:
            print("  " + camera_line(cam))
        return 0
    if action == "connect":
        folder = link.save_connection(args.url, args.token)
        print(f"saved the brain's address and token in {folder}")
        return 0
    conn = link.find_connection(args.brain, args.token, paths=paths)
    if conn is None:
        print(
            "Kit's eyes don't know where the brain is. Run `kit eyes connect URL TOKEN` with "
            "the brain's address (as in the desk app's settings) and the token from `kit token` "
            "on the server."
        )
        return 1
    client = BrainClient(conn.url, conn.token, transport=transport)
    try:
        if action == "show":
            seen = client.eyes()
            print(seen["detail"])
            if seen.get("paused"):
                print("(the eyes are switched off: `kit eyes resume` turns them on)")
            return 0
        if action == "faces":
            names = client.known_faces().get("names", {})
            if not names:
                print("Kit's eyes don't know anyone yet: `kit eyes enrol NAME` introduces someone.")
            for name, count in names.items():
                print(f"  {name}: {count} looks")
            return 0
        if action == "forget":
            gone = client.forget_face(args.who)["forgot"]
            print(f"Kit's eyes have forgotten {gone}'s face; nothing of it is kept.")
            return 0
        if action in ("pause", "resume"):
            state = client.set_eyes(action == "resume")
            print(
                "Kit's eyes are off: the camera is released until `kit eyes resume`."
                if state["paused"]
                else "Kit's eyes are on."
            )
            return 0
        client.check()  # proves the token before loading any model
        settings = EyesSettings.model_validate(client.settings()["settings"].get("eyes", {}))
    except BrainError as e:
        print(f"can't reach Kit's brain at {conn.url} ({e})")
        return 1
    except (KeyError, ValueError) as e:
        print(f"Kit's brain gave an answer the eyes don't understand ({e}); update both sides")
        return 1
    if not settings.enabled:
        print("eyes.enabled is false in Kit's settings; turn it on first (`kit config set`)")
        return 1
    if action == "enrol":
        try:
            return _enrol(client, args, settings, enroller)
        finally:
            client.close()
    if build is None:
        from kit.eyes.run import build_eyes

        build = build_eyes
    on_frame = None
    if args.show:
        from kit.eyes.preview import previewer

        holder: dict = {}
        on_frame = previewer(lambda: holder["eyes"].fps if "eyes" in holder else 0.0)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        eyes = build(
            settings,
            client.report_scene,
            camera=args.camera,
            camera_name=args.name,
            on_frame=on_frame,
            load_faces=client.known_faces,
        )
    except ImportError as e:
        print(f'the eyes need the camera and model libraries: pip install "kit[eyes]" ({e})')
        return 1
    if args.show:
        holder["eyes"] = eyes
    camera = settings.camera if args.camera is None else args.camera
    print(
        f"Kit's eyes are open: camera {camera}, reporting to {conn.url} (found via "
        f"{conn.source}). Ctrl+C closes them."
    )
    try:
        eyes.run(max_steps=args.frames)
    except KeyboardInterrupt:
        print("eyes closed")
    finally:
        client.close()
    return 0


def _enrol_voice(client, args: argparse.Namespace, settings, parts=None) -> int:
    """``kit hearing enrol``: someone reads a few lines; their voice prints go to the
    brain. Stop ``kit hearing`` first if the mic can only be opened once."""
    from kit.desk.client import BrainError
    from kit.hearing import enrol

    who = args.who
    if who.casefold() == "me":
        who = client.settings()["settings"].get("persona", {}).get("owner", "") or who
    mic = None
    try:
        if parts is None:
            from kit.hearing.engines import CamPlusPlus, SileroVad
            from kit.hearing.link import models_dir
            from kit.hearing.mic import SoundDeviceMic, input_devices, pick_device

            folder = models_dir()
            device = pick_device(settings.mic, input_devices()) if settings.mic else None
            parts = (lambda: SoundDeviceMic(device), SileroVad(folder, settings, ahead=False))
            parts += (CamPlusPlus(folder, settings),)
        open_mic, vad, printer = parts
        mic = open_mic()
        print(f"{who}: read these out loud, at your normal pace and distance from the mic:\n")
        for line in enrol.LINES:
            print(f"  {line}")
        print()
        stretches = enrol.listen_for(mic.read, vad, args.seconds)
        prints = enrol.voice_prints(stretches, printer)
    except ImportError as e:
        print(f'introducing a voice needs the hearing libraries: pip install "kit[hearing]" ({e})')
        return 1
    except ValueError as e:  # no such mic
        print(e)
        return 1
    finally:
        if mic is not None:
            mic.close()
    if len(prints) < 3:
        print(f"only heard {len(prints)} good stretch(es) of {who} talking; try again, closer")
        return 1
    try:
        done = client.enrol_voice(who, prints)
    except BrainError as e:
        print(f"Kit's brain didn't take them ({e})")
        return 1
    print(
        f"Kit's ears know {done['name']}'s voice now ({done['count']} prints). Running ears "
        "pick this up by themselves; `kit hearing forget` undoes it."
    )
    return 0


def cmd_hearing(
    paths: KitPaths,
    args: argparse.Namespace,
    transport: httpx.BaseTransport | None = None,
    mics=None,
    build=None,
    parts=None,
) -> int:
    """Kit's ears (kit.hearing): run them beside the mic, list mics, save where the
    brain is, switch them off and on, or introduce voices to them (enrol, voices,
    forget)."""
    from kit.desk.client import BrainClient, BrainError
    from kit.hearing import link
    from kit.settings import HearingSettings

    action = args.hearing_action or "run"
    if action == "mics":
        try:
            if mics is None:
                from kit.hearing.mic import input_devices

                mics = input_devices
            found = mics()
        except ImportError:
            print('the sound libraries aren\'t installed here: pip install "kit[hearing]"')
            return 1
        if not found:
            print("No microphones found.")
            return 1
        for index, name in found:
            print(f"  {index}: {name}")
        return 0
    if action == "connect":
        folder = link.save_connection(args.url, args.token)
        print(f"saved the brain's address and token in {folder}")
        return 0
    conn = link.find_connection(args.brain, args.token, paths=paths)
    if conn is None:
        print(
            "Kit's ears don't know where the brain is. Run `kit hearing connect URL TOKEN` "
            "with the brain's address (as in the desk app's settings) and the token from "
            "`kit token` on the server."
        )
        return 1
    client = BrainClient(conn.url, conn.token, transport=transport)
    try:
        if action == "show":
            ears = client.hearing()
            state = "switched off" if ears.get("paused") else "on"
            online = "listening" if ears.get("online") else "not running"
            print(f"Kit's ears: {state}, {online}" + (f" ({ears['mic']})" if ears["mic"] else ""))
            if ears.get("last"):
                last = ears["last"]
                print(f"last heard at {last['at']}: {last['action']} ({last['why']})")
            return 0
        if action == "voices":
            names = client.known_voices().get("names", {})
            if not names:
                print("Kit's ears don't know anyone's voice yet: `kit hearing enrol NAME`.")
            for name, count in names.items():
                print(f"  {name}: {count} voice prints")
            return 0
        if action == "forget":
            gone = client.forget_voice(args.who)["forgot"]
            print(f"Kit's ears have forgotten {gone}'s voice; nothing of it is kept.")
            return 0
        if action in ("pause", "resume"):
            state = client.set_hearing(action == "resume")
            print(
                "Kit's ears are off: the mic is let go until `kit hearing resume`."
                if state["paused"]
                else "Kit's ears are on."
            )
            return 0
        client.check()  # proves the token before loading any model
        settings = HearingSettings.model_validate(client.settings()["settings"].get("hearing", {}))
    except BrainError as e:
        print(f"can't reach Kit's brain at {conn.url} ({e})")
        return 1
    except (KeyError, ValueError) as e:
        print(f"Kit's brain gave an answer the ears don't understand ({e}); update both sides")
        return 1
    if not settings.enabled:
        print("hearing.enabled is false in Kit's settings; turn it on first (`kit config set`)")
        return 1
    if action == "enrol":
        try:
            return _enrol_voice(client, args, settings, parts)
        finally:
            client.close()
    if build is None:
        from kit.hearing.run import build_ears

        build = build_ears
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        ears = build(settings, client, mic_name=args.name, words=args.words)
    except ImportError as e:
        print(f'the ears need the sound and speech libraries: pip install "kit[hearing]" ({e})')
        return 1
    except ValueError as e:  # no such mic
        print(e)
        return 1
    print(
        f"Kit's ears are open: {settings.mic or 'the default mic'}, reporting to {conn.url} "
        f"(found via {conn.source}). Sound stays on this PC. Ctrl+C closes them."
    )
    try:
        ears.run(max_steps=args.steps)
    except KeyboardInterrupt:
        print("ears closed")
    finally:
        client.close()
    return 0


def tailscale_address(run: checks.Runner = checks.run_command) -> str | None:
    """This machine's Tailscale address, for a pairing code, if Tailscale is up."""
    try:
        result = run(["tailscale", "ip", "-4"])
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.split() if result.returncode == 0 else []
    return lines[0] if lines else None


def _print_qr(text: str) -> None:
    try:
        import qrcode
    except ImportError:
        print("(install the qrcode package to see this as a QR code: pip install qrcode)")
        return
    qr = qrcode.QRCode(border=2)
    qr.add_data(text)
    qr.print_ascii(invert=True)


def cmd_pair(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.devices import DEVICES_FILE, DeviceError, Devices, pairing_link

    paths.ensure()
    port = SettingsStore(paths).current().brain.port
    url = args.address
    if not url:
        address = tailscale_address()
        if address is None:
            print("Tailscale isn't up here, so give Kit's address: kit pair phone --address URL")
            return 1
        url = f"http://{address}:{port}"
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    again = any(d.name == args.name for d in devices.all())
    try:
        token = devices.pair(args.name, args.kind)
    except DeviceError as e:
        print(e)
        return 2
    link = pairing_link(url, args.name, token)
    print(f"Scan this with Kit's app on the {args.kind} to pair it as {args.name!r}:\n")
    _print_qr(link)
    print(f"\nor enter it by hand:\n  {link}\n")
    if again:
        print(f"{args.name} was paired before; its old token has stopped working.")
    print(f"Kit's address in the code is {url}. Unpair it with: kit devices forget {args.name}")
    return 0


def cmd_devices(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.devices import DEVICES_FILE, Devices

    devices = Devices(paths.secrets_dir / DEVICES_FILE)
    if args.devices_action == "forget":
        if devices.forget(args.name):
            print(f"forgot {args.name}; its token no longer works")
            return 0
        print(f"no paired device called {args.name}")
        return 1
    found = devices.all()
    if not found:
        print("no devices paired; pair one with: kit pair phone")
    for d in found:
        print(f"{d.name:<20} {d.kind:<8} paired {d.created}")
    return 0


def cmd_new_chat(paths: KitPaths) -> int:
    from kit.memory import Memory

    paths.ensure()
    memory = Memory(paths.state_dir / "memory.db")
    memory.new_chat()
    memory.close()
    print("new chat started; the old one is still in Kit's memory")
    return 0


def cmd_memory(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.memory import Memory

    paths.ensure()
    if args.action in ("summarise", "remember", "search", "reindex", "tidy"):
        return asyncio.run(_memory_async(paths, args))
    memory = Memory(paths.state_dir / "memory.db")
    code = 0
    if args.action == "facts":
        facts = memory.facts()
        if not facts:
            print("nothing remembered yet")
        for f in facts:
            print(_show_item(f))
        if facts:
            print("\n* = pinned (always in mind)")
    elif args.action == "history":
        for item in memory.index.history(args.id):
            gone = "  (replaced)" if item.superseded_by else ""
            print(_show_item(item) + gone)
    elif args.action in ("pin", "unpin"):
        if memory.index.set_pinned(args.id, args.action == "pin"):
            print(f"{args.action}ned {args.id}")
        else:
            print(f"no fact {args.id}")
            code = 1
    elif args.action == "forget":
        if memory.forget(args.id, conversation=True):
            print("forgotten")
        else:
            print(f"no fact or conversation {args.id}")
            code = 1
    elif args.action == "scrub":
        code = _scrub(paths, memory, args)
    elif args.action == "days":
        for item in memory.index.items("days"):
            print(f"{item.ref}  {item.text}\n")
    elif args.action == "backup":
        keep = SettingsStore(paths).current().memory.backups_keep
        print(f"backed up to {memory.backup(paths.backups_dir, keep)}")
    elif args.action == "spend":
        cap = SettingsStore(paths).current().cloud.monthly_cap_aud
        print(f"Cloud models this month: A${memory.month_spend():.2f} of A${cap:.2f}")
        # "cached 1830/2400": how much of the input was read from the prompt cache.
        for s in memory.spend_log(20):
            print(
                f"  {s.at}  {s.model}  in {s.input_tokens}  cached {s.cached_tokens}/"
                f"{s.input_tokens}  out {s.output_tokens}  A${s.cost_aud:.4f}  {s.question[:60]}"
            )
    memory.close()
    return code


def _scrub(paths: KitPaths, memory, args: argparse.Namespace) -> int:
    """``kit memory scrub``: show what would go, then take it out with ``--apply``."""
    from datetime import date, datetime

    now = memory.clock()
    try:
        day = date.fromisoformat(args.since) if args.since else now.date()
    except ValueError:
        print(f"--since needs a date like {now:%Y-%m-%d}")
        return 2
    since = datetime.combine(day, datetime.min.time(), tzinfo=now.tzinfo)
    if args.apply:
        keep = SettingsStore(paths).current().memory.backups_keep
        print(f"backed up to {memory.backup(paths.backups_dir, keep)}")
    found = memory.scrub(args.words, since, apply=args.apply)
    if not found.messages and not found.items:
        print(f"nothing since {day} says that")
        return 0
    for _, at, role, text in found.messages:
        print(f"{at[:16]}  {'you' if role == 'user' else 'Kit'}: {text[:100]}")
    for item in found.items:
        print(f"{item.created[:16]}  {item.source} #{item.id}: {item.text[:100]}")
    told = f"{len(found.messages)} messages and {len(found.items)} things kept from them"
    if not args.apply:
        print(f"\n{told} would go. Run it again with --apply to take them out.")
        return 0
    again = f"; {', '.join(found.days)} will be summarised again" if found.days else ""
    print(f"\n{told} are gone{again}. Restart Kit so nothing of them stays in mind.")
    return 0


def file_place(item) -> str:
    """Where a ``files`` hit came from: its root, path and page."""
    m = item.meta
    page = f", page {m['page']}" if m.get("page", 1) > 1 else ""
    return f"{m.get('root')}: {m.get('rel')}{page}"


async def _memory_async(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.files import FILES
    from kit.memory import CONVERSATION, DAYS, FACTS
    from kit.notes import NOTES

    async with httpx.AsyncClient() as client:
        store, memory, brain = _runtime(paths, client)
        try:
            if args.action == "summarise":
                days = await brain.summarise_past_days()
                print(f"summarised {', '.join(days)}" if days else "nothing to summarise")
            elif args.action == "remember":
                learned = await brain.learner.learn(
                    args.text, args.kind, store.current().persona.owner
                )
                if learned.decision == "same":
                    print(f"already known: {learned.text}")
                elif learned.decision == "update":
                    print(f"updated: {learned.replaced}\n     ->  {learned.text}")
                else:
                    print(f"remembered: {learned.text}")
            elif args.action == "search":
                sources = [FACTS, DAYS, CONVERSATION, NOTES, FILES]
                hits = await brain.recall.search(args.query, sources, 10)
                if brain.recall.embed_problem:
                    print(f"(words only: {brain.recall.embed_problem})")
                if not hits:
                    print("nothing found")
                for h in hits:
                    how = (
                        "words+meaning"
                        if h.word_match and h.similarity
                        else ("words" if h.word_match else f"meaning {h.similarity:.2f}")
                    )
                    text = " / ".join(h.item.text.splitlines())[:110]
                    print(f"{h.item.id:>5}  {h.item.day}  {h.item.source:<12} {how:<14} {text}")
                    if h.item.source == FILES:
                        print(f"{'':>19}{file_place(h.item)}")
            elif args.action == "tidy":
                return await _tidy(paths, store, memory, brain, args.apply)
            elif args.action == "reindex":
                done = await brain.recall.index_pending(limit=1_000_000)
                problem = brain.recall.embed_problem
                print(f"indexed {done} item(s)" + (f"; stopped: {problem}" if problem else ""))
                return 1 if problem else 0
        finally:
            memory.close()
    return 0


async def _tidy(paths: KitPaths, store, memory, brain, apply: bool) -> int:
    """Sort what Kit already knows: each fact to the kind that fits, logs of what was
    asked dropped (or kept as the lasting fact they show). Shows the plan; ``apply``
    carries it out after a backup."""
    from kit.learning import apply_tidy, plan_tidy

    settings = store.current()
    facts = memory.facts()
    if not facts:
        print("nothing remembered yet")
        return 0
    ask = brain.learner.ask if settings.memory.day_pass == "work" else None
    who = settings.profile("work").name if ask else settings.ollama.model
    print(f"sorting {len(facts)} facts with {who}...")
    p = settings.persona
    plans = await plan_tidy(facts, p.owner, p.name, brain.model, ask)
    changes = [t for t in plans if t.changes]
    for t in changes:
        if not t.keep:
            print(f"drop   [{t.item.kind}] {t.item.text}")
        else:
            move = f"[{t.item.kind} -> {t.kind}]" if t.kind != t.item.kind else f"[{t.kind}]"
            print(f"keep   {move} {t.text or t.item.text}")
            if t.text:
                print(f"       was: {t.item.text}")
    dropped = sum(not t.keep for t in changes)
    print(
        f"\n{len(changes) - dropped} to move or reword, {dropped} to drop, "
        f"{len(plans) - len(changes)} fine as they are"
    )
    if not changes:
        return 0
    if not apply:
        print("Nothing changed yet: `kit memory tidy --apply` does it, after a backup.")
        return 0
    backup = memory.backup(paths.backups_dir, settings.memory.backups_keep)
    changed, gone = apply_tidy(memory, changes)
    await brain.recall.index_pending()
    print(f"backed up to {backup}; moved or reworded {changed}, dropped {gone}")
    print("A moved fact keeps its old version in its history on the memory page.")
    return 0


def _parse_link(text: str) -> dict:
    system, _, target = text.partition("=")
    if not target:
        raise SystemExit(f"links look like system=target, e.g. nas=Documents/Tax (got {text!r})")
    return {"system": system.strip(), "target": target.strip()}


def cmd_notes(paths: KitPaths, args: argparse.Namespace | None = None) -> int:
    """``kit notes``: read the vault now and show what Kit sees; ``tasks``, ``shape``
    and ``undo`` (kit.notes, kit.notes_tasks, kit.notes_edit)."""
    from kit.memory import Memory
    from kit.notes import NoteError, Notes, shape_lines
    from kit.notes_edit import undo
    from kit.notes_tasks import TASKS, due_window

    paths.ensure()
    settings = SettingsStore(paths).current()
    nas = settings.nas
    action = getattr(args, "action", None) or "list"
    if not nas.vault:
        print("no notes vault set; see docs/4 Guides/Notes Setup.md (kit config set nas.vault ...)")
        return 1
    if action == "undo":
        try:
            print(undo(nas, paths.state_dir / "notes" / "undo"))
        except NoteError as e:
            print(e)
            return 1
        return 0
    memory = Memory(paths.state_dir / "memory.db")
    try:
        notes = Notes(memory.index, memory.clock)
        indexed, removed = notes.sync(nas)
        if action == "shape":
            for line in shape_lines(notes.shape(nas, settings.notes)) or ["(nothing read yet)"]:
                print(line)
            return 0
        if action == "tasks":
            start, end = due_window(args.due, memory.clock())
            tasks = sorted(
                memory.index.items(TASKS, limit=1_000_000),
                key=lambda t: (t.meta.get("due") or "9999", t.text),
            )
            if args.due:
                tasks = [
                    t
                    for t in tasks
                    if t.meta.get("due")
                    and not (start and t.meta["due"] < start.isoformat())
                    and not (end and t.meta["due"] > end.isoformat())
                ]
            for t in tasks:
                print(f"- {t.text}")
            print(f"{len(tasks)} open tasks")
            return 0
        names = notes.names(limit=1_000_000)
        print(f"{len(names)} notes in {nas.vault} ({indexed} read now, {removed} gone)")
        for name in names[:15]:
            print(f"  {name}")
        if len(names) > 15:
            print(f"  ... and {len(names) - 15} more")
    finally:
        memory.close()
    return 0


def cmd_files(paths: KitPaths, args: argparse.Namespace) -> int:
    """``kit files``: the folders Kit indexes, what's in each, and indexing them now."""
    from kit.files import RootError, add_root, change_root, remove_root
    from kit.files.index import Files
    from kit.memory import Memory

    paths.ensure()
    store = SettingsStore(paths)
    if args.action in ("index", "search"):
        return asyncio.run(_files_async(paths, args))
    memory = Memory(paths.state_dir / "memory.db")
    files = Files(memory.index, store.current, paths.state_dir)
    try:
        if args.action == "add":
            add_root(store, args.name, args.path, args.private, args.ocr)
            private = " (private)" if args.private else ""
            print(f"added {args.name}{private}: {args.path}; `kit files index` reads it now")
        elif args.action == "remove":
            remove_root(store, args.name)
            print(f"removed {args.name}; {files.drop_root(args.name)} pieces left the index")
        elif args.action == "private":
            on = args.state == "on"
            change_root(store, args.name, private=on)
            n = files.set_private(args.name, on)
            print(f"{args.name} is {'private' if on else 'not private'} ({n} pieces changed)")
        elif args.action == "status":
            roots = files.status()
            if not roots:
                print("no folders yet; add one with `kit files add NAME PATH`")
            for name, r in roots.items():
                flags = "".join([", private" if r["private"] else "", ", OCR" if r["ocr"] else ""])
                there = "" if r["reachable"] else "  (can't be reached just now)"
                print(f"{name}: {r['path']}{flags}{there}")
                print(f"  {r['files']} files, {r['pieces']} pieces")
                if r["last_run"]:
                    print(f"  last run {r['last_run']['at']}: {r['last_run']['result']}")
                for ref in r["unreadable"][:10]:
                    print(f"  couldn't read {ref}")
                if len(r["unreadable"]) > 10:
                    print(f"  ... and {len(r['unreadable']) - 10} more it couldn't read")
    except (RootError, SettingsError) as e:
        print(e)
        return 1
    finally:
        memory.close()
    return 0


def cmd_house(paths: KitPaths, args: argparse.Namespace, connect=None) -> int:
    """``kit house``: what Kit can see of the house through Home Assistant, a thing's
    state, and switching one on or off (kit.house)."""
    return asyncio.run(_house_async(paths, args, connect))


async def _house_async(paths: KitPaths, args: argparse.Namespace, connect=None) -> int:
    from kit.house.client import HomeAssistant, HouseError, websocket_connect
    from kit.house.model import House

    s = SettingsStore(paths).current().house
    token = home_assistant_token(paths)
    if not s.url or not token:
        print("set house.url and put Kit's token in the secrets folder first (kit check)")
        return 1
    client = HomeAssistant(s.url, token, connect or websocket_connect)
    house = House(client, datetime.now)
    await client.start()
    try:
        if not await client.wait_ready(10, first_try=True):
            print(f"can't reach Home Assistant: {client.last_error or 'no answer'}")
            return 1
        await house.refresh()
        if args.action == "list":
            things = sorted(house.entities.values(), key=lambda e: (e.area, e.name))
            if args.area:
                things = [e for e in things if e.area.lower() == args.area.lower()]
            for e in things:
                print(e.line())
            print(f"{len(things)} things Kit can see")
            return 0
        found = house.find(args.name)
        if len(found) != 1:
            listed = ", ".join(f"{e.name} ({e.id})" for e in found[:8]) or "nothing"
            print(f"'{args.name}' matches {listed}")
            return 1
        entity = found[0]
        if args.action == "state":
            print(entity.line())
            return 0
        if entity.domain not in ("light", "switch", "fan", "input_boolean"):
            print(f"{entity.name} isn't a light, switch or fan")
            return 1
        service = "turn_on" if args.state == "on" else "turn_off"
        await client.call_service(entity.domain, service, None, entity.id)
        print(f"{entity.name}: {args.state}")
        return 0
    except HouseError as e:
        print(e)
        return 1
    finally:
        await client.close()


async def _files_async(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.files import FILES
    from kit.files.index import Files

    async with httpx.AsyncClient() as client:
        store, memory, brain = _runtime(paths, client)
        try:
            if args.action == "index":
                if args.root and args.root not in store.current().files.roots:
                    print(f"no root called {args.root}")
                    return 1
                files = Files(
                    memory.index,
                    store.current,
                    paths.state_dir,
                    names=lambda: [n for t in brain.register.all() for n in t.names],
                )
                report = await asyncio.to_thread(
                    files.sync, args.full, args.root, lambda ref: print(f"  {ref}", flush=True)
                )
                print(report.line())
                for ref, why in report.failed[:20]:
                    print(f"  couldn't read {ref}: {why}")
                done = await brain.recall.index_pending(limit=1_000_000)
                problem = brain.recall.embed_problem
                print(
                    f"{done} pieces searchable by meaning"
                    + (f"; stopped: {problem}" if problem else "")
                )
                return 0
            hits = await brain.recall.search(args.query, [FILES], 10)
            if brain.recall.embed_problem:
                print(f"(words only: {brain.recall.embed_problem})")
            if not hits:
                print("nothing found")
            for h in hits:
                text = " / ".join(h.item.text.splitlines())[:100]
                print(f"{file_place(h.item)}\n    {text}")
        finally:
            memory.close()
    return 0


def cmd_tools(
    paths: KitPaths, args: argparse.Namespace, transport: httpx.BaseTransport | None = None
) -> int:
    """``kit tools``: the running Kit's packs and tools, or one tool run by hand."""
    s = SettingsStore(paths).current().brain
    host = "127.0.0.1" if s.host in ("0.0.0.0", "::") else s.host
    headers = {"Authorization": f"Bearer {api_token(paths)}"}
    with httpx.Client(
        base_url=f"http://{host}:{s.port}", headers=headers, timeout=120, transport=transport
    ) as client:
        try:
            if args.action == "run":
                try:
                    arguments = json.loads(args.args)
                except ValueError as e:
                    print(f"--args isn't JSON: {e}")
                    return 2
                r = client.post(
                    "/api/tools/run",
                    json={"tool": args.tool, "arguments": arguments, "yes": args.yes},
                )
                if r.status_code in (404, 409):
                    print(r.json().get("detail", r.text))
                    return 1
                r.raise_for_status()
                out = r.json()
                print(("" if out["ok"] else "failed: ") + out["text"])
                return 0 if out["ok"] else 1
            r = client.get("/api/tools")
            r.raise_for_status()
            packs = r.json()["packs"]
        except httpx.HTTPError as e:
            print(f"couldn't reach Kit at {host}:{s.port}: {e} (is `kit serve` running?)")
            return 1
    for pack in packs:
        if args.action == "packs":
            state = "always" if pack["always"] else "on" if pack["enabled"] else "off"
            print(f"{pack['name']:<10} {state:<7} {pack['card']}")
            continue
        for tool in pack["tools"]:
            asks = "  (asks first)" if tool["asks_first"] else ""
            print(f"{tool['name']:<16} {pack['name']:<10} {tool['effect']:<7}{asks}")
    return 0


def cmd_things(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.memory import Memory
    from kit.things import Register

    paths.ensure()
    memory = Memory(paths.state_dir / "memory.db")
    register = Register(memory)
    code = 0
    try:
        if args.action == "list":
            things = sorted(register.all(), key=lambda t: t.name.lower())
            if not things:
                print("the register is empty")
            for t in things:
                print(f"{t.id:>5}  {t.line()}")
        elif args.action == "suggestions":
            things = register.suggestions()
            if not things:
                print("no suggestions waiting")
            for t in things:
                print(f"{t.id:>5}  {t.line()}")
        elif args.action == "add":
            links = [_parse_link(x) for x in args.link]
            new_id = register.add(args.name, args.kind, args.alias, links, args.about)
            print(f"{new_id:>5}  {register.get(new_id).line()}")
        elif args.action == "link":
            try:
                new_id = register.set_link(args.id, args.system, args.target)
                print(f"{new_id:>5}  {register.get(new_id).line()}")
            except KeyError:
                print(f"no thing {args.id}")
                code = 1
        elif args.action == "confirm":
            new_id = register.confirm(args.id)
            if new_id is None:
                print(f"no suggestion {args.id}")
                code = 1
            else:
                print(f"{new_id:>5}  {register.get(new_id).line()}")
        elif args.action in ("reject", "forget"):
            done = getattr(register, args.action)(args.id)
            print(
                f"{args.action}ed"
                if done
                else f"no {'suggestion' if args.action == 'reject' else 'thing'} {args.id}"
            )
            code = 0 if done else 1
        elif args.action == "history":
            for t in register.history(args.id):
                print(f"{t.id:>5}  {t.line()}")
    finally:
        memory.close()
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kit", description="Kit, your desk companion.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="show where Kit keeps its files")
    sub.add_parser("init", help="create Kit's data folder and a starter settings file")
    check = sub.add_parser("check", help="check this machine is ready to run Kit (stage 0)")
    check.add_argument(
        "--skip", action="append", default=[], choices=CHECK_NAMES, help="skip a check (repeatable)"
    )

    serve = sub.add_parser("serve", help="run Kit's brain with the chat and settings pages")
    serve.add_argument("--host", help="override brain.host")
    serve.add_argument("--port", type=int, help="override brain.port")
    sub.add_parser("chat", help="talk to Kit in this terminal")
    sub.add_parser("new-chat", help="start a fresh conversation (the old one stays in memory)")
    sub.add_parser("token", help="show the API token for the pages and home_app")
    pair = sub.add_parser("pair", help="pair a device (a phone) with a token of its own")
    pair.add_argument("name", help="what to call it, e.g. phone")
    pair.add_argument("--kind", default="phone", help="phone, tablet, watch, pc, robot or other")
    pair.add_argument("--address", help="Kit's address for the device (default: Tailscale's)")
    devices = sub.add_parser("devices", help="list paired devices, or forget one")
    dsub = devices.add_subparsers(dest="devices_action")
    dsub.add_parser("list", help="list paired devices")
    dsub.add_parser("forget", help="unpair a device; its token stops working").add_argument("name")
    life = sub.add_parser(
        "life", help="Kit's mood and thoughts; poke, think or reflect now; his notebook"
    )
    life.add_argument(
        "action",
        nargs="?",
        choices=["show", "poke", "think", "reflect", "notebook"],
        default="show",
    )

    config = sub.add_parser("config", help="see or change Kit's settings")
    csub = config.add_subparsers(dest="action", required=True)
    csub.add_parser("show", help="print the settings in force")
    csub.add_parser("schema", help="print the settings schema (JSON)")
    cset = csub.add_parser("set", help="change one setting, e.g. persona.name Kit")
    cset.add_argument("key")
    cset.add_argument("value")
    csub.add_parser("undo", help="go back to the settings before the last change")
    csub.add_parser("reset", help="back to the defaults (memory is untouched; undo restores)")
    csub.add_parser("history", help="list earlier versions")
    crestore = csub.add_parser("restore", help="go back to an earlier version")
    crestore.add_argument("version")
    csub.add_parser("check", help="check the settings file is valid")

    models = sub.add_parser(
        "models", help="the models Kit uses and their prices; switch, add or remove one"
    )
    models.add_argument(
        "action",
        nargs="?",
        choices=["chat", "work", "expert", "add", "remove", "prices"],
        help="a role to switch (chat, work, expert), add, remove, or prices (fetch today's)",
    )
    models.add_argument("name", nargs="?", help="the model's name in settings")
    models.add_argument(
        "--provider", choices=["anthropic", "openai", "google", "ollama"], help="add: who runs it"
    )
    models.add_argument("--model", help="add: the provider's model id, e.g. claude-sonnet-5-5")
    models.add_argument("--label", help="add: the name Kit calls it")
    models.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="add: how hard it thinks",
    )
    models.add_argument("--max-tokens", type=int, dest="max_tokens", help="add: longest answer")
    models.add_argument("--no-thinking", action="store_true", help="add: no thinking first")
    models.add_argument("--no-search", action="store_true", help="add: no web search")

    speech = sub.add_parser("speech", help="Kit's voice: engines, switch, try a line, compare")
    spsub = speech.add_subparsers(dest="action")
    spsub.add_parser("show", help="list the voice engines and which one is in use")
    spuse = spsub.add_parser("use", help="switch engine, e.g. kit speech use chatterbox-turbo")
    spuse.add_argument("engine")
    spsub.add_parser("on", help="Kit speaks his replies in the desk app")
    spsub.add_parser("off", help="Kit stops speaking (frees the voice engine's memory)")
    spsay = spsub.add_parser("say", help="say a line and show how long it took")
    spsay.add_argument("text")
    spsay.add_argument("--engine", help="default: the one in use")
    spsay.add_argument("--mood", default="neutral", help="one of Kit's emotions, e.g. excited")
    spbench = spsub.add_parser("bench", help="compare engines on the same Kit lines")
    spbench.add_argument("--engines", nargs="+", default=[], help="default: the one in use")
    weather = sub.add_parser("weather", help="show the forecast Kit sees")
    weather.add_argument("place", nargs="?", help="somewhere else, e.g. 'Broome, WA'")

    mem = sub.add_parser("memory", help="see what Kit remembers and spends")
    msub = mem.add_subparsers(dest="action", required=True)
    msub.add_parser("facts", help="list what Kit knows (* = pinned)")
    mremember = msub.add_parser("remember", help="teach Kit a fact")
    mremember.add_argument("text")
    mremember.add_argument("--kind", default="other", choices=list(FACT_KINDS))
    msearch = msub.add_parser("search", help="search memory the way Kit does")
    msearch.add_argument("query")
    for name, text in [
        ("pin", "keep a fact always in mind"),
        ("unpin", "stop keeping a fact always in mind"),
        ("forget", "delete a fact or a recalled conversation"),
        ("history", "show a fact's earlier versions"),
    ]:
        msub.add_parser(name, help=text).add_argument("id", type=int)
    msub.add_parser("days", help="list day summaries")
    msub.add_parser("summarise", help="summarise finished days now")
    mtidy = msub.add_parser(
        "tidy", help="sort what Kit knows into the right kinds and drop logs of chats"
    )
    mtidy.add_argument("--apply", action="store_true", help="do it (after a backup)")
    mscrub = msub.add_parser(
        "scrub", help="take out lines that should never have been said, and all kept of them"
    )
    mscrub.add_argument("words", nargs="+", help="words or phrases to find, any of them")
    mscrub.add_argument("--since", help="from this date (YYYY-MM-DD); default today")
    mscrub.add_argument("--apply", action="store_true", help="do it (after a backup)")
    msub.add_parser("reindex", help="build any missing meaning vectors now")
    msub.add_parser("backup", help="back up memory now")
    msub.add_parser("spend", help="show this month's cloud spend")

    notes = sub.add_parser("notes", help="the notes vault: what Kit sees, tasks, its shape, undo")
    nsub = notes.add_subparsers(dest="action")
    nsub.add_parser("list", help="read the vault now and list what Kit sees (the default)")
    ntasks = nsub.add_parser("tasks", help="the open tasks in your notes")
    ntasks.add_argument("--due", default="", help="today, tomorrow, week, overdue...")
    nsub.add_parser("shape", help="how Kit sees the vault laid out (what his prompt says)")
    nsub.add_parser("undo", help="undo Kit's last change to a note")
    eyes = sub.add_parser(
        "eyes", help="Kit's eyes: run them beside the camera (docs/4 Guides/Vision Stage 1.md)"
    )
    eyes.add_argument("--camera", type=int, help="camera index (default: eyes.camera in settings)")
    eyes.add_argument("--brain", help="the brain's address, e.g. http://kit-server:8600")
    eyes.add_argument("--token", help="Kit's API token (`kit token` on the server)")
    eyes.add_argument("--name", default="desk", help="what to call this camera (default: desk)")
    eyes.add_argument("--show", action="store_true", help="show what the eyes see in a window")
    eyes.add_argument("--frames", type=int, help="stop after this many frames (for testing)")
    esub = eyes.add_subparsers(dest="eyes_action")
    esub.add_parser("cameras", help="list the cameras on this machine")
    econnect = esub.add_parser(
        "connect", help="save where the brain is, e.g. http://kit-server:8600 TOKEN"
    )
    econnect.add_argument("url")
    econnect.add_argument("token")
    esub.add_parser("show", help="what Kit can see right now, as he's told it")
    enrol = esub.add_parser(
        "enrol", help="introduce someone to Kit's eyes, from the camera or a folder of photos"
    )
    enrol.add_argument("who", help="their name, or `me` for you (persona.owner)")
    enrol.add_argument("--photos", type=Path, help="a folder of photos of them, one face each")
    enrol.add_argument("--shots", type=int, default=24, help="looks to take from the camera")
    esub.add_parser("faces", help="who Kit's eyes know")
    forget_face = esub.add_parser("forget", help="forget someone's face completely")
    forget_face.add_argument("who")
    esub.add_parser("pause", help="switch the eyes off (the camera is released)")
    esub.add_parser("resume", help="switch the eyes on again")
    hearing = sub.add_parser(
        "hearing",
        help="Kit's ears: run them beside the mic (docs/4 Guides/Companion Stage 5.md)",
    )
    hearing.add_argument("--brain", help="the brain's address, e.g. http://kit-server:8600")
    hearing.add_argument("--token", help="Kit's API token (`kit token` on the server)")
    hearing.add_argument("--name", default="desk", help="what to call this mic (default: desk)")
    hearing.add_argument(
        "--words",
        action="store_true",
        help="show the words the ears heard, in this window only (for tuning hearing.names)",
    )
    hearing.add_argument("--steps", type=int, help="stop after this many 32 ms steps (testing)")
    hsub = hearing.add_subparsers(dest="hearing_action")
    hsub.add_parser("mics", help="list the microphones on this machine")
    hconnect = hsub.add_parser(
        "connect", help="save where the brain is, e.g. http://kit-server:8600 TOKEN"
    )
    hconnect.add_argument("url")
    hconnect.add_argument("token")
    hsub.add_parser("show", help="whether Kit's ears are listening, and what he last made of it")
    henrol = hsub.add_parser("enrol", help="introduce someone's voice to Kit's ears")
    henrol.add_argument("who", help="their name, or `me` for you (persona.owner)")
    henrol.add_argument("--seconds", type=float, default=30, help="how long to listen")
    hsub.add_parser("voices", help="whose voices Kit's ears know")
    forget_voice = hsub.add_parser("forget", help="forget someone's voice completely")
    forget_voice.add_argument("who")
    hsub.add_parser("pause", help="switch the ears off (the mic is let go)")
    hsub.add_parser("resume", help="switch the ears on again")
    things = sub.add_parser("things", help="the register of things and where they live")
    tsub = things.add_subparsers(dest="action", required=True)
    tsub.add_parser("list", help="list the register")
    tsub.add_parser("suggestions", help="list names Kit suggested adding")
    tadd = tsub.add_parser("add", help="add a thing, e.g. Hilux --kind vehicle --link nas=Cars")
    tadd.add_argument("name")
    tadd.add_argument("--kind", default="other", choices=list(THING_KINDS))
    tadd.add_argument("--alias", action="append", default=[], help="another name (repeatable)")
    tadd.add_argument(
        "--link", action="append", default=[], help="system=target, e.g. nas=Documents/Tax"
    )
    tadd.add_argument("--about", default="", help="a few words on what it is")
    tlink = tsub.add_parser("link", help="set where a thing lives in one system")
    tlink.add_argument("id", type=int)
    tlink.add_argument("system", choices=list(SYSTEMS))
    tlink.add_argument("target")
    for name, text in [
        ("confirm", "add a suggested thing to the register"),
        ("reject", "drop a suggested thing"),
        ("forget", "delete a thing"),
        ("history", "show a thing's earlier versions"),
    ]:
        tsub.add_parser(name, help=text).add_argument("id", type=int)

    docs = sub.add_parser("docs", help="the docs vault: what's gone stale")
    dosub = docs.add_subparsers(dest="docs_action", required=True)
    dcheck = dosub.add_parser(
        "check", help="report rows of Where Kit Is Up To that say open for a landed pull request"
    )
    dcheck.add_argument(
        "--vault", type=Path, default=None, help="the docs folder (default: the checkout's)"
    )

    ev = sub.add_parser(
        "eval",
        help="test the local model's replies, memory recall, routing, voice, how good a "
        "companion he is or how well he reads your mood, or compare cloud models",
    )
    ev.add_argument(
        "which",
        nargs="?",
        default="replies",
        choices=[
            "replies",
            "memory",
            "routing",
            "tools",
            "compare",
            "voice",
            "companion",
            "mood",
        ],
    )
    ev.add_argument("--pack", help="tools: only this pack's questions")
    ev.add_argument(
        "--live",
        action="store_true",
        help="tools: ask the real chat model (every tool stubbed); spends real money",
    )
    ev.add_argument("--n", type=int, help="how many prompts (replies: 50, compare: 10, voice: 16)")
    ev.add_argument(
        "--models",
        nargs="+",
        default=[],
        help="compare: model profiles, e.g. sonnet gpt-sol; voice and companion: local "
        "models, e.g. qwen3:8b gemma4:e4b (default: the one in use)",
    )
    ev.add_argument(
        "--one-pass", action="store_true", help="voice: answer in one JSON pass, as in stage 1"
    )
    ev.add_argument(
        "--replay",
        metavar="SNAPSHOT",
        help="memory: ask your own questions (config/memory-questions.toml) of a copy of "
        "this memory snapshot, e.g. a backup from backups/, to see the right fact still wins",
    )
    ev.add_argument(
        "--questions",
        metavar="FILE",
        help="memory --replay or tools: a different questions file",
    )

    house = sub.add_parser("house", help="the house through Home Assistant: list, state, set")
    hsub = house.add_subparsers(dest="action", required=True)
    hsub.add_parser("list", help="the things Kit can see, by room").add_argument(
        "area", nargs="?", default="", help="only this room"
    )
    hsub.add_parser("state", help="one thing's state, e.g. study lamp").add_argument("name")
    hset = hsub.add_parser("set", help="turn a light or switch on or off")
    hset.add_argument("name")
    hset.add_argument("state", choices=["on", "off"])

    files = sub.add_parser("files", help="the folders Kit indexes: add, remove, status, index")
    fsub = files.add_subparsers(dest="action", required=True)
    fadd = fsub.add_parser(
        "add", help="add a folder for Kit to read, e.g. finance /mnt/nas/Finance"
    )
    fadd.add_argument("name")
    fadd.add_argument("path")
    fadd.add_argument(
        "--private", action="store_true", help="its contents stay with the local model"
    )
    fadd.add_argument("--ocr", action="store_true", help="read scanned PDFs too (slow)")
    fsub.add_parser(
        "remove", help="stop indexing a folder; its pieces leave the index"
    ).add_argument("name")
    fpriv = fsub.add_parser("private", help="mark a folder private or not")
    fpriv.add_argument("name")
    fpriv.add_argument("state", choices=["on", "off"])
    fsub.add_parser("status", help="each folder: files and pieces indexed, last run, unreadable")
    findex = fsub.add_parser("index", help="read new and changed files now, showing each")
    findex.add_argument("--root", help="only this folder")
    findex.add_argument("--full", action="store_true", help="read every file again")
    fsub.add_parser("search", help="search the indexed files only").add_argument("query")

    tools = sub.add_parser("tools", help="Kit's tools: the packs, each tool, trying one by hand")
    tosub = tools.add_subparsers(dest="action", required=True)
    tosub.add_parser("list", help="every tool with its pack and effect")
    tosub.add_parser("packs", help="each pack: its card, and whether it may load")
    trun = tosub.add_parser("run", help="run one tool on the running Kit, to try it")
    trun.add_argument("tool")
    trun.add_argument(
        "--args", default="{}", help='its arguments as JSON, e.g. \'{"query": "tax"}\''
    )
    trun.add_argument(
        "--yes", action="store_true", help="run it even though it changes something of yours"
    )

    args = parser.parse_args(argv)
    paths = KitPaths.default()
    if args.command == "paths":
        return cmd_paths(paths)
    if args.command == "init":
        return cmd_init(paths)
    if args.command == "config":
        return cmd_config(paths, args)
    if args.command == "token":
        return cmd_token(paths)
    if args.command == "pair":
        return cmd_pair(paths, args)
    if args.command == "devices":
        return cmd_devices(paths, args)
    if args.command == "serve":
        return cmd_serve(paths, args)
    if args.command == "chat":
        return asyncio.run(_chat_loop(paths))
    if args.command == "life":
        return cmd_life(paths, args.action)
    if args.command == "new-chat":
        return cmd_new_chat(paths)
    if args.command == "memory":
        return cmd_memory(paths, args)
    if args.command == "models":
        return cmd_models(paths, args)
    if args.command == "speech":
        return cmd_speech(paths, args)
    if args.command == "notes":
        return cmd_notes(paths, args)
    if args.command == "eyes":
        return cmd_eyes(paths, args)
    if args.command == "hearing":
        return cmd_hearing(paths, args)
    if args.command == "things":
        return cmd_things(paths, args)
    if args.command == "tools":
        return cmd_tools(paths, args)
    if args.command == "files":
        return cmd_files(paths, args)
    if args.command == "house":
        return cmd_house(paths, args)
    if args.command == "docs":
        return docs_check.check(args.vault or docs_check.repo_docs())
    if args.command == "weather":
        return asyncio.run(_weather(paths, args.place))
    if args.command == "eval":
        from kit.evals_cli import cmd_eval

        return cmd_eval(paths, args)
    results = run_checks(paths, set(args.skip))
    print_report(results)
    return 1 if any(r.status is Status.FAIL for r in results) else 0
