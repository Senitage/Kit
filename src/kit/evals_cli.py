"""The ``kit eval`` runners: each eval in kit.evals run against the real models
and Kit's real settings, with what it found printed (``kit eval``, ``kit eval
memory``, ``voice``, ``companion``, ``mood``, ``routing``, ``tools`` and ``compare``).
Most run in a scratch memory inside the data folder that's deleted after."""

from __future__ import annotations

import argparse
import asyncio
import shutil
from datetime import datetime
from pathlib import Path

import httpx

from kit.cli import make_cloud
from kit.paths import KitPaths
from kit.settings import Settings, local_settings
from kit.settings_store import SettingsStore


def cmd_eval(paths: KitPaths, args: argparse.Namespace) -> int:
    """``kit eval [WHICH]``: run one eval and say how it went (0 when it passed)."""
    if args.which == "routing":
        return asyncio.run(_eval_routing(paths))
    if args.which == "tools":
        return asyncio.run(_eval_tools(paths, args.pack, args.live, args.questions))
    if args.which == "memory":
        return asyncio.run(_eval_memory(paths, args.replay, args.questions))
    if args.which == "voice":
        return asyncio.run(_eval_voice(paths, args.models, args.one_pass, args.n))
    if args.which == "companion":
        return asyncio.run(_eval_companion(paths, args.models))
    if args.which == "mood":
        return asyncio.run(_eval_mood(paths))
    if args.which == "compare":
        if not args.models:
            print("name the models to compare, e.g. kit eval compare --models sonnet gpt-sol")
            return 2
        return asyncio.run(_eval_compare(paths, args.models, args.n or 10))
    return asyncio.run(_eval(paths, args.n or 50))


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
                print(
                    f"{mark} {r.model:<14} {r.seconds:5.1f}s  A${r.cost_aud:.4f}  {r.prompt[:50]}"
                )
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


async def _eval_memory(
    paths: KitPaths, replay: str | None = None, questions: str | None = None
) -> int:
    """Run the memory test in a scratch memory inside the data folder, then delete it.
    With ``replay``, ask your own questions of a copy of a memory snapshot instead."""
    from kit.embed import OllamaEmbedder
    from kit.evals import run_memory_eval
    from kit.learning import Learner
    from kit.local_model import OllamaModel
    from kit.memory import Memory
    from kit.recall import Recall

    paths.ensure()
    if replay is not None:
        return await _eval_replay(paths, Path(replay), Path(questions) if questions else None)
    store = SettingsStore(paths)
    scratch = paths.state_dir / "memory-eval"
    shutil.rmtree(scratch, ignore_errors=True)
    memory = Memory(scratch / "memory.db")
    try:
        async with httpx.AsyncClient() as client:
            model = OllamaModel(lambda: local_settings(store.current()), client)
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


async def _eval_replay(paths: KitPaths, snapshot: Path, questions: Path | None) -> int:
    """``kit eval memory --replay``: your questions (config/memory-questions.toml) against
    a copy of a memory snapshot, usually a backup from ``backups/``. The snapshot itself
    is never written to."""
    from kit.embed import OllamaEmbedder
    from kit.evals import load_replay_questions, run_replay_eval
    from kit.memory import Memory
    from kit.recall import Recall

    questions = questions or paths.config_dir / REPLAY_QUESTIONS
    if not snapshot.is_file():
        print(f"no memory snapshot at {snapshot}")
        return 2
    if not questions.is_file():
        print(f"no questions at {questions}: add some, e.g.\n{REPLAY_EXAMPLE}")
        return 2
    asked = load_replay_questions(questions)
    if not asked:
        print(f"{questions} has no questions, e.g.\n{REPLAY_EXAMPLE}")
        return 2
    store = SettingsStore(paths)
    scratch = paths.state_dir / "memory-eval"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    copy = scratch / "replay.db"
    shutil.copyfile(snapshot, copy)
    memory = Memory(copy)
    try:
        async with httpx.AsyncClient() as client:
            recall = Recall(memory, OllamaEmbedder(store.current, client), store.current)
            print(f"replaying {len(asked)} questions against {snapshot.name}...")
            report = await run_replay_eval(memory, recall, asked)
    finally:
        memory.close()
        shutil.rmtree(scratch, ignore_errors=True)
    if recall.embed_problem:
        print(f"warning: searching by words only: {recall.embed_problem}")
    if report.embedded:
        print(f"embedded {report.embedded} items the snapshot had no vectors for")
    for r in report.results:
        mark = "ok  " if r.wins else ("LOW " if r.found else "MISS")
        where = "" if r.wins else (f" (came {r.rank}th)" if r.found else " (not recalled)")
        print(f"{mark} {r.question}{where}")
        if not r.wins:
            for t in r.recalled[:3] or ["(nothing recalled)"]:
                print(f"       recalled: {t}")
    print()
    print(f"facts in the snapshot:      {report.facts}")
    print(f"the right fact came first:  {report.wins}/{len(report.results)}")
    print(f"the right fact was recalled: {report.found}/{len(report.results)}")
    return 0 if report.passed else 1


