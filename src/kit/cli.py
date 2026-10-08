"""The ``kit`` command."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tomllib
from importlib import resources

import httpx

from kit import checks
from kit.checks import CheckResult, Status
from kit.credentials import api_token, cloud_api_key
from kit.memory import FACT_KINDS
from kit.paths import KitPaths
from kit.settings import Settings, SettingsError, load_settings, settings_to_toml
from kit.settings_store import SettingsStore
from kit.things import SYSTEMS, THING_KINDS

CHECK_NAMES = ["data", "gpu", "ollama", "tailscale", "nas", "cloud"]


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
    if "cloud" not in skip:
        results.extend(checks.check_cloud(settings, lambda p: cloud_api_key(paths, p)))
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
    """Show the models Kit can use and which one does what, or switch one."""
    store = SettingsStore(paths)
    if args.role:
        if args.name is None:
            print("give a model name too, for example: kit models work gpt-sol")
            return 2
        try:
            store.update({"routing": {args.role: args.name}}, "cli")
        except SettingsError as e:
            print(e)
            return 1
        print(f"{args.role} now uses {args.name}; Kit uses it from the next message")
        return 0
    s = store.current()
    roles = {s.routing.work: "work", s.routing.expert: "expert"}
    if s.routing.work == s.routing.expert:
        roles[s.routing.work] = "work, expert"
    print(f"routing: {s.routing.mode}   local model: {s.ollama.model}")
    print(f"cloud budget: ${s.cloud.monthly_cap_usd:.2f} a month\n")
    print(
        f"  {'name':<14} {'role':<13} {'provider':<10} {'model':<20} {'effort':<7}"
        f" {'$ in/out per M':<15} {'search/1k'}"
    )
    for name, m in s.models.items():
        price = f"{m.input_usd_per_mtok:g}/{m.output_usd_per_mtok:g}"
        search = f"${m.search_usd_per_k:g}" if m.web_search else "off"
        print(
            f"  {name:<14} {roles.get(name, ''):<13} {m.provider:<10} {m.model:<20}"
            f" {m.effort:<7} {price:<15} {search}"
        )
    print("\nSwitch with: kit models work <name>   or   kit config set routing.mode cloud-first")
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
    model = OllamaModel(lambda: store.current().ollama, client)
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
    return Cloud(memory, lambda provider: cloud_api_key(paths, provider), providers)


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
    app = create_app(store, memory, brain, token, paths=paths)
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
            async for event in brain.chat(text, "terminal"):
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
    felt = state.get("feeling")
    if felt:
        print(f"feeling:  {felt['name']}, because {felt['why']} (since {felt['since'][11:16]})")
    print("drives:   " + ", ".join(f"{k} {v}" for k, v in state["drives"].items()))
    if state.get("thinking"):
        print(f"thinking: {state['thinking']}")
    for want in state.get("wants", [])[:3]:
        print(f"wants to: {want}")
    for want in state.get("later", [])[:3]:
        print(f"later:    {want['text']} (from {want['after'][:16].replace('T', ' ')})")
    print(f"quiet:    {state.get('quiet_because') or 'ready to pipe up'}")
    if state.get("closeness"):
        print(f"you two:  {state['closeness']}")
    if state.get("away_since"):
        print(f"away:     since {state['away_since'][11:16]} (as far as Kit can tell)")
    if state.get("hello_owed"):
        print(f"hello:    owed ({state['hello_owed']}), said at the next chance")
    if state.get("goodbye"):
        print(f'goodbye:  "{state["goodbye"]}" (he\'ll ask how it went)')
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
    for title, key in [
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
                said = "  (said)" if e.get("meta", {}).get("said") else ""
                print(f"{e['id']:>6}  {e['day']}  {e['text']}{said}")
    print("\nForget an entry on the memory page (Kit's notebook tab).")


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
    if args.action in ("summarise", "remember", "search", "reindex"):
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
    elif args.action == "days":
        for item in memory.index.items("days"):
            print(f"{item.ref}  {item.text}\n")
    elif args.action == "backup":
        keep = SettingsStore(paths).current().memory.backups_keep
        print(f"backed up to {memory.backup(paths.backups_dir, keep)}")
    elif args.action == "spend":
        cap = SettingsStore(paths).current().cloud.monthly_cap_usd
        print(f"Cloud models this month: ${memory.month_spend():.2f} of ${cap:.2f}")
        for s in memory.spend_log(20):
            print(
                f"  {s.at}  {s.model}  in {s.input_tokens}  out {s.output_tokens}"
                f"  ${s.cost_usd:.4f}  {s.question[:60]}"
            )
    memory.close()
    return code


async def _memory_async(paths: KitPaths, args: argparse.Namespace) -> int:
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
                hits = await brain.recall.search(args.query, [FACTS, DAYS, CONVERSATION, NOTES], 10)
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
            elif args.action == "reindex":
                done = await brain.recall.index_pending(limit=1_000_000)
                problem = brain.recall.embed_problem
                print(f"indexed {done} item(s)" + (f"; stopped: {problem}" if problem else ""))
                return 1 if problem else 0
        finally:
            memory.close()
    return 0


async def _eval(paths: KitPaths, n: int) -> int:
    from datetime import datetime

    from kit.evals import PROMPTS, run_eval
    from kit.local_model import OllamaModel

    store = SettingsStore(paths)
    settings = store.current()
    prompts = (PROMPTS * (n // len(PROMPTS) + 1))[:n]
    async with httpx.AsyncClient() as client:
        model = OllamaModel(lambda: settings.ollama, client)
        print(f"warming up {settings.ollama.model}...")
        await run_eval(model, settings, ["Hi."], datetime.now())

        def show(r):
            mark = "ok  " if r.valid else "BAD "
            t = f"{r.first_word_s:.2f}s" if r.first_word_s is not None else "  -  "
            print(f"{mark} {t}  {r.prompt[:60]}" + (f"\n       {r.error}" if r.error else ""))

        report = await run_eval(model, settings, prompts, datetime.now(), on_result=show)
    median, p90 = report.latency(0.5), report.latency(0.9)
    print()
    print(f"valid replies: {report.valid}/{len(report.results)}")
    if median is not None:
        print(f"first words:   median {median:.2f}s, 90% within {p90:.2f}s")
    return 0 if report.valid == len(report.results) else 1


async def _eval_compare(paths: KitPaths, names: list[str], n: int) -> int:
    """Ask several cloud models the same questions and write their answers side by side."""
    from datetime import datetime

    from kit.evals import COMPARE_PROMPTS, compare_report, run_compare
    from kit.memory import Memory

    paths.ensure()
    settings = SettingsStore(paths).current()
    unknown = [name for name in names if name not in settings.models]
    if unknown:
        print(f"unknown model(s): {', '.join(unknown)}; see `kit models`")
        return 2
    prompts = COMPARE_PROMPTS[: max(1, n)]
    print(f"asking {', '.join(names)} {len(prompts)} questions each; this spends real money")
    memory = Memory(paths.state_dir / "memory.db")
    try:
        async with httpx.AsyncClient() as client:
            cloud = make_cloud(paths, memory, client)

            def show(r):
                mark = "ok  " if r.ok else "FAIL"
                print(f"{mark} {r.model:<14} {r.seconds:5.1f}s  ${r.cost_usd:.4f}  {r.prompt[:50]}")
                if r.error:
                    print(f"       {r.error}")

            results = await run_compare(
                cloud, settings, names, prompts, datetime.now(), on_result=show
            )
    finally:
        memory.close()
    out = paths.state_dir / "evals" / f"compare-{datetime.now():%Y%m%d-%H%M%S}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = compare_report(results, names)
    out.write_text(report, encoding="utf-8")
    print()
    print("\n".join(line for line in report.splitlines() if line.startswith("- **")))
    print(f"\nfull answers, side by side: {out}")
    return 0 if all(r.ok for r in results) else 1


async def _eval_memory(paths: KitPaths) -> int:
    """Run the memory test in a scratch memory inside the data folder, then delete it."""
    from kit.embed import OllamaEmbedder
    from kit.evals import run_memory_eval
    from kit.learning import Learner
    from kit.local_model import OllamaModel
    from kit.memory import Memory
    from kit.recall import Recall

    paths.ensure()
    store = SettingsStore(paths)
    scratch = paths.state_dir / "memory-eval"
    shutil.rmtree(scratch, ignore_errors=True)
    memory = Memory(scratch / "memory.db")
    try:
        async with httpx.AsyncClient() as client:
            model = OllamaModel(lambda: store.current().ollama, client)
            recall = Recall(memory, OllamaEmbedder(store.current, client), store.current)
            print("teaching Kit 13 facts, some repeated or changed...")
            report = await run_memory_eval(memory, Learner(memory, recall, model), recall)
    finally:
        memory.close()
        shutil.rmtree(scratch, ignore_errors=True)
    if recall.embed_problem:
        print(f"warning: searching by words only: {recall.embed_problem}")
    for decision, text in report.learned:
        print(f"  {decision:<6} {text}")
    print()
    for question, ok, texts in report.found:
        print(f"{'ok  ' if ok else 'MISS'} {question}")
        if not ok:
            for t in texts[:3]:
                print(f"       recalled: {t}")
    for question, texts in report.unknown:
        print(f"{'ok  ' if not texts else 'NOISE'} {question}")
        for t in texts[:3]:
            print(f"       recalled: {t}")
    for name, ok in report.tidy:
        print(f"{'ok  ' if ok else 'MESSY'} {name}")
    print()
    print(f"recalled the right fact:    {report.recall_score}/{len(report.found)}")
    print(f"nothing for unknown things: {report.unknown_clean}/{len(report.unknown)}")
    print(f"memory kept tidy:           {report.tidy_score}/{len(report.tidy)}")
    if report.right and report.unrelated:
        cutoff = store.current().memory.min_similarity
        print()
        print(f"closeness of the right facts:   {min(report.right):.2f} to {max(report.right):.2f}")
        print(f"closest fact to unknown things: {max(report.unrelated):.2f}")
        print(f"memory.min_similarity is now:   {cutoff:.2f}")
        suggested = report.suggested_cutoff()
        if suggested is None:
            print("the two overlap, so no cut-off separates them for this embedding model")
        elif abs(suggested - cutoff) >= 0.02:
            print(f"try: kit config set memory.min_similarity {suggested}")
    return 0 if report.passed else 1


async def _eval_routing(paths: KitPaths) -> int:
    """Check Kit knows where to look: the built-in questions against a scratch
    register, then Dan's own questions (routing-questions.toml) against his register."""
    from kit.embed import OllamaEmbedder
    from kit.evals import load_routing_questions, run_routing_eval, seed_routing_things
    from kit.memory import Memory
    from kit.recall import Recall
    from kit.things import Register

    paths.ensure()
    store = SettingsStore(paths)
    scratch = paths.state_dir / "routing-eval"
    shutil.rmtree(scratch, ignore_errors=True)
    reports = []
    async with httpx.AsyncClient() as client:
        embedder = OllamaEmbedder(store.current, client)
        memory = Memory(scratch / "memory.db")
        try:
            seed_routing_things(Register(memory))
            recall = Recall(memory, embedder, store.current)
            reports.append(("built-in questions", await run_routing_eval(recall), recall))
        finally:
            memory.close()
            shutil.rmtree(scratch, ignore_errors=True)
        own = paths.config_dir / "routing-questions.toml"
        if own.exists():
            memory = Memory(paths.state_dir / "memory.db")
            try:
                recall = Recall(memory, embedder, store.current)
                questions = load_routing_questions(own)
                reports.append(
                    (
                        f"your questions ({own.name})",
                        await run_routing_eval(recall, questions),
                        recall,
                    )
                )
            finally:
                memory.close()
    passed = True
    for title, report, recall in reports:
        print(f"{title}:")
        if recall.embed_problem:
            print(f"  warning: searching by words only: {recall.embed_problem}")
        for r in report.results:
            print(f"  {'ok  ' if r.ok else 'MISS'} {r.question}")
            if not r.ok:
                print(f"         wanted {r.system}: {r.target}")
                for line in r.got[:3] or ["(nothing recalled)"]:
                    print(f"         recalled: {line}")
        print(f"  knew where to look: {report.score}/{len(report.results)}\n")
        passed = passed and report.passed
    if len(reports) == 1:
        print(f"add your own questions in {own} to test your real register")
    return 0 if passed else 1


