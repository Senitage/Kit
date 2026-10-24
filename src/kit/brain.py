"""Kit's conversation loop.

Each turn (``Brain._run_turn``: read, recall, route, converse, afterwards):

0. Read: the message goes in the log, with whether Dan kept it local. Its words give
   a first reading of what it is (a goodbye, news, a question about Kit, a bad-night
   phrase: ``Reading``), which shapes the prompt; the model's own reading, from its
   plan or a cloud reply, is laid over it and decides everything after.
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
   - look_around: Kit reads everything his eyes see (kit.scene_context: who's
     at the desk, what they're doing, what's about), then answers again;
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
from datetime import date, datetime, timedelta

from kit.activity import ACTIVITY, write_days
from kit.audience import aloud, audience_line, pets_by_kind, speaker_meta
from kit.body_registry import BodyRegistry
from kit.brief import (
    FOLLOW_UP,
    Brief,
    asked_about,
    brief_aside,
    brief_prompt,
    follow_up_aside,
    sources_for,
)
from kit.channels import Arrival, channel_line, known
from kit.cloud import Cloud, CloudAnswer, CloudError, tool_turns
from kit.daily import Daily
from kit.desk_commands import DeskCommands
from kit.files.index import Files
from kit.heard import (
    TONE_FEELINGS,
    HeardTurns,
    Hearing,
    Utterance,
    speaker_aside,
    tone_aside,
)
from kit.house.model import House
from kit.house.noticing import Watcher
from kit.knowledge import Item
from kit.learning import Learner, asking, relations_in, said_so
from kit.life import (
    CLOUD_TIRES,
    FAREWELL,
    FEELING_KINDS,
    FIGURE_OF_SPEECH,
    GAME_PRESS,
    GAMES,
    HOME_LINES,
    LAUGH,
    REPLY_FEELINGS,
    SHUSH,
    THOUGHT_FEELS,
    UNSHUSH,
    Homecoming,
    Life,
    Voice,
    bad_night_after_aside,
    bad_night_aside,
    bad_night_in,
    cheek_style,
    crisis_check_aside,
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
    KEEP_LOCAL,
    RECALL_STEP,
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
    share_kind,
    thread_in,
    tomorrow_morning,
)
from kit.notes import (
    ALL,
    NoteError,
    Notes,
    Request,
    asked_text,
    asks_for_note,
    request,
    title_for,
)
from kit.pastimes import Pastime, Pastimes, Readers, weather_doing
from kit.pc_context import PcContext, away_on
from kit.projects import PROJECTS, Projects
from kit.prompt import (
    IN_WORDS,
    about_yourself,
    answering_pipe_up,
    bedtime_aside,
    expert_yes_aside,
    history_messages,
    interview_aside,
    later_note,
    new_subject_note,
    news_aside,
    not_again,
    opener_aside,
    picked_up,
    speak_note,
    split_turn,
    system_prompt,
    with_mind,
    with_now,
    with_pc_look,
    with_scene_look,
    within_budget,
    wrong_fact_aside,
)
from kit.recall import Recall, Recalled
from kit.reflection import Reflector
from kit.reply import (
    READING_FIELDS,
    Action,
    Plan,
    Reply,
    ReplyError,
    SayExtractor,
    SpokenStream,
    StreamedReply,
    early_plan,
    mood_read,
    parse_cloud_reply,
    parse_plan,
    parse_reply,
    plan_json,
    plan_schema,
    reading_read,
    reply_events,
    reply_json,
    reply_schema,
    sentences,
    spoken_reply,
    without_laughs,
    without_plans,
)
from kit.scene_context import SEEN, Happening, SceneContext, SceneReport
from kit.settings import ModelProfile, Settings, cloud_background, local_stands_in
from kit.shows import show_for
from kit.things import Register, named_in
from kit.thinking import THOUGHT_SCHEMA, THOUGHT_SHAPE, Thought, parse_thought, thinking_messages
from kit.tools import Context, Pack, Registry, Tool, ToolCall, ToolResult, definitions
from kit.tools.confirm import Held, ask_first, needs_yes, one_at_a_time, said_yes
from kit.tools.core import ACTION_ARGS, core_pack
from kit.tools.files import files_pack
from kit.tools.house import house_pack
from kit.tools.match import match
from kit.tools.mcp import App, write_contents
from kit.tools.notes import notes_pack
from kit.tools.pc import pc_pack
from kit.tools.private import for_cloud, lifted
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
# How it came (said aloud, written earlier, through which body), the same way.
ARRIVAL: contextvars.ContextVar[Arrival | None] = contextvars.ContextVar("arrival", default=None)
# Who sent it, when it wasn't Dan (kit.audience); empty for Dan.
SPEAKER: contextvars.ContextVar[str] = contextvars.ContextVar("speaker", default="")
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
# The turn's asides, for the record (the speaking step points back at them in one line
# rather than saying them again, kit.prompt.speak_note).
MIND: contextvars.ContextVar[str] = contextvars.ContextVar("mind", default="")
# What a cloud answer this turn is for, so a low budget skips the least needed first
# (kit.cloud.SKIP_ORDER): "moment" for a key moment (bad news) the work model answers.
PRIORITY: contextvars.ContextVar[str] = contextvars.ContextVar("priority", default="chat")
# How Dan seems, as the model answering this turn read it (``life.read_mood`` meaning).
READ: contextvars.ContextVar[dict | None] = contextvars.ContextVar("read", default=None)
# Which of the things on his mind this turn's plan says he's bringing up (by number), or
# None when there was no plan to say (then the words are matched, ``Notebook.said_in``).
BROUGHT_UP: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "brought_up", default=None
)
READ_ON: contextvars.ContextVar[bool] = contextvars.ContextVar("read_on", default=False)
# What Kit's ears heard, when the message came in out loud (kit.heard): tone, who.
HEARD: contextvars.ContextVar[Utterance | None] = contextvars.ContextVar("heard", default=None)
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
# Plainly about what Kit can see: he looks through the camera first and his own
# model answers (own_role), like a look at the PC.
SCENE_QUESTION = re.compile(
    r"\b(can you see( me| us| anything| the cat| the dog| what)?|what (can|do) you see|"
    r"what('?s| is| are) (in front of|around|near|behind) (you|me)|look around|"
    r"who('?s| is) (here|there|at the desk|with me|in the room|around)|"
    r"through (the|your) camera|(with|through) your eyes|"
    r"is (anyone|anybody|someone|the cat|the dog) (here|there|around|about|in view)|"
    r"what am i (wearing|holding|doing)|am i (wearing|holding)|(see|look at) (me|my face|"
    r"my shirt)|how do i look(?! (up|for|into|at|after|through))|what('?s| is) on (my|the) desk)\b",
    re.IGNORECASE,
)
SCENE_FOLLOW_UP = timedelta(minutes=10)
EYES_PAUSED = "eyes_paused"  # kit_self key: the "Let Kit see me" switch, kept over restarts
HEARING_PAUSED = "hearing_paused"  # kit_self key: the "Let Kit hear me" switch
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


@dataclass(frozen=True)
class Reading:
    """What Dan's message is, read twice: a guess from its words as it arrives (the
    regex tables above), then the model's own reading laid over it from its plan or a
    cloud reply (kit.reply.READING_FIELDS). Where the model gave a field, it decides;
    where it didn't (a small model forgot it, a one-pass reply), the words do."""

    intent: str = "chat"  # chat, question, request, goodbye, news
    about_kit: bool = False
    wants_pc_look: bool = False
    wants_camera_look: bool = False
    said_it: bool | None = None  # no guess from the words: that's per fact (said_so, named_in)
    crisis_candidate: bool | None = None
    self_q: bool = False  # the words alone: a question about Kit (SELF_Q)
    tag_question: bool = False  # the words alone: "..., isn't it?" (TAG_Q)
    candidate: str = ""  # a bad night in the words: "bad_night", "self_harm" or ""
    given: frozenset[str] = frozenset()  # the fields the model gave

    @classmethod
    def of(cls, text: str, candidate: str = "") -> Reading:
        """The words' guess, before any model has read the message."""
        if is_farewell(text):
            intent = "goodbye"
        elif is_news(text):
            intent = "news"
        elif "?" in text:
            intent = "question"
        else:
            intent = "chat"
        self_q = bool(SELF_Q.search(text))
        return cls(
            intent,
            about_kit=self_q,
            wants_pc_look=bool(PC_QUESTION.search(text)),
            wants_camera_look=bool(SCENE_QUESTION.search(text)),
            self_q=self_q,
            tag_question=bool(TAG_Q.search(text)),
            candidate=candidate,
        )

    def with_model(self, fields: dict) -> Reading:
        """The model's reading laid over the words' guess."""
        known = {k: v for k, v in fields.items() if k in READING_FIELDS and v is not None}
        return replace(self, **known, given=self.given | frozenset(known))

    @property
    def goodbye(self) -> bool:
        return self.intent == "goodbye"

    @property
    def news(self) -> bool:
        return self.intent == "news"

    def new_about_kit(self) -> bool:
        """The model read it as about Kit when the words hadn't: he's handed what's
        true about himself after the plan, not before."""
        return "about_kit" in self.given and self.about_kit and not self.self_q

    def remembers(self, fact: str, said: list[str], owner: str) -> bool:
        """Did Dan say the fact the model wants to remember? The model's ``said_it``,
        or failing that the words it shares with what Dan said (``said_so``)."""
        return bool(self.said_it) if "said_it" in self.given else said_so(fact, said, owner)

    def named(self, name: str, said: str) -> bool:
        """Did Dan name the thing the model wants in the register? ``said_it``, else
        ``named_in``."""
        return bool(self.said_it) if "said_it" in self.given else named_in(name, said)

    def asked_for_note(self, text: str) -> bool:
        """Did Dan ask for the note the model wants to write? A request, as the model
        read it, else the words (``asks_for_note``)."""
        return self.intent == "request" if "intent" in self.given else asks_for_note(text)

    def crisis(self, text: str) -> bool:
        """A really bad time: the words raised it (``candidate``) and the model agreed
        (``crisis_candidate``). With no reading from the model, the words alone count
        only when nothing in them says work, code or a game (``FIGURE_OF_SPEECH``)."""
        if not self.candidate:
            return False
        if "crisis_candidate" in self.given:
            return bool(self.crisis_candidate)
        return not FIGURE_OF_SPEECH.search(text)