REPLAY_QUESTIONS = "memory-questions.toml"
REPLAY_EXAMPLE = '''[[question]]
ask = "What do I drive?"
expect = "Ranger"'''


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


class _HouseStandIn:
    """An empty, always-answering Home Assistant, so ``kit eval tools`` can ask the
    house pack's questions on a machine with no house set up. Nothing is switched."""

    connected, last_error = True, ""

    def subscribe(self, callback) -> None:
        pass

    async def call_service(self, domain, service, data=None, entity=None) -> None:
        pass


async def _eval_tools(paths: KitPaths, pack: str | None, live: bool, questions) -> int:
    """Does each question load the right pack and reach the right tool? Offline it
    checks matching and what's offered; ``--live`` asks the real chat model, with
    every tool stubbed, in a scratch memory (its spend is added to the real log)."""
    from kit.brain import Brain
    from kit.embed import OllamaEmbedder
    from kit.evals import load_tool_cases, run_tool_eval, tool_cases
    from kit.house.model import House
    from kit.local_model import OllamaModel
    from kit.memory import Memory
    from kit.recall import Recall
    from kit.weather import Weather

    paths.ensure()
    store = SettingsStore(paths)
    settings = store.current()
    scratch = paths.state_dir / "tools-eval"
    shutil.rmtree(scratch, ignore_errors=True)
    own = Path(questions) if questions else paths.config_dir / "tool-questions.toml"

    def show(r):
        mark = "ok  " if r.passed else "MISS"
        want = r.case.tool or "nothing"
        got = r.called or "nothing"
        cost = f"  A${r.cost_aud:.4f}" if live else ""
        print(f"{mark} {r.case.question[:52]:<52}  wanted {want:<12} got {got:<12}{cost}")
        if not r.passed:
            print(f"       {r.why}")

    async with httpx.AsyncClient() as client:
        memory = Memory(scratch / "memory.db")
        try:
            model = OllamaModel(lambda: local_settings(settings), client)
            cloud = make_cloud(paths, memory, client)
            recall = Recall(memory, OllamaEmbedder(store.current, client), store.current)
            brain = Brain(store.current, memory, model, cloud, recall, Weather(client))
            if brain.house is None:  # the house pack's questions, without Home Assistant
                brain.use_house(House(_HouseStandIn(), datetime.now))
            if pack and pack not in brain.tools.packs:
                print(f"there's no pack called {pack}; see `kit tools packs`")
                return 2
            cases = tool_cases(brain.tools, pack)
            if own.exists():
                cases += [c for c in load_tool_cases(own) if not pack or c.pack == pack]
            if live:
                print(
                    f"asking {settings.profile('chat').name} {len(cases)} questions; "
                    "this spends real money"
                )
            report = await run_tool_eval(brain, cases, live, on_result=show)
            spends = memory.spend_log(1000)
        finally:
            memory.close()
            shutil.rmtree(scratch, ignore_errors=True)
    if spends:  # the eval's cloud calls count toward the month's cap
        real = Memory(paths.state_dir / "memory.db")
        try:
            for sp in reversed(spends):
                real.record_spend(
                    sp.model,
                    sp.input_tokens,
                    sp.output_tokens,
                    sp.cost_usd,
                    f"kit eval tools: {sp.question}",
                    sp.cached_tokens,
                    sp.cache_write_tokens,
                    sp.searches,
                    sp.cost_aud,
                    sp.aud_per_usd,
                )
        finally:
            real.close()
    if recall.embed_problem:
        print(f"warning: matching by words only: {recall.embed_problem}")
    print(
        f"\nright tool: {report.score}/{len(report.results)}"
        + (f", A${report.cost_aud:.4f} spent" if live else "")
    )
    if not own.exists():
        print(f"add your own questions in {own} to test them too")
    return 0 if report.passed else 1


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
    """Settings for a local-model eval: that model, local-heavy (no key moments for the
    work model either), no nightly reflection."""
    return base.model_copy(
        update={
            "ollama": base.ollama.model_copy(update={"model": name, "speak_pass": not one_pass}),
            "routing": base.routing.model_copy(
                update={"mode": "local-heavy", "key_moments": False}
            ),
            "life": base.life.model_copy(update={"reflect_with": "off"}),
        }
    )


