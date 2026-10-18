"""Kit's brain service: the chat and settings pages, and the API behind them.

Every /api route except /api/health needs the token from Kit's secrets folder
(`kit token`). Configurators such as home_app use the same API; Kit never
calls them. The routes themselves are in kit.routes, one router per part of
Kit, sharing one ``AppState``; this module builds the app around them and runs
Kit's background loops (his heartbeat, upkeep, notes and voice engine).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI

import kit
from kit.body_registry import BodyRegistry
from kit.brain import Brain
from kit.devices import DEVICES_FILE, Devices
from kit.files.index import Files
from kit.known_faces import FACES_FILE, KnownFaces
from kit.known_voices import VOICES_FILE, KnownVoices
from kit.life import TICK_S
from kit.memory import Memory
from kit.paths import KitPaths
from kit.routes import ROUTERS
from kit.routes.life import pipe_up_now
from kit.routes.state import AppState
from kit.settings_store import SettingsStore
from kit.speech.service import SpeechError, SpeechService

__all__ = ["create_app", "life_tick", "pipe_up_now"]

log = logging.getLogger(__name__)

SUMMARY_INTERVAL_S = 3600
NOTES_SYNC_S = 300  # how often Kit looks for new and changed notes in the vault
SPEECH_CHECK_S = 5  # how often the voice engine is started or stopped to match settings
FILES_CHECK_S = 60  # how often Kit checks whether a files sync is due (files.sync_every_minutes)


def create_app(
    store: SettingsStore,
    memory: Memory,
    brain: Brain,
    token: str,
    summarise_every_s: float | None = SUMMARY_INTERVAL_S,
    paths: KitPaths | None = None,
    life_every_s: float | None = TICK_S,
    notes_every_s: float | None = NOTES_SYNC_S,
    speech: SpeechService | None = None,
    speech_check_s: float | None = SPEECH_CHECK_S,
    faces: KnownFaces | None = None,
    voices: KnownVoices | None = None,
    devices: Devices | None = None,
    registry: BodyRegistry | None = None,
    files_every_s: float | None = FILES_CHECK_S,
) -> FastAPI:
    if faces is None:
        faces = KnownFaces(paths.state_dir / FACES_FILE if paths is not None else None)
    if voices is None:
        voices = KnownVoices(paths.state_dir / VOICES_FILE if paths is not None else None)
    if devices is None:
        devices = Devices(paths.secrets_dir / DEVICES_FILE if paths is not None else None)
    if registry is None:
        registry = brain.bodies
    brain.bodies = registry
    if brain.files is None:
        brain.files = Files(
            memory.index,
            store.current,
            store.paths.state_dir,
            names=lambda: [n for t in brain.register.all() for n in t.names],
        )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if summarise_every_s:
            tasks.append(asyncio.create_task(_upkeep_loop(brain, paths, store, summarise_every_s)))
        if life_every_s:
            tasks.append(asyncio.create_task(_life_loop(brain, life_every_s)))
        if notes_every_s:
            tasks.append(asyncio.create_task(_notes_loop(brain, store, notes_every_s)))
        if files_every_s:
            tasks.append(asyncio.create_task(_files_loop(brain, store, files_every_s)))
        if speech is not None and speech_check_s:
            tasks.append(asyncio.create_task(_speech_loop(speech, store, speech_check_s)))
        yield
        for task in tasks:
            task.cancel()
        await brain.close()  # learning that was running after a reply
        await brain.cloud.close()
        if speech is not None:
            await asyncio.to_thread(speech.close)

    app = FastAPI(title="Kit", version=kit.__version__, lifespan=lifespan)
    if speech is not None:
        brain.voice_quiet = speech.quiet_s  # reading ahead waits for his voice to finish
    app.state.kit = AppState(store, memory, brain, token, faces, devices, registry, speech, voices)
    for router in ROUTERS:
        app.include_router(router)
    return app


async def _notes_loop(brain: Brain, store: SettingsStore, every_s: float) -> None:
    """Keep the index in step with Dan's notes vault, from start-up on."""
    while True:
        try:
            indexed, removed = await asyncio.to_thread(brain.notes.sync, store.current().nas)
            if indexed or removed:
                log.info("notes: %d indexed, %d removed", indexed, removed)
                await brain.recall.index_pending(limit=5000)
        except Exception:
            log.exception("reading the notes vault failed")
        await asyncio.sleep(every_s)