# This turn's reading of Dan's message, for the steps after the model has read it.
READING: contextvars.ContextVar[Reading | None] = contextvars.ContextVar("reading", default=None)
# Dan said to keep this message local (kit.memory.KEEP_LOCAL, read once as it arrives).
PRIVATE: contextvars.ContextVar[bool] = contextvars.ContextVar("private", default=False)


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


@dataclass
class Turn:
    """One message's turn (``Brain._run_turn``), carried from reading it to what comes
    after it: what was read from the words, gathered beside it, recalled, decided
    about who answers, and said."""

    text: str
    settings: Settings
    owner: str
    now: datetime
    user_id: int
    history: list[Message]
    before: list[Message]  # what Dan is answering, if anything
    reading: Reading  # the words' reading; the model's is laid over it in READING
    private: bool  # Dan said to keep it local
    speaker: str = ""  # who said it: Dan, or someone else (kit.audience, kit.heard)
    heard: Utterance | None = None  # how it sounded, when it came in through his ears
    felt: tuple[str, str, float] | None = None
    home: Homecoming | None = None
    farewell: bool = False
    game: str | None = None  # a game he suggested, which this may answer
    quiet: bool = False  # a long quiet before it: he picks up one thing from last time
    lead: str = ""  # "(2 hours later) ", in front of the message for the model
    learn: list[str] = field(default_factory=list)
    asides: list[str] = field(default_factory=list)
    answer_aside: str = ""
    check_fact: bool = False
    picked: Item | None = None
    bit: Item | None = None
    expert_ask: str = ""
    declined: Reply | None = None
    recalled: Recalled | None = None
    showing: asyncio.Task | None = None
    forecasting: asyncio.Task | None = None
    noting: asyncio.Task | None = None
    role: str = LOCAL
    chosen: bool = False
    forecast: str = ""
    pc_detail: str = ""
    scene_detail: str = ""
    said: list[str] = field(default_factory=list)
    emotion: str = ""
    reply_id: int | None = None
    kinds: list[str | None] = field(default_factory=list)  # each aside's kind, for the budget
    fact_at: int = -1  # where the fact-check aside is, to fill in when the check is back
    voice: Voice | None = None
    source: str = LOCAL  # who answered: his own model, or the cloud

    def sent(self) -> list[str]:
        """The asides that ride with the message: at most two of the ranked ones
        (``kit.prompt.within_budget``), in their places."""
        return within_budget(self.asides, self.kinds) if self.kinds else self.asides

    @property
    def answering(self) -> str:
        return "\n\n".join(a for a in self.sent() if a)

    def mind(self) -> str:
        """The asides but the pipe-up he's answered (``MIND``)."""
        return "\n".join(a for a in self.sent()[1:] if a)


async def _replay(events: list[Event]) -> AsyncIterator[Event]:
    for event in events:
        yield event


def _message_meta(
    arrival: Arrival | None, speaker: str, owner: str, heard: Utterance | None = None
) -> str | None:
    """What's kept with the message: how it came (kit.channels.Arrival), who sent it
    when it wasn't Dan (kit.audience.speaker_meta) and how it sounded (kit.heard)."""
    meta = dict(arrival.meta()) if arrival and arrival.meta() else {}
    if who := speaker_meta(speaker, owner):
        meta.update(json.loads(who))
    meta.update(_heard_meta(heard, speaker, owner))
    return json.dumps(meta) if meta else None


def _asked(exchange: str) -> str:
    """What Dan said in an indexed exchange ("Dan: ...\nKit: ...")."""
    first = exchange.split("\n", 1)[0]
    return first.split(": ", 1)[-1]


def route(text: str, settings: Settings, private: bool | None = None) -> tuple[str, bool]:
    """Who answers first: (role, whether Dan chose it for this message). ``private``:
    whether Dan said to keep it local, if the caller has read that already."""
    if private is None:
        private = bool(KEEP_LOCAL.search(text))
    if private:
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


def looking_role(role: str, chosen: bool, settings: Settings) -> str:
    """Who answers a question about the PC or the room, with the full picture in the
    prompt: Kit's own role (the chat model in cloud-only), unless "keep it local" was
    said, which keeps every window title and face at home."""
    return LOCAL if chosen and role == LOCAL else own_role(settings)


def reads_ahead(settings: Settings) -> bool:
    """The local model reads the conversation in ahead of Dan's next message
    (``ollama.warm_up``), while it's the one answering him. In cloud-only routing it
    only stands in, and reading ahead would just load it onto the GPU for nothing."""
    return settings.ollama.warm_up and own_role(settings) == LOCAL


