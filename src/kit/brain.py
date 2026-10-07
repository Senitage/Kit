"""Kit's conversation loop.

Each turn:

1. Route: pick who answers. The routing mode sets the default (the local model,
   or the cloud ``work`` model in cloud-first), and Dan can say "keep it local",
   "ask Claude" or "think hard" to choose for one message.
2. Recall: search memory (facts, past days, old conversations) for anything
   relevant to the message, and put it in the prompt.
3. Answer. The local model's words stream out as they arrive; a cloud model
   answers in one piece. Both answer in the same JSON, as the same Kit.
4. Act on the reply's action:
   - recall: Kit searches memory for something specific, then answers again;
   - look_at_pc: Kit reads the full picture from the desk app (open windows,
     what's had focus this hour and today, PC health), then answers again;
   - remember: the fact is learned, merging with or updating what Kit knew;
   - note: a note Dan asked for is saved as markdown in his Obsidian vault
     (kit.notes), and indexed so it can be found later;
   - thing: a named thing goes in the register of things. A new name becomes a
     suggestion Dan confirms with a quick "yes" (or on the memory page); a link
     for a known thing ("no, it's in Tax/2023") corrects the entry;
   - weather: Kit gets the forecast (kit.weather), then answers again from it;
   - ask_cloud / ask_expert: the question goes to the work or expert model.
   If a cloud model can't answer (offline, no key, budget used up), the local
   model answers instead when ``routing.fallback_to_local`` is on.
5. Index the exchange so it can be found later.

A turn runs as its own task, so Kit keeps talking while a slow one works. While
a cloud model is busy, new messages are answered by the local model, which is
told what Kit is working on, for how long, and what it has done so far ("still
searching, I've looked up x"), so "how's it going?" gets an answer in character.
The slow answer arrives when it's ready, even if the page that asked has gone.

Each message says where Dan is talking from (kit.channels: the desk app, voice,
his phone, the chat page or the terminal). Kit is told in the prompt and answers
to suit, and the message is stored with it.

Kit has a life of his own between messages (kit.life): drives and feelings with
causes, private thoughts (``think``, kit.thinking) kept in his notebook
(kit.notebook), and a nightly reflection (``reflect``, kit.reflection) in which
he writes his journal and his self-sheet. All of it colours what he says.

With ``ollama.speak_pass`` the local model answers in two steps: a quick plan in
JSON (emotion, gesture, action), then Kit's words in plain text at a livelier
temperature, so he sounds like himself rather than a form being filled in.

Settings are read on every turn, so model, routing and persona changes apply at once.
"""

from __future__ import annotations

import asyncio
import contextvars
import itertools
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from kit.channels import channel_line, known
from kit.cloud import Cloud, CloudError
from kit.learning import Learner, said_so
from kit.life import (
    REPLY_FEELINGS,
    SHUSH,
    UNSHUSH,
    Life,
    Voice,
    cheek_style,
    feeling_from,
    pipe_up_prompt,
    quoted,
    repeats,
    same_words,
)
from kit.local_model import LocalModel, LocalModelError, lively
from kit.memory import CONVERSATION, DAYS, FACTS, RECALL_STEP, SELF, Memory, Message
from kit.notebook import (
    ASK_LATER,
    FOR_LATER,
    Notebook,
    as_aim,
    basis,
    later_want,
    tomorrow_morning,
)
from kit.notes import (
    ALL,
    NOTES,
    NoteError,
    Notes,
    Request,
    asked_text,
    asks_for_note,
    request,
    title_for,
)
from kit.pc_context import PcContext
from kit.prompt import (
    IN_WORDS,
    answering_pipe_up,
    history_messages,
    not_again,
    recall_results,
    speak_note,
    split_turn,
    system_prompt,
    weather_results,
    with_mind,
    with_now,
    with_pc_look,
)
from kit.recall import Recall, Recalled
from kit.reflection import Reflector
from kit.reply import (
    Action,
    Plan,
    Reply,
    ReplyError,
    SayExtractor,
    SpokenStream,
    early_plan,
    parse_cloud_reply,
    parse_plan,
    parse_reply,
    plan_json,
    plan_schema,
    reply_json,
    reply_schema,
    sentences,
    spoken_reply,
    without_plans,
)
from kit.settings import Settings
from kit.things import THINGS, Register, named_in
from kit.thinking import THOUGHT_SCHEMA, Thought, parse_thought, thinking_messages
from kit.weather import Weather, WeatherError

log = logging.getLogger(__name__)

Event = dict
LOCAL, WORK, EXPERT = "local", "work", "expert"
PIPE_UP = "pipe_up"  # the source of a message Kit said of his own accord
HELD_TRIES = 3  # a pipe-up that repeats a recent line gets two more goes, then he keeps quiet
DEEP_RECALL = 10

# Where the message being answered came from. Each turn is its own task, so each
# sees its own channel without passing it through every call.
CHANNEL: contextvars.ContextVar[str] = contextvars.ContextVar("channel", default="web")
# Reading the conversation into the local model ahead of Dan's next message
# (ollama.warm_up): a moment after Kit has finished, once his voice has been quiet
# for a moment too (they share the GPU, and his voice mustn't stutter).
WARM_AFTER_S = 1.0
VOICE_QUIET_S = 1.0
WARM_POLL_S = 0.25
WARM_WAIT_S = 120.0  # no quiet moment in this long: don't bother
# How Kit feels and sounds this turn (kit.life.Voice), for the local model's prompt.
VOICE: contextvars.ContextVar[Voice | None] = contextvars.ContextVar("voice", default=None)
# A plain note request Kit has already carried out this turn (kit.notes.request), as
# told to the model; while set, the model's own note and read_note actions are skipped.
NOTE_DONE: contextvars.ContextVar[str] = contextvars.ContextVar("note_done", default="")
SAID_SHOWN = 6  # Kit's own recent lines shown so he doesn't repeat them
SAID_CHARS = 160

# A short answer to "shall I add it?" that confirms or rejects a suggested thing.
# The whole message must be the answer, so "ok, open VS Code" isn't a yes.
_END = r"(,? (please|thanks|mate|kit))?[.!]*"
YES = re.compile(rf"(yes|yep|yeah|yup|sure|ok|okay|do it|add it|go ahead){_END}", re.I)
NO = re.compile(rf"(no|nope|nah|skip it|don'?t|leave it|no thanks){_END}", re.I)
# "Where?" or "what's that?" back: the question is still open, so a "yes" after
# Kit explains still adds the thing.
ASKED_BACK = re.compile(r"^\W*(where|what|which|why|how|huh|eh|sorry|pardon)\b|\?\W*$", re.I)
ASKED_BACK_WORDS = 3