async def _files_loop(brain: Brain, store: SettingsStore, every_s: float) -> None:
    """Keep the index in step with Dan's folders (kit.files): a sync once at start-up
    and then every ``files.sync_every_minutes`` (once a day when that's 0). Only new
    and changed files are read; the pieces are embedded as they come."""
    last = None
    while True:
        try:
            s = store.current().files
            gap = (s.sync_every_minutes or 24 * 60) * 60
            now = asyncio.get_running_loop().time()
            if s.roots and (last is None or now - last >= gap) and not brain.files.running:
                last = now
                report = await asyncio.to_thread(brain.files.sync)
                if report.indexed or report.removed:
                    log.info("files: %s", report.line())
                while await brain.recall.index_pending(limit=5000):
                    pass
        except Exception:
            log.exception("reading the files roots failed")
        await asyncio.sleep(every_s)


async def _speech_loop(speech: SpeechService, store: SettingsStore, every_s: float) -> None:
    """Load the voice engine when speech is on, so the first reply isn't kept waiting
    while it loads; stop it when speech is off, which frees the graphics card."""
    last_problem = ""
    while True:
        try:
            if store.current().speech.enabled:
                await asyncio.to_thread(speech.ensure)
            elif speech.running():
                await asyncio.to_thread(speech.stop)
            last_problem = ""
        except SpeechError as e:
            if str(e) != last_problem:  # once per problem, not every few seconds
                log.warning("voice engine: %s", e)
            last_problem = str(e)
        except Exception:
            log.exception("managing the voice engine failed")
        await asyncio.sleep(every_s)


async def _life_loop(brain: Brain, every_s: float, step_s: float = 1.0) -> None:
    """Kit's heartbeat: drives move, he fidgets, and now and then he pipes up. A
    hello waiting to be said (Dan just sat down, or came back to the keyboard)
    gets a beat straight away rather than at the next one, so he says hi while
    Dan's still sitting down. The same goes for the cat just spotted, and for
    someone else Kit knows sitting down."""
    loop = asyncio.get_running_loop()
    last = loop.time()
    greeted = None
    while True:
        await asyncio.sleep(min(step_s, every_s))
        life = brain.life
        home = life.homecoming or getattr(life, "visitor", None) or getattr(life, "spotted", None)
        due = loop.time() - last >= every_s
        if not due and (home is None or home is greeted):
            continue
        greeted = home  # one early beat per hello: quiet hours or a snooze can hold it
        last = loop.time()
        try:
            await life_tick(brain)
        except Exception:
            log.exception("Kit's heartbeat failed")


async def life_tick(brain: Brain) -> None:
    """One heartbeat: drives move on, and Kit may pipe up or, failing that, have a
    thought of his own. Neither happens while he's answering something. Once a day
    he may think of a small game to suggest, a getting-to-know-you question, or a
    nudge toward bed or outside (``Brain.offer_wants``). While Dan's out he finds
    something to do (``Brain.start_pastime``), and late in the afternoon he settles
    any weather bet."""
    brain.offer_wants()
    await brain.free_gpu()
    brain.life.wanting = brain.notebook.pressing()
    reason = brain.life.tick()
    await brain.settle_bet()
    await brain.start_pastime()
    if brain.jobs or brain.talking():
        return
    if reason is not None:
        await pipe_up_now(brain, reason)
        return
    trigger = brain.life.think_now()
    if trigger is None:
        return
    if trigger[0] != "alone":
        await brain.think(trigger)
        return
    # A thought on his own runs as its own task, so a message from Dan stops it.
    brain._musing = asyncio.create_task(brain.think(trigger))
    await asyncio.wait({brain._musing})


async def _upkeep_loop(
    brain: Brain, paths: KitPaths | None, store: SettingsStore, every_s: float
) -> None:
    """Summarise finished days, let Kit reflect on them, embed anything not yet
    indexed, back up memory daily, and fetch the day's model prices."""
    while True:
        try:
            await brain.summarise_past_days()
        except Exception:
            log.exception("summarising past days failed")
        try:
            await brain.reflect()
        except Exception:
            log.exception("Kit's nightly reflection failed")
        try:
            brain.tidy()
        except Exception:
            log.exception("tidying memory and the notebook failed")
        try:
            await brain.recall.index_pending(limit=5000)
        except Exception:
            log.exception("indexing memories failed")
        if paths is not None:
            try:
                if not brain.memory.backed_up_today(paths.backups_dir):
                    keep = store.current().memory.backups_keep
                    await asyncio.to_thread(brain.memory.backup, paths.backups_dir, keep)
            except Exception:
                log.exception("backing up memory failed")
        try:
            if not brain.cloud.prices.fetched_today():
                await brain.cloud.prices.refresh()  # today's model prices and exchange rate
        except Exception:
            log.exception("fetching prices failed")
        await asyncio.sleep(every_s)