def _heard_meta(heard: Utterance | None, speaker: str, owner: str) -> dict:
    """What's kept with a message that came in out loud: how it sounded, and who
    said it when that wasn't Dan (the history marks their lines)."""
    if heard is None:
        return {}
    meta: dict = {"heard": {k: v for k, v in (("tone", heard.tone), ("sound", heard.sound)) if v}}
    if speaker != owner:
        meta["speaker"] = speaker
    return meta


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
        self.bodies = BodyRegistry(memory.clock)  # the desk apps, the phone, the Pod...
        self.scene = SceneContext(memory.clock)
        self.hearing = Hearing(memory.clock)  # his ears, and his voice in the room
        self.heard_turns = HeardTurns()  # replies to what he heard, for bodies to read
        self._hearing_tasks: set[asyncio.Task] = set()
        self.life = Life(settings, self.pc, memory.clock, store=memory, scene=self.scene)
        # Opening things on the PC through the desk app (kit.desk_commands), and Dan's
        # code projects (kit.projects).
        self.desk = DeskCommands(self.life, self.pc)
        self.projects = Projects(lambda: self.settings().projects.roots)
        self.notebook = Notebook(memory)
        self.notebook.swap_work_quirks(settings().persona.owner)
        self.notebook.drop_slang(settings().persona.owner)
        self.notebook.keep_own_name(settings().persona.owner, settings().persona.name)
        self.notebook.drop_written_laughs(settings().persona.owner)
        self.daily = Daily(memory, self.notebook, self.life, settings)
        self.reflector = Reflector(memory, self.notebook, model, cloud, settings)
        self.weather = weather
        self._weather_at: datetime | None = None  # when Kit last looked at a forecast
        self._pc_at: datetime | None = None  # when Kit last looked at the PC for Dan
        self._scene_at: datetime | None = None  # when Kit last looked around for Dan
        self.learner = Learner(memory, recall, model, asking(cloud, settings))
        # His thoughts in the cloud (routing.background chat): the chat model, giving way
        # first as the month's budget runs low.
        self._ask_life = asking(cloud, settings, CHAT, priority="life")
        self._local_freed = False  # the local model was taken off the GPU for the voice
        self.register = Register(memory)
        self.notes = Notes(memory.index, memory.clock)
        # Dan's folders in the index (kit.files); the server sets it up with the data folder.
        self.files: Files | None = None
        # The house through Home Assistant (kit.house): set by use_house once
        # house.enabled is on with a token; None means Kit has no house.
        self.house: House | None = None
        self.house_watch: Watcher | None = None
        self.apps: dict[str, App] = {}  # Dan's apps' MCP servers, each a pack (kit.tools.mcp)
        self._apps_read: date | None = None
        # The morning brief (kit.brief): once a day, at the desk or in his first answer.
        self.brief = Brief(memory, settings, sources_for(self))
        # The tools a model may call mid-answer (kit.tools) and what there is to look
        # at this turn, set at the start of every turn.
        self.tool_context = Context()
        self.tools = Registry()
        self.tools.add(core_pack(self))
        self.tools.add(files_pack(self))
        self.tools.add(pc_pack(self))
        self.tools.add(notes_pack(self))
        self.current_text = ""  # the message being answered, for tools that read it
        # The packs this turn loaded (kit.tools.match), and a call waiting for a yes.
        self.loaded_packs: list[str] = [p.name for p in self.tools.packs.values() if p.always]
        self.pending_tool: Held | None = None
        self._ran_held: tuple[str, str] | None = None  # the call a yes just ran
        self.pending_thing: int | None = None
        self._notes_tidied: date | None = None  # the Sunday the notes were last looked over
        self.pending_note: tuple[str, str] | None = None  # (title, text) Kit offered to note
        self.pending_expert = ""  # the question Kit asked to hand to the expert model
        self.jobs: dict[int, Job] = {}
        self._job_ids = itertools.count(1)
        self._turns: set[asyncio.Task] = set()
        self._learning: set[asyncio.Task] = set()  # learning after a reply is out
        # His latest pipe-up and why he said it, for when Dan answers it ("what's up?").
        self._pipe_up: tuple[int, str] | None = None
        # (his message, the thread or getting-to-know-you want it asked about), so Dan's
        # answer is kept with it: how the dentist went, or the cat's name.
        self._asked: tuple[int, int] | None = None
        self._bit_out: tuple[int, datetime] | None = None  # a running joke he just used
        readers = Readers(self._read_weather, self._read_journal, self._read_thing, self._music)
        self.pastimes = Pastimes(readers, memory.clock, memory, self.life.rng)
        self._musing: asyncio.Task | None = None  # a thought while alone; a chat stops it
        # Seconds since his voice was last being made (kit.speech; the server sets it).
        self.voice_quiet: Callable[[], float] = lambda: float("inf")
        self._warm_task: asyncio.Task | None = None
        self._warming = False  # reading ahead right now
        self._channel = CHANNEL.get()  # where Dan last talked from

    @property
    def quirks(self) -> list[str]:
        """The quirks Kit picked for himself; the nightly reflection may change one."""
        return self.notebook.quirks()

    def voice_body(self) -> str | None:
        """Which body should say a pipe-up out loud (kit.body_registry.speaker)."""
        snap = self.pc.latest if self.pc.online() else None
        in_use = snap is not None and not away_on(snap)
        return self.bodies.speaker(self.pc.host(), in_use)

    def room(self) -> dict[str, tuple[float, float]]:
        """Who Kit's eyes see in the room by name (people and pets), and where."""
        pets = [
            (t.name, " ".join([t.about, *t.aliases]))
            for t in self.register.all()
            if t.kind == "pet"
        ]
        return self.scene.present(pets_by_kind(pets))

    def _speaker(self, speaker: str | None, channel: str) -> str:
        owner = self.settings().persona.owner
        if speaker and speaker.strip():
            name = speaker.strip()
            return "" if name.lower() == owner.lower() else name
        if aloud(channel):  # nobody said: the one person in the room Kit knows
            people = list(self.scene.present(animals=False))
            if len(people) == 1 and not self.scene.strangers() and people[0] != owner:
                return people[0]
        return ""

    def _channel_line(self, owner: str) -> str:
        """Where the message came from, who can hear Kit, and who sent it."""
        channel = CHANNEL.get()
        room = self.room()
        speaker = "" if HEARD.get() is not None else SPEAKER.get()  # heard: an aside says
        heard = audience_line(channel, owner, speaker, room, self.scene.strangers())
        came = channel_line(channel, owner, ARRIVAL.get(), self.memory.clock())
        return f"{came} {heard}"

    def talking(self) -> bool:
        """A chat turn is under way."""
        return bool(self._turns)

    async def chat(
        self,
        text: str,
        channel: str | None = None,
        *,
        sent_at: datetime | None = None,
        spoken: bool = False,
        body: str | None = None,
        speaker: str | None = None,
        heard: Utterance | None = None,
    ) -> AsyncIterator[Event]:
        """One message's events, as they happen. The turn runs as its own task, so
        other messages can be answered meanwhile, and it finishes (and is saved)
        even if whoever asked stops listening. ``sent_at`` is when it was written if
        it waited to be sent, ``spoken`` that it was said aloud, ``body`` which of
        Kit's bodies it came through (kit.body_registry) and ``heard`` how it
        sounded, when it came in through Kit's ears (kit.heard). ``speaker`` is who
        sent it, when that isn't Dan; otherwise the voice his ears know, or out loud
        with nobody named, the one person Kit's eyes know in the room."""
        text = text.strip()
        if not text:
            return
        if self._musing is not None and not self._musing.done():
            self._musing.cancel()  # Dan's here: his thought can wait
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        context = contextvars.copy_context()
        context.run(CHANNEL.set, known(channel))
        if sent_at is not None or spoken or body:
            context.run(ARRIVAL.set, Arrival(spoken=spoken, sent_at=sent_at, body=body))
        who = speaker or (heard.who if heard is not None else None)
        context.run(SPEAKER.set, self._speaker(who, known(channel)))
        context.run(HEARD.set, heard)
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
        """One message, in five steps: read it (how it lands, what it is, the asides),
        recall (memory, the forecast, the fact check, a note request, all at once),
        route (who answers, a look first if it's about the PC or the room), converse
        (the model's plan and words, streamed out), and afterwards (what the reading
        changed: feelings, a bad night the model confirmed, what was said and learned)."""
        turn = await self._read(text, emit)
        answered = await self._answer_tool_offer(turn, emit)
        if answered is None:
            answered = self._quick_answer(turn)
        if answered is not None:
            for event in self._say_locally(answered):
                emit(event)
            self.memory.index_exchange(
                turn.user_id,
                turn.speaker,
                text,
                turn.settings.persona.name,
                answered.text,
                private=turn.private,
            )
            return
        await self._recall(turn)
        await self._route(turn, emit)
        await self._converse_turn(turn, emit)
        self._afterwards(turn)

    async def _read(self, text: str, emit: Callable[[Event], None]) -> Turn:
        """How the message lands, before any model sees it: it goes in the log (with
        whether Dan kept it local), the words give a first reading of it (a goodbye,
        news, about Kit, a bad-night candidate) and a feeling with a reason, a quick
        reaction goes to the face, and the asides beside it are gathered. A long quiet
        or a change of subject is a hint in the prompt, not a cut to the conversation."""
        settings = self.settings()
        self._channel = CHANNEL.get()
        owner = settings.persona.owner
        before = self.memory.recent(1)  # what Dan is answering, if anything
        quiet = self._long_quiet(settings)
        history = self.memory.recent(settings.brain.history_messages)
        new_subject = await self._new_topic(text, history, settings)
        if new_subject:
            emit({"type": "new_topic"})
        arrival = ARRIVAL.get()
        heard = HEARD.get()
        speaker = SPEAKER.get() or owner  # who said it (kit.audience, kit.heard)
        private = bool(KEEP_LOCAL.search(text))  # read once; the flag goes with the message
        PRIVATE.set(private)
        user_id = self.memory.add_message(
            "user",
            text,
            channel=CHANNEL.get(),
            meta_json=_message_meta(arrival, speaker, owner, heard),
            private=private,
        )
        now = self.memory.clock()
        READ.set(None)
        BROUGHT_UP.set(None)
        READ_ON.set(self._reading_mood(settings))
        candidate = bad_night_in(text) if settings.life.bad_night else ""
        reading = Reading.of(text, candidate)
        READING.set(reading)
        turn = Turn(text, settings, owner, now, user_id, history, before, reading, private)
        turn.speaker, turn.heard = speaker, heard
        turn.game = self.life.game_out  # a game he suggested, which this may answer
        turn.quiet = quiet
        if history:
            turn.lead = later_note(history[-1].at, now.isoformat(timespec="seconds"))
        felt = feeling_from(text, speaker)
        if felt is not None:
            self.life.feel(*felt, show=False)
        home = self.life.homecoming_for_chat()  # a hello he still owes Dan
        if home is not None and home.miffed and felt is not None and felt[0] in SOFT_NEWS:
            home = replace(home, miffed=False)  # no huffing at bad news
            self.life.feel(*felt, show=False, force=True)
        farewell = reading.goodbye
        if FAREWELL.search(text):
            self.life.said_goodbye(text)
        self._react(felt, home, farewell)
        turn.felt, turn.home, turn.farewell = felt, home, farewell
        # "Emma's my cousin", from Dan (someone else's cousin isn't his).
        turn.learn = relations_in(text, owner) if "?" not in text and speaker == owner else []
        turn.answer_aside, named = self._answering_ask(text, before, owner, private)
        turn.learn += [named] if named else []
        self._follow_life(text, now, settings, farewell, private)
        self._gather_asides(turn, new_subject)
        if THINKING_Q.search(text) and (shared := self.notebook.latest_thought()):
            self.notebook.mark_said(shared.id)
        # Before note_chat: how Kit felt till now. The hello says how long Dan was gone.
        voice = turn.voice = self._voice(settings, history, text, home=home is not None)
        turn.bit = self._bit_for(text, now, felt, farewell)
        VOICE.set(replace(voice, bit=turn.bit.text) if turn.bit is not None else voice)
        self.life.note_chat(text)
        return turn

    def _gather_asides(self, turn: Turn, new_subject: bool) -> None:
        """The notes beside Dan's message: what he's answering (a pipe-up, a question Kit
        asked), a hello owed or one thing from last time, a bedtime nudge, a goodbye, a
        question about Kit himself, a claim to check, news to take in, a yes to the
        expert, a bad night (confirmed earlier) or words that could mean one."""
        text, owner, now, settings = turn.text, turn.owner, turn.now, turn.settings
        reading, farewell = turn.reading, turn.farewell
        # Each aside with its kind, for the budget (kit.prompt.within_budget): at most
        # two ride with a message, the best-ranked ones; None is always sent.
        asides = [self._answering(turn.history, owner), turn.answer_aside]
        kinds: list[str | None] = ["pipe_up", "interview"]
        if turn.heard is not None:
            self._heard_asides(turn, asides, kinds)
        pick_up = ""
        if turn.quiet and settings.life.chat_opener and not farewell and not self.jobs:
            pick_up, turn.picked = self._pick_up(turn.history, now, owner)
        if turn.home is not None:
            asides.append(homecoming_aside(turn.home, owner, now, pick_up))
            kinds.append("homecoming")
        elif pick_up:
            asides.append(opener_aside(owner, pick_up))
            kinds.append("opener")
        if turn.picked is not None:
            log.info("a new chat picks up %r", turn.picked.text)
        if new_subject:
            asides.append(new_subject_note(owner))
            kinds.append("new_subject")
        self._brief_asides(turn, asides, kinds)
        bedtime = next(
            (w for w in self.notebook.open_wants() if w.meta.get("nudge") == "sleep"), None
        )
        if bedtime is not None:
            self.notebook.mark_said(bedtime.id)  # once, said or not
            if not farewell:
                asides.append(bedtime_aside(owner, now))
                kinds.append("bedtime")
        if farewell:
            asides.append(farewell_aside(text, owner))
            kinds.append(None)
            LINT.set(Lint(farewell_fault, farewell_line(text, self.life.rng)))
        elif reading.about_kit and not self.jobs:
            asides.append(self._about_me(owner))
            kinds.append(None)
        elif reading.tag_question:
            # Not when Dan said to keep it local: that never leaves the house.
            turn.check_fact = settings.routing.check_facts and route(
                text, settings, turn.private
            ) == (LOCAL, False)
            asides.append(wrong_fact_aside(owner))
            kinds.append(None)
            turn.fact_at = len(asides) - 1
        elif reading.news and not turn.answer_aside:
            asides.append(news_aside(owner))
            kinds.append("news")
        turn.expert_ask, turn.declined = self._answer_expert_offer(text)
        if turn.expert_ask:
            asides.append(expert_yes_aside(owner, turn.expert_ask))
            kinds.append(None)
        if self.life.bad_night() and (reading.candidate or not self.life.bad_night_met):
            # No cheek, he stays with it; once, someone to talk to.
            name_help = not self.life.bad_night_named
            self_harm = reading.candidate == "self_harm"
            asides.append(bad_night_aside(owner, self_harm, self._someone(), name_help))
            kinds.append("bad_night")
            if name_help or self_harm:
                self.life.named_help()
            self.life.met_bad_night()
        elif self.life.bad_night():  # he's met it already: he follows Dan's lead now
            asides.append(bad_night_after_aside(owner))
            kinds.append("bad_night")
        elif reading.candidate:  # words that could mean one: the model reads which
            self_harm = reading.candidate == "self_harm"
            asides.append(crisis_check_aside(owner, self_harm, self._someone()))
            kinds.append(None)  # what the message may be about: always sent
        turn.asides, turn.kinds = asides, kinds
        MIND.set(turn.mind())

    def _brief_asides(self, turn: Turn, asides: list[str], kinds: list[str | None]) -> None:
        """The morning brief beside Dan's first message of the morning (brief.in_reply),
        once; or, later that day, what was in it when he asks about "the second one"."""
        now, owner = turn.now, turn.owner
        given = self.brief.today(now)
        if given:
            if FOLLOW_UP.search(turn.text):
                asides.append(follow_up_aside(owner, given, asked_about(turn.text, given)))
                kinds.append(None)  # what the message is about
            return
        parts = self.brief.ready(now)
        if not parts or not turn.settings.brief.in_reply or turn.farewell:
            return
        asides.append(brief_aside(owner, parts))
        kinds.append("brief")
        self.brief.mark_given(now, "reply")  # once, said or not, like the bedtime nudge
        self.life.brief_ready = False

    def _quick_answer(self, turn: Turn) -> Reply | None:
        """An answer that needs no model: a no to the expert, a yes or no to a note or
        a thing Kit offered, a shush."""
        text = turn.text
        return (
            turn.declined
            or self._answer_note_offer(text, turn.settings)
            or self._answer_suggestion(text)
            or self._answer_shush(text)
        )

    async def _recall(self, turn: Turn) -> None:
        """What he looks up while he thinks, all at once: what his face shows, the fact
        check, the forecast for a weather question, a plain note request, and memory."""
        text, settings, owner = turn.text, turn.settings, turn.owner
        # What his face shows (the time, the weather), looked up while he thinks.
        turn.showing = asyncio.create_task(self._show_for(text, settings))
        recent_refs = {str(m.id) for m in turn.history if m.role == "user"}
        # The check runs while he recalls, so it costs next to no time.
        checking = (
            asyncio.create_task(self._check_fact(text, settings)) if turn.check_fact else None
        )
        turn.role, turn.chosen = route(text, settings, turn.private)
        # A weather question: the forecast is fetched while he recalls, not after.
        if turn.role == LOCAL and self.weather is not None:
            plainly = bool(WEATHER.search(text))
            if plainly or (WHEN.search(text) and self._weather_recently()):
                turn.forecasting = asyncio.create_task(self._home_forecast(settings))
        # The plain note request is spotted in a thread: a big vault is real work.
        if settings.nas.vault:
            turn.noting = asyncio.create_task(asyncio.to_thread(self._note_request, text))
        recalled = await self.recall.for_turn(text, recent_refs)
        if checking is not None and (checked := await checking):
            turn.asides[turn.fact_at] = wrong_fact_aside(owner, checked)
            MIND.set(turn.mind())
        # "hey" finds every earlier "hey", and the model copies what it said then.
        fresh = [h for h in recalled.conversation if not same_words(_asked(h.item.text), text)]
        # His notes already on his mind (kit.notebook) are in the prompt once, not twice.
        shown = {e.id for e in self.notebook.on_mind()}
        own = [h for h in recalled.own if h.item.id not in shown]
        turn.recalled = replace(recalled, conversation=fresh, own=own)

    async def _route(self, turn: Turn, emit: Callable[[Event], None]) -> None:
        """Who answers, and what he looks at first: the expert Dan said yes to, his own
        model while a cloud job runs or for a goodbye or his own thoughts, the work model
        at a key moment; a look at the PC or the room when the message is plainly about
        it, the forecast, and a note request already carried out."""
        text, settings, history = turn.text, turn.settings, turn.history
        role, chosen = turn.role, turn.chosen
        if turn.expert_ask:
            role, chosen = EXPERT, True  # Dan said yes to the expert
        if self.jobs and not chosen:
            role = own_role(settings)  # busy: chat locally (or with the chat model) meanwhile
        if self._key_moment(turn.felt, settings, role, chosen, turn.farewell):
            role = WORK  # bad news: the work model answers, as Kit
            PRIORITY.set("moment")
        if role == own_role(settings) and THINKING_Q.search(text):
            chosen = True  # his own thoughts: nobody else can answer that
        if turn.farewell and not chosen:
            role, chosen = own_role(settings), True  # a goodbye is his own to say
        if role not in (LOCAL, CHAT) and chosen:
            name = settings.profile(role).name
            for event in self._say_locally(Reply.plain(f"Sure, asking {name}.", "thinking", "nod")):
                emit(event)
        asked_cloud = chosen and role not in (LOCAL, CHAT)
        again = AGAIN.search(text)
        about_pc = turn.reading.wants_pc_look or (again and self._pc_recently())
        if self.pc.latest is not None and about_pc and not asked_cloud:
            self._pc_at = self.memory.clock()
            role, chosen = looking_role(role, chosen, settings), True
            turn.pc_detail = self.pc.detail(turn.owner)
            emit({"type": "looked_at_pc", "online": self.pc.online()})
        about_scene = turn.reading.wants_camera_look or (again and self._scene_recently())
        if self.scene.latest is not None and about_scene and not turn.pc_detail and not asked_cloud:
            self._scene_at = self.memory.clock()
            role, chosen = looking_role(role, chosen, settings), True
            turn.scene_detail = self.scene.detail(turn.owner)
            emit({"type": "looked_around", "in_view": self.scene.in_view()})
        if turn.forecasting is not None and role != LOCAL:
            turn.forecasting.cancel()  # bad news or a cloud job: the weather can wait
        elif turn.forecasting is not None:
            turn.forecast = await turn.forecasting
            self._weather_at = self.memory.clock()
            emit({"type": "weather", "place": settings.persona.location})
            chosen = chosen or bool(WEATHER.search(text))  # a weather question stays local
        if turn.noting is not None and (asked := await turn.noting) is not None:
            done, events = await asyncio.to_thread(self._do_note, asked, settings)
            NOTE_DONE.set(done)
            for event in events:
                emit(event)
        if role != LOCAL and turn.asides[0] and history[-1].id in self.memory.private_said():
            turn.asides[0] = ""  # he piped up about something Dan kept local
        turn.role, turn.chosen = role, chosen

    async def _converse_turn(self, turn: Turn, emit: Callable[[Event], None]) -> None:
        """The model answers, as Kit: its events stream out as they come, and what his
        face shows (looked up meanwhile) goes out as soon as it's ready."""
        await asyncio.sleep(0)  # the time and date are ready at once; the weather may be
        shown = turn.showing.done()
        if shown:
            self._emit_show(turn.showing, emit)
        async for event in self._converse(
            turn.text,
            turn.history,
            turn.recalled,
            turn.settings,
            turn.role,
            turn.chosen,
            forecast=turn.forecast,
            pc_detail=turn.pc_detail,
            answering=turn.answering,
            scene_detail=turn.scene_detail,
            lead=turn.lead,
        ):
            if event["type"] == "reply":
                turn.emotion, turn.reply_id = event["reply"]["emotion"], event["message_id"]
                turn.source = str(event.get("source", LOCAL))
                if self.jobs:
                    event = {**event, "question": turn.text}
            emit(self._track(event, turn.said))
        if not shown:  # still looking it up when he started, maybe done since
            if not turn.showing.done():
                await asyncio.wait({turn.showing}, timeout=SHOW_WAIT_S)
            self._emit_show(turn.showing, emit)

    def _afterwards(self, turn: Turn) -> None:
        """Once the reply is out: what the model's reading of Dan changes (his feeling,
        a bad night it confirmed), how Kit felt answering, a weather bet, what he brought
        up himself, and the exchange indexed and anything learned, in the background."""
        text, owner, settings, felt = turn.text, turn.owner, turn.settings, turn.felt
        reading = READING.get() or turn.reading  # with the model's reading laid over
        read = READ.get()
        from_read = feeling_from_read(read, text, owner) if read else None
        if from_read is not None:  # the model's reading takes over from the words
            other = felt is not None and felt[0] != from_read[0]
            self.life.feel(*from_read, show=False, force=other)
        why = f'{owner} said "{quoted(text)}"'
        if reading.crisis(text):  # the words raised it, and the model agreed
            self.life.start_bad_night(why)
            self.life.named_help()  # the aside beside the words named someone to talk to
            self.life.met_bad_night()  # and his answer met it
        elif read and read.get("dan_mood") == "awful" and settings.life.bad_night:
            self.life.start_bad_night(why)
        if turn.emotion in REPLY_FEELINGS and felt is None and from_read is None:
            # How he felt answering lingers a little: "sad" about Dan's news stays.
            self.life.feel(REPLY_FEELINGS[turn.emotion], why, 0.4)
        if turn.said:
            whole = " ".join(turn.said)
            before = turn.before
            if turn.game == "weather_bet":
                pipe_up = before[-1].text if before and before[-1].role != "user" else ""
                self._place_bet(text, f"{pipe_up} {whole}")
            if turn.picked is not None:  # the thread the new chat picked up: asked, once
                self.notebook.mark_said(turn.picked.id)
                self._asked_in([turn.picked.id], turn.reply_id)
            # What he brought up himself: the plan says which (by number), or failing a
            # plan (a cloud answer, one JSON pass), his words are matched to the wants.
            self._asked_in(self._brought_up(whole, owner, turn.voice, turn.source), turn.reply_id)
            if turn.bit is not None and self.notebook.bit_said(turn.bit, whole):
                self.notebook.bit_used(turn.bit.id)
                self._bit_out = (turn.bit.id, turn.now)
            self.memory.index_exchange(
                turn.user_id, turn.speaker, text, settings.persona.name, whole, private=turn.private
            )
        if turn.said or turn.learn:  # the reply is out; learning needn't hold it up
            facts = [(fact, "person") for fact in turn.learn]
            self._learn_later(facts, owner, turn.private, settings)

    def _learn_later(
        self, facts: list[tuple[str, str]], owner: str, private: bool, settings: Settings
    ) -> asyncio.Task:
        """Learn ``facts`` ((text, kind)) and embed what's new after the reply is out, as
        a tracked background task (``close`` stops it): a "remember that" never holds
        the chat up for the embedding model or a comparison, and in cloud-only routing
        the local model isn't loaded for one. What was learned goes to the bodies as a
        ``remembered`` event; anything that goes wrong is logged."""
        task = asyncio.create_task(self._learn_now(facts, owner, private, settings))
        self._learning.add(task)
        task.add_done_callback(self._learning.discard)
        return task

    async def _learn_now(
        self, facts: list[tuple[str, str]], owner: str, private: bool, settings: Settings
    ) -> None:
        try:
            for text, kind in facts:
                learned = await self.learner.learn(
                    text,
                    kind,
                    owner,
                    private=private,
                    cloud=cloud_background(settings),
                    local=not local_stands_in(settings),
                )
                self.life.publish(
                    {
                        "type": "remembered",
                        "fact": learned.text,
                        "decision": learned.decision,
                        "replaced": learned.replaced,
                    }
                )
            await self.recall.index_pending()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("learning after the reply failed")

    def learning(self) -> bool:
        """Still learning or embedding something from a finished turn."""
        return any(not t.done() for t in self._learning)

    async def settle(self) -> None:
        """Wait for the learning that follows replies to finish (tests, the terminal)."""
        while self._learning:
            await asyncio.gather(*list(self._learning), return_exceptions=True)

    async def close(self) -> None:
        """Shutting down: stop the learning that runs after replies, cleanly."""
        for task in list(self._learning):
            task.cancel()
        await asyncio.gather(*list(self._learning), return_exceptions=True)

    def _answering_ask(
        self, text: str, before: list[Message], owner: str, private: bool = False
    ) -> tuple[str, str]:
        """Dan answering a thread or a getting-to-know-you question Kit just asked: how
        it went is kept with the thread (unless Dan kept it local, ``private``), and a
        name ("Milo") is a fact to learn. Returns (an aside for the reply, the fact, or "")."""
        asked, self._asked = self._asked, None
        if asked is None or not before or before[-1].id != asked[0]:
            return "", ""
        item = self.memory.index.get(asked[1])
        if item is None:
            return "", ""
        if item.kind == "thread":
            if not private:
                self.notebook.thread_outcome(item.id, text)
            return "", ""
        key = str(item.meta.get("interview") or "")
        if not key:
            return "", ""
        return interview_aside(owner, self.daily.question(item)), self.daily.name_answer(key, text)

    def _brought_up(self, said: str, owner: str, voice: Voice, source: str = LOCAL) -> list[int]:
        """The wants his reply brought up, now said: as the plan declared (numbers into
        ``voice.mind``), so a want asked in other words counts. The words are matched
        too (``Notebook.said_in``) as a backstop, and alone when there was no plan to
        say (a cloud answer, a one-pass reply)."""
        numbers = BROUGHT_UP.get()
        done = []
        if numbers is not None and source == LOCAL:
            done = self.notebook.brought_up(numbers, voice.mind_ids)
        return done + [i for i in self.notebook.said_in(said, owner) if i not in done]

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

    def _follow_life(
        self, text: str, now: datetime, settings: Settings, farewell: bool, private: bool = False
    ) -> None:
        """What Dan said about his life, for Kit to follow up: "ask me this arvo how it
        went" is a want for then; "dentist Thursday arvo" a thread, to ask how it went
        once it's over; "dentist was fine" closes that thread before he asks. What Dan
        keeps local (``private``) is never kept with a thread or started as one, since
        threads go in the nightly reflection, which may be a cloud model's."""
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
            and not m.private
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
        """A clearly new subject: the chat so far isn't what this is about (the model
        kept bringing up the API key testing), so a note says so beside the message
        (``new_subject_note``); the conversation itself is kept. Judged by meaning,
        against Dan's last few messages, with the embedder recall already uses."""
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

    def _long_quiet(self, settings: Settings) -> bool:
        """Back after a long quiet (``brain.new_chat_after_minutes``): he picks up one
        thing from last time, as a new chat does. The conversation isn't cut (a reset
        after dinner made him forget what you were just doing): the gap is a hint in the
        prompt, "(3 hours later)" in front of the message, and the model reads on from
        there. `kit new-chat` still starts fresh by hand."""
        after = settings.brain.new_chat_after_minutes
        last = self.memory.recent(1)
        if not after or not last:
            return False
        return self.memory.clock() - datetime.fromisoformat(last[-1].at) >= timedelta(minutes=after)

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

    def _scene_recently(self) -> bool:
        return self._scene_at is not None and self.memory.clock() - self._scene_at < SCENE_FOLLOW_UP

    def _weather_recently(self) -> bool:
        return (
            self._weather_at is not None
            and self.memory.clock() - self._weather_at < WEATHER_FOLLOW_UP
        )

    async def _home_forecast(self, settings: Settings) -> str:
        place = settings.persona.location
        try:
            return await self.weather.forecast(place, settings.persona.country)
        except WeatherError as e:
            return f"The forecast lookup for {place or 'home'} failed: {e}"

    def _user_turn(
        self,
        text: str,
        role: str,
        settings: Settings,
        pc_detail: str,
        answering: str = "",
        scene_detail: str = "",
        lead: str = "",
    ) -> str:
        """Dan's message as the model sees it: ``lead`` ("(2 hours later) ") in front,
        and beside it his thoughts if asked for them, the background work, a fresh look
        at the PC or the room, and the turn's asides (``answering``)."""
        owner = settings.persona.owner
        text = lead + text
        if THINKING_Q.search(text) and not pc_detail and not scene_detail:
            text = with_mind(text, self.notebook.mind(owner, shared=role != LOCAL), owner)
        text = self._with_busy_note(text, role)
        text = with_pc_look(text, pc_detail, owner) if pc_detail else text
        text = with_scene_look(text, scene_detail, owner) if scene_detail else text
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

    def _heard_asides(self, turn: Turn, asides: list[str], kinds: list[str | None]) -> None:
        """A message that came in out loud: who said it (someone else in the house, by
        their voice) and how it sounded, which he may ask about but never states.
        A tone gives a light feeling, when the words gave none."""
        heard, speaker, owner = turn.heard, turn.speaker, turn.owner
        if heard is None:
            return
        if speaker != owner:
            asides.append(speaker_aside(speaker, owner))
            kinds.append(None)  # who it's from is what the message is about
        if not turn.settings.hearing.tone or not heard.tone:
            return
        if aside := tone_aside(speaker, heard.tone):
            asides.append(aside)
            kinds.append("tone")
        if turn.felt is None and heard.tone in TONE_FEELINGS:
            name, strength = TONE_FEELINGS[heard.tone]
            self.life.feel(name, f"{speaker}'s voice sounded {heard.tone}", strength, show=False)

    # Kit's ears (kit.hearing beside the mic; kit.heard decides what it means)

    async def hear(self, heard: Utterance) -> dict:
        """Something Kit's ears heard. Talk meant for him starts a chat turn on the
        voice channel straight away; bodies read it from ``heard_turns`` (the
        "heard" event says which) and say it aloud. A laugh at his last line makes
        him chuffed. Anything else is let go: not kept, not logged."""
        settings = self.settings()
        owner = settings.persona.owner
        verdict = self.hearing.decide(heard, settings.hearing)
        who = heard.who or owner
        if verdict.laughed:
            self.life.laughed(who, self.hearing.last_line())
        if verdict.action != "answer":
            return {"heard": verdict.action, "why": verdict.why}
        if verdict.called:
            self.life.called("heard his name")
        log.info("heard: %s (%s)", verdict.why, who)
        turn = self.heard_turns.start()
        self.life.publish({"type": "heard", "turn": turn, "text": heard.text.strip(), "who": who})
        task = asyncio.create_task(self._heard_turn(turn, heard))
        self._hearing_tasks.add(task)
        task.add_done_callback(self._hearing_tasks.discard)
        return {"heard": "answer", "why": verdict.why, "turn": turn}

    async def _heard_turn(self, turn: int, heard: Utterance) -> None:
        try:
            async for event in self.chat(heard.text, "voice", heard=heard):
                self.heard_turns.add(turn, event)
        except Exception:
            log.exception("a heard turn failed")
            self.heard_turns.add(turn, {"type": "error", "message": "Sorry, say again?"})
        finally:
            self.heard_turns.finish(turn)
            self.hearing.answered()

    def hush(self) -> bool:
        """Someone talked over Kit (``hearing.barge_in``): bodies stop his voice now.
        True if he was talking."""
        if not (self.hearing.speaking() or self.talking()):
            return False
        self.hearing.hushed()
        self.life.publish({"type": "hush"})
        return True

    @property
    def hearing_paused(self) -> bool:
        """The "Let Kit hear me" switch: off means the ears let the mic go."""
        return self.memory.self_value(HEARING_PAUSED) == "1"

    def pause_hearing(self, paused: bool) -> None:
        self.memory.set_self_value(HEARING_PAUSED, "1" if paused else "0")

    def saw(self, report: SceneReport) -> list[Happening]:
        """A report from Kit's eyes (kit.eyes): the scene is updated, his life hears
        what happened (someone arrived or left, the cat wandered in), and the
        happenings worth remembering go in the index under ``seen``."""
        happenings = self.scene.update(report)
        self.life.on_scene(happenings)
        when = self.memory.clock()
        for h in happenings:
            if h.remember:
                text = f"{when:%A %d %B %Y, %I:%M %p}: {h.text}"
                self.memory.index.add(SEEN, h.kind, text, meta={"camera": report.camera})
        return happenings

    @property
    def eyes_paused(self) -> bool:
        """The "Let Kit see me" switch: off means the eyes release the camera."""
        return self.memory.self_value(EYES_PAUSED) == "1"

    def pause_eyes(self, paused: bool) -> None:
        self.memory.set_self_value(EYES_PAUSED, "1" if paused else "0")

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

    async def _answer_tool_offer(self, turn: Turn, emit: Callable[[Event], None]) -> Reply | None:
        """Kit asked whether to do something (a held ``change`` call, kit.tools.confirm):
        a yes runs it and he says what happened, in his own words, from its result; a
        no leaves it; anything else, or a long wait, lets it lapse."""
        held, self.pending_tool = self.pending_tool, None
        self._ran_held = None
        if held is None:
            return None
        settings, text = turn.settings, turn.text
        if held.lapsed(self.memory.clock(), settings.tools.confirm_lapse_minutes):
            return None
        if NO.fullmatch(text):
            return Reply.plain("Okay, I'll leave it.", "neutral", "nod")
        if not YES.fullmatch(text):
            return None
        call = held.call
        emit({"type": "tool", "tool": call.name, "line": call.line()})
        result = await self.tools.run(call)
        tool = self.tools.get(call.name)
        self.memory.log_tool_call(
            turn.user_id,
            call.name,
            call.arguments,
            tool.effect if tool else "change",
            result.text,
            result.ok,
            held.role,
        )
        if result.event:
            emit(result.event)
        if not result.ok:
            reason = result.text.rstrip(".")
            return Reply.plain(f"I couldn't: {reason}.", "concerned", "droop")
        self._ran_held = (call.name, json.dumps(call.arguments, sort_keys=True))
        text = result.text if not result.private else ""
        turn.asides.append(f"{said_yes(turn.owner, call.line())}\n{text}".rstrip())
        turn.kinds.append(None)
        MIND.set(turn.mind())
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
            return Reply.plain("Okay, zipping it for an hour.", "shy", "nod")
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
        brief = self.brief.for_desk(self.memory.clock()) if reason == "brief" else []
        if reason == "brief" and not brief:
            self.life.brief_ready = False
            return  # given meanwhile, in an answer, or the morning's over
        history = self.memory.recent(settings.brain.history_messages)
        share = self.notebook.to_share() if reason in SHARES else None
        if reason == "want" and share is None:
            reason = "bored"  # it was dropped meanwhile; he's still restless
        aim, about = "", share.text if share else ""
        if reason == "visitor":
            if self.life.visitor is None:
                return  # they've been greeted, or it's too late now
            about = self.life.visitor[0]
        if share is not None and share.kind in ASKING:
            aim, about = aim_of(share, owner, self.memory.clock())  # "tell Dan", not read out
        now = self.memory.clock()
        bar = settings.life.pipe_up_bar
        if bar > 0 and home is None and reason not in ("nag", "visitor", "check_in", "brief"):
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
        voice = self._voice(settings, history, replying=False, home=home is not None)
        voice_token = VOICE.set(voice)
        lint_token = LINT.set(self._hello_lint(home) if home is not None else None)
        mind = homecoming_facts(home, owner, now, also) if home is not None else ""
        mind_token = MIND.set(mind)
        BROUGHT_UP.set(None)
        said: list[str] = []
        message_id = None
        kept_quiet = False
        self._cancel_warm()  # only once he's going to say something: it reads ahead after
        try:
            doing = (
                self.pc.now_line(owner) or self.scene.now_line(owner) or f"what {owner} is up to"
            )
            recalled = await self.recall.for_turn(doing, {str(m.id) for m in history})
            quiet_h = (self.memory.clock() - self.life.last_chat).total_seconds() / 3600
            if home is not None:
                prompt = homecoming_prompt(
                    home, owner, self.life.cheek(), now, also, settings.persona.speech
                )
            elif brief:
                prompt = brief_prompt(owner, brief, settings.persona.speech)
            else:
                prompt = pipe_up_prompt(
                    reason,
                    owner,
                    self.life.cheek(),
                    about if reason == "visitor" else self.life.curious_about,
                    quiet_h,
                    self.life.butting_in,
                    share=about,
                    aim=aim,
                    speech=settings.persona.speech,
                    held=self.life.held_words(owner),
                )
            messages = self._local_messages(
                settings,
                self._system(settings, recalled, LOCAL, False),
                history_messages(history, "desk", plain=settings.ollama.speak_pass),
                prompt,
            )
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
            self._keep_warm()
        if brief:
            self.life.brief_ready = False
            if said:
                self.brief.mark_given(now, "desk")
            else:
                self.brief.tried(now)  # again next beat, or in his next answer
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
        self._asked_in(self._brought_up(" ".join(said), owner, voice), message_id)
        why = self._why_piped(reason, aim, about, owner)
        if share is not None and share.meta.get("private") and message_id is not None:
            self.memory.said_privately(message_id)  # from what Dan kept local
        self._pipe_up = (message_id, why) if message_id is not None else None
        self.life.piped_up(reason, share_kind(share))
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
        said = [without_laughs(without_plans(m.text)) for m in history if m.role != "user"][
            -SAID_SHOWN:
        ]
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
        meta = {"model": answer.model, "cost_aud": round(answer.cost_aud, 4)}
        message_id = self._remember_reply(reply, PIPE_UP, meta)
        return [
            {"type": "say", "text": reply.text, "source": "cloud"},
            {
                "type": "reply",
                "source": PIPE_UP,
                "reply": reply.model_dump(),
                "message_id": message_id,
                "model": answer.model,
                "cost_aud": round(answer.cost_aud, 4),
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

    def use_house(self, house: House) -> None:
        """Give Kit the house (kit.house): the house pack, and what he notices in it."""
        self.house = house
        self.house_watch = Watcher(house, self.life, self.settings, self.memory.clock)
        self.tools.add(house_pack(self))

    def use_app(self, app: App) -> None:
        """Give Kit one of Dan's apps (kit.tools.mcp): its MCP server's tools as a pack."""
        app.brain = self
        self.apps[app.name] = app
        self.tools.add(app.pack)

    async def app_contents(self) -> int:
        """Once a day (``apps.contents_daily``), each app's saved work into memory
        (kit.tools.mcp.write_contents). How many rows were written."""
        today = self.memory.clock().date()
        if self._apps_read == today or not self.settings().apps.contents_daily:
            return 0
        written = 0
        waiting = False
        for app in self.apps.values():
            if not app.connected:
                waiting = True  # try again later today
                continue
            try:
                written += await write_contents(app, self.memory.index)
            except Exception:
                log.exception("reading %s's saved work failed", app.name)
        if not waiting:
            self._apps_read = today
        return written

    def note_activity(self) -> int:
        """Fold each day still in the PC's focus history into its ``activity`` item
        (kit.activity), so yesterday is kept after the history moves on."""
        if not self.settings().pc.keep_activity or not self.pc.spans:
            return 0
        days = sorted(
            {s.start.date() for s in self.pc.spans} | {s.end.date() for s in self.pc.spans}
        )
        return write_days(
            self.memory.index, self.pc.spans, self.pc.recent_files, self.register, days
        )

    def notes_tidy(self) -> list[str]:
        """On Sundays (``notes.tidy_weekly``), what looks untidy in the notes vault
        (kit.notes.Notes.tidy_report) goes into his notebook as something he may bring
        up, and to the bodies as a ``notes_tidy`` event. He changes nothing. Once a day."""
        settings = self.settings()
        now = self.memory.clock()
        if (
            now.weekday() != 6
            or not settings.notes.tidy_weekly
            or not settings.nas.vault
            or self._notes_tidied == now.date()
        ):
            return []
        self._notes_tidied = now.date()
        lines = self.notes.tidy_report(now)
        if lines:
            owner = settings.persona.owner
            self.notebook.write(
                "want",
                f"I had a look over {owner}'s notes this week (I changed nothing): "
                + "; ".join(lines)
                + ". Mention it if it fits, lightly.",
                again=True,
            )
            self.life.publish({"type": "notes_tidy", "lines": lines})
        return lines

    def refresh_projects(self) -> int:
        """Once a day, Dan's code projects into the index (kit.projects)."""
        today = self.memory.clock().date()
        if self.projects.refreshed == today or not self.settings().projects.roots:
            return 0
        self.projects.refreshed = today
        return self.projects.refresh(self.memory.index, self.register)

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
        hearing = self.hearing.online() and not self.hearing_paused
        if self.scene.online():
            senses += (
                " You can see the desk with your own eyes: who's there, what they're doing "
                "or holding, and the cat when it wanders in."
            )
        else:
            senses += f" You can't see {owner} right now: your eyes aren't open."
        if hearing:
            senses += (
                " You can hear the room through a microphone at the desk: you answer when "
                "someone says your name or answers you, and you notice a laugh or how a "
                "voice sounds. Talk that isn't meant for you, you let go of."
            )
        else:
            senses += f" You can't hear {owner} right now: your ears aren't on."
        feeling = self.life.feeling_line(owner)
        did = self.life.did_line(owner)
        if did:
            senses += f" {did} That's all true; don't add to it."
        return about_yourself(owner, feeling, self.life.why_quiet(owner), senses)

    def _why_piped(self, reason: str, aim: str, about: str, owner: str) -> str:
        """Why he piped up, in a few words for his next prompt, or "" when the line
        says it all."""
        if reason == "visitor":
            return f"you'd just said hi to {about}, who sat down at the desk"
        if reason == "brief":
            return f"it was {owner}'s morning brief"
        if aim:
            return f'you wanted to {aim}: "{about}"'
        if about:
            return f'you\'d been thinking: "{about}"'
        if reason == "nag" and self._pipe_up:
            return self._pipe_up[1]  # still on about the same thing
        if reason in ("curious", "watching") and self.life.curious_about:
            if self.life.curious_kind == "seen":
                return f"you'd just seen {self.life.curious_about}"
            if self.life.curious_kind == "house":
                return f"you'd just noticed in the house: {self.life.curious_about}"
            return f"{owner} had just opened {self.life.curious_about}"
        return ""

    async def brief_tick(self) -> None:
        """Once a beat: gather the morning brief while it's due, and tell his life it's
        ready to say at the desk (``Life._urge_now`` asks for the "brief" pipe-up)."""
        now = self.memory.clock()
        parts = await self.brief.prepare(now)
        self.life.brief_ready = bool(parts) and bool(self.brief.for_desk(now))

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
        scene = self.scene.now_line(owner)
        try:
            recalled = await self.recall.for_turn(pc or scene or happened, set())
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
                self.life.feeling_line(owner, replying=False),
                self.notebook.mind(owner, 5),
                remembered,
                said_today,
                scene=scene,
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
        finally:
            self._keep_warm()
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
        if thought.feeling:  # felt, but never over something Dan did
            self.life.feel(thought.feeling, thought.why or thought.text, THOUGHT_FEELS)
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

    def _voice(
        self,
        settings: Settings,
        history: list[Message],
        text: str = "",
        replying: bool = True,
        home: bool = False,
    ) -> Voice:
        """How Kit feels and sounds this turn (``Life.voice``). ``replying`` is False
        for a pipe-up, where nobody has spoken; ``home``: a hello is in play, whose
        facts say how long Dan was gone, so the time line stays out."""
        persona = settings.persona
        said = [
            without_laughs(without_plans(m.text))[:SAID_CHARS] for m in history if m.role != "user"
        ]
        said = [line for line in said if line][-SAID_SHOWN:]
        own = [(ex.user, ex.kit) for ex in persona.examples]
        mind = self.notebook.mind_with_ids(persona.owner)
        opinions = self._opinions(settings)
        lines = [line for _, line in mind]
        voice = self.life.voice(
            persona.owner, own, said, self.quirks, text, lines, opinions, replying, home
        )
        voice.mind_ids = [item_id for item_id, _ in mind]
        return voice

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

    def _note_request(self, text: str) -> Request | None:
        """A plain note request in Dan's words (kit.notes.request), against every
        note's name. Called in a thread: a big vault takes real time."""
        return request(text, self.notes.names(limit=ALL))

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

    def forecast_fetched(self) -> None:
        """A forecast was just looked at (the weather tool), so a follow-up about the
        weather is answered from it rather than fetched again."""
        self._weather_at = self.memory.clock()

    def _offered(self, role: str, settings: Settings) -> list[Tool]:
        """The tools a cloud model gets as native tool calls this turn. The local model
        (and a cloud profile that is really Ollama) keeps its one action in the reply
        JSON, which the loop turns into the same calls."""
        if role == LOCAL or settings.profile(role).provider == "ollama":
            return []
        return self.tools.offered(self.loaded_packs)

    def _hold(
        self,
        call: ToolCall,
        pack: Pack | None,
        said: str,
        role: str,
        message_id: int | None,
        owner: str,
    ) -> ToolResult:
        """A call that waits for Dan's yes (kit.tools.confirm): kept on
        ``pending_tool``, and the model is told to ask. One waits at a time."""
        tool = self.tools.get(call.name)
        asking = tool.asking(call) if tool else call.line()
        if self.pending_tool is not None:
            return ToolResult(one_at_a_time(self.pending_tool.asking), ok=False)
        preview = ""
        if tool is not None and tool.preview is not None:
            try:
                preview = tool.preview(dict(call.arguments))
            except Exception as e:  # it can't be done as asked: say so, ask nothing
                return ToolResult(f"It can't be done as asked: {e}", ok=False)
        self.pending_tool = Held(
            call,
            pack.name if pack else "",
            said,
            role,
            message_id,
            self.memory.clock(),
            asking,
            preview,
        )
        text = ask_first(owner, asking)
        if preview:
            text += f"\nThe change, as it would be made (show {owner} the gist):\n{preview}"
        return ToolResult(text)

    def _action_calls(self, reply: Reply, role: str) -> list[ToolCall]:
        """A look-up asked for the old way, as the reply's action, as a tool call.
        What has already been looked at this turn (``tool_context``) isn't looked at
        again for the reading's sake."""
        ctx = self.tool_context
        kind = self._look_wanted(reply.action.kind, role, ctx.pc_detail, ctx.scene_detail)
        if kind not in ACTION_ARGS or self.tools.get(kind) is None:
            return []
        if kind == "read_note" and NOTE_DONE.get():
            return []
        arg = ACTION_ARGS[kind]
        text = reply.action.text.strip() or reply.action.title.strip()
        if kind == "recall" and (not text or SPOKEN_NOT_SEARCH.search(text)):
            text = ""  # the brain fills in Dan's message below
        return [ToolCall(kind, kind, {arg: text} if arg else {})]

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
        scene_detail: str = "",
    ) -> str:
        """The system prompt. For a cloud model, ``history`` is what it's shown of the
        chat, and his voice keeps to that and to what he can share."""
        routing = settings.routing
        voice = VOICE.get()
        if role != LOCAL and voice is not None:
            said = [
                without_laughs(without_plans(m.text))[:SAID_CHARS]
                for m in history or []
                if m.role != "user"
            ]
            mind = self.notebook.mind_with_ids(settings.persona.owner, shared=True)
            opinions = self._opinions(settings, shared=True)
            voice = replace(
                voice,
                said=[x for x in said if x][-SAID_SHOWN:],
                mind=[line for _, line in mind],
                mind_ids=[item_id for item_id, _ in mind],
                opinions=opinions,
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
            channel=self._channel_line(settings.persona.owner),
            weather=self.weather is not None,
            notes=bool(settings.nas.vault),
            note_names=self.notes.names() if settings.nas.vault else None,
            note_done=NOTE_DONE.get(),
            forecast=forecast,
            pc_detail=pc_detail,
            scene=self.scene.now_line(settings.persona.owner),
            scene_detail=scene_detail,
            sheet=sheet.text if sheet else "",
            traits=sheet is None or sheet.meta.get("basis") != basis(settings.persona),
            two_pass=role == LOCAL and settings.ollama.speak_pass,
            dan=self._about_dan(role),
            read_mood=READ_ON.get(),
            tools=self.tools.cards(self.loaded_packs),
            tool_names=[t.name for t in self._offered(role, settings)],
            tool_context=self.tools.context(self.loaded_packs),
        )

    def _about_dan(self, role: str) -> str:
        """What's going on with Dan, as Kit wrote it last night; not for a cloud model
        if it was written from something Dan kept local."""
        dan = self.notebook.dan()
        if dan is None or (role != LOCAL and dan.meta.get("private")):
            return ""
        return dan.text

    @staticmethod
    def _local_messages(settings: Settings, system: str, past: list[dict], user: str) -> list[dict]:
        """The local model's prompt. When it reads ahead (``reads_ahead``), this turn's
        part of the instructions goes beside Dan's message, so everything before his
        message is what was read ahead (``_warm``) and only his message is left to read."""
        if reads_ahead(settings):
            system, now = split_turn(system)
            user = with_now(user, now, settings.persona.owner)
        return [{"role": "system", "content": system}, *past, {"role": "user", "content": user}]

    @staticmethod
    def _cloud_messages(settings: Settings, system: str, past: list[dict], user: str) -> list[dict]:
        """A cloud model's prompt: this turn's part of the instructions goes beside
        Dan's message, so the instructions and the conversation so far read the same
        every turn and the provider serves them from its prompt cache (kit.cloud)."""
        system, now = split_turn(system)
        user = with_now(user, now, settings.persona.owner)
        return [{"role": "system", "content": system}, *past, {"role": "user", "content": user}]

    def _keep_warm(self) -> None:
        """Once Kit has finished, read the conversation into the local model ahead of
        Dan's next message (``reads_ahead``)."""
        self._cancel_warm()
        if reads_ahead(self.settings()):
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
        settings = self.settings()
        if not reads_ahead(settings):  # switched off, or to cloud-only, meanwhile
            return
        self._warming = True
        try:
            await self.model.warm(self._warm_messages(settings))
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
        scene_detail: str = "",
        lead: str = "",
    ) -> AsyncIterator[Event]:
        hand_off = role in (LOCAL, CHAT) and not chosen and hops == 0
        seen, shown = history, recalled
        if role != LOCAL:  # what Dan kept local, and what Kit kept from it, stays home
            seen, shown = self.memory.shared(history), recalled.for_cloud()
        self.tool_context = Context(
            pc=self.pc.latest is not None,
            pc_detail=bool(pc_detail),
            scene=self.scene.latest is not None,
            scene_detail=bool(scene_detail),
            weather=self.weather is not None,
            forecast=bool(forecast),
            notes=bool(settings.nas.vault),
            note_done=bool(NOTE_DONE.get()),
            files=self.files is not None and bool(settings.files.roots),
            desk=self.pc.online(),
            activity=bool(self.memory.index.count(ACTIVITY) or self.memory.index.count(PROJECTS)),
            projects=bool(settings.projects.roots),
        )
        self.current_text = text
        lift = lifted(text)  # "send it to Claude": private results go whole, this once
        # The packs this message needs, chosen before any model is asked (kit.tools.match).
        self.loaded_packs = await match(text, self.tools, self.recall, self.register, settings)
        loaded_tools = self.tools.tool_names(self.loaded_packs)
        owner = settings.persona.owner
        offered = self._offered(role, settings)
        system = self._system(
            settings, shown, role, hand_off, forecast, pc_detail, seen, scene_detail
        )
        plain = role == LOCAL and settings.ollama.speak_pass  # the words come as plain text
        past = history_messages(seen, CHANNEL.get(), plain=plain)
        user = self._user_turn(text, role, settings, pc_detail, answering, scene_detail, lead)
        if role == LOCAL:
            messages = self._local_messages(settings, system, past, user)
        else:
            messages = self._cloud_messages(settings, system, past, user)
        job = None
        if role != LOCAL:
            job = Job(next(self._job_ids), question or text, settings.profile(role).name)
            self.jobs[job.id] = job
        try:
            reply, message_id, calls, content = None, None, [], None
            async for event in self._reply(messages, role, settings, text, job, offered):
                if event["type"] in ("reply", "tool_calls"):
                    reply = Reply.model_validate(event["reply"])
                    message_id = event["message_id"]
                    calls = [ToolCall(**c) for c in event.get("calls", [])]
                    content = event.get("content")
                yield event
            if reply is None:
                return

            # The tool loop: what the model asked for (its native calls, or the one
            # look-up in its action) is run and handed back, until it answers in words.
            done_calls: set[tuple[str, str]] = set()
            for _ in range(settings.tools.hops):
                native = bool(calls)
                if not native:
                    calls = self._action_calls(reply, role)
                if not calls:
                    break
                results: list[tuple[ToolCall, ToolResult]] = []
                for call in calls:
                    if call.name == "recall" and not call.arguments.get("query"):
                        call.arguments["query"] = text
                    key = (call.name, json.dumps(call.arguments, sort_keys=True))
                    yield {"type": "tool", "tool": call.name, "line": call.line()}
                    tool = self.tools.get(call.name)
                    pack = self.tools.packs.get(self.tools.pack_of(call.name))
                    if tool is None or call.name not in loaded_tools:
                        result = ToolResult(f"There is no tool called {call.name}.", ok=False)
                    elif key in done_calls or key == self._ran_held:
                        # The same call twice: answer from the first.
                        result = ToolResult(
                            f"You already ran {call.line()} this turn; use what it gave you "
                            "and answer now.",
                            ok=False,
                        )
                    elif needs_yes(tool, pack, settings, call.arguments):
                        done_calls.add(key)
                        result = self._hold(call, pack, text, role, message_id, owner)
                        if result.ok:
                            yield {
                                "type": "confirm",
                                "tool": call.name,
                                "line": call.line(),
                                "ask": tool.asking(call),
                                "preview": self.pending_tool.preview if self.pending_tool else "",
                            }
                    else:
                        done_calls.add(key)
                        result = await self.tools.run(call)
                        self.tool_context.looked(call.name)
                    if result.event:
                        yield result.event
                    if job and result.step:
                        job.steps.append(result.step)
                    self.memory.log_tool_call(
                        message_id,
                        call.name,
                        call.arguments,
                        tool.effect if tool else "read",
                        result.text,
                        result.ok,
                        role,
                    )
                    if role != LOCAL and result.private and not lift:
                        result = replace(
                            result, text=await for_cloud(result, text, self.model), private=False
                        )
                    results.append((call, result))
                if native:
                    messages += tool_turns(
                        reply.full_text if reply.text else "",
                        [c for c, _ in results],
                        [(c.id, r.text) for c, r in results],
                        content,
                    )
                else:
                    said = reply.full_text if plain else reply_json(reply)
                    messages += [
                        {"role": "assistant", "content": said},
                        {"role": "user", "content": results[0][1].text},
                    ]
                # The "Let me think..." turn is kept as a working note (RECALL_STEP), so
                # later history shows one answer per message, not a recall habit.
                if message_id is not None:
                    self.memory.set_message_source(message_id, RECALL_STEP)
                reply, message_id, calls, content = None, None, [], None
                offered = self._offered(role, settings)
                async for event in self._reply(messages, role, settings, text, job, offered):
                    if event["type"] in ("reply", "tool_calls"):
                        reply = Reply.model_validate(event["reply"])
                        message_id = event["message_id"]
                        calls = [ToolCall(**c) for c in event.get("calls", [])]
                        content = event.get("content")
                    yield event
                if reply is None:
                    return
            if calls and not reply.text.strip():
                # Out of hops with the model still asking and nothing said: one last
                # answer, with no tools on offer, so the turn ends in words.
                messages += tool_turns(
                    "",
                    calls,
                    [
                        (c.id, "No more tools this turn; answer now from what you have.")
                        for c in calls
                    ],
                    content,
                )
                if message_id is not None:
                    self.memory.set_message_source(message_id, RECALL_STEP)
                reply = None
                async for event in self._reply(messages, role, settings, text, job, []):
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
        # Only what Dan said or named counts, as the model read it (said_it), or failing
        # that by the words: small models "remembered" their own lines and guesses.
        reading = READING.get() or Reading.of(text)
        owner = settings.persona.owner
        if kind == "remember" and fact and not reading.remembers(fact, said, owner):
            log.info("not remembering %r: %s didn't say it", fact, owner)
        elif kind == "remember" and fact:
            # Learned once the reply is out (``_learn_later``), never on the chat path.
            self._learn_later(
                [(fact, reply.action.category)], settings.persona.owner, PRIVATE.get(), settings
            )
        elif kind == "thing" and reading.named(fact, " ".join(said)):
            event = self._note_thing(reply)
            if event:
                yield event
        elif kind == "note" and not NOTE_DONE.get():
            if reading.asked_for_note(text):
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

    def _look_wanted(self, kind: str, role: str, pc_detail: bool, scene_detail: bool) -> str:
        """The action, or the look the model's reading asked for (``wants_pc_look``,
        ``wants_camera_look``) when it set none: the words missed it ("the build died
        and so did my weekend" isn't a PC question, "what am I even running" is), and
        there's a PC or a scene to look at that he hasn't looked at for this yet. His
        own model looks, as for a question plainly about the PC, never a cloud one."""
        reading = READING.get()
        if kind != "none" or reading is None or role not in (LOCAL, CHAT):
            return kind
        if "wants_pc_look" in reading.given and reading.wants_pc_look:
            if self.pc.latest is not None and not pc_detail:
                return "look_at_pc"
        if "wants_camera_look" in reading.given and reading.wants_camera_look:
            if self.scene.latest is not None and not scene_detail and not pc_detail:
                return "look_around"
        return kind

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
        tools: list[Tool] | None = None,
    ) -> AsyncIterator[Event]:
        """``tools`` are offered to a cloud model as native tool calls; what it asks for
        comes back on the ``reply`` event (``calls``), or on a ``tool_calls`` event when
        it asked without a word to say, so no empty line reaches the chat."""
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
        lint, sounds = LINT.get(), settings.speech.sounds
        words = None  # the answer read as it streams in (cloud.stream)
        offered = definitions(tools or [])
        if lint is not None:  # a goodbye: checked whole before a word of it is said
            answer, reply = await self._cloud_checked(
                profile, messages, settings, question, on_step, lint
            )
        elif settings.cloud.stream:
            words = StreamedReply("cloud", sounds)
            async for event in self._cloud_stream(
                profile, messages, settings, question, on_step, words, offered
            ):
                if isinstance(event, CloudAnswer):
                    answer = event
                else:
                    yield event
            reply = parse_cloud_reply(answer.text)
        else:
            answer = await self.cloud.answer(
                profile,
                messages,
                settings,
                question,
                on_step,
                priority=PRIORITY.get(),
                tools=offered,
            )
            reply = parse_cloud_reply(answer.text)
        if answer.calls and not reply.text.strip():
            # It asked for tools without a word to say: nothing reaches the chat yet.
            message_id = self._remember_reply(reply, "cloud", {"role": role, "working": True})
            yield {
                "type": "tool_calls",
                "source": "cloud",
                "reply": reply.model_dump(),
                "message_id": message_id,
                "calls": [c.__dict__ for c in answer.calls],
                "content": answer.content,
            }
            return
        if words is None or not words.said:
            self.life.react("perk_up", "the answer came back")
        if role != CHAT:  # a real job tires him; an everyday answer doesn't
            self.life.spend(CLOUD_TIRES)
        if READ_ON.get() and READ.get() is None:
            READ.set(mood_read(answer.text))
        self._read_by_model(reading_read(answer.text))
        if answer.truncated:
            reply.detail = reply.detail + "\n\n(I ran out of room there; ask me to continue.)"
        meta = {
            "role": role,
            "model": answer.model,
            "label": profile.name,
            "cost_aud": round(answer.cost_aud, 4),
            "searches": answer.searches,
        }
        message_id = self._remember_reply(reply, "cloud", meta)
        if words is None or not words.said:  # it came in one piece: his words now
            for event in reply_events(reply, "cloud", sounds):
                yield event
        yield {
            "type": "reply",
            "source": "cloud",
            **meta,
            "reply": reply.model_dump(),
            "message_id": message_id,
            "month_aud": round(self.memory.month_spend(), 4),
            **({"calls": [c.__dict__ for c in answer.calls]} if answer.calls else {}),
            **({"content": answer.content} if answer.calls else {}),
        }

    async def _cloud_stream(
        self,
        profile: ModelProfile,
        messages: list[dict],
        settings: Settings,
        question: str,
        on_step: Callable[[str], None] | None,
        words: StreamedReply,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[Event | CloudAnswer]:
        """A cloud answer as it's written (``cloud.stream``): his mood, sounds and words
        as chat events the moment they're in, then the whole answer (a ``CloudAnswer``,
        last). He perks up at the first word. Raises CloudError as ``Cloud.answer``
        does; a model that can't stream gives its words at the end instead."""
        pieces: asyncio.Queue[str | None] = asyncio.Queue()
        call = asyncio.create_task(
            self.cloud.answer(
                profile,
                messages,
                settings,
                question,
                on_step,
                priority=PRIORITY.get(),
                on_text=pieces.put_nowait,
                tools=tools,
            )
        )
        call.add_done_callback(lambda _: pieces.put_nowait(None))
        try:
            while (piece := await pieces.get()) is not None:
                for event in words.feed(piece):
                    if event["type"] == "say" and words.said == event["text"]:
                        self.life.react("perk_up", "the answer started coming back")
                    yield event
            yield await call
        finally:
            if not call.done():  # nobody's listening any more
                call.cancel()

    async def _cloud_checked(
        self,
        profile: ModelProfile,
        messages: list[dict],
        settings: Settings,
        question: str,
        on_step: Callable[[str], None] | None,
        lint: Lint,
    ) -> tuple[CloudAnswer, Reply]:
        """A cloud answer that's checked whole before it's said (a goodbye): one that
        fails the check gets one more go with what was wrong, then the stock line."""
        talk = messages
        for _ in range(2):
            answer = await self.cloud.answer(
                profile, talk, settings, question, on_step, priority=PRIORITY.get()
            )
            reply = parse_cloud_reply(answer.text)
            fault = lint.check(reply.text)
            if not fault:
                return answer, reply
            log.info("the cloud's %r didn't pass: %s", reply.text, fault)
            asked = messages[-1]
            talk = [*messages[:-1], {**asked, "content": asked["content"] + fault}]
        if not lint.fallback:
            return answer, reply
        log.info("said a stock line: no clean answer in two goes")
        return answer, Reply.plain(lint.fallback, reply.emotion, reply.segments[0].gesture)

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
        plan = early
        if plan is None:
            try:
                plan = parse_plan(raw)
            except ReplyError:
                plan = Plan.default()
        BROUGHT_UP.set(list(plan.brought_up))
        self._read_by_model(plan.reading())
        return plan

    @staticmethod
    def _read_by_model(fields: dict) -> None:
        """The model's reading of Dan's message (from its plan or a cloud reply) laid
        over the words' guess for the rest of the turn (``READING``)."""
        reading = READING.get()
        if reading is not None and fields:
            READING.set(reading.with_model(fields))

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
        said_all = False  # his words are complete, though the model may still be writing
        try:
            plan = await self._plan(messages)
            reading = READING.get() or Reading.of(heard)  # with the plan's reading in it
            if plan.action.kind == "thing" and not reading.named(plan.action.text, heard):
                # Dan never named it, so no "shall I add it to the register?"
                plan = plan.model_copy(update={"action": Action(kind="none")})
            if plan.action.kind == "note" and not reading.asked_for_note(heard):
                # Dan didn't ask for a note, so Kit offers rather than writes one.
                offer = plan.action.model_copy(update={"kind": "offer_note"})
                plan = plan.model_copy(update={"action": offer})
            if not hold:  # how he feels, before his words: the voice speaks in this mood
                yield {"type": "mood", "emotion": plan.emotion}
            # The plan read the message as about Kit when the words hadn't: what's true
            # about him goes beside the speaking step, the one new thing it carries.
            about_me = self._about_me(settings.persona.owner) if reading.new_about_kit() else ""
            note = speak_note(
                plan.action,
                settings.persona.owner,
                settings.profile(WORK).name,
                settings.profile(EXPERT).name,
                voice,
                heard,
                about_me,
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
                    if not hold and not said_all:
                        yield {"type": "spoken"}
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

    def _remember_reply(self, reply: Reply, source: str, meta: dict | None = None) -> int:
        """Keep a reply; ``meta`` (who answered, what it cost) goes with it for the
        desk chat's colours and details."""
        return self.memory.add_message(
            "kit",
            reply.full_text,
            reply_json(reply),
            source,
            meta_json=json.dumps(meta) if meta else None,
        )

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