# Ways to choose who answers one message.
KEEP_LOCAL = re.compile(
    r"\b(keep (it|this) local|answer (it )?locally|don'?t ask (claude|the cloud|anyone))\b",
    re.IGNORECASE,
)
ASK_EXPERT = re.compile(r"\b(think (really )?(hard|carefully)|ask (the|your) expert)\b", re.I)
ASK_CLOUD = re.compile(r"\b(ask (claude|gpt|gemini|the cloud)|use the cloud)\b", re.IGNORECASE)
# Plainly about the weather: Kit fetches the forecast first and the local model
# answers from it, rather than handing a two-second question to the cloud.
WEATHER = re.compile(
    r"\b(weather|forecast|umbrella|rain(ing|y)?|showers|sunny|windy|storms?|"
    r"how (hot|cold|warm) (is it|will it be)|what'?s the temp(erature)?)\b",
    re.IGNORECASE,
)
# A follow-up like "and tomorrow?" soon after a weather answer is about the weather too.
WHEN = re.compile(
    r"\b(today|tonight|tomorrow|this (morning|afternoon|arvo|evening)|weekend|later|"
    r"(mon|tues|wednes|thurs|fri|satur|sun)day|next few days|this week)\b",
    re.IGNORECASE,
)
WEATHER_FOLLOW_UP = timedelta(minutes=15)
# "Check again" soon after a look at the PC means look again, not repeat the answer.
AGAIN = re.compile(r"\b((check|look|have a look) again\W*$|again\?*$|and now\??$|refresh)", re.I)
PC_FOLLOW_UP = timedelta(minutes=10)
# Messages that lean on what came before are never a new topic.
FOLLOW_ON = re.compile(
    r"\b(it|that|this|those|these|them|they|he|she|again|also|too|another|other|more|"
    r"instead|same|what about|how about|and|but|so|then|why|yes|no|yeah|nah|ok|okay)\b",
    re.IGNORECASE,
)
TOPIC_MIN_WORDS = 4
TOPIC_LOOKBACK = 3
# Plainly about Dan's PC: Kit looks first and the local model answers, since the
# cloud can't see the PC and window titles stay at home.
PC_QUESTION = re.compile(
    r"\b(my (pc|computer|laptop|desktop|screen)|on (my|the) (pc|computer|screen)|"
    r"what('?s| is| have i got| do i have| have i) open|have (i )?(got )?open|"
    r"(have|had) i been (doing|working on|up to)\s*(\?|$|today|this|for|in the|over|all|"
    r"since|lately)|cpu|ram usage|disk space|memory usage|tabs? (open|i have))",
    re.IGNORECASE,
)
# "How are you going?" while a slow answer is still coming means "how's that going?".
CHECKING_IN = re.compile(
    r"\b(how('?s| is| are) (it|you|that|things) (going|coming along)|how are you going|"
    r"nearly (done|there)|done yet|any luck|still (going|working|thinking)|hurry up|"
    r"what'?s taking so long|status|anything yet|any (update|news|luck|progress)s?)\b",
    re.IGNORECASE,
)
# "No, it's actually in Tax/2023": a correction naming a folder-like place.
CORRECTION = re.compile(
    r"\b(actually|not in|it'?s in|they'?re in|are in|is in|moved|lives? in|kept in|"
    r"keep (it|them) in|live in)\b|^\s*no\b",
    re.IGNORECASE,
)
PLACE = re.compile(r"\b[\w.\-]+(?:/[\w.\-]+)+")
# A bare "hello?" or "hey" while Kit is busy is checking in too.
NUDGE = re.compile(r"^\W*(hello|hey|hi|oi|kit|um+|so+|and|well|anything)?\W*\?+\W*$", re.I)
# "What are you thinking about?" gets Kit's actual recent thoughts (kit.notebook).
THINKING_Q = re.compile(
    r"\b(what('?s| is) on your mind|what('?re| are) you (thinking|pondering)( about)?|"
    r"penny for (your|them)|what('?ve| have) you been (thinking|pondering)( about)?)\b",
    re.IGNORECASE,
)
SHARES = ("want", "bored", "social")  # pipe-ups that can bring up a thought or want
# Words a small model sometimes gives as its search when it meant to say them
# ("Let me think...", "I checked the log for you"): Dan's message is the better search.
SPOKEN_NOT_SEARCH = re.compile(
    r"^\W*(let me|lemme|let's see|hmm+|um+|uh+|one (sec|second|moment)|hang on|"
    r"just a (sec|second|moment)|give me a (sec|second|moment)|thinking|checking|"
    r"i('m| am|'ll| will|'ve| have)?\b|you('re| are)?\b)",
    re.I,
)


def _patience(asked: int) -> str:
    """How Kit takes being asked again and again while it's busy."""
    if asked <= 1:
        return "This is the first time they've asked: easy-going, like 'give me a sec'."
    if asked == 2:
        return "They've asked twice now: a touch of mock impatience."
    if asked == 3:
        return "Third time they've asked: openly exasperated, cheeky about it."
    return (
        f"They've asked {asked} times: theatrically fed up, a sigh or a one-word answer, "
        f"still fond underneath."
    )


@dataclass
class Job:
    """Something a cloud model is working on while Kit carries on talking."""

    id: int
    question: str
    model: str
    started: float = field(default_factory=time.monotonic)
    steps: list[str] = field(default_factory=list)
    check_ins: int = 0  # how often Dan has asked how it's going

    def line(self) -> str:
        secs = int(time.monotonic() - self.started)
        if self.steps:
            done = f" So far you've {', then '.join(self.steps)}."
        else:
            done = " Nothing to report yet, it's still thinking; don't invent progress."
        return f'"{self.question}": you asked {self.model} {secs} seconds ago.{done}'

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "model": self.model,
            "seconds": round(time.monotonic() - self.started, 1),
            "steps": list(self.steps),
        }


def _asked(exchange: str) -> str:
    """What Dan said in an indexed exchange ("Dan: ...\nKit: ...")."""
    first = exchange.split("\n", 1)[0]
    return first.split(": ", 1)[-1]


def route(text: str, settings: Settings) -> tuple[str, bool]:
    """Who answers first: (role, whether Dan chose it for this message)."""
    if KEEP_LOCAL.search(text):
        return LOCAL, True
    if ASK_EXPERT.search(text):
        return EXPERT, True
    if ASK_CLOUD.search(text):
        return WORK, True
    return (WORK if settings.routing.mode == "cloud-first" else LOCAL), False