async def _voice_run(paths: KitPaths, client: httpx.AsyncClient, settings: Settings, prompts, show):
    """One model's turn at the voice eval, in a scratch memory that's deleted after."""
    from kit.evals import run_voice_eval

    return await _local_run(
        paths,
        client,
        settings,
        lambda brain, name: run_voice_eval(brain, name, prompts, on_line=show),
    )


async def _local_run(
    paths: KitPaths, client: httpx.AsyncClient, settings: Settings, run, clock=None
):
    """``run(brain, model name)`` for one local model, with Kit seeded the same way
    every time (``seed_voice``), in a scratch memory that's deleted after. ``clock``
    sets the time Kit thinks it is."""
    from kit.brain import Brain
    from kit.cloud import Cloud
    from kit.evals import seed_voice
    from kit.local_model import LocalModelError, OllamaModel
    from kit.memory import Memory
    from kit.recall import Recall

    name = settings.ollama.model
    model = OllamaModel(lambda: settings.ollama, client)
    print(f"warming up {name}...")
    try:
        await model.complete([{"role": "user", "content": "Hi."}], None)
    except LocalModelError as e:
        print(f"  skipped {name}: {e}\n  (is it pulled? ollama pull {name})")
        return None
    scratch = paths.state_dir / "voice-eval"
    shutil.rmtree(scratch, ignore_errors=True)
    memory = Memory(scratch / "memory.db", clock) if clock else Memory(scratch / "memory.db")
    try:
        # No cloud, no web and words-only recall: the local model alone, as on the desk.
        cloud = Cloud(memory, lambda provider: None, {})
        brain = Brain(
            lambda: settings, memory, model, cloud, Recall(memory, None, lambda: settings)
        )
        seed_voice(brain)
        return await run(brain, name)
    finally:
        memory.close()
        shutil.rmtree(scratch, ignore_errors=True)