async def _eval_mood(paths: KitPaths) -> int:
    """Calibrate reading Dan's mood by meaning (``life.read_mood``): Dan's labelled
    lines (companion-lines.toml in Kit's config folder) read by the model that would
    read them in chat, against the word rules. Reading by meaning switches on only
    once it beats them on at least 40 lines; the result is kept in Kit's memory."""
    import json
    from datetime import datetime

    from kit.brain import CHAT, MOOD_CALIBRATION, own_role
    from kit.evals import (
        MOOD_LINES_FILE,
        MOOD_LINES_NEEDED,
        load_mood_lines,
        mood_starter,
        run_mood_eval,
    )
    from kit.local_model import OllamaModel
    from kit.memory import Memory
    from kit.prompt import mood_lines
    from kit.reply import mood_read, plan_schema

    paths.ensure()
    store = SettingsStore(paths)
    settings = store.current()
    own = paths.config_dir / MOOD_LINES_FILE
    if not own.exists():
        own.write_text(mood_starter(), encoding="utf-8")
        print(f"started {own} with a few generic lines: add your own, the way you talk")
    lines = load_mood_lines(own)
    owner = settings.persona.owner
    system = "\n".join(
        [
            f"You read how {owner} seems from one message they sent.",
            *mood_lines(owner),
            "Answer only with JSON: emotion, gesture, dan_mood, about, for_whom, expected, "
            'and action {"kind": "none"}.',
        ]
    )

    def messages(text: str) -> list[dict]:
        return [{"role": "system", "content": system}, {"role": "user", "content": text}]

    memory = Memory(paths.state_dir / "memory.db")
    try:
        async with httpx.AsyncClient() as client:
            role = own_role(settings)
            plain = None
            if role == CHAT:
                cloud = make_cloud(paths, memory, client)
                profile = settings.profile(CHAT).model_copy(update={"web_search": False})
                reader = profile.name

                async def read(text: str):
                    answer = await cloud.answer(profile, messages(text), settings, "mood eval")
                    return mood_read(answer.text)

            else:
                model = OllamaModel(lambda: settings.ollama, client)
                reader = settings.ollama.model

                async def read(text: str):
                    return mood_read(await model.complete(messages(text), plan_schema(True)))

                async def plain(text: str):
                    await model.complete(messages(text), plan_schema(False))

            print(f"reading {len(lines)} lines with {reader}...")

            def show(line) -> None:
                mark = "ok  " if line.meaning_right else "MISS"
                words = "ok" if line.words_right else "miss"
                print(
                    f"{mark} {line.seconds:4.1f}s  {line.text[:52]:52}  wanted {line.label}, "
                    f"meaning {line.meaning}, words {line.words} ({words})"
                )

            report = await run_mood_eval(lines, read, plain, owner, show)
        result = report.as_dict(datetime.now(), reader)
        memory.set_self_value(MOOD_CALIBRATION, json.dumps(result))
    finally:
        memory.close()
    print()
    print(f"right by meaning: {report.meaning}/{len(report.lines)}")
    print(f"right by words:   {report.words}/{len(report.lines)}")
    if report.seconds() is not None:
        print(f"reading took:     median {report.seconds():.2f}s a line")
    if report.added_seconds() is not None:
        print(f"adds to a plan:   median {report.added_seconds():+.2f}s before he starts talking")
    if len(report.lines) < MOOD_LINES_NEEDED:
        print(f"add more lines to {own}: {MOOD_LINES_NEEDED} are needed, there are {len(lines)}")
    if report.passed:
        print("passed: with life.read_mood = meaning, Kit now reads you by meaning")
    else:
        print("not passed: Kit keeps reading your words, whatever life.read_mood says")
    return 0 if report.passed else 1


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
