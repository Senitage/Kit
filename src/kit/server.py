"""Kit's brain service: the chat and settings pages, and the API behind them.

Every /api route except /api/health needs the token from Kit's secrets folder
(`kit token`). Configurators such as home_app use the same API; Kit never
calls them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import AsyncIterator
from importlib import resources
from typing import Annotated

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

import kit
from kit.brain import Brain
from kit.knowledge import Item
from kit.life import TICK_S
from kit.memory import CONVERSATION, DAYS, FACTS, SELF, Memory
from kit.notes import NOTES
from kit.paths import KitPaths
from kit.pc_context import Snapshot
from kit.settings import Settings, SettingsError
from kit.settings_store import SettingsStore
from kit.things import THINGS, Register

log = logging.getLogger(__name__)

SUMMARY_INTERVAL_S = 3600
NOTES_SYNC_S = 300  # how often Kit looks for new and changed notes in the vault
NOW_PINNED = "A 'now' fact can't be pinned: it's how things are lately, and goes after two weeks."


class ChatIn(BaseModel):
    text: str
    # Where Dan is talking from (kit.channels): desk, voice, phone, web, home or terminal.
    channel: str = Field("web", max_length=20)


class FactIn(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "other"
    pinned: bool = False


class FactEdit(BaseModel):
    text: str | None = None
    kind: str | None = None
    pinned: bool | None = None


class LinkIn(BaseModel):
    system: str
    target: str


class ThingIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "other"
    aliases: list[str] = []
    links: list[LinkIn] = []
    about: str = ""


class QuirkIn(BaseModel):
    quirk: str = Field(min_length=1)


class VersionIn(BaseModel):
    id: int


class ThingEdit(BaseModel):
    name: str | None = None
    kind: str | None = None
    aliases: list[str] | None = None
    links: list[LinkIn] | None = None
    about: str | None = None


def _item(item: Item | None) -> dict:
    if item is None:
        return {}
    return {
        "id": item.id,
        "source": item.source,
        "kind": item.kind,
        "title": item.title,
        "text": item.text,
        "day": item.day,
        "created": item.created,
        "updated": item.updated,
        "pinned": item.pinned,
        "superseded_by": item.superseded_by,
        "ref": item.ref,
        "meta": item.meta,
    }


def _page(name: str) -> str:
    return resources.files("kit").joinpath("web", name).read_text(encoding="utf-8")


def _settings_error(e: SettingsError) -> HTTPException:
    lines = [line.strip() for line in str(e).splitlines()]
    return HTTPException(422, {"message": lines[0], "problems": [x for x in lines[1:] if x]})


def create_app(
    store: SettingsStore,
    memory: Memory,
    brain: Brain,
    token: str,
    summarise_every_s: float | None = SUMMARY_INTERVAL_S,
    paths: KitPaths | None = None,
    life_every_s: float | None = TICK_S,
    notes_every_s: float | None = NOTES_SYNC_S,
) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if summarise_every_s:
            tasks.append(asyncio.create_task(_upkeep_loop(brain, paths, store, summarise_every_s)))
        if life_every_s:
            tasks.append(asyncio.create_task(_life_loop(brain, life_every_s)))
        if notes_every_s:
            tasks.append(asyncio.create_task(_notes_loop(brain, store, notes_every_s)))
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="Kit", version=kit.__version__, lifespan=lifespan)

    def require_token(authorization: Annotated[str, Header()] = "") -> None:
        given = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(401, "missing or wrong token; run `kit token` to see it")

    auth = [Depends(require_token)]

    @app.get("/", response_class=HTMLResponse)
    def chat_page() -> str:
        return _page("chat.html")

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page() -> str:
        return _page("settings.html")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "name": store.current().persona.name, "version": kit.__version__}

    @app.get("/api/status", dependencies=auth)
    def status() -> dict:
        s = store.current()
        return {
            "name": s.persona.name,
            "version": kit.__version__,
            "settings_problem": store.problem,
            "routing": s.routing.mode,
            "local_model": s.ollama.model,
            "work_model": s.profile("work").model,
            "expert_model": s.profile("expert").model,
            "cloud_month_usd": round(memory.month_spend(), 4),
            "cloud_cap_usd": s.cloud.monthly_cap_usd,
            "working_on": brain.busy(),
            "memory_facts": len(memory.facts()),
            "memory_items": memory.index.count(),
            "memory_search": "words only: " + brain.recall.embed_problem
            if brain.recall.embed_problem
            else "words and meaning",
            "pc": brain.pc.now_line(s.persona.owner) or "the desk app hasn't reported yet",
        }

    @app.get("/api/settings", dependencies=auth)
    def get_settings() -> dict:
        return {"settings": store.current().model_dump(mode="json"), "problem": store.problem}

    @app.get("/api/settings/schema", dependencies=auth)
    def get_schema() -> dict:
        return Settings.model_json_schema()

    @app.patch("/api/settings", dependencies=auth)
    def patch_settings(
        patch: Annotated[dict, Body()], x_changed_by: Annotated[str, Header()] = "api"
    ) -> dict:
        try:
            settings = store.update(patch, x_changed_by)
        except SettingsError as e:
            raise _settings_error(e) from e
        return {"settings": settings.model_dump(mode="json"), "problem": store.problem}

    @app.get("/api/settings/history", dependencies=auth)
    def history() -> list[dict]:
        return [
            {"id": v.id, "saved_at": v.saved_at, "replaced_by": v.changed_by}
            for v in store.history()
        ]

    @app.post("/api/settings/undo", dependencies=auth)
    def undo() -> dict:
        try:
            settings = store.undo()
        except SettingsError as e:
            raise _settings_error(e) from e
        return {"settings": settings.model_dump(mode="json"), "problem": store.problem}

    @app.post("/api/chat", dependencies=auth)
    async def chat(body: ChatIn) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            async for event in brain.chat(body.text, body.channel):
                yield json.dumps(event) + "\n"

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.post("/api/chat/new", dependencies=auth)
    def new_chat() -> dict:
        memory.new_chat()
        return {"ok": True}

    @app.get("/api/messages", dependencies=auth)
    def messages(limit: int = 50) -> list[dict]:
        return [
            {
                "at": m.at,
                "role": m.role,
                "text": m.text,
                "source": m.source,
                "channel": m.channel,
                "reply": json.loads(m.reply_json) if m.reply_json else None,
            }
            for m in memory.recent(min(limit, 500))
        ]

    @app.get("/memory", response_class=HTMLResponse)
    def memory_page() -> str:
        return _page("memory.html")

    @app.get("/api/memory/facts", dependencies=auth)
    def facts() -> list[dict]:
        return [_item(f) for f in reversed(memory.facts())]

    @app.post("/api/memory/facts", dependencies=auth)
    async def add_fact(body: FactIn) -> dict:
        owner = store.current().persona.owner
        if body.pinned and body.kind == "now":
            raise HTTPException(422, NOW_PINNED)
        learned = await brain.learner.learn(body.text, body.kind, owner)
        if body.pinned:
            memory.index.set_pinned(learned.item_id, True)
        return {"decision": learned.decision, "id": learned.item_id, "replaced": learned.replaced}

    @app.patch("/api/memory/facts/{fact_id}", dependencies=auth)
    async def edit_fact(fact_id: int, body: FactEdit) -> dict:
        item = memory.index.get(fact_id)
        if item is None or item.source != FACTS or item.superseded_by:
            raise HTTPException(404, "no such current fact")
        kind = body.kind or item.kind
        if body.pinned and kind == "now":
            raise HTTPException(422, NOW_PINNED)
        if body.text is not None and body.text.strip() != item.text:
            fact_id = memory.replace_fact(fact_id, body.text.strip(), body.kind)
            await brain.recall.index_pending()
        elif body.kind is not None:
            memory.index.update(fact_id, kind=body.kind)
        if body.pinned is not None:
            memory.index.set_pinned(fact_id, body.pinned)
        if kind == "now":
            memory.index.set_pinned(fact_id, False)  # lately is never always
        return _item(memory.index.get(fact_id))

    @app.get("/api/memory/facts/{fact_id}/history", dependencies=auth)
    def fact_history(fact_id: int) -> list[dict]:
        return [_item(i) for i in memory.index.history(fact_id)]

    @app.delete("/api/memory/facts/{fact_id}", dependencies=auth)
    def forget(fact_id: int) -> dict:
        if not memory.forget(fact_id):
            raise HTTPException(404, "no such fact")
        return {"ok": True}

    @app.get("/api/memory/search", dependencies=auth)
    async def search(q: str, k: Annotated[int, Query(ge=1, le=100)] = 10) -> dict:
        hits = await brain.recall.search(
            q, [FACTS, DAYS, CONVERSATION, THINGS, SELF, NOTES], min(k, 50)
        )
        return {
            "words_only": brain.recall.embed_problem is not None,
            "hits": [
                {**_item(h.item), "similarity": h.similarity, "word_match": h.word_match}
                for h in hits
            ],
        }

    register = Register(memory)

    def _thing(thing_id: int) -> dict:
        thing = register.get(thing_id)
        if thing is None:
            raise HTTPException(404, "no such thing")
        return thing.as_dict()

    @app.get("/api/things", dependencies=auth)
    def things() -> list[dict]:
        return [t.as_dict() for t in sorted(register.all(), key=lambda t: t.name.lower())]

    @app.get("/api/things/suggestions", dependencies=auth)
    def thing_suggestions() -> list[dict]:
        return [t.as_dict() for t in register.suggestions()]

    @app.post("/api/things", dependencies=auth)
    async def add_thing(body: ThingIn) -> dict:
        links = [x.model_dump() for x in body.links]
        new_id = register.add(body.name, body.kind, body.aliases, links, body.about)
        await brain.recall.index_pending()
        return _thing(new_id)

    @app.patch("/api/things/{thing_id}", dependencies=auth)
    async def edit_thing(thing_id: int, body: ThingEdit) -> dict:
        links = None if body.links is None else [x.model_dump() for x in body.links]
        try:
            new_id = register.change(
                thing_id, body.name, body.kind, body.aliases, links, body.about
            )
        except KeyError:
            raise HTTPException(404, "no such thing") from None
        await brain.recall.index_pending()
        return _thing(new_id)

    @app.post("/api/things/{thing_id}/confirm", dependencies=auth)
    async def confirm_thing(thing_id: int) -> dict:
        new_id = register.confirm(thing_id)
        if new_id is None:
            raise HTTPException(404, "no such suggestion")
        await brain.recall.index_pending()
        return _thing(new_id)

    @app.post("/api/things/{thing_id}/reject", dependencies=auth)
    def reject_thing(thing_id: int) -> dict:
        if not register.reject(thing_id):
            raise HTTPException(404, "no such suggestion")
        return {"ok": True}

    @app.get("/api/things/{thing_id}/history", dependencies=auth)
    def thing_history(thing_id: int) -> list[dict]:
        return [t.as_dict() for t in register.history(thing_id)]

    @app.delete("/api/things/{thing_id}", dependencies=auth)
    def forget_thing(thing_id: int) -> dict:
        if not register.forget(thing_id):
            raise HTTPException(404, "no such thing")
        return {"ok": True}

    @app.get("/api/memory/days", dependencies=auth)
    def days() -> list[dict]:
        return [_item(i) for i in reversed(memory.index.items(DAYS))]

    @app.post("/api/pc/context", dependencies=auth)
    def pc_report(snap: Snapshot) -> dict:
        """The desk app's report: open windows, focus, idle time and PC health."""
        brain.pc.update(snap)
        brain.life.on_report()
        return {"ok": True}

    @app.get("/api/pc/context", dependencies=auth)
    def pc_context() -> dict:
        """What Kit can see of Dan's PC, as Kit sees it."""
        return brain.pc.as_dict(store.current().persona.owner)

    @app.get("/api/life", dependencies=auth)
    def life() -> dict:
        """Kit's mood, feeling and drives, what he's thinking and wants to bring up, and
        whether he's been told to keep quiet."""
        s = store.current().life
        thought = brain.notebook.latest_thought()
        return {
            **brain.life.state(),
            "thinking": thought.text if thought else None,
            "wants": [w.text for w in brain.notebook.open_wants() if w.kind == "want"],
            "later": [
                {"text": w.text, "after": w.meta.get("after")}
                for w in brain.notebook.unsaid_wants()
                if w.kind == "want" and not brain.notebook.due(w)
            ],
            "threads": [
                {"text": t.text, "after": t.meta.get("after"), "due": brain.notebook.due(t)}
                for t in brain.notebook.threads()
            ],
            "quirks": brain.quirks,
            "games_retired": brain.life.retired_games(),
            "mood_reading": brain.mood_reading(),
            "settings": s.model_dump(),
        }

    @app.get("/api/life/notebook", dependencies=auth)
    def notebook() -> dict:
        """Kit's own notebook: his self-sheet and its earlier versions, the weekly
        reviews, his quirks, wants, thoughts, opinions, moments and journal."""
        nb = brain.notebook
        sheet, dan = nb.sheet(), nb.dan()
        return {
            "sheet": _item(sheet) if sheet else None,
            "sheet_history": [_item(i) for i in nb.sheet_history()[1:]],
            "dan": _item(dan) if dan else None,
            "dan_history": [_item(i) for i in nb.dan_history()[1:]],
            "reviews": [_item(i) for i in nb.reviews(3)],
            "quirks": brain.quirks,
            "retired_quirks": nb.retired_quirks(),
            "wants": [
                {**_item(w), "pressure": round(nb.pressure(w), 2), "due": nb.due(w)}
                for w in nb.unsaid_wants()
                if w.kind == "want"
            ],
            "threads": [{**_item(t), "due": nb.due(t)} for t in nb.entries("thread", 60)],
            "bits": [_item(i) for i in nb.entries("bit", 50)],
            "thoughts": [_item(i) for i in nb.entries("thought", 40)],
            "opinions": [_item(i) for i in nb.entries("opinion", 100)],
            "moments": [_item(i) for i in nb.entries("moment", 100)],
            "journal": [_item(i) for i in nb.entries("journal", 30)],
            "vetoes": nb.vetoes(),
        }

    @app.delete("/api/life/notebook/{item_id}", dependencies=auth)
    def forget_note(item_id: int) -> dict:
        if not brain.notebook.forget(item_id):
            raise HTTPException(404, "no such entry in Kit's notebook")
        brain.life.wanting = brain.notebook.pressing()
        return {"ok": True}

    @app.post("/api/life/sheet/restore", dependencies=auth)
    def restore_sheet(body: VersionIn) -> dict:
        """Go back to an earlier version of Kit's self-sheet. He's told it was undone."""
        new_id = brain.notebook.restore_sheet(body.id, store.current().persona.owner)
        if new_id is None:
            raise HTTPException(404, "no such version of Kit's self-sheet")
        return _item(memory.index.get(new_id))

    def _quirks() -> dict:
        return {"quirks": brain.quirks, "retired_quirks": brain.notebook.retired_quirks()}

    @app.post("/api/life/quirks/retire", dependencies=auth)
    def retire_quirk(body: QuirkIn) -> dict:
        """Take a quirk away; Kit won't pick it up again."""
        if not brain.notebook.retire_quirk(body.quirk, store.current().persona.owner):
            raise HTTPException(404, "Kit doesn't have that quirk")
        return _quirks()

    @app.post("/api/life/quirks/restore", dependencies=auth)
    def restore_quirk(body: QuirkIn) -> dict:
        """Give a retired quirk back."""
        if not brain.notebook.restore_quirk(body.quirk, store.current().persona.owner):
            raise HTTPException(404, "that isn't one of Kit's retired quirks")
        return _quirks()

    @app.post("/api/life/think", dependencies=auth)
    async def think() -> dict:
        """Make Kit have a thought now, whatever his schedule says (for testing)."""
        thought = await brain.think(("asked", "A moment to yourself."))
        return {"thought": thought.as_dict() if thought else None}

    @app.post("/api/life/reflect", dependencies=auth)
    async def reflect() -> dict:
        """Make Kit reflect on today so far, now (for testing). Tonight's reflection
        replaces today's journal entry; earlier versions stay in its history."""
        if store.current().life.reflect_with == "off":
            raise HTTPException(409, "Kit's reflection is off (life.reflect_with)")
        first = brain.notebook.sheet() is None and await brain.reflector.first_sheet()
        done = await brain.reflector.reflect_day(memory.today())
        if done is None:
            raise HTTPException(503, "no model could reflect just now; see logs/kit.log")
        await brain.recall.index_pending()
        return {**done.as_dict(), "first_sheet": first}

    @app.get("/api/life/events", dependencies=auth)
    async def life_events(after: int = 0, wait: Annotated[float, Query(ge=0, le=60)] = 25) -> dict:
        """Fidgets and pipe-ups after event ``after``. Waits up to ``wait`` seconds for
        one, so the desk app (and later the arm) hears about them at once."""
        events = await brain.life.wait_for_events(after, wait)
        return {"events": events, "last": brain.life.state()["last_event"]}

    @app.post("/api/life/poke", dependencies=auth)
    async def life_poke() -> dict:
        """Make Kit pipe up now, whatever his manners say (for testing)."""
        reply = await pipe_up_now(brain, "bored")
        return {"ok": reply is not None, "reply": reply}

    @app.post("/api/life/snooze", dependencies=auth)
    def snooze(minutes: Annotated[float, Body(embed=True, ge=0, le=24 * 60)] = 60) -> dict:
        """Keep Kit from piping up for a while (0 lets him again)."""
        if minutes:
            brain.life.snooze(minutes)
        else:
            brain.life.wake()
        return brain.life.state()

    @app.get("/api/spend", dependencies=auth)
    def spend(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict:
        return {
            "month_usd": round(memory.month_spend(), 4),
            "cap_usd": store.current().cloud.monthly_cap_usd,
            "log": [s.__dict__ for s in memory.spend_log(limit)],
        }

    @app.get("/api/spend/summary", dependencies=auth)
    def spend_summary(days: Annotated[int, Query(ge=1, le=366)] = 30) -> dict:
        """Cloud spend per day and per model, for a chart (the home_app Kit page)."""
        return {
            **memory.spend_summary(days),
            "month_usd": round(memory.month_spend(), 4),
            "cap_usd": store.current().cloud.monthly_cap_usd,
        }

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


async def _life_loop(brain: Brain, every_s: float) -> None:
    """Kit's heartbeat: drives move, he fidgets, and now and then he pipes up."""
    while True:
        await asyncio.sleep(every_s)
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


async def pipe_up_now(brain: Brain, reason: str) -> dict | None:
    """Kit says something unprompted, and every body (desk app, arm) is told."""
    reply = None
    async for event in brain.pipe_up(reason):
        if event["type"] == "reply":
            reply = event
    if reply:
        brain.life.publish(
            {
                "type": "pipe_up",
                "reason": reason,
                "reply": reply["reply"],
                "message_id": reply["message_id"],
            }
        )
        return reply["reply"]
    return None


async def _upkeep_loop(
    brain: Brain, paths: KitPaths | None, store: SettingsStore, every_s: float
) -> None:
    """Summarise finished days, let Kit reflect on them, embed anything not yet
    indexed, and back up memory daily."""
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
        await asyncio.sleep(every_s)