async def _eval_voice(paths: KitPaths, names: list[str], one_pass: bool, n: int | None) -> int:
    """The same chat, pipe-ups and thoughts through each local model, written side by
    side, to pick the model that sounds most like Kit."""
    from datetime import datetime

    from kit.evals import VOICE_PROMPTS, voice_report

    paths.ensure()
    base = SettingsStore(paths).current()
    names = names or [base.ollama.model]
    prompts = VOICE_PROMPTS[:n] if n else VOICE_PROMPTS

    def show(line):
        mark = "FAIL" if not line.ok else ("ECHO" if line.echo else "ok  ")
        t = line.first_s if line.first_s is not None else line.total_s
        said = line.error or line.text or "(nothing came to mind)"
        print(f"{mark} {t:4.1f}s  {line.prompt[:28]:<28}  {said[:90]}")

    reports = []
    async with httpx.AsyncClient() as client:
        for name in names:
            settings = _eval_settings(base, name, one_pass)
            report = await _voice_run(paths, client, settings, prompts, show)
            if report is not None:
                reports.append(report)
            print()
    if not reports:
        return 1
    out = paths.state_dir / "evals" / f"voice-{datetime.now():%Y%m%d-%H%M%S}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(voice_report(reports), encoding="utf-8")
    for report in reports:
        print(f"- {report.summary()}".replace("**", ""))
    print(f"\nevery line, side by side: {out}")
    print("pick one with: kit config set ollama.model <name>")
    return 0 if all(r.answered == len(r.spoken) for r in reports) else 1


