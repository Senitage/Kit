"""Kit's conversation loop.

Each turn:

1. Route: pick who answers. The routing mode sets the default (the local model,
   the cloud ``work`` model in cloud-first, or the cloud ``chat`` model in
   cloud-only), and Dan can say "keep it local", "ask Claude" or "think hard" to
   choose for one message.
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
   - ask_cloud / ask_expert: the question goes to the work or expert model. With
     ``routing.confirm_expert``, Kit asks Dan first when the work model wants the
     expert, and only a "yes" sends it.
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
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from kit.channels import channel_line, known
from kit.cloud import Cloud, CloudAnswer, CloudError
from kit.daily import Daily
from kit.knowledge import Item
from kit.learning import Learner, asking, relations_in, said_so
from kit.life import (
    CLOUD_TIRES,
    FAREWELL,
    FEELING_KINDS,
    GAME_PRESS,
    GAMES,
    HOME_LINES,
    LAUGH,
    REPLY_FEELINGS,
    SHUSH,
    UNSHUSH,
    Homecoming,
    Life,
    Voice,
    bad_night_aside,
    bad_night_in,
    cheek_style,
    day_part,
    farewell_aside,
    farewell_fault,
    farewell_line,
    feeling_from,
    feeling_from_read,
    homecoming_aside,
    homecoming_facts,
    homecoming_fault,
    homecoming_prompt,
    is_farewell,
    parse_time,
    pipe_up_prompt,
    pipe_up_score,
    quoted,
    repeats,
    same_words,
    since_words,
)
from kit.local_model import LocalModel, LocalModelError, lively
from kit.memory import (
    CONVERSATION,
    DAYS,
    FACTS,
    KEEP_LOCAL,
    RECALL_STEP,
    SELF,
    Memory,
    Message,
)
from kit.notebook import (
    ASKED_STRENGTH,
    ASKING,
    FOR_LATER,
    Notebook,
    aim_of,
    asks_later,
    basis,
    later_want,
    thread_in,
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
from kit.pastimes import Pastime, Pastimes, Readers, weather_doing
from kit.pc_context import PcContext
from kit.prompt import (
    IN_WORDS,
    about_yourself,
    answering_pipe_up,
    bedtime_aside,
    expert_yes_aside,
    history_messages,
    interview_aside,
    news_aside,
    not_again,
    opener_aside,
    picked_up,
    recall_results,
    speak_note,
    system_prompt,
    weather_results,
    with_mind,
    with_pc_look,
    wrong_fact_aside,
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
    mood_read,
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
from kit.settings import Settings, cloud_background, local_stands_in
from kit.shows import show_for
from kit.things import THINGS, Register, named_in
from kit.thinking import THOUGHT_SCHEMA, THOUGHT_SHAPE, Thought, parse_thought, thinking_messages
from kit.weather import Weather, WeatherError
from kit.when import follow_up

log = logging.getLogger(__name__)


MUSING = re.compile(
    r"^\W*(i wonder|wonder|maybe|perhaps|what if|i'?m not sure|not sure|could it be|"
    r"is|are|does|do|can|could|would|should|will)\b",
    re.I,
)


SENTENCES = re.compile(r"(?<=[.!?…])\s+|\.{3}\s*|…\s*|\s+-\s+|\s*[;:]\s+")


ABOUT_HIM = re.compile(r"\b(he|he's|him|his)\b", re.I)


def a_view(text: str, owner: str = "") -> bool:
    """An opinion he can stand by: statements only, with no question or passing musing
    in it anywhere ("Is that AI thing actually smarter than me?", "... Wonder if he'll
    ever stop"), and on a topic, not a remark about ``owner``."""
    text = text.strip()
    if len(text.split()) < 4 or "?" in text:
        return False
    if owner and (ABOUT_HIM.search(text) or re.search(rf"\b{re.escape(owner)}\b", text, re.I)):
        return False
    return not any(MUSING.search(part) for part in SENTENCES.split(text) if part.strip())


def temperatures(text: str) -> list[float]:
    """Plausible temperatures in ``text``, in order ("I reckon 31, you?")."""
    found = []
    for m in TEMPERATURE.finditer(text):
        value = float(m.group(1))
        if -10 <= value <= 55:
            found.append(value)
    return found


Event = dict
LOCAL, CHAT, WORK, EXPERT = "local", "chat", "work", "expert"
PIPE_UP = "pipe_up"  # the source of a message Kit said of his own accord
HELD_TRIES = 3  # a pipe-up that repeats a recent line gets two more goes, then he keeps quiet
DEEP_RECALL = 10

# Where the message being answered came from. Each turn is its own task, so each
# sees its own channel without passing it through every call.
CHANNEL: contextvars.ContextVar[str] = contextvars.ContextVar("channel", default="web")
# How Kit feels and sounds this turn (kit.life.Voice), for the local model's prompt.
VOICE: contextvars.ContextVar[Voice | None] = contextvars.ContextVar("voice", default=None)
# A plain note request Kit has already carried out this turn (kit.notes.request), as
# told to the model; while set, the model's own note and read_note actions are skipped.
NOTE_DONE: contextvars.ContextVar[str] = contextvars.ContextVar("note_done", default="")


@dataclass
class Lint:
    """A check on a whole line before it's said (a goodbye, a hello). ``check`` says
    what's wrong as a note for another go ("" if nothing); after the last go fails,
    ``fallback`` is said instead (or he keeps quiet, if there is none). ``repeats``
    also holds him to saying something new."""

    check: Callable[[str], str]
    fallback: str = ""
    repeats: bool = True


# The check on this turn's lines, if any: a goodbye is linted for guilt hooks.
LINT: contextvars.ContextVar[Lint | None] = contextvars.ContextVar("lint", default=None)
# The turn's asides, said again beside the speaking step (kit.prompt.speak_note).
MIND: contextvars.ContextVar[str] = contextvars.ContextVar("mind", default="")
# What a cloud answer this turn is for, so a low budget skips the least needed first
# (kit.cloud.SKIP_ORDER): "moment" for a key moment (bad news) the work model answers.
PRIORITY: contextvars.ContextVar[str] = contextvars.ContextVar("priority", default="chat")
# How Dan seems, as the model answering this turn read it (``life.read_mood`` meaning).
READ: contextvars.ContextVar[dict | None] = contextvars.ContextVar("read", default=None)
READ_ON: contextvars.ContextVar[bool] = contextvars.ContextVar("read_on", default=False)
MOOD_CALIBRATION = "mood_calibration"  # kit_self: the last `kit eval mood` (kit.evals)
CLOSE = re.compile(
    r"\b(partner|wife|husband|girlfriend|boyfriend|fianc\w*|mum|mom|dad|mother|father|"
    r"brother|sister|best mate|mate|best friend|friend)\b",
    re.I,
)
# A temperature in a weather bet: "I reckon 31", "28 degrees". Not a time ("2 pm").
TEMPERATURE = re.compile(r"(?<![\d:.])(-?\d{1,2}(?:\.\d)?)(?!\s*(?:pm|am|:|%|\d))", re.I)
SAID_SHOWN = 6  # Kit's own recent lines shown so he doesn't repeat them
OPINION_STANDS = timedelta(days=1)  # an opinion held this long is one he stands by
SAID_CHARS = 160
# A new chat (or a hello) this long after the last talk picks up one thing from it.
OPENER_GAP = timedelta(hours=1)
OPENER_SAID = 3  # Dan's last few lines from it, to pick from
OPENER_WORDS = 4  # shorter than this ("ok", "thanks") isn't worth picking up
OPENER_SPAN = timedelta(hours=6)  # what he picks from: that last talk, not days before it
LAUGHED_WITHIN = timedelta(minutes=10)  # a laugh this soon after a running joke: it landed
SENTENCE = re.compile(r"(?<=[.!?])\s+")

# A short answer to "shall I add it?" that confirms or rejects a suggested thing.
# The whole message must be the answer, so "ok, open VS Code" isn't a yes.
_END = r"(,? (please|thanks|mate|kit))?[.!]*"
YES = re.compile(rf"(yes|yep|yeah|yup|sure|ok|okay|do it|add it|go ahead){_END}", re.I)
NO = re.compile(rf"(no|nope|nah|skip it|don'?t|leave it|no thanks){_END}", re.I)
# "Where?" or "what's that?" back: the question is still open, so a "yes" after
# Kit explains still adds the thing.
ASKED_BACK = re.compile(r"^\W*(where|what|which|why|how|huh|eh|sorry|pardon)\b|\?\W*$", re.I)
ASKED_BACK_WORDS = 3

# Ways to choose who answers one message (KEEP_LOCAL is in kit.cloud).
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
SHOW_WAIT_S = 5.0  # how long a show (the weather) may still take once he's answered
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
# Dan's bad news: no huff, no perking up, whatever else is going on.
SOFT_NEWS = {"sad", "worried", "sympathetic"}
# A question about Kit himself: he's given what's true about him right now to answer from.
# Not "how do you feel about Python?", "are you ok with that?" or "what can you see in
# this log?": those are about something else.
SELF_Q = re.compile(
    r"\bwhy(\s+(did|do|have|had|would)|'?d)\s+you\s+((go|gone) (quiet|silent|to sleep|off|"
    r"away|all)|keep|stop|stopped|pipe|ask|been)\b|"
    r"\bwhy (are|were|have) you (been )?(so )?(quiet|grumpy|sulk\w*|miffed|annoyed|upset|sad|"
    r"cheeky|chatty|asleep|dozing)|\b(do|did) you (miss|care about|like|love|remember) me\b|"
    r"\bare you (real|alive|conscious|sentient|human|a person|lonely|bored)\b|"
    r"\bare you (ok|okay|alright|all right|happy)\b(?!\s+(about|with|in|on|for|if|to|that)\b)|"
    r"\bdo you (have|get) (feelings|emotions|bored|lonely)|"
    r"\bwhat can you (see|hear|sense)\b(?!\s+(about|with|in|on|from|there)\b)|"
    r"\bcan you (see|hear) me\b|\bhow (do|are) you feel(ing)?\b(?!\s+(about|with|in|on)\b)|"
    r"\bwhat('?s| is) it like (being|to be) you|"
    r"\bwhat (do|did) you (do|get up to)\b[^.?!]*\b(while|when) i\b|"
    r"\bwhat (did|have) you (been )?(do|doing|get up to|getting up to|been up to)\b"
    r"(\s+(today|this (morning|arvo|afternoon)|while i was (out|away|gone)))?\s*\??\s*$",
    re.IGNORECASE,
)
# "Sydney's the capital, isn't it?": Dan wants Kit to agree, and might be wrong.
TAG_Q = re.compile(
    r"[,\s](isn'?t|aren'?t|wasn'?t|weren'?t|doesn'?t|don'?t|didn'?t|innit|right|yeah)"
    r"(\s+(it|they|he|she|there|that|this))?\s*\?\s*$",
    re.IGNORECASE,
)
# Dan telling Kit something ("Had a big one at the shops", "My boss moved the deadline
# up again"), not asking or asking for something.
NEWS = re.compile(
    r"^\W*(i(?!'?d like|\s+(want|need|wonder|think|reckon))|i'?m|i'?ve|i was|had|my|we|we'?re|"
    r"our|rough|long|big|busy|today|just|finally|got)\b",
    re.IGNORECASE,
)


FACT_CHECK = (
    "You check an everyday claim someone made. Reply with one short line: 'True.' or "
    "'False: <the right fact>.' Nothing else."
)
FACT_CHECK_S = 4.0  # longer than this and he answers without it
FACT_VERDICT = re.compile(r"(true|false)\b", re.IGNORECASE)


def is_news(text: str) -> bool:
    return "?" not in text and len(text.split()) >= 4 and bool(NEWS.search(text))


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


async def _replay(events: list[Event]) -> AsyncIterator[Event]:
    for event in events:
        yield event


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
    mode = settings.routing.mode
    return (WORK if mode == "cloud-first" else own_role(settings)), False


def own_role(settings: Settings) -> str:
    """Who answers what is Kit's own to say (a goodbye, his thoughts, chat while a
    cloud model works): the chat model in cloud-only, else the local model."""
    return CHAT if settings.routing.mode == "cloud-only" else LOCAL


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
        self.daily = Daily(memory, self.notebook, self.life, settings)
        self.reflector = Reflector(memory, self.notebook, model, cloud, settings)
        self.weather = weather
        self._weather_at: datetime | None = None  # when Kit last looked at a forecast
        self._pc_at: datetime | None = None  # when Kit last looked at the PC for Dan
        self.learner = Learner(memory, recall, model, asking(cloud, settings))
        # His thoughts in the cloud (routing.background chat): the chat model, giving way
        # first as the month's budget runs low.
        self._ask_life = asking(cloud, settings, CHAT, priority="life")
        self._local_freed = False  # the local model was taken off the GPU for the voice
        self.register = Register(memory)
        self.notes = Notes(memory.index, memory.clock)
        self.pending_thing: int | None = None
        self.pending_note: tuple[str, str] | None = None  # (title, text) Kit offered to note
        self.pending_expert = ""  # the question Kit asked to hand to the expert model
        self.jobs: dict[int, Job] = {}
        self._job_ids = itertools.count(1)
        self._turns: set[asyncio.Task] = set()
        # His latest pipe-up and why he said it, for when Dan answers it ("what's up?").
        self._pipe_up: tuple[int, str] | None = None
        # (his message, the thread or getting-to-know-you want it asked about), so Dan's
        # answer is kept with it: how the dentist went, or the cat's name.
        self._asked: tuple[int, int] | None = None
        self._bit_out: tuple[int, datetime] | None = None  # a running joke he just used
        readers = Readers(self._read_weather, self._read_journal, self._read_thing, self._music)
        self.pastimes = Pastimes(readers, memory.clock, memory, self.life.rng)
        self._musing: asyncio.Task | None = None  # a thought while alone; a chat stops it

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
        if self._musing is not None and not self._musing.done():
            self._musing.cancel()  # Dan's here: his thought can wait
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        context = contextvars.copy_context()
        context.run(CHANNEL.set, known(channel))
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

    async def _run_turn(self, text: str, emit: Callable[[Event], None]) -> None:
        settings = self.settings()
        before = self.memory.recent(1)  # what Dan is answering, if anything
        new_chat = self._new_chat_if_quiet(settings)
        history = self.memory.recent(settings.brain.history_messages)
        if await self._new_topic(text, history, settings):
            self.memory.new_chat()
            history = []
            emit({"type": "new_topic"})
        user_id = self.memory.add_message("user", text, channel=CHANNEL.get())
        owner = settings.persona.owner
        now = self.memory.clock()
        game = self.life.game_out  # a game he suggested, which this may answer
        READ.set(None)
        READ_ON.set(self._reading_mood(settings))
        night = bad_night_in(text) if settings.life.bad_night else ""
        felt = feeling_from(text, owner)
        if night:  # a really bad time: worried for Dan, whatever the words matched
            felt = ("worried", f'{owner} said "{quoted(text)}"', 0.9)
            self.life.start_bad_night(felt[1])
        if felt is not None:
            self.life.feel(*felt, show=False)
        home = self.life.homecoming_for_chat()  # a hello he still owes Dan
        if home is not None and home.miffed and felt is not None and felt[0] in SOFT_NEWS:
            home = replace(home, miffed=False)  # no huffing at bad news
            self.life.feel(*felt, show=False, force=True)
        farewell = is_farewell(text)
        if FAREWELL.search(text):
            self.life.said_goodbye(text)
        self._react(felt, home, farewell)
        keep_local = bool(KEEP_LOCAL.search(text))
        learn = relations_in(text, owner) if "?" not in text else []  # "Emma's my cousin"
        answer_aside, named = self._answering_ask(text, before, owner)
        learn += [named] if named else []
        self._follow_life(text, now, settings, farewell)
        asides = [self._answering(history, owner), answer_aside]
        check_fact = False
        pick_up, picked = "", None
        if new_chat and settings.life.chat_opener and not farewell and not self.jobs:
            pick_up, picked = self._pick_up(self.memory.previous_chat(), now, owner)
        if home is not None:
            asides.append(homecoming_aside(home, owner, now, pick_up))
        elif pick_up:
            asides.append(opener_aside(owner, pick_up))
        if picked is not None:
            log.info("a new chat picks up %r", picked.text)
        bedtime = next(
            (w for w in self.notebook.open_wants() if w.meta.get("nudge") == "sleep"), None
        )
        if bedtime is not None:
            self.notebook.mark_said(bedtime.id)  # once, said or not
            if not farewell:
                asides.append(bedtime_aside(owner, now))
        if farewell:
            asides.append(farewell_aside(text, owner))
            LINT.set(Lint(farewell_fault, farewell_line(text, self.life.rng)))
        elif SELF_Q.search(text) and not self.jobs:
            asides.append(self._about_me(owner))
        elif TAG_Q.search(text):
            # Not when Dan said to keep it local: that never leaves the house.
            check_fact = settings.routing.check_facts and route(text, settings) == (LOCAL, False)
            asides.append(wrong_fact_aside(owner))
        elif is_news(text) and not answer_aside:
            asides.append(news_aside(owner))
        expert_ask, declined = self._answer_expert_offer(text)
        if expert_ask:
            asides.append(expert_yes_aside(owner, expert_ask))
        if self.life.bad_night():  # no cheek, he stays; once, someone to talk to
            name_help = not self.life.bad_night_named
            asides.append(bad_night_aside(owner, night == "self_harm", self._someone(), name_help))
            if name_help or night == "self_harm":
                self.life.named_help()
        answering = "\n\n".join(a for a in asides if a)
        MIND.set("\n".join(a for a in asides[1:] if a))  # not the pipe-up he's answered
        if THINKING_Q.search(text) and (shared := self.notebook.latest_thought()):
            self.notebook.mark_said(shared.id)
        voice = self._voice(settings, history, text)  # before note_chat: how Kit felt till now
        bit = self._bit_for(text, now, felt, farewell)
        VOICE.set(replace(voice, bit=bit.text) if bit is not None else voice)
        self.life.note_chat(text)
        answered = (
            declined
            or self._answer_note_offer(text, settings)
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
        # What his face shows (the time, the weather), looked up while he thinks.
        showing = asyncio.create_task(self._show_for(text, settings))
        recent_refs = {str(m.id) for m in history if m.role == "user"}
        # The check runs while he recalls, so it costs next to no time.
        checking = asyncio.create_task(self._check_fact(text, settings)) if check_fact else None
        recalled = await self.recall.for_turn(text, recent_refs)
        if checking is not None and (checked := await checking):
            asides[-1] = wrong_fact_aside(owner, checked)
            answering = "\n\n".join(a for a in asides if a)
            MIND.set("\n".join(a for a in asides[1:] if a))
        # "hey" finds every earlier "hey", and the model copies what it said then.
        fresh = [h for h in recalled.conversation if not same_words(_asked(h.item.text), text)]
        # His notes already on his mind (kit.notebook) are in the prompt once, not twice.
        shown = {e.id for e in self.notebook.on_mind()}
        own = [h for h in recalled.own if h.item.id not in shown]
        recalled = replace(recalled, conversation=fresh, own=own)
        role, chosen = route(text, settings)
        if expert_ask:
            role, chosen = EXPERT, True  # Dan said yes to the expert
        if self.jobs and not chosen:
            role = own_role(settings)  # busy: chat locally (or with the chat model) meanwhile
        if self._key_moment(felt, settings, role, chosen, farewell):
            role = WORK  # bad news: the work model answers, as Kit
            PRIORITY.set("moment")
        if role == own_role(settings) and THINKING_Q.search(text):
            chosen = True  # his own thoughts: nobody else can answer that
        if farewell and not chosen:
            role, chosen = own_role(settings), True  # a goodbye is his own to say
        said: list[str] = []

        if role not in (LOCAL, CHAT) and chosen:
            name = settings.profile(role).name
            for event in self._say_locally(Reply.plain(f"Sure, asking {name}.", "thinking", "nod")):
                emit(event)
        pc_detail = ""
        about_pc = PC_QUESTION.search(text) or (AGAIN.search(text) and self._pc_recently())
        if self.pc.latest is not None and about_pc and not (chosen and role not in (LOCAL, CHAT)):
            self._pc_at = self.memory.clock()
            role, chosen = own_role(settings), True
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
        if role != LOCAL and asides[0] and history[-1].id in self.memory.private_said():
            asides[0] = ""  # he piped up about something Dan kept local
            answering = "\n\n".join(a for a in asides if a)
        await asyncio.sleep(0)  # the time and date are ready at once; the weather may be
        shown = showing.done()
        if shown:
            self._emit_show(showing, emit)
        emotion, reply_id = "", None
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
                emotion, reply_id = event["reply"]["emotion"], event["message_id"]
                if self.jobs:
                    event = {**event, "question": text}
            emit(self._track(event, said))

        if not shown:  # still looking it up when he started, maybe done since
            if not showing.done():
                await asyncio.wait({showing}, timeout=SHOW_WAIT_S)
            self._emit_show(showing, emit)
        read = READ.get()
        from_read = feeling_from_read(read, text, owner) if read else None
        if from_read is not None:  # the model's reading takes over from the words
            other = felt is not None and felt[0] != from_read[0]
            self.life.feel(*from_read, show=False, force=other)
        if read and read.get("dan_mood") == "awful" and settings.life.bad_night:
            self.life.start_bad_night(f'{owner} said "{quoted(text)}"')
        if emotion in REPLY_FEELINGS and felt is None and from_read is None:
            # How he felt answering lingers a little: "sad" about Dan's news stays.
            self.life.feel(REPLY_FEELINGS[emotion], f'{owner} said "{quoted(text)}"', 0.4)
        if said:
            whole = " ".join(said)
            if game == "weather_bet":
                pipe_up = before[-1].text if before and before[-1].role != "user" else ""
                self._place_bet(text, f"{pipe_up} {whole}")
            if picked is not None:  # the thread the new chat picked up: asked, once
                self.notebook.mark_said(picked.id)
                self._asked_in([picked.id], reply_id)
            self._asked_in(self.notebook.said_in(whole, owner), reply_id)  # brought it up himself
            if bit is not None and self.notebook.bit_said(bit, whole):
                self.notebook.bit_used(bit.id)
                self._bit_out = (bit.id, now)
            self.memory.index_exchange(
                user_id, settings.persona.owner, text, settings.persona.name, whole
            )
        for fact in learn:
            learned = await self.learner.learn(
                fact, "person", owner, private=keep_local, cloud=cloud_background(settings)
            )
            emit(
                {
                    "type": "remembered",
                    "fact": learned.text,
                    "decision": learned.decision,
                    "replaced": learned.replaced,
                }
            )
        if said or learn:
            await self.recall.index_pending()

    def _answering_ask(self, text: str, before: list[Message], owner: str) -> tuple[str, str]:
        """Dan answering a thread or a getting-to-know-you question Kit just asked: how
        it went is kept with the thread, and a name ("Milo") is a fact to learn.
        Returns (an aside for the reply, the fact, or "")."""
        asked, self._asked = self._asked, None
        if asked is None or not before or before[-1].id != asked[0]:
            return "", ""
        item = self.memory.index.get(asked[1])
        if item is None:
            return "", ""
        if item.kind == "thread":
            if not KEEP_LOCAL.search(text):
                self.notebook.thread_outcome(item.id, text)
            return "", ""
        key = str(item.meta.get("interview") or "")
        if not key:
            return "", ""
        return interview_aside(owner, self.daily.question(item)), self.daily.name_answer(key, text)

    def _asked_in(self, item_ids: list[int], message_id: int | None) -> None:
        """He just brought these up: a getting-to-know-you question counts as asked, and
        the next message is Dan's answer to it, or to how a thread went."""
        for item_id in item_ids:
            item = self.memory.index.get(item_id)
            if item is None:
                continue
            if item.meta.get("interview"):
                self.daily.asked(str(item.meta["interview"]))
            if message_id is not None and (item.kind == "thread" or item.meta.get("interview")):
                self._asked = (message_id, item.id)

    def _follow_life(self, text: str, now: datetime, settings: Settings, farewell: bool) -> None:
        """What Dan said about his life, for Kit to follow up: "ask me this arvo how it
        went" is a want for then; "dentist Thursday arvo" a thread, to ask how it went
        once it's over; "dentist was fine" closes that thread before he asks. What Dan
        keeps local is never kept with a thread or started as one, since threads go in
        the nightly reflection, which may be a cloud model's."""
        private = bool(KEEP_LOCAL.search(text))
        if not private:
            self.notebook.heard_about(text)
        owner, wake = settings.persona.owner, settings.life.quiet_until
        due = asks_later(text, now, wake)
        if due is not None:
            want = later_want(text, owner)
            after = due.isoformat(timespec="seconds")
            meta = {"private": True} if private else {}
            self.notebook.write("want", want, after=after, strength=ASKED_STRENGTH, **meta)
            return
        if not settings.life.threads or farewell or private:
            return
        coming = thread_in(text, now, wake)
        if coming is not None:
            about, w = coming
            heard = next((s for s in SENTENCE.split(text) if w.words in s), text)
            self.notebook.write_thread(about, w, follow_up(w, wake), heard=heard)

    def _pick_up(self, before: list[Message], now: datetime, owner: str) -> tuple[str, Item | None]:
        """One thing from last time, for a new chat or a hello: a thread of Dan's that's
        over now, else what Dan said when they last talked, if that was a while ago.
        Returns (the line for the prompt, or "", and the thread it's about)."""
        thread = next((t for t in self.notebook.open_wants() if t.kind == "thread"), None)
        if thread is not None:
            return picked_up(owner, thread=aim_of(thread, owner, now)[1]), thread
        if not before:
            return "", None
        last = parse_time(before[-1].at, now)
        if now - last < OPENER_GAP:
            return "", None
        said = [
            quoted(m.text, SAID_CHARS)
            for m in before
            if m.role == "user"
            and timedelta(0) <= last - parse_time(m.at, now) <= OPENER_SPAN
            and len(m.text.split()) >= OPENER_WORDS
            and not KEEP_LOCAL.search(m.text)
        ]
        if not said:
            return "", None
        return picked_up(owner, since_words(last, now), said[-OPENER_SAID:]), None

    def _bit_for(
        self, text: str, now: datetime, felt: tuple[str, str, float] | None, farewell: bool
    ) -> Item | None:
        """A running joke something Dan said sets off, to bring back if it fits; never
        at bad news or a goodbye. A laugh just after the last one means it landed."""
        out, self._bit_out = self._bit_out, None
        if out is not None and now - out[1] < LAUGHED_WITHIN and LAUGH.search(text):
            self.notebook.bit_used(out[0], landed=True)
        if farewell or (felt is not None and felt[0] in SOFT_NEWS):
            return None
        return self.notebook.bit_for(text)

    def _key_moment(
        self,
        felt: tuple[str, str, float] | None,
        settings: Settings,
        role: str,
        chosen: bool,
        farewell: bool,
    ) -> bool:
        """Dan's had bad news (a strong sad or worried feeling): the work model answers,
        as Kit, when ``routing.key_moments`` is on. Never when he said to keep it local,
        chose a model himself, or a cloud model is already busy."""
        routing = settings.routing
        if not routing.key_moments or felt is None or farewell or self.jobs:
            return False
        if felt[0] not in SOFT_NEWS or felt[2] < routing.key_moment_strength:
            return False
        home_turn = role in (LOCAL, CHAT) and not chosen
        return home_turn and settings.profile(WORK).provider != "ollama"

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

    def _new_chat_if_quiet(self, settings: Settings) -> bool:
        """Back after a long quiet: start fresh, so this morning's topic doesn't
        follow Dan into the afternoon. Recall still finds the old conversation.
        Returns whether it did."""
        after = settings.brain.new_chat_after_minutes
        last = self.memory.recent(1)
        if not after or not last:
            return False
        if self.memory.clock() - datetime.fromisoformat(last[-1].at) >= timedelta(minutes=after):
            self.memory.new_chat()
            return True
        return False

    async def _show_for(self, text: str, settings: Settings) -> dict | None:
        persona = settings.persona
        return await show_for(
            text,
            self.memory.clock(),
            self.weather,
            persona.location,
            persona.country,
            settings.face.hot_c,
        )

    @staticmethod
    def _emit_show(showing: asyncio.Task, emit: Callable[[Event], None]) -> None:
        """Send what his face shows, once. A show that failed or took too long is
        skipped: it's a nicety, never worth an error."""
        if not showing.done():
            showing.cancel()
            return
        if showing.cancelled():
            return
        error = showing.exception()
        if error is not None:
            log.info("nothing to show on his face: %s", error)
            return
        show = showing.result()
        if show:
            emit({"type": "show", "show": show})

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
            text = with_mind(text, self.notebook.mind(owner, shared=role != LOCAL), owner)
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
        if role not in (LOCAL, CHAT) or not self.jobs:
            return text
        work = " ".join(job.line() for job in self.jobs.values())
        owner = self.settings().persona.owner
        # A few words while Kit is busy ("hey", "kit", "you there") is getting its
        # attention about the work, the same as asking how it's going.
        short = len(re.findall(r"\w+", text)) <= 3
        checking_in = CHECKING_IN.search(text) or NUDGE.search(text) or short
        if not checking_in or is_farewell(text):  # "ok bye" isn't asking how it's going
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

    def _answer_expert_offer(self, text: str) -> tuple[str, Reply | None]:
        """Kit asked whether to hand a question to the expert model: a yes gives the
        question to ask it, a no a reply that leaves it; anything else lets it lapse."""
        pending, self.pending_expert = self.pending_expert, ""
        if not pending:
            return "", None
        if YES.fullmatch(text):
            return pending, None
        if NO.fullmatch(text):
            return "", Reply.plain("Okay, I'll leave it there.", "neutral", "nod")
        return "", None

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
        settings = self.settings()
        owner = settings.persona.owner
        home = self.life.take_homecoming() if reason == "back" else None
        if reason == "back" and home is None:
            return  # the moment passed meanwhile
        history = self.memory.recent(settings.brain.history_messages)
        share = self.notebook.to_share() if reason in SHARES else None
        if reason == "want" and share is None:
            reason = "bored"  # it was dropped meanwhile; he's still restless
        aim, about = "", share.text if share else ""
        if share is not None and share.kind in ASKING:
            aim, about = aim_of(share, owner, self.memory.clock())  # "tell Dan", not read out
        now = self.memory.clock()
        bar = settings.life.pipe_up_bar
        if bar > 0 and home is None and reason != "nag":
            score, parts = self._pipe_up_score(reason, about, history, now)
            if score < bar:
                why = f"had something to say, but it scored {score:.2f} of {bar:.2f} ({parts})"
                log.info("Kit kept a pipe-up to himself: %s", why)
                self.life.scored_out(reason, why)
                return
        also, picked = "", None
        if home is not None and settings.life.chat_opener:
            also, picked = self._pick_up(history, now, owner)
        token = CHANNEL.set("desk")
        voice_token = VOICE.set(self._voice(settings, history))
        lint_token = LINT.set(self._hello_lint(home) if home is not None else None)
        mind = homecoming_facts(home, owner, now, also) if home is not None else ""
        mind_token = MIND.set(mind)
        said: list[str] = []
        message_id = None
        kept_quiet = False
        try:
            doing = self.pc.now_line(owner) or f"what {owner} is up to"
            recalled = await self.recall.for_turn(doing, {str(m.id) for m in history})
            quiet_h = (self.memory.clock() - self.life.last_chat).total_seconds() / 3600
            if home is not None:
                prompt = homecoming_prompt(home, owner, self.life.cheek(), now, also)
            else:
                prompt = pipe_up_prompt(
                    reason,
                    owner,
                    self.life.cheek(),
                    self.life.curious_about,
                    quiet_h,
                    self.life.butting_in,
                    share=about,
                    aim=aim,
                )
            messages = [
                {"role": "system", "content": self._system(settings, recalled, LOCAL, False)},
                *history_messages(history, "desk", plain=settings.ollama.speak_pass),
                {"role": "user", "content": prompt},
            ]
            hello: list[Event] | None = None
            if home is not None and self._key_hello(home, settings):
                hello = await self._cloud_hello(home, prompt, history, recalled, settings) or None
            private = share is not None and bool(share.meta.get("private"))
            if hello is None and self._life_in_cloud(settings) and not private:
                hello = await self._cloud_pipe_up(prompt, history, recalled, settings)
            if hello is not None:
                replies = _replay(hello)
            else:
                replies = self._local_reply(messages, PIPE_UP, hold=True)
            async for event in replies:
                if event["type"] == "reply":
                    event = {**self._track(event, said), "piped_up": reason}
                    message_id = event["message_id"]
                kept_quiet = kept_quiet or event["type"] == "kept_quiet"
                yield event
        finally:
            CHANNEL.reset(token)
            VOICE.reset(voice_token)
            LINT.reset(lint_token)
            MIND.reset(mind_token)
        if not said:
            self.life.held_back(reason, home)
            if kept_quiet:  # he was about to say something, and thought better of it
                self.life.react("look_away", "thought better of it")
            return
        if share is not None:
            self.notebook.mark_said(share.id)
            if share.meta.get("game"):
                self.life.game_asked(str(share.meta["game"]))
            self._asked_in([share.id], message_id)
        if picked is not None:  # the thread the hello picked up: asked, once
            self.notebook.mark_said(picked.id)
            self._asked_in([picked.id], message_id)
        self._asked_in(self.notebook.said_in(" ".join(said), owner), message_id)
        why = self._why_piped(reason, aim, about, owner)
        if share is not None and share.meta.get("private") and message_id is not None:
            self.memory.said_privately(message_id)  # from what Dan kept local
        self._pipe_up = (message_id, why) if message_id is not None else None
        self.life.piped_up(reason)
        self.life.wanting = self.notebook.pressing()

    def _pipe_up_score(
        self, reason: str, about: str, history: list[Message], now: datetime
    ) -> tuple[float, str]:
        """How worth saying this pipe-up is (``life.pipe_up_bar``): its subject
        against what Dan's doing, the time and what's been said lately."""
        owner = self.settings().persona.owner
        context = " ".join(
            [self.pc.now_line(owner), *(m.text for m in history[-4:]), day_part(now), f"{now:%A}"]
        )
        said = [without_plans(m.text) for m in history if m.role != "user"][-SAID_SHOWN:]
        d = self.life.drives
        urgency = {
            "want": self.life.wanting,
            "bored": d.boredom,
            "social": d.social,
            "curious": d.curiosity,
            "watching": d.curiosity,
        }.get(reason, 0.5)
        rate = self.life.take_up_rate(reason)
        return pipe_up_score(reason, about, context, said, urgency, rate)

    def _key_hello(self, home: Homecoming, settings: Settings) -> bool:
        """A hello after a night or days away is a key moment, for the work model
        (``routing.key_moments``)."""
        routing = settings.routing
        if not routing.key_moments or home.kind not in routing.key_moment_hellos:
            return False
        return settings.profile(WORK).provider != "ollama"

    async def _cloud_hello(
        self,
        home: Homecoming,
        prompt: str,
        history: list[Message],
        recalled: Recalled,
        settings: Settings,
    ) -> list[Event]:
        """The hello written by the work model, as Kit, and checked like any hello. []
        if it can't be (offline, budget kept for the nightly reflection, a guilt trip):
        then the local model says hello."""
        try:
            reply, answer = await self._cloud_line(
                prompt, history, recalled, settings, WORK, "a hello", "moment"
            )
        except CloudError as e:
            log.info("the hello is the local model's: %s", e)
            return []
        fault = homecoming_fault(reply.text, home.miffed, home.kind)
        if not reply.text or fault:
            log.info("the work model's hello %r didn't pass: %s", reply.text, fault)
            return []
        return self._said_by_cloud(reply, answer)

    async def _cloud_pipe_up(
        self, prompt: str, history: list[Message], recalled: Recalled, settings: Settings
    ) -> list[Event] | None:
        """A pipe-up written by the chat model (``routing.background`` chat), held and
        checked like the local model's: a line he's said lately, or one the turn's
        ``LINT`` fails, gets two more goes; then the stock line, or he keeps quiet.
        None when the cloud can't answer and the local model should
        (``routing.fallback_to_local``)."""
        voice, lint = VOICE.get(), LINT.get()
        retry, again = "", ""
        for _ in range(HELD_TRIES):
            try:
                reply, answer = await self._cloud_line(
                    prompt + retry, history, recalled, settings, CHAT, "a pipe-up", "life"
                )
            except CloudError as e:
                log.info("the pipe-up is the local model's: %s", e)
                return None if settings.routing.fallback_to_local else []
            fault = lint.check(reply.text) if lint is not None and reply.text else ""
            again = (
                "" if fault or (lint and not lint.repeats) else self._repeated(reply.text, voice)
            )
            if reply.text and not fault and not again:
                return self._said_by_cloud(reply, answer)
            retry = fault or (not_again(again) if again else "")
        if lint is not None and lint.fallback:
            log.info("said a stock line: no clean pipe-up in %d goes", HELD_TRIES)
            return self._said_by_cloud(Reply.plain(lint.fallback), answer)
        log.info("kept quiet rather than say %r again", again)
        return [{"type": "kept_quiet", "repeated": again}]

    async def _cloud_line(
        self,
        prompt: str,
        history: list[Message],
        recalled: Recalled,
        settings: Settings,
        role: str,
        what: str,
        priority: str,
    ) -> tuple[Reply, CloudAnswer]:
        """One line of Kit's own (a hello, a pipe-up) from the cloud model ``role``, shown
        only what Dan hasn't kept local. Raises CloudError if it can't be had."""
        profile = settings.profile(role).model_copy(update={"web_search": False})
        seen = self.memory.shared(history)
        system = self._system(settings, recalled.for_cloud(), role, False, history=seen)
        messages = [
            {"role": "system", "content": system},
            *history_messages(seen, "desk"),
            {"role": "user", "content": prompt},
        ]
        answer = await self.cloud.answer(profile, messages, settings, what, priority=priority)
        reply = parse_cloud_reply(answer.text)
        return reply.model_copy(update={"detail": "", "action": Action(kind="none")}), answer

    def _said_by_cloud(self, reply: Reply, answer: CloudAnswer) -> list[Event]:
        """A line of his own from a cloud model, kept and told as a pipe-up."""
        message_id = self._remember_reply(reply, PIPE_UP)
        return [
            {"type": "say", "text": reply.text, "source": "cloud"},
            {
                "type": "reply",
                "source": PIPE_UP,
                "reply": reply.model_dump(),
                "message_id": message_id,
                "model": answer.model,
                "cost_usd": round(answer.cost_usd, 4),
            },
        ]

    async def free_gpu(self) -> None:
        """Once the local model only stands in (``kit.settings.local_stands_in``), take it
        off the GPU at once: switching over sends it nothing more, so without this it
        would stay loaded till its old keep_alive ran out. When it's used again, its
        short keep_alive sees it off by itself."""
        if not local_stands_in(self.settings()):
            self._local_freed = False
            return
        if self._local_freed:
            return
        try:
            await self.model.unload()
        except LocalModelError as e:
            log.info("couldn't take the local model off the GPU: %s", e)
            return
        self._local_freed = True
        log.info("the local model is off the GPU; the cloud does Kit's background work")

    def _life_in_cloud(self, settings: Settings) -> bool:
        """His thoughts and pipe-ups go to the chat model (``routing.background``)."""
        return cloud_background(settings) and settings.profile(CHAT).provider != "ollama"

    def _hello_lint(self, home: Homecoming) -> Lint:
        """A hello is checked for guilt ("where have you been?"), not for being said
        before: "there you are" is fine every time."""
        fallback = self.life.rng.choice(HOME_LINES)
        return Lint(
            lambda line: homecoming_fault(line, home.miffed, home.kind), fallback, repeats=False
        )

    def offer_wants(self) -> list[str]:
        """Once a heartbeat: what Kit might write into his notebook to bring up (a
        game, a getting-to-know-you question, a nudge, how the weekend went). Returns
        what he wrote."""
        game = ["game"] if self.offer_game() else []
        return game + self.daily.offer()

    def tidy(self) -> int:
        """Old "now" facts and stale notebook entries go. Returns how many."""
        return self.memory.tidy_now(self.settings().memory.now_days) + self.notebook.tidy()

    def offer_game(self) -> bool:
        """At most once a day, when he's bored and Dan's about (``Life.game_due``),
        Kit writes a small game into his notebook as something he wants to bring up."""
        name = self.life.game_due()
        if name is None:
            return False
        for want in self.notebook.unsaid_wants():
            if want.meta.get("game"):
                self.notebook.forget(want.id)  # an earlier day's, never got to: moot now
        text = GAMES[name][0].format(owner=self.settings().persona.owner)
        added = self.notebook.write("want", text, again=True, game=name, strength=GAME_PRESS)
        return added is not None

    # His life while Dan's out (kit.pastimes), and the weather bet

    async def start_pastime(self) -> Pastime | None:
        """Alone and awake with nothing to do: he finds something (``Life.wants_pastime``)."""
        if not self.life.wants_pastime():
            return None
        d = self.life.drives
        drives = {"boredom": d.boredom, "curiosity": d.curiosity, "social": d.social}
        pastime = await self.pastimes.pick(drives, self.life.away_since or self.memory.clock())
        if self.life.presence() != "alone":
            return None  # Dan came back (or he dozed off) while he looked
        if pastime is None:
            self.life.nothing_to_do()
            return None
        self.life.start_doing(pastime)
        return pastime

    async def _read_weather(self) -> tuple[str, str] | None:
        if self.weather is None:
            return None
        persona = self.settings().persona
        try:
            today = await self.weather.today(persona.location, persona.country)
        except WeatherError as e:
            log.info("no weather to watch: %s", e)
            return None
        if today.now_c is None:
            return None
        top = f"; today's top is {today.top_c:.0f}°C" if today.top_c is not None else ""
        rain = f", {today.rain_chance}% chance of rain" if today.rain_chance is not None else ""
        return (
            weather_doing(today.sky),
            f"Outside in {today.place} it's {today.now_c:.0f}°C and {today.sky}{top}{rain}.",
        )

    def _read_journal(self) -> tuple[str, str] | None:
        yesterday = (self.memory.clock().date() - timedelta(days=1)).isoformat()
        entry = self.notebook.journal(yesterday)
        if entry is None:
            return None
        return (
            "reading yesterday's journal",
            f'Your journal from yesterday says: "{quoted(entry.text, 300)}"',
        )

    def _read_thing(self, rng) -> tuple[str, str] | None:
        """Someone or something everyday from the register (never work projects)."""
        things = [
            t
            for t in self.register.all()
            if t.kind in ("person", "pet", "vehicle", "place") and not t.suggested
        ]
        if not things:
            return None
        thing = rng.choice(things)
        about = f" {thing.about}" if thing.about else ""
        return (
            f"thinking about {thing.name}",
            f"From your register of things: {thing.name} ({thing.kind}).{about}",
        )

    def _music(self) -> tuple[str, str] | None:
        """What the PC is playing, only when the desk app's tray switch shares it."""
        snap = self.pc.latest if self.pc.online() else None
        playing = snap.now_playing.strip() if snap else ""
        if not playing:
            return None
        owner = self.settings().persona.owner
        return f"listening to {quoted(playing, 40)}", f"{owner}'s PC is playing {playing}."

    def _place_bet(self, dan_said: str, kit_said: str) -> None:
        """Dan answered the weather bet: his guess, and Kit's (from his pipe-up or this
        reply), for settling it this afternoon."""
        dans = temperatures(dan_said)
        if not dans:
            return
        kits = [t for t in temperatures(kit_said) if t != dans[0]]
        if kits:
            self.life.bet_placed(dans[0], kits[-1])

    async def settle_bet(self) -> str | None:
        """Late afternoon: today's top is in, so who won the weather bet? He feels it
        (put out if he lost) and wants to tell Dan. Returns what he'll say."""
        bet = self.life.bet_open()
        if bet is None or self.weather is None:
            return None
        persona = self.settings().persona
        try:
            today = await self.weather.today(persona.location, persona.country)
        except WeatherError as e:
            log.info("can't settle the weather bet yet: %s", e)
            return None
        if today.top_c is None:
            return None
        line = self.life.bet_settled(float(today.top_c))
        self.notebook.write("want", line, again=True, strength=GAME_PRESS)
        self.life.wanting = self.notebook.pressing()
        return line

    # How Dan is (life.read_mood, life.bad_night)

    def _reading_mood(self, settings: Settings) -> bool:
        """Read Dan's mood from meaning: only once ``kit eval mood`` has passed."""
        if settings.life.read_mood != "meaning":
            return False
        try:
            calibration = json.loads(self.memory.self_value(MOOD_CALIBRATION) or "{}")
        except ValueError:
            return False
        return isinstance(calibration, dict) and bool(calibration.get("passed"))

    def mood_reading(self) -> str:
        """How he reads Dan's mood just now, in words for ``kit life``."""
        if self.settings().life.read_mood != "meaning":
            return "your words"
        if self._reading_mood(self.settings()):
            return "meaning (calibrated)"
        return "your words (meaning is on, but `kit eval mood` hasn't passed yet)"

    def _someone(self) -> str:
        """Someone real and close that Dan could talk to, from the register."""
        for thing in self.register.all():
            if thing.kind == "person" and not thing.suggested and CLOSE.search(thing.about):
                return thing.name
        return ""

    def _react(
        self, felt: tuple[str, str, float] | None, home: Homecoming | None, farewell: bool
    ) -> None:
        """A visible reaction the moment a message lands, before any answer: perking up
        when Dan's back, a wave goodbye, a wiggle at praise. Bodies play these even
        mid-conversation, so Dan sees he's been heard."""
        if home is not None and not (felt is not None and felt[0] in SOFT_NEWS):
            self.life.react("look_away" if home.miffed else "perk_up", "you're back")
        elif farewell:
            self.life.react("wave", "see you")
        elif felt is not None:
            self.life.react(self.life.rng.choice(FEELING_KINDS[felt[0]][2]), felt[0])

    async def _check_fact(self, text: str, settings: Settings) -> str:
        """A claim Dan wants Kit to agree with, checked by the work model: "True." or
        "False: <the right fact>.", or "" if it couldn't say in time."""
        profile = settings.profile(WORK)
        if profile.provider == "ollama":
            return ""
        quick = profile.model_copy(update={"web_search": False, "max_tokens": 300})
        messages = [
            {"role": "system", "content": FACT_CHECK},
            {"role": "user", "content": text},
        ]
        try:
            answer = await asyncio.wait_for(
                self.cloud.answer(quick, messages, settings, text, priority="check"),
                FACT_CHECK_S,
            )
        except (CloudError, TimeoutError) as e:
            log.info("couldn't check %r: %s", text, e or "too slow")
            return ""
        line = " ".join(answer.text.split())
        return line if FACT_VERDICT.match(line) else ""

    def _about_me(self, owner: str) -> str:
        """What's true about Kit right now, for a question about himself."""
        snap = self.pc.latest if self.pc.online() else None
        if snap is None:
            senses = (
                f"The desk app isn't reporting just now, so you can't tell what's on {owner}'s "
                f"PC. You know the time and date, and the weather when you look it up."
            )
        else:
            tabs = f", the tabs open in {snap.browser.name}" if snap.browser else ""
            senses = (
                f"What you can sense: {owner}'s PC through the desk app (the window in "
                f"front{tabs}, how long since they touched the keyboard or mouse, and whether "
                f"it's locked), the time and date, and the weather when you look it up."
            )
        senses += f" You can't see or hear {owner}: you have no camera or microphone yet."
        feeling = self.life.feeling_line(owner)
        did = self.life.did_line(owner)
        if did:
            senses += f" {did} That's all true; don't add to it."
        return about_yourself(owner, feeling, self.life.why_quiet(owner), senses)

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
            today = self.memory.messages_on(self.memory.today())[-8:]
            said_today = [
                f"{owner}: {quoted(m.text, 200)}"
                if m.role == "user"
                else f"{persona.name}: {quoted(without_plans(m.text), 200)}"
                for m in today
            ]
            # From what Dan kept local, or what Kit kept from it: the thought is private.
            private = len(self.memory.shared(today)) < len(today) or (
                recalled.for_cloud().ids() != recalled.ids()
            )
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
                stances=settings.life.opinions > 0,
            )
            raw = None
            if self._life_in_cloud(settings) and not private:
                data = await self._ask_life(messages, THOUGHT_SCHEMA, THOUGHT_SHAPE, "a thought")
                if data is None and not settings.routing.fallback_to_local:
                    self.life.thought_failed()
                    return None
                raw = json.dumps(data) if data is not None else None
            if raw is None:
                options = lively(settings.ollama, plain=False)
                raw = await self.model.complete(messages, THOUGHT_SCHEMA, None, options)
        except LocalModelError as e:
            log.warning("Kit couldn't think just now: %s", e)
            self.life.thought_failed()  # costs no budget, but no hammering a model that's down
            return None
        except asyncio.CancelledError:
            self.life.thought_failed()  # Dan started talking: the thought can wait
            raise
        self.life.thought_had(kind)
        thought = parse_thought(raw, kind)
        if thought is None:
            return None
        keep = {"private": True} if private else {}
        if kind == "alone" and self.life.doing is not None:
            keep["doing"] = self.life.doing.doing
        if thought.text and self.notebook.write(thought.kind, thought.text, trigger=kind, **keep):
            self.life.publish({"type": "fidget", "gesture": "look_up", "mood": "thinking"})
        if thought.want:
            later = FOR_LATER.search(thought.want)
            when = tomorrow_morning(self.memory.clock(), settings.life.quiet_until)
            due = {"after": when} if later else {}
            self.notebook.write("want", thought.want, trigger=kind, **due, **keep)
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
        opinions = self._opinions(settings)
        return self.life.voice(persona.owner, own, said, self.quirks, text, mind, opinions)

    def _opinions(self, settings: Settings, shared: bool = False) -> list[str]:
        """His standing opinions (``life.opinions``): stances he's held at least a day,
        newest first. Only ones the nightly reflection chose as stances count (the
        local model can't be trusted to tell a stance from a remark mid-thought), never
        remarks about Dan. ``shared``: none formed from what Dan kept local."""
        want = settings.life.opinions
        if want <= 0:
            return []
        now = self.memory.clock()
        held = [
            e
            for e in self.notebook.entries("opinion", 30)
            if now - parse_time(e.created, now) >= OPINION_STANDS
            and not (shared and e.meta.get("private"))
            and e.meta.get("stance")
            and a_view(e.text, settings.persona.owner)
        ]
        return [e.text for e in held[:want]]

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
        history: list[Message] | None = None,
    ) -> str:
        """The system prompt. For a cloud model, ``history`` is what it's shown of the
        chat, and his voice keeps to that and to what he can share."""
        routing = settings.routing
        voice = VOICE.get()
        if role != LOCAL and voice is not None:
            said = [without_plans(m.text)[:SAID_CHARS] for m in history or [] if m.role != "user"]
            mind = self.notebook.mind(settings.persona.owner, shared=True)
            opinions = self._opinions(settings, shared=True)
            voice = replace(
                voice, said=[x for x in said if x][-SAID_SHOWN:], mind=mind, opinions=opinions
            )
        work, expert = settings.profile(WORK), settings.profile(EXPERT)
        sheet = self.notebook.sheet()
        if role == LOCAL:
            helper, further, web = (work.name if hand_off else None), None, False
        elif role == CHAT:
            chat = settings.profile(CHAT)
            onward = hand_off and routing.chat != routing.work
            helper, further, web = (work.name if onward else None), None, chat.web_search
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
            confirm_expert=routing.confirm_expert,
            web_search=web,
            busy=[job.line() for job in self.jobs.values()],
            quirks=self.quirks,
            voice=voice,
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
            dan=self._about_dan(role),
            read_mood=READ_ON.get(),
        )

    def _about_dan(self, role: str) -> str:
        """What's going on with Dan, as Kit wrote it last night; not for a cloud model
        if it was written from something Dan kept local."""
        dan = self.notebook.dan()
        if dan is None or (role != LOCAL and dan.meta.get("private")):
            return ""
        return dan.text

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
        hand_off = role in (LOCAL, CHAT) and not chosen and hops == 0
        seen, shown = history, recalled
        if role != LOCAL:  # what Dan kept local, and what Kit kept from it, stays home
            seen, shown = self.memory.shared(history), recalled.for_cloud()
        system = self._system(settings, shown, role, hand_off, forecast, pc_detail, seen)
        plain = role == LOCAL and settings.ollama.speak_pass  # the words come as plain text
        messages = [
            {"role": "system", "content": system},
            *history_messages(seen, CHANNEL.get(), plain=plain),
            {
                "role": "user",
                "content": self._user_turn(text, role, settings, pc_detail, answering),
            },
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
            failed = self._cloud_failed(e, text, history, recalled, settings, chosen, answering)
            async for event in failed:
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
            private = bool(KEEP_LOCAL.search(text))
            learned = await self.learner.learn(
                fact,
                reply.action.category,
                settings.persona.owner,
                private=private,
                cloud=cloud_background(settings),
            )
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
        if kind == "ask_expert" and role == WORK and settings.routing.confirm_expert:
            # Kit has asked whether to hand it over; it goes only on a "yes".
            self.pending_expert = reply.action.text.strip() or text
            expert = settings.profile(EXPERT).name
            yield {"type": "notice", "message": f"Say yes to ask {expert}."}
        elif (kind == "ask_cloud" and hand_off) or (kind == "ask_expert" and role == WORK):
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
        answering: str = "",
    ) -> AsyncIterator[Event]:
        """A cloud model couldn't answer. Unless Dan asked for it by name, the local
        model has a go instead (when fallback is on), with the same asides (a hello he
        owes, what he piped up about); otherwise Kit says why."""
        self.life.react("droop", "the cloud didn't answer")
        if settings.routing.fallback_to_local and not chosen:
            yield {"type": "notice", "message": f"{error} I'll answer myself."}
            async for event in self._converse(
                text, history, recalled, settings, LOCAL, chosen=True, hops=1, answering=answering
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
        answer = await self.cloud.answer(
            profile, messages, settings, question, on_step, priority=PRIORITY.get()
        )
        self.life.react("perk_up", "the answer came back")
        if role != CHAT:  # a real job tires him; an everyday answer doesn't
            self.life.spend(CLOUD_TIRES)
        if READ_ON.get() and READ.get() is None:
            READ.set(mood_read(answer.text))
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
        raw, early = "", None
        read = READ_ON.get()
        async with aclosing(self.model.stream(messages, plan_schema(read))) as pieces:
            async for piece in pieces:
                raw += piece
                early = early_plan(raw, read)
                if early is not None:
                    break
        if read:
            READ.set(mood_read(raw))
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
        again, and a pipe-up has no written detail. A ``LINT`` for the turn (a goodbye,
        a hello) also holds the line back till it's whole and checked; if every go
        fails it, or the model is down, its stock line is said instead."""
        settings = self.settings()
        voice = VOICE.get()
        lint = LINT.get()
        hold = hold or lint is not None
        spoken = detail = ""
        tries = HELD_TRIES if hold else 2
        plan = Plan.default()
        try:
            plan = await self._plan(messages)
            if plan.action.kind == "thing" and not named_in(plan.action.text, heard):
                # Dan never named it, so no "shall I add it to the register?"
                plan = plan.model_copy(update={"action": Action(kind="none")})
            if plan.action.kind == "note" and not asks_for_note(heard):
                # Dan didn't ask for a note, so Kit offers rather than writes one.
                offer = plan.action.model_copy(update={"kind": "offer_note"})
                plan = plan.model_copy(update={"action": offer})
            note = speak_note(
                plan.action,
                settings.persona.owner,
                settings.profile(WORK).name,
                settings.profile(EXPERT).name,
                voice,
                heard,
                MIND.get(),
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
                        if hold:
                            continue
                        if not stream.released:
                            first = stream.first()
                            if first is None:
                                continue
                            if not last and self._repeats(first, voice):
                                again = first
                                break
                            stream.release()
                        if out := stream.take():
                            yield {"type": "say", "text": out}
                retry = ""  # what the speaking note says next go, if there is one
                if hold:
                    whole = stream.result()[0]
                    fault = lint.check(whole) if lint is not None and whole else ""
                    if not fault and (lint is None or lint.repeats):
                        again = self._repeated(whole, voice)
                    retry = fault or (not_again(again) if again else "")
                    if retry and last:
                        if lint is not None and lint.fallback:
                            log.info("said a stock line rather than %r", whole)
                            spoken, detail = lint.fallback, ""
                            yield {"type": "say", "text": spoken}
                            break
                        log.info("kept quiet rather than say %r again", again)
                        yield {"type": "kept_quiet", "repeated": again}
                        return
                elif not again and not stream.released and not last:
                    whole = stream.result()[0]  # it ended before the opening was judged
                    again = whole if whole and self._repeats(whole, voice) else ""
                if again and not retry:
                    retry = not_again(again)
                if retry:
                    talk = [*talk[:-1], {"role": "user", "content": note + retry}]
                    options = {**options, "temperature": options["temperature"] + 0.1}
                    continue
                if out := stream.end():
                    yield {"type": "say", "text": out}
                spoken, detail = stream.result()
                if spoken:
                    break
                if stream.wrote_json():  # his plan again rather than words
                    talk = [*talk[:-1], {"role": "user", "content": note + IN_WORDS}]
        except LocalModelError as e:
            if lint is None or not lint.fallback:
                yield {"type": "error", "message": f"My local brain isn't answering: {e}"}
                return
            log.warning("the local model isn't answering (%s): a stock line instead", e)
        except Exception as e:  # a bug in the stream reader must not drop the chat
            log.exception("reading the local model's reply failed")
            yield {"type": "error", "message": f"I lost my train of thought ({e}). Say again?"}
            return
        if not spoken and lint is not None and lint.fallback:
            spoken, detail = lint.fallback, ""
            yield {"type": "say", "text": spoken}
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
        if (lint := LINT.get()) is not None:
            async for event in self._one_pass_checked(messages, source, model, lint):
                yield event
            return
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

    async def _one_pass_checked(
        self, messages: list[dict], source: str, model: str | None, lint: Lint
    ) -> AsyncIterator[Event]:
        """A one-pass reply with a ``LINT`` (a goodbye, a hello): the whole reply is
        checked before it's shown, with two more goes, then the stock line."""
        reply, talk = None, messages
        for _ in range(HELD_TRIES):
            try:
                reply = parse_reply(await self.model.complete(talk, reply_schema(), model))
            except LocalModelError as e:
                log.warning("the local model isn't answering (%s): a stock line instead", e)
                reply = None
                break
            except ReplyError:
                reply = None
                continue
            fault = lint.check(reply.text)
            if not fault:
                break
            reply = None
            asked = messages[-1]
            talk = [*messages[:-1], {**asked, "content": asked["content"] + fault}]
        if reply is None:
            if not lint.fallback:
                yield {"type": "error", "message": "I lost my train of thought. Say again?"}
                return
            log.info("said a stock line: no clean reply in %d goes", HELD_TRIES)
            reply = Reply.plain(lint.fallback)
        yield {"type": "say", "text": reply.text}
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
        settings = self.settings()
        persona = settings.persona
        cloud = settings.memory.day_pass == "work"
        for day in self.memory.days_to_summarise():
            if not await self.learner.summarise_day(day, persona.owner, persona.name, cloud):
                break
            done.append(day)
        return done
