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
from kit.credentials import anthropic_api_key, api_token
from kit.paths import KitPaths
from kit.settings import Settings, SettingsError, load_settings, settings_to_toml
from kit.settings_store import SettingsStore

CHECK_NAMES = ["data", "gpu", "ollama", "tailscale", "nas", "claude"]


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
    if "claude" not in skip:
        results.append(checks.check_claude(settings, anthropic_api_key(paths)))
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


def cmd_config(paths: KitPaths, args: argparse.Namespace) -> int:
    store = SettingsStore(paths)
    try:
        if args.action == "show":
            print(settings_to_toml(store.current()), end="")
        elif args.action == "schema":
            print(json.dumps(Settings.model_json_schema(), indent=2))
        elif args.action == "set":
            section, _, field = args.key.partition(".")
            if not field:
                print("use section.field, for example persona.name")
                return 2
            store.update({section: {field: parse_value(args.value)}}, "cli")
            print(f"set {args.key}; Kit uses it from the next message")
        elif args.action == "undo":
            store.undo()
            print("went back to the previous settings")
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


def _runtime(paths: KitPaths, client: httpx.AsyncClient):
    from kit.brain import Brain
    from kit.expert import Expert
    from kit.local_model import OllamaModel
    from kit.memory import Memory

    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db")
    model = OllamaModel(lambda: store.current().ollama, client)
    expert = Expert(memory, lambda: anthropic_api_key(paths))
    return store, memory, Brain(store.current, memory, model, expert)


def cmd_serve(paths: KitPaths, args: argparse.Namespace) -> int:
    import uvicorn

    from kit.server import create_app

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
    app = create_app(store, memory, brain, token)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


async def _chat_loop(paths: KitPaths) -> int:
    async with httpx.AsyncClient() as client:
        store, memory, brain = _runtime(paths, client)
        name = store.current().persona.name
        if store.problem:
            print(f"warning: {store.problem}\n")
        print(f"Talking to {name}. Ctrl+C or an empty line to stop.")
        while True:
            try:
                text = await asyncio.to_thread(input, "you> ")
            except (EOFError, KeyboardInterrupt):
                break
            if not text.strip():
                break
            print(f"{name.lower()}> ", end="", flush=True)
            async for event in brain.chat(text):
                kind = event["type"]
                if kind == "say":
                    print(event["text"], end="", flush=True)
                elif kind == "reply":
                    r = event["reply"]
                    tags = [r["emotion"], *(s["gesture"] for s in r["segments"])]
                    if event["source"] == "claude":
                        tags += [event["model"], f"${event['cost_usd']:.3f}"]
                    print(f"  [{' · '.join(t for t in tags if t != 'none')}]")
                elif kind == "asking_claude":
                    print(f"{name.lower()}> (asking Claude) ", end="", flush=True)
                elif kind == "remembered":
                    print(f"  (remembered: {event['fact']})")
                elif kind == "error":
                    print(f"\n  ! {event['message']}")
        memory.close()
    return 0


def cmd_memory(paths: KitPaths, args: argparse.Namespace) -> int:
    from kit.memory import Memory

    paths.ensure()
    if args.action == "summarise":
        return asyncio.run(_summarise(paths))
    memory = Memory(paths.state_dir / "memory.db")
    if args.action == "facts":
        facts = memory.facts()
        if not facts:
            print("nothing remembered yet")
        for f in facts:
            print(f"{f.id:>5}  {f.day}  {f.text}")
    elif args.action == "remember":
        memory.add_fact(args.text)
        print("remembered")
    elif args.action == "forget":
        print("forgotten" if memory.forget(args.id) else f"no fact {args.id}")
    elif args.action == "spend":
        cap = SettingsStore(paths).current().claude.monthly_cap_usd
        print(f"Claude this month: ${memory.month_spend():.2f} of ${cap:.2f}")
        for s in memory.spend_log(20):
            print(
                f"  {s.at}  {s.model}  in {s.input_tokens}  out {s.output_tokens}"
                f"  ${s.cost_usd:.4f}  {s.question[:60]}"
            )
    memory.close()
    return 0


async def _summarise(paths: KitPaths) -> int:
    async with httpx.AsyncClient() as client:
        _, memory, brain = _runtime(paths, client)
        days = await brain.summarise_past_days()
        print(f"summarised {len(days)} day(s): {', '.join(days)}" if days else "nothing to do")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kit", description="Kit, your personal assistant.")
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
    sub.add_parser("token", help="show the API token for the pages and home_app")

    config = sub.add_parser("config", help="see or change Kit's settings")
    csub = config.add_subparsers(dest="action", required=True)
    csub.add_parser("show", help="print the settings in force")
    csub.add_parser("schema", help="print the settings schema (JSON)")
    cset = csub.add_parser("set", help="change one setting, e.g. persona.name Kit")
    cset.add_argument("key")
    cset.add_argument("value")
    csub.add_parser("undo", help="go back to the settings before the last change")
    csub.add_parser("history", help="list earlier versions")
    crestore = csub.add_parser("restore", help="go back to an earlier version")
    crestore.add_argument("version")
    csub.add_parser("check", help="check the settings file is valid")

    mem = sub.add_parser("memory", help="see what Kit remembers and spends")
    msub = mem.add_subparsers(dest="action", required=True)
    msub.add_parser("facts", help="list remembered facts")
    mremember = msub.add_parser("remember", help="add a fact")
    mremember.add_argument("text")
    mforget = msub.add_parser("forget", help="delete a fact by its number")
    mforget.add_argument("id", type=int)
    msub.add_parser("summarise", help="turn finished days into facts now")
    msub.add_parser("spend", help="show this month's Claude spend")

    ev = sub.add_parser("eval", help="check the local model's replies are valid and quick")
    ev.add_argument("--n", type=int, default=50, help="how many prompts (default 50)")

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
    if args.command == "memory":
        return cmd_memory(paths, args)
    if args.command == "eval":
        return asyncio.run(_eval(paths, args.n))
    results = run_checks(paths, set(args.skip))
    print_report(results)
    return 1 if any(r.status is Status.FAIL for r in results) else 0