def _eval_settings(base: Settings, name: str, one_pass: bool = False) -> Settings:
    """Settings for a local-model eval: that model, local-heavy, no nightly reflection."""
    return base.model_copy(
        update={
            "ollama": base.ollama.model_copy(update={"model": name, "speak_pass": not one_pass}),
            "routing": base.routing.model_copy(update={"mode": "local-heavy"}),
            "life": base.life.model_copy(update={"reflect_with": "off"}),
        }
    )


async def _eval_companion(paths: KitPaths, names: list[str]) -> int:
    """Goodbyes, hellos, wrong facts and news through each local model: does he act
    like a good companion? Written side by side to read."""
    from datetime import datetime

    from kit.evals import companion_clock, companion_report, run_companion_eval

    paths.ensure()
    base = SettingsStore(paths).current()
    names = names or [base.ollama.model]

    def show(line):
        mark = "ok  " if line.passed else "FAIL"
        print(f"{mark} {line.kind:<9} {line.prompt[:30]:<30}  {(line.text or line.why)[:80]}")

    reports = []
    async with httpx.AsyncClient() as client:
        for name in names:
            settings = _eval_settings(base, name)
            report = await _local_run(
                paths,
                client,
                settings,
                lambda brain, n: run_companion_eval(brain, n, show),
                companion_clock(),
            )
            if report is not None:
                reports.append(report)
            print()
    if not reports:
        return 1
    out = paths.state_dir / "evals" / f"companion-{datetime.now():%Y%m%d-%H%M%S}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(companion_report(reports), encoding="utf-8")
    for report in reports:
        print(f"- {report.summary()}".replace("**", ""))
    print(f"\nevery line, side by side: {out}")
    return 0 if all(r.passed == len(r.lines) for r in reports) else 1