class Brain:
    def __init__(
        self,
        settings: Callable[[], Settings],
        memory: Memory,
        model: LocalModel,
        cloud: Cloud,
        recall: Recall,
        weather: Weather | None = None,
    ) -> None:
        self.settings = settings
        self.memory = memory
        self.model = model
        self.cloud = cloud
        self.recall = recall
        self.pc = PcContext(memory.clock)
        self.life = Life(settings, self.pc, memory.clock, store=memory)
        self.notebook = Notebook(memory)
        self.notebook.swap_work_quirks(settings().persona.owner)
        self.reflector = Reflector(memory, self.notebook, model, cloud, settings)
        self.weather = weather
        self._weather_at: datetime | None = None  # when Kit last looked at a forecast
        self._pc_at: datetime | None = None  # when Kit last looked at the PC for Dan
        self.learner = Learner(memory, recall, model)
        self.register = Register(memory)
        self.notes = Notes(memory.index, memory.clock)
        self.pending_thing: int | None = None
        self.pending_note: tuple[str, str] | None = None  # (title, text) Kit offered to note
        self.jobs: dict[int, Job] = {}
        self._job_ids = itertools.count(1)
        self._turns: set[asyncio.Task] = set()
        # His latest pipe-up and why he said it, for when Dan answers it ("what's up?").
        self._pipe_up: tuple[int, str] | None = None
        # Seconds since his voice was last being made (kit.speech; the server sets it).
        self.voice_quiet: Callable[[], float] = lambda: float("inf")
        self._warm_task: asyncio.Task | None = None
        self._warming = False  # reading ahead right now
        self._channel = CHANNEL.get()  # where Dan last talked from

    @property
    def quirks(self) -> list[str]:
        """The quirks Kit picked for himself; the nightly reflection may change one."""
        return self.notebook.quirks()

    def talking(self) -> bool:
        """A chat turn is under way."""
        return bool(self._turns)

    async def chat(self, text: str, channel: str | None = None) -> AsyncIterator[Event]:
        """One message's events, as they happen. The turn runs as its own task, so
        other messages can be answered meanwhile, and it finishes (and is saved)
        even if whoever asked stops listening."""
        text = text.strip()
        if not text:
            return
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        context = contextvars.copy_context()
        context.run(CHANNEL.set, known(channel))
        self._cancel_warm()
        task = asyncio.create_task(self._turn(text, queue.put_nowait), context=context)
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)
        while (event := await queue.get()) is not None:
            yield event
        await task  # raise anything that went wrong

    async def _turn(self, text: str, emit: Callable[[Event | None], None]) -> None:
        try:
            await self._run_turn(text, emit)
        except Exception:
            log.exception("a chat turn failed")
            emit({"type": "error", "message": "Something went wrong there. Say again?"})
        finally:
            emit(None)
            self._keep_warm()

    async def _run_turn(self, text: str, emit: Callable[[Event], None]) -> None:
        settings = self.settings()
        self._channel = CHANNEL.get()
        self._new_chat_if_quiet(settings)
        history = self.memory.recent(settings.brain.history_messages)
        if await self._new_topic(text, history, settings):
            self.memory.new_chat()
            history = []
            emit({"type": "new_topic"})
        user_id = self.memory.add_message("user", text, channel=CHANNEL.get())
        owner = settings.persona.owner
        felt = feeling_from(text, owner)
        if felt is not None:
            self.life.feel(*felt)
        if ASK_LATER.search(text):  # "ask me tomorrow how the shutdown went"
            due = tomorrow_morning(self.memory.clock(), settings.life.quiet_until)
            self.notebook.write("want", later_want(text, owner), after=due)
        answering = self._answering(history, owner)
        if THINKING_Q.search(text) and (shared := self.notebook.latest_thought()):
            self.notebook.mark_said(shared.id)
        VOICE.set(self._voice(settings, history, text))  # before note_chat: how Kit felt till now
        self.life.note_chat()
        answered = (
            self._answer_note_offer(text, settings)
            or self._answer_suggestion(text)
            or self._answer_shush(text)
        )
        if answered is not None:
            for event in self._say_locally(answered):
                emit(event)
            self.memory.index_exchange(
                user_id, settings.persona.owner, text, settings.persona.name, answered.text
            )
            return
        recent_refs = {str(m.id) for m in history if m.role == "user"}
        recalled = await self.recall.for_turn(text, recent_refs)
        # "hey" finds every earlier "hey", and the model copies what it said then.
        fresh = [h for h in recalled.conversation if not same_words(_asked(h.item.text), text)]
        # His notes already on his mind (kit.notebook) are in the prompt once, not twice.
        shown = {e.id for e in self.notebook.on_mind()}
        own = [h for h in recalled.own if h.item.id not in shown]
        recalled = replace(recalled, conversation=fresh, own=own)
        role, chosen = route(text, settings)
        if self.jobs and not chosen:
            role = LOCAL  # busy: chat locally while the cloud works
        if role == LOCAL and THINKING_Q.search(text):
            chosen = True  # his own thoughts: nobody else can answer that
        said: list[str] = []

        if role != LOCAL and chosen:
            name = settings.profile(role).name
            for event in self._say_locally(Reply.plain(f"Sure, asking {name}.", "thinking", "nod")):
                emit(event)
        pc_detail = ""
        about_pc = PC_QUESTION.search(text) or (AGAIN.search(text) and self._pc_recently())
        if self.pc.latest is not None and about_pc and not (chosen and role != LOCAL):
            self._pc_at = self.memory.clock()
            role, chosen = LOCAL, True
            pc_detail = self.pc.detail(settings.persona.owner)
            emit({"type": "looked_at_pc", "online": self.pc.online()})
        forecast = ""
        if role == LOCAL and self.weather is not None:
            plainly = bool(WEATHER.search(text))
            if plainly or (WHEN.search(text) and self._weather_recently()):
                forecast = await self._home_forecast(settings)
                emit({"type": "weather", "place": settings.persona.location})
                chosen = chosen or plainly  # a weather question stays local
        if settings.nas.vault:
            asked = request(text, self.notes.names(limit=ALL))
            if asked is not None:
                done, events = await asyncio.to_thread(self._do_note, asked, settings)
                NOTE_DONE.set(done)
                for event in events:
                    emit(event)
        emotion = ""
        async for event in self._converse(
            text,
            history,
            recalled,
            settings,
            role,
            chosen,
            forecast=forecast,
            pc_detail=pc_detail,
            answering=answering,
        ):
            if event["type"] == "reply":
                emotion = event["reply"]["emotion"]
                if self.jobs:
                    event = {**event, "question": text}
            emit(self._track(event, said))

        if emotion in REPLY_FEELINGS and felt is None:
            # How he felt answering lingers a little: "sad" about Dan's news stays.
            self.life.feel(REPLY_FEELINGS[emotion], f'{owner} said "{quoted(text)}"', 0.4)
        if said:
            self.notebook.said_in(" ".join(said), owner)  # brought something up himself
            self.memory.index_exchange(
                user_id, settings.persona.owner, text, settings.persona.name, " ".join(said)
            )
            await self.recall.index_pending()

    async def _new_topic(self, text: str, history: list[Message], settings: Settings) -> bool:
        """A clearly new subject: the chat so far would only lead the model astray (it
        kept bringing up the API key testing). Judged by meaning, against Dan's last
        few messages, with the embedder recall already uses."""
        below = settings.brain.new_topic_below
        asked = [m.text for m in history if m.role == "user"][-TOPIC_LOOKBACK:]
        if not below or len(asked) < 2 or len(text.split()) < TOPIC_MIN_WORDS:
            return False
        if FOLLOW_ON.search(text) or self.jobs:
            return False
        close = await self.recall.closeness(text, asked)
        if close is not None:
            log.info("topic closeness %.2f (new topic below %.2f)", close, below)
        return close is not None and close < below

    def _new_chat_if_quiet(self, settings: Settings) -> None:
        """Back after a long quiet: start fresh, so this morning's topic doesn't
        follow Dan into the afternoon. Recall still finds the old conversation."""
        after = settings.brain.new_chat_after_minutes
        last = self.memory.recent(1)
        if not after or not last:
            return
        if self.memory.clock() - datetime.fromisoformat(last[-1].at) >= timedelta(minutes=after):
            self.memory.new_chat()

    def _pc_recently(self) -> bool:
        return self._pc_at is not None and self.memory.clock() - self._pc_at < PC_FOLLOW_UP

    def _weather_recently(self) -> bool:
        return (
            self._weather_at is not None
            and self.memory.clock() - self._weather_at < WEATHER_FOLLOW_UP
        )

    async def _home_forecast(self, settings: Settings) -> str:
        self._weather_at = self.memory.clock()
        place = settings.persona.location
        try:
            return await self.weather.forecast(place, settings.persona.country)
        except WeatherError as e:
            return f"The forecast lookup for {place or 'home'} failed: {e}"

    def _user_turn(
        self, text: str, role: str, settings: Settings, pc_detail: str, answering: str = ""
    ) -> str:
        owner = settings.persona.owner
        if THINKING_Q.search(text) and not pc_detail:
            text = with_mind(text, self.notebook.mind(owner), owner)
        text = self._with_busy_note(text, role)
        text = with_pc_look(text, pc_detail, owner) if pc_detail else text
        return f"{text}\n\n{answering}" if answering else text

    def _answering(self, history: list[Message], owner: str) -> str:
        """The note beside a message that answers a pipe-up (Kit had the last word, of
        his own accord), saying why he piped up, so "yeah what's up?" gets the actual
        thing rather than the same line again."""
        last = history[-1] if history else None
        if last is None or last.role == "user" or last.source != PIPE_UP:
            return ""
        why = self._pipe_up[1] if self._pipe_up and self._pipe_up[0] == last.id else ""
        return answering_pipe_up(last.text.split("\n\n", 1)[0], why, owner)

    def _with_busy_note(self, text: str, role: str) -> str:
        """A small local model can miss the background work listed at the end of a
        long prompt, so when Dan checks in, say it again right next to his words."""
        if role != LOCAL or not self.jobs:
            return text
        work = " ".join(job.line() for job in self.jobs.values())
        owner = self.settings().persona.owner
        # A few words while Kit is busy ("hey", "kit", "you there") is getting its
        # attention about the work, the same as asking how it's going.
        short = len(re.findall(r"\w+", text)) <= 3
        if not (CHECKING_IN.search(text) or NUDGE.search(text) or short):
            return (
                f"{text}\n\n(Note for you, not from {owner}: you're still working on this "
                f"in the background: {work} Answer this message normally; mention the "
                f"background work only if it fits.)"
            )
        for job in self.jobs.values():
            job.check_ins += 1
        asked = max(job.check_ins for job in self.jobs.values())
        return (
            f"{text}\n\n(Note for you, not from {owner}: they're "
            f"checking in on the work you're doing in the background. {work} Say which "
            f"question you're on (in a few words, e.g. 'the cabbage one') and roughly how "
            f"long it's been, in one short line, in character. {_patience(asked)} Never "
            f"reuse a line you've already said. Don't answer the question itself.)"
        )

    def busy(self) -> list[dict]:
        """What cloud models are working on right now."""
        return [job.as_dict() for job in self.jobs.values()]

    def _answer_suggestion(self, text: str) -> Reply | None:
        """If Kit just suggested a thing and Dan answers yes or no, act on it without
        asking a model. A short question back ("where?") keeps the question open;
        anything else leaves the suggestion for the memory page."""
        pending, self.pending_thing = self.pending_thing, None
        if pending is None:
            return None
        thing = self.register.get(pending)
        if thing is None or not thing.suggested:
            return None
        if YES.fullmatch(text):
            self.register.confirm(pending)
            return Reply.plain(f"Done, {thing.name} is in the register.", "happy", "nod")
        if NO.fullmatch(text):
            self.register.reject(pending)
            return Reply.plain(f"Okay, I'll leave {thing.name} out.", "neutral", "nod")
        if ASKED_BACK.search(text) and len(text.split()) <= ASKED_BACK_WORDS:
            self.pending_thing = pending
        return None

    def _answer_note_offer(self, text: str, settings: Settings) -> Reply | None:
        """Kit offered to write something down ("want me to note that?"): a yes
        saves it, a no drops it, anything else lets the offer lapse."""
        pending, self.pending_note = self.pending_note, None
        if pending is None or not settings.nas.vault:
            return None
        if YES.fullmatch(text):
            title, note = pending
            try:
                saved = self.notes.take(settings.nas, title or title_for(note), note)
            except NoteError as e:
                return Reply.plain(f"I couldn't save it: {e}.", "concerned", "droop")
            return Reply.plain(f"Done, it's in {saved.shown}.", "happy", "nod")
        if NO.fullmatch(text):
            return Reply.plain("Okay, I'll leave it.", "neutral", "nod")
        return None

    def _answer_shush(self, text: str) -> Reply | None:
        """ "Shush" or "not now" keeps Kit from piping up for an hour; "you can talk
        again" lets him. Answered on the spot, so it works even when models are down."""
        owner = self.settings().persona.owner
        if UNSHUSH.search(text):
            self.life.wake()
            self.life.feel("pleased", f"{owner} said you can talk again", 0.6)
            return Reply.plain("Oh good. I had things to say.", "excited", "perk_up")
        if SHUSH.search(text) and len(text) < 60:
            self.life.snooze(60)
            self.life.feel("put_out", f"{owner} told you to shush", 0.5)
            return Reply.plain("Righto, zipping it for an hour.", "shy", "nod")
        return None

    async def pipe_up(self, reason: str) -> AsyncIterator[Event]:
        """Kit says something of his own accord (see kit.life): one short line, written
        by the local model from what Dan's doing and what Kit remembers. A bored or
        lonely Kit, or one with something to say, brings up his most pressing want or
        newest thought from his notebook. Nobody is waiting on it, so the line is
        judged whole before it's shown, and if all he comes up with is something he's
        said lately, he keeps quiet."""
        self._cancel_warm()
        settings = self.settings()
        owner = settings.persona.owner
        history = self.memory.recent(settings.brain.history_messages)
        share = self.notebook.to_share() if reason in SHARES else None
        if reason == "want" and share is None:
            reason = "bored"  # it was dropped meanwhile; he's still restless
        aim, about = "", share.text if share else ""
        if share is not None and share.kind == "want":
            aim, about = as_aim(share.text, owner)  # "tell Dan", not a note read out
        token = CHANNEL.set("desk")
        voice_token = VOICE.set(self._voice(settings, history))
        said: list[str] = []
        message_id = None
        try:
            doing = self.pc.now_line(owner) or f"what {owner} is up to"
            recalled = await self.recall.for_turn(doing, {str(m.id) for m in history})
            quiet_h = (self.memory.clock() - self.life.last_chat).total_seconds() / 3600
            prompt = pipe_up_prompt(
                reason,
                owner,
                settings.life.cheek,
                self.life.curious_about,
                quiet_h,
                self.life.butting_in,
                share=about,
                aim=aim,
            )
            messages = self._local_messages(
                settings,
                self._system(settings, recalled, LOCAL, False),
                history_messages(history, "desk", plain=settings.ollama.speak_pass),
                prompt,
            )
            async for event in self._local_reply(messages, PIPE_UP, hold=True):
                if event["type"] == "reply":
                    event = {**self._track(event, said), "piped_up": reason}
                    message_id = event["message_id"]
                yield event
        finally:
            CHANNEL.reset(token)
            VOICE.reset(voice_token)
            self._keep_warm()
        if not said:
            self.life.held_back(reason)
            return
        if share is not None:
            self.notebook.mark_said(share.id)
        self.notebook.said_in(" ".join(said), owner)
        why = self._why_piped(reason, aim, about, owner)
        self._pipe_up = (message_id, why) if message_id is not None else None
        self.life.piped_up(reason)
        self.life.wanting = self.notebook.pressing()

    def _why_piped(self, reason: str, aim: str, about: str, owner: str) -> str:
        """Why he piped up, in a few words for his next prompt, or "" when the line
        says it all."""
        if aim:
            return f'you wanted to {aim}: "{about}"'
        if about:
            return f'you\'d been thinking: "{about}"'
        if reason == "nag" and self._pipe_up:
            return self._pipe_up[1]  # still on about the same thing
        if reason in ("curious", "watching") and self.life.curious_about:
            return f"{owner} had just opened {self.life.curious_about}"
        return ""

    async def think(self, trigger: tuple[str, str] | None = None) -> Thought | None:
        """One private thought (kit.thinking), kept in Kit's notebook. It may add
        something he wants to bring up, or change how he feels. ``trigger`` is what
        set it off, from ``Life.think_now``."""
        kind, happened = trigger or ("asked", "A moment to yourself.")
        self._cancel_warm()
        settings = self.settings()
        persona = settings.persona
        owner = persona.owner
        pc = self.pc.now_line(owner)
        try:
            recalled = await self.recall.for_turn(pc or happened, set())
            remembered = (
                [i.text for i in recalled.pinned][:3]
                + [h.item.text for h in recalled.memories][:4]
                + [h.item.text for h in recalled.own][:3]
            )
            sheet = self.notebook.sheet()
            who = sheet.text if sheet else f"{persona.backstory} {', '.join(persona.traits)}."
            said_today = [
                f"{owner}: {quoted(m.text, 200)}"
                if m.role == "user"
                else f"{persona.name}: {quoted(without_plans(m.text), 200)}"
                for m in self.memory.messages_on(self.memory.today())[-8:]
            ]
            messages = thinking_messages(
                persona.name,
                owner,
                who,
                self.quirks,
                cheek_style(settings.life.cheek),
                self.memory.clock(),
                happened,
                pc,
                self.life.feeling_line(owner),
                self.notebook.mind(owner, 5),
                remembered,
                said_today,
            )
            options = lively(settings.ollama, plain=False)
            raw = await self.model.complete(messages, THOUGHT_SCHEMA, None, options)
        except LocalModelError as e:
            log.warning("Kit couldn't think just now: %s", e)
            return None
        finally:
            self.life.thought_had()  # tried, at least: no hammering a model that's down
            self._keep_warm()
        thought = parse_thought(raw, kind)
        if thought is None:
            return None
        if thought.text and self.notebook.write(thought.kind, thought.text, trigger=kind):
            self.life.publish({"type": "fidget", "gesture": "look_up", "mood": "thinking"})
        if thought.want:
            later = FOR_LATER.search(thought.want)
            when = tomorrow_morning(self.memory.clock(), settings.life.quiet_until)
            due = {"after": when} if later else {}
            self.notebook.write("want", thought.want, trigger=kind, **due)
            self.life.wanting = self.notebook.pressing()
        if thought.feeling:
            self.life.feel(thought.feeling, thought.why or thought.text, 0.7)
        await self.recall.index_pending()
        return thought

    async def reflect(self) -> list[str]:
        """Kit's nightly reflection (kit.reflection): his first self-sheet if he has
        none, each finished day since he last reflected, and the weekly review when
        it's due. Returns the days he reflected on."""
        if self.settings().life.reflect_with == "off":
            return []
        r = self.reflector
        first = "first sheet"
        if self.notebook.sheet() is None and not r.gave_up(first) and not await r.first_sheet():
            r.failed(first)  # his nightly reflection writes one if this never works
            return []
        done = []
        for day in r.days_to_reflect():
            if await r.reflect_day(day) is not None:
                done.append(day)
            elif not r.failed(day):
                break  # no model could do it: try again next time
            r.reflected(day)
        await r.review_week()
        await self.recall.index_pending()
        return done

    def _voice(self, settings: Settings, history: list[Message], text: str = "") -> Voice:
        persona = settings.persona
        said = [without_plans(m.text)[:SAID_CHARS] for m in history if m.role != "user"]
        said = [line for line in said if line][-SAID_SHOWN:]
        own = [(ex.user, ex.kit) for ex in persona.examples]
        mind = self.notebook.mind(persona.owner)
        return self.life.voice(persona.owner, own, said, self.quirks, text, mind)

    def _say_locally(self, reply: Reply) -> list[Event]:
        message_id = self._remember_reply(reply, LOCAL)
        return [
            {"type": "say", "text": reply.text},
            {
                "type": "reply",
                "source": LOCAL,
                "reply": reply.model_dump(),
                "message_id": message_id,
            },
        ]

    def _note_thing(self, reply: Reply) -> Event | None:
        """Act on a ``thing`` action: update a known thing's link, or suggest a new one."""
        a = reply.action
        name = a.text.strip()
        if not name:
            return None
        link = (
            []
            if a.link_system == "none" or not a.link_target.strip()
            else [{"system": a.link_system, "target": a.link_target}]
        )
        known = self.register.named(name)
        if known:
            if not link:
                return None
            new_id = self.register.set_link(known.id, a.link_system, a.link_target)
            thing = self.register.get(new_id)
            return {"type": "thing_updated", "thing": thing.as_dict() if thing else None}
        thing = self.register.suggest(name, a.thing_kind, link)
        self.pending_thing = thing.id
        return {"type": "thing_suggested", "thing": thing.as_dict()}

    def _take_note(self, reply: Reply, settings: Settings, heard: str) -> Event:
        """Save the note. If the model left it empty (a small model planning in a
        hurry), what Dan asked to note is taken from his message."""
        text = reply.action.text.strip() or asked_text(heard)
        try:
            saved = self.notes.take(settings.nas, reply.action.title, text)
        except NoteError as e:
            log.warning("note not saved: %s", e)
            return {"type": "notice", "message": f"The note wasn't saved: {e}."}
        verb = "Added to" if saved.added else "Saved"
        return {"type": "notice", "message": f"{verb} {saved.shown} in your notes."}

    def _offer_note(self, reply: Reply, heard: str) -> None:
        note = reply.action.text.strip() or heard.strip()
        self.pending_note = (reply.action.title.strip(), note) if note else None

    def _do_note(self, asked: Request, settings: Settings) -> tuple[str, list[Event]]:
        """Carry out a plain note request before the model answers, so a small model
        can't mistake "what's in my planner?" for "write that down", or ask first.
        Returns what to tell the model and the events to show."""
        owner, nas = settings.persona.owner, settings.nas
        if asked.kind == "read":
            event = {"type": "reading_note", "note": asked.note}
            try:
                where, body = self.notes.read(nas, asked.note)
            except NoteError as e:
                return f"You tried to open {owner}'s note '{asked.note}', but {e}.", [event]
            return f"{owner}'s note {where}, opened just now:\n{body}", [event]
        try:
            saved = self.notes.take(nas, asked.note or title_for(asked.text), asked.text)
        except NoteError as e:
            log.warning("note not saved: %s", e)
            message = f"The note wasn't saved: {e}."
            return f"You couldn't save {owner}'s note: {e}.", [
                {"type": "notice", "message": message}
            ]
        verb = "Added to" if saved.added else "Saved"
        did = "added to" if saved.added else "saved a new note,"
        return (
            f"You've just {did} {saved.shown} in {owner}'s notes: \"{asked.text}\". It's "
            f"done, so don't ask whether to write it down.",
            [{"type": "notice", "message": f"{verb} {saved.shown} in your notes."}],
        )

    def _read_note(self, name: str, settings: Settings) -> str:
        owner = settings.persona.owner
        try:
            where, body = self.notes.read(settings.nas, name)
        except NoteError as e:
            return (
                f"[Not from {owner}. You tried to open the note '{name}', but {e}. Tell "
                f"{owner}, or try the recall action to search the notes instead.]"
            )
        return (
            f"[Not from {owner}. {owner}'s note {where}, as it is now:]\n{body}\n"
            f"[Answer {owner}'s last message from it. Action none.]"
        )

    def _implied_correction(self, text: str, recalled: Recalled) -> Event | None:
        """A correction the model didn't act on: "my tax stuff is actually in Tax/2023"
        names a place, and the thing it's about is the closest one recalled with a
        link. Update that link (the old one stays in its history)."""
        place = PLACE.search(text)
        if not place or not CORRECTION.search(text):
            return None
        linked = [t for t in recalled.things if t.links]
        if not linked:
            return None
        thing, target = linked[0], place.group(0).rstrip(".")
        if any(link.target == target for link in thing.links):
            return None
        systems = [link.system for link in thing.links]
        system = "nas" if "nas" in systems else systems[0]
        new_id = self.register.set_link(thing.id, system, target)
        updated = self.register.get(new_id)
        return {"type": "thing_updated", "thing": updated.as_dict() if updated else None}

    @staticmethod
    def _track(event: Event, said: list[str]) -> Event:
        if event["type"] == "reply":
            said.append(Reply.model_validate(event["reply"]).full_text)
        return event

    def _system(
        self,
        settings: Settings,
        recalled: Recalled,
        role: str,
        hand_off: bool,
        forecast: str = "",
        pc_detail: str = "",
    ) -> str:
        routing = settings.routing
        work, expert = settings.profile(WORK), settings.profile(EXPERT)
        sheet = self.notebook.sheet()
        if role == LOCAL:
            helper, further, web = (work.name if hand_off else None), None, False
        elif role == WORK:
            different = routing.expert != routing.work
            helper, further, web = None, (expert.name if different else None), work.web_search
        else:
            helper, further, web = None, None, expert.web_search
        return system_prompt(
            settings.persona,
            recalled,
            self.memory.clock(),
            role=role,
            mode=routing.mode,
            helper=helper,
            expert=further,
            web_search=web,
            busy=[job.line() for job in self.jobs.values()],
            quirks=self.quirks,
            voice=VOICE.get() if role == LOCAL else None,
            pc=self.pc.now_line(settings.persona.owner),
            channel=channel_line(CHANNEL.get(), settings.persona.owner),
            weather=self.weather is not None,
            notes=bool(settings.nas.vault),
            note_names=self.notes.names() if settings.nas.vault else None,
            note_done=NOTE_DONE.get(),
            forecast=forecast,
            pc_detail=pc_detail,
            sheet=sheet.text if sheet else "",
            traits=sheet is None or sheet.meta.get("basis") != basis(settings.persona),
            two_pass=role == LOCAL and settings.ollama.speak_pass,
        )

    @staticmethod
    def _local_messages(settings: Settings, system: str, past: list[dict], user: str) -> list[dict]:
        """The local model's prompt. With ``ollama.warm_up`` this turn's part of the
        instructions goes beside Dan's message, so everything before his message is
        what was read ahead (``_warm``) and only his message is left to read."""
        if settings.ollama.warm_up:
            system, now = split_turn(system)
            user = with_now(user, now, settings.persona.owner)
        return [{"role": "system", "content": system}, *past, {"role": "user", "content": user}]

    def _keep_warm(self) -> None:
        """Once Kit has finished, read the conversation into the local model ahead of
        Dan's next message (``ollama.warm_up``)."""
        self._cancel_warm()
        if self.settings().ollama.warm_up:
            self._warm_task = asyncio.create_task(self._warm())

    def _cancel_warm(self) -> None:
        """Kit's starting something: a read-ahead still waiting is dropped. One that's
        reading carries on; stopping it would save nothing, as the model reads it
        either way before it gets to what's next."""
        task, self._warm_task = self._warm_task, None
        if task is not None and not self._warming:
            task.cancel()

    async def _warm(self) -> None:
        waited = WARM_AFTER_S
        await asyncio.sleep(WARM_AFTER_S)
        while any(not t.done() for t in self._turns) or self.voice_quiet() < VOICE_QUIET_S:
            if waited > WARM_WAIT_S:
                return
            await asyncio.sleep(WARM_POLL_S)
            waited += WARM_POLL_S
        self._warming = True
        try:
            await self.model.warm(self._warm_messages(self.settings()))
        except LocalModelError as e:
            log.info("couldn't read the conversation in ahead: %s", e)
        except Exception:
            log.exception("reading the conversation in ahead failed")
        finally:
            self._warming = False

    def _warm_messages(self, settings: Settings) -> list[dict]:
        """The start of the local model's prompt for Dan's next message, as far as
        it's known before he sends it: Kit's instructions and the conversation so far.
        A message that's answered differently (Kit can't hand it to the cloud, or it
        starts a new conversation) starts differently, and is read in full as before."""
        history = self.memory.recent(settings.brain.history_messages)
        system = self._system(settings, Recalled([], [], []), LOCAL, hand_off=True)
        plain = settings.ollama.speak_pass
        past = history_messages(history, self._channel, plain=plain)
        return self._local_messages(settings, system, past, "")[:-1]

    async def _converse(
        self,
        text: str,
        history: list[Message],
        recalled: Recalled,
        settings: Settings,
        role: str,
        chosen: bool = False,
        hops: int = 0,
        question: str = "",
        forecast: str = "",
        pc_detail: str = "",
        answering: str = "",
    ) -> AsyncIterator[Event]:
        hand_off = role == LOCAL and not chosen and hops == 0
        system = self._system(settings, recalled, role, hand_off, forecast, pc_detail)
        plain = role == LOCAL and settings.ollama.speak_pass  # the words come as plain text
        past = history_messages(history, CHANNEL.get(), plain=plain)
        user = self._user_turn(text, role, settings, pc_detail, answering)
        if role == LOCAL:
            messages = self._local_messages(settings, system, past, user)
        else:
            messages = [
                {"role": "system", "content": system},
                *past,
                {"role": "user", "content": user},
            ]
        job = None
        if role != LOCAL:
            job = Job(next(self._job_ids), question or text, settings.profile(role).name)
            self.jobs[job.id] = job
        try:
            reply, message_id = None, None
            async for event in self._reply(messages, role, settings, text, job):
                if event["type"] == "reply":
                    reply = Reply.model_validate(event["reply"])
                    message_id = event["message_id"]
                yield event
            if reply is None:
                return

            look_up = None
            owner = settings.persona.owner
            if reply.action.kind == "recall":
                query = reply.action.text.strip()
                if not query or SPOKEN_NOT_SEARCH.search(query):
                    query = text
                hits = await self.recall.search(
                    query, [FACTS, DAYS, CONVERSATION, THINGS, SELF, NOTES], DEEP_RECALL
                )
                yield {"type": "recalled", "query": query, "found": len(hits)}
                if job:
                    job.steps.append(f"looked through your memory for '{query}'")
                look_up = recall_results(query, hits, owner)
            elif reply.action.kind == "look_at_pc":
                yield {"type": "looked_at_pc", "online": self.pc.online()}
                if job:
                    job.steps.append("looked at what's open on your PC")
                look_up = f"What you can see on {owner}'s PC:\n{self.pc.detail(owner)}"
            elif reply.action.kind == "weather" and self.weather is not None:
                place = reply.action.text.strip() or settings.persona.location
                try:
                    forecast = await self.weather.forecast(place, settings.persona.country)
                except WeatherError as e:
                    forecast = f"The forecast lookup failed: {e}"
                self._weather_at = self.memory.clock()
                yield {"type": "weather", "place": place}
                if job:
                    job.steps.append(f"checked the forecast for {place}")
                look_up = weather_results(place, forecast, owner)
            elif reply.action.kind == "read_note" and not NOTE_DONE.get():
                name = reply.action.text.strip() or reply.action.title.strip()
                yield {"type": "reading_note", "note": name}
                look_up = self._read_note(name, settings)
                if job:
                    job.steps.append(f"read your note '{name}'")
            if look_up is not None:
                said = reply.full_text if plain else reply_json(reply)
                messages += [
                    {"role": "assistant", "content": said},
                    {"role": "user", "content": look_up},
                ]
                # The "Let me think..." turn is kept as a working note (RECALL_STEP), so
                # later history shows one answer per message, not a recall habit.
                self.memory.set_message_source(message_id, RECALL_STEP)
                reply = None
                async for event in self._reply(messages, role, settings, text, job):
                    if event["type"] == "reply":
                        reply = Reply.model_validate(event["reply"])
                    yield event
                if reply is None:
                    return
        except CloudError as e:
            self._end_job(job)
            async for event in self._cloud_failed(e, text, history, recalled, settings, chosen):
                yield event
            return
        finally:
            self._end_job(job)

        kind = reply.action.kind
        said = [text, *[m.text for m in history if m.role == "user"][-2:]]
        fact = reply.action.text.strip()
        if kind == "remember" and fact and not said_so(fact, said, settings.persona.owner):
            # Small models "remember" their own lines and guesses; only what Dan said counts.
            log.info("not remembering %r: %s didn't say it", fact, settings.persona.owner)
        elif kind == "remember" and fact:
            learned = await self.learner.learn(fact, reply.action.category, settings.persona.owner)
            yield {
                "type": "remembered",
                "fact": learned.text,
                "decision": learned.decision,
                "replaced": learned.replaced,
            }
        elif kind == "thing" and named_in(fact, " ".join(said)):
            event = self._note_thing(reply)
            if event:
                yield event
        elif kind == "note" and not NOTE_DONE.get():
            if asks_for_note(text):
                yield self._take_note(reply, settings, text)
            else:  # never a note Dan didn't ask for: it waits for his yes
                self._offer_note(reply, text)
                yield {"type": "notice", "message": "Not in your notes yet: say yes to add it."}
        elif kind == "offer_note" and not NOTE_DONE.get():
            self._offer_note(reply, text)
        if kind in ("none", "remember") and hops == 0:
            event = self._implied_correction(text, recalled)
            if event:
                yield event
        if (kind == "ask_cloud" and hand_off) or (kind == "ask_expert" and role == WORK):
            to = WORK if kind == "ask_cloud" else EXPERT
            question = reply.action.text.strip() or text
            yield {"type": "handing_off", "to": settings.profile(to).name, "question": question}
            async for event in self._converse(
                text,
                history,
                recalled,
                settings,
                to,
                chosen,
                hops + 1,
                question,
                answering=answering,
            ):
                yield event

    def _end_job(self, job: Job | None) -> None:
        if job:
            self.jobs.pop(job.id, None)

    async def _cloud_failed(
        self,
        error: CloudError,
        text: str,
        history: list[Message],
        recalled: Recalled,
        settings: Settings,
        chosen: bool,
    ) -> AsyncIterator[Event]:
        """A cloud model couldn't answer. Unless Dan asked for it by name, the local
        model has a go instead (when fallback is on); otherwise Kit says why."""
        if settings.routing.fallback_to_local and not chosen:
            yield {"type": "notice", "message": f"{error} I'll answer myself."}
            async for event in self._converse(
                text, history, recalled, settings, LOCAL, chosen=True, hops=1
            ):
                yield event
            return
        reply = Reply.plain(str(error), "concerned", "shrug")
        message_id = self._remember_reply(reply, LOCAL)
        yield {"type": "say", "text": reply.text}
        yield {
            "type": "reply",
            "source": LOCAL,
            "reply": reply.model_dump(),
            "message_id": message_id,
        }

    async def _reply(
        self,
        messages: list[dict],
        role: str,
        settings: Settings,
        question: str,
        job: Job | None = None,
    ) -> AsyncIterator[Event]:
        if role == LOCAL:
            async for event in self._local_reply(messages, LOCAL, heard=question):
                yield event
            return
        profile = settings.profile(role)
        if profile.provider == "ollama":
            async for event in self._local_reply(messages, LOCAL, profile.model):
                yield event
            return
        on_step = job.steps.append if job else None
        answer = await self.cloud.answer(profile, messages, settings, question, on_step)
        reply = parse_cloud_reply(answer.text)
        if answer.truncated:
            reply.detail = reply.detail + "\n\n(I ran out of room there; ask me to continue.)"
        message_id = self._remember_reply(reply, "cloud")
        yield {"type": "say", "text": reply.text, "source": "cloud"}
        yield {
            "type": "reply",
            "source": "cloud",
            "role": role,
            "model": answer.model,
            "label": profile.name,
            "reply": reply.model_dump(),
            "message_id": message_id,
            "cost_usd": round(answer.cost_usd, 4),
            "searches": answer.searches,
            "month_usd": round(self.memory.month_spend(), 4),
        }

    async def _local_reply(
        self,
        messages: list[dict],
        source: str,
        model: str | None = None,
        heard: str = "",
        hold: bool = False,
    ) -> AsyncIterator[Event]:
        """The local model's reply: in two passes with ``ollama.speak_pass`` (for Kit's
        own local model), else in one JSON pass. ``heard`` is what Dan said, if this
        answers him; ``hold`` judges the whole line before showing it (a pipe-up)."""
        if model is None and self.settings().ollama.speak_pass:
            replies = self._two_pass_reply(messages, source, heard, hold)
        else:
            replies = self._one_pass_reply(messages, source, model)
        async for event in replies:
            yield event

    async def _plan(self, messages: list[dict]) -> Plan:
        """The first pass: how Kit feels, a gesture and an action. Reading stops as soon
        as it's plain the action is "none" (the rest would be empty fields), so he
        starts talking sooner."""
        raw = ""
        async with aclosing(self.model.stream(messages, plan_schema())) as pieces:
            async for piece in pieces:
                raw += piece
                early = early_plan(raw)
                if early is not None:
                    return early
        try:
            return parse_plan(raw)
        except ReplyError:
            return Plan.default()

    def _repeats(self, line: str, voice: Voice | None) -> bool:
        return voice is not None and repeats(line, voice.said, voice.examples)

    def _repeated(self, line: str, voice: Voice | None) -> str:
        """What in ``line`` he's said lately or copied from an example: all of it, or
        a sentence of four words or more ("" if nothing)."""
        if not line or self._repeats(line, voice):
            return line
        long_enough = (s for s in sentences(line) if len(s.split()) >= 4)
        return next((s for s in long_enough if self._repeats(s, voice)), "")

    async def _two_pass_reply(
        self, messages: list[dict], source: str, heard: str = "", hold: bool = False
    ) -> AsyncIterator[Event]:
        """A plan in JSON, then Kit's words in plain text at a livelier temperature,
        shown as they arrive. If his opening repeats a recent line (or copies an
        example), he's asked once more, before anything is shown. With ``hold`` (a
        pipe-up, which nobody is waiting on) nothing is shown till the line is whole;
        if any of it repeats he has two more goes, then keeps quiet rather than say it
        again, and a pipe-up has no written detail."""
        settings = self.settings()
        voice = VOICE.get()
        spoken = detail = ""
        tries = HELD_TRIES if hold else 2
        said_all = False  # his words are complete, though the model may still be writing
        try:
            plan = await self._plan(messages)
            if plan.action.kind == "thing" and not named_in(plan.action.text, heard):
                # Dan never named it, so no "shall I add it to the register?"
                plan = plan.model_copy(update={"action": Action(kind="none")})
            if plan.action.kind == "note" and not asks_for_note(heard):
                # Dan didn't ask for a note, so Kit offers rather than writes one.
                offer = plan.action.model_copy(update={"kind": "offer_note"})
                plan = plan.model_copy(update={"action": offer})
            if not hold:  # how he feels, before his words: the voice speaks in this mood
                yield {"type": "mood", "emotion": plan.emotion}
            note = speak_note(
                plan.action,
                settings.persona.owner,
                settings.profile(WORK).name,
                settings.profile(EXPERT).name,
                voice,
                heard,
            )
            talk = [
                *messages,
                {"role": "assistant", "content": plan_json(plan)},
                {"role": "user", "content": note},
            ]
            options = lively(settings.ollama)
            for attempt in range(tries):
                last = attempt == tries - 1
                stream, again = SpokenStream(settings.persona.name), ""
                async with aclosing(self.model.stream(talk, None, None, options)) as pieces:
                    async for piece in pieces:
                        stream.feed(piece)
                        if hold or said_all:
                            continue
                        if not stream.released:
                            first = stream.first()
                            if first is None:
                                continue
                            if not last and self._repeats(first, voice):
                                again = first
                                break
                            stream.release()
                        if stream.finished():
                            # The rest is written detail, or dropped: his voice needn't
                            # wait for it to say his last sentence.
                            if out := stream.end():
                                yield {"type": "say", "text": out}
                            yield {"type": "spoken"}
                            said_all = True
                        elif out := stream.take():
                            yield {"type": "say", "text": out}
                if hold:
                    again = self._repeated(stream.result()[0], voice)
                    if again and last:
                        log.info("kept quiet rather than say %r again", again)
                        yield {"type": "kept_quiet", "repeated": again}
                        return
                elif not again and not stream.released and not last:
                    whole = stream.result()[0]  # it ended before the opening was judged
                    again = whole if whole and self._repeats(whole, voice) else ""
                if again:
                    talk = [*talk[:-1], {"role": "user", "content": note + not_again(again)}]
                    options = {**options, "temperature": options["temperature"] + 0.1}
                    continue
                if out := stream.end():
                    yield {"type": "say", "text": out}
                spoken, detail = stream.result()
                if spoken:
                    if not hold and not said_all:
                        yield {"type": "spoken"}
                    break
                if stream.wrote_json():  # his plan again rather than words
                    talk = [*talk[:-1], {"role": "user", "content": note + IN_WORDS}]
        except LocalModelError as e:
            yield {"type": "error", "message": f"My local brain isn't answering: {e}"}
            return
        except Exception as e:  # a bug in the stream reader must not drop the chat
            log.exception("reading the local model's reply failed")
            yield {"type": "error", "message": f"I lost my train of thought ({e}). Say again?"}
            return
        if not spoken:
            yield {"type": "error", "message": "I lost my train of thought. Say again?"}
            return
        reply = spoken_reply(plan, spoken, "" if hold else detail)
        message_id = self._remember_reply(reply, source)
        yield {
            "type": "reply",
            "source": source,
            "reply": reply.model_dump(),
            "message_id": message_id,
        }

    async def _one_pass_reply(
        self, messages: list[dict], source: str, model: str | None = None
    ) -> AsyncIterator[Event]:
        extractor = SayExtractor()
        raw, said = [], []
        try:
            async for piece in self.model.stream(messages, reply_schema(), model):
                raw.append(piece)
                spoken = extractor.feed(piece)
                if spoken:
                    said.append(spoken)
                    yield {"type": "say", "text": spoken}
        except LocalModelError as e:
            yield {"type": "error", "message": f"My local brain isn't answering: {e}"}
            return
        except Exception as e:  # a bug in the stream reader must not drop the chat
            log.exception("reading the local model's reply failed")
            yield {"type": "error", "message": f"I lost my train of thought ({e}). Say again?"}
            return
        try:
            reply = parse_reply("".join(raw))
        except ReplyError:
            # The words got through even if the JSON didn't; keep them.
            spoken = "".join(said).strip()
            if not spoken:
                yield {"type": "error", "message": "I lost my train of thought. Say again?"}
                return
            reply = Reply.plain(spoken)
        message_id = self._remember_reply(reply, source)
        yield {
            "type": "reply",
            "source": source,
            "reply": reply.model_dump(),
            "message_id": message_id,
        }

    def _remember_reply(self, reply: Reply, source: str) -> int:
        return self.memory.add_message("kit", reply.full_text, reply_json(reply), source)

    async def summarise_past_days(self) -> list[str]:
        """Summarise each finished day and learn its facts. Returns the days done."""
        done = []
        persona = self.settings().persona
        for day in self.memory.days_to_summarise():
            if not await self.learner.summarise_day(day, persona.owner, persona.name):
                break
            done.append(day)
        return done