def _parse_link(text: str) -> dict:
    system, _, target = text.partition("=")
    if not target:
        raise SystemExit(f"links look like system=target, e.g. nas=Documents/Tax (got {text!r})")
    return {"system": system.strip(), "target": target.strip()}


def cmd_notes(paths: KitPaths) -> int:
    """Read the notes vault now and show what Kit sees."""
    from kit.memory import Memory
    from kit.notes import Notes

    paths.ensure()
    nas = SettingsStore(paths).current().nas
    if not nas.vault:
        print("no notes vault set; see docs/notes.md (kit config set nas.vault ...)")
        return 1
    memory = Memory(paths.state_dir / "memory.db")
    try:
        notes = Notes(memory.index, memory.clock)
        indexed, removed = notes.sync(nas)
        names = notes.names(limit=1_000_000)
        print(f"{len(names)} notes in {nas.vault} ({indexed} read now, {removed} gone)")
        for name in names[:15]:
            print(f"  {name}")
        if len(names) > 15:
            print(f"  ... and {len(names) - 15} more")
    finally:
        memory.close()
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

    models = sub.add_parser("models", help="see the models Kit uses, or switch one")
    models.add_argument("role", nargs="?", choices=["work", "expert"], help="role to switch")
    models.add_argument("name", nargs="?", help="model profile to use for it")

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
    msub.add_parser("reindex", help="build any missing meaning vectors now")
    msub.add_parser("backup", help="back up memory now")
    msub.add_parser("spend", help="show this month's cloud spend")

    sub.add_parser("notes", help="read the notes vault now and list what Kit sees")
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

    ev = sub.add_parser(
        "eval",
        help="test the local model's replies, memory recall, routing, voice or how good a "
        "companion he is, or compare cloud models",
    )
    ev.add_argument(
        "which",
        nargs="?",
        default="replies",
        choices=["replies", "memory", "routing", "compare", "voice", "companion"],
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
    if args.command == "notes":
        return cmd_notes(paths)
    if args.command == "things":
        return cmd_things(paths, args)
    if args.command == "weather":
        return asyncio.run(_weather(paths, args.place))
    if args.command == "eval":
        if args.which == "routing":
            return asyncio.run(_eval_routing(paths))
        if args.which == "memory":
            return asyncio.run(_eval_memory(paths))
        if args.which == "voice":
            return asyncio.run(_eval_voice(paths, args.models, args.one_pass, args.n))
        if args.which == "companion":
            return asyncio.run(_eval_companion(paths, args.models))
        if args.which == "compare":
            if not args.models:
                print("name the models to compare, e.g. kit eval compare --models sonnet gpt-sol")
                return 2
            return asyncio.run(_eval_compare(paths, args.models, args.n or 10))
        return asyncio.run(_eval(paths, args.n or 50))
    results = run_checks(paths, set(args.skip))
    print_report(results)
    return 1 if any(r.status is Status.FAIL for r in results) else 0
