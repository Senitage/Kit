"""What Kit brings up on his own, at most once a day each: a getting-to-know-you
question till he knows the people and things that matter, a nudge toward bed when
Dan's up late, a nudge outside after a long stretch at the desk, and on Monday,
how the weekend went.

Each is written into his notebook at the right moment (a want, or a thread for the
weekend), so it comes up the way his own wants do: in a pipe-up, or in his next
reply. A question is only written while you two are talking, never out of the blue.
What he's done today is kept in kit_self, so a restart doesn't repeat it. The
questions are everyday ones, names first, and he skips what he already knows.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from kit.knowledge import STOPWORDS, Item
from kit.life import DAYTIME, Life, day_part, in_quiet_hours, parse_time, since_clock
from kit.memory import Memory
from kit.notebook import Notebook
from kit.settings import Settings
from kit.things import Register
from kit.when import When

DAILY_KEY = "daily"  # kit_self: {"asked": {question: times}, "done": {what: day}}
NUDGE_PRESS = 0.85  # soon, but not at once
ASK_PRESS = 0.6  # a getting-to-know-you question waits behind what he means to say
ASK_TIMES = 2  # a question nobody answered comes round once more, then he lets it go
ASK_FROM, ASK_UNTIL = 9, 21  # hours he asks in
LATE_UNTIL = 4  # past bedtime until this hour counts as the night before
ANSWER_WORDS = 8  # an answer to "what's the cat called?" this short is the name
TALKING = timedelta(hours=1)  # he asks while you two are talking, never out of the blue


@dataclass(frozen=True)
class Question:
    """A getting-to-know-you question. ``about`` finds a fact that answers it;
    ``needs_name`` means that fact must name someone; ``relation`` turns a one-name
    answer ("Milo") into a fact ("Milo is Dan's cat.")."""

    key: str
    ask: str
    about: str
    needs_name: bool = False
    relation: str = ""


QUESTIONS = [
    Question(
        "partner",
        "what's your partner's name?",
        r"\b(partner|wife|husband|girlfriend|boyfriend|fianc)",
        True,
        "partner",
    ),
    Question("cat", "what's the cat called?", r"\b(cat|kitten)\b", True, "cat"),
    Question(
        "family",
        "who's in your family? Any brothers or sisters, or folks nearby?",
        r"\b(sister|brother|mum|mother|dad|father|parents|family)\b",
        True,
    ),
    Question("mates", "who are the mates you see most?", r"\b(mates?|friends?)\b", True),
    Question("weekend", "what's your idea of a good weekend?", r"\bweekends?\b"),
    Question("food", "what's your go-to dinner?", r"\b(dinner|favourite food|meal|cook)"),
    Question("music", "what music have you got on most?", r"\b(music|band|songs?|listens? to)\b"),
    Question(
        "sport",
        "do you follow a footy team, or any sport?",
        r"\b(footy|afl|nrl|cricket|rugby|soccer|team|sport)\b",
    ),
    Question(
        "fun",
        "what do you get up to when you're not working?",
        r"\b(hobby|hobbies|fishing|camping|gym|garden\w*|surf\w*|golf|hik\w+|bike|riding)\b",
    ),
    Question("birthday", "when's your birthday?", r"\b{owner}['’]?s birthday\b|\bborn\b"),
]
NAME = re.compile(r"\b[A-Z][a-z]+\b(?!['\u2019])")
NOT_NAMES = frozenset(
    """i im ive i'm the a an it its she he they we my our yes yeah yep nah no oh well
    actually called named his her their kit nope single dunno lol haha don dont none
    never not why what who sorry mate bro hmm um""".split()
)
# Not an answer with a name in it: "nope, single", "don't have one", "why?".
NO_NAME = re.compile(
    r"\?|\b(no|nope|nah|not|none|never|single|dunno|don'?t|haven'?t|hasn'?t|isn'?t|"
    r"aren'?t|no one|nobody|not sure|n/a)\b|\bdon\u2019t\b",
    re.I,
)
MORNING_ENDS = 12  # Monday's "how was the weekend?" is a morning thing


def names_in(text: str, owner: str) -> list[str]:
    """Capitalised words that could be names: "Emma, Dan's sister" has Emma."""
    found = []
    for name in NAME.findall(text):
        low = name.lower()
        if low in NOT_NAMES or low in STOPWORDS or low == owner.lower():
            continue
        if low in WEEK_AND_MONTH:
            continue
        if name not in found:
            found.append(name)
    return found


WEEK_AND_MONTH = frozenset(
    """monday tuesday wednesday thursday friday saturday sunday january february march
    april may june july august september october november december""".split()
)


def night_of(now: datetime) -> date:
    """Which night it is: 1 am is still last night."""
    return (now - timedelta(hours=LATE_UNTIL)).date()


class Daily:
    def __init__(
        self,
        memory: Memory,
        notebook: Notebook,
        life: Life,
        settings: Callable[[], Settings],
    ) -> None:
        self.memory = memory
        self.notebook = notebook
        self.life = life
        self.settings = settings
        self.register = Register(memory)

    # What's been done

    def _state(self) -> dict:
        try:
            state = json.loads(self.memory.self_value(DAILY_KEY) or "{}")
        except ValueError:
            return {"asked": {}, "done": {}}
        if not isinstance(state, dict):
            return {"asked": {}, "done": {}}
        asked, done = state.get("asked"), state.get("done")
        return {
            "asked": {str(k): v for k, v in (asked or {}).items() if isinstance(v, int)}
            if isinstance(asked, dict)
            else {},
            "done": {str(k): str(v) for k, v in (done or {}).items()}
            if isinstance(done, dict)
            else {},
        }

    def _save(self, state: dict) -> None:
        self.memory.set_self_value(DAILY_KEY, json.dumps(state))

    def _done(self, what: str, day: date) -> bool:
        return self._state()["done"].get(what) == day.isoformat()

    def _mark(self, what: str, day: date) -> None:
        state = self._state()
        state["done"][what] = day.isoformat()
        self._save(state)

    def asked(self, key: str) -> None:
        """He asked getting-to-know-you question ``key``."""
        state = self._state()
        state["asked"][key] = state["asked"].get(key, 0) + 1
        self._save(state)

    # Once a heartbeat

    def offer(self) -> list[str]:
        """Write whatever's due now into his notebook. Returns what was written."""
        life = self.settings().life
        if not life.enabled or life.chattiness <= 0:
            return []
        now = self.memory.clock()
        written = []
        for what, due in (
            ("sleep", self._sleep),
            ("outside", self._outside),
            ("weekend", self._weekend),
            ("interview", self._interview),
        ):
            if due(now):
                written.append(what)
        return written

    def _present(self) -> bool:
        snap = self.life.pc.latest if self.life.pc.online() else None
        return bool(snap and not snap.locked and snap.idle_seconds < 300 and not self.life.asleep)

    def _talking(self, now: datetime) -> bool:
        """Has Dan said something to him lately?"""
        said = [m for m in self.memory.recent(6) if m.role == "user"]
        return bool(said) and now - parse_time(said[-1].at, now) < TALKING

    def _low(self) -> bool:
        """Dan's had bad news or a rough day: no questions or nudges just now."""
        return self.life.bad_night() or self.life.feels("sad", "worried", "sympathetic", "hurt")

    def _sleep(self, now: datetime) -> bool:
        life = self.settings().life
        night = night_of(now)
        if not life.nudges or self._done("sleep", night) or self._low():
            return False
        hh, mm = (int(x) for x in life.bedtime.split(":"))
        bedtime = datetime.combine(night, datetime.min.time()).replace(
            hour=hh, minute=mm, tzinfo=now.tzinfo
        )
        if hh < 12:  # "00:30": after midnight, that night
            bedtime += timedelta(days=1)
        until = datetime.combine(night + timedelta(days=1), datetime.min.time())
        until = until.replace(hour=LATE_UNTIL, tzinfo=now.tzinfo)
        if not bedtime <= now < until:
            return False
        recent_chat = now - self.life.last_chat < timedelta(minutes=15)
        if not (self._present() or recent_chat):
            return False
        owner = self.settings().persona.owner
        self.notebook.write(
            "want",
            f"Tell {owner} to get to bed: it's late.",
            again=True,
            nudge="sleep",
            strength=NUDGE_PRESS,
            until=until.isoformat(timespec="seconds"),
        )
        self._mark("sleep", night)
        return True

    def _outside(self, now: datetime) -> bool:
        life = self.settings().life
        since = self.life.present_since
        if not life.nudges or since is None or self._done("outside", now.date()):
            return False
        if day_part(now) not in DAYTIME or not self._present() or self._low():
            return False
        if now - since < timedelta(hours=life.desk_hours):
            return False
        owner = self.settings().persona.owner
        self.notebook.write(
            "want",
            f"Tell {owner} to get some fresh air or catch up with someone: {owner}'s been "
            f"at the desk since {since_clock(since, now)}.",
            again=True,
            nudge="outside",
            strength=NUDGE_PRESS,
            until=now.replace(hour=21, minute=0, second=0).isoformat(timespec="seconds"),
        )
        self._mark("outside", now.date())
        return True

    def _weekend(self, now: datetime) -> bool:
        """Monday morning, once: how was the weekend? Not if he's already following
        something from it."""
        life = self.settings().life
        if not life.threads or now.weekday() != 0 or self._done("weekend", now.date()):
            return False
        if now.hour >= MORNING_ENDS:
            return False
        if not self._present() or in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return False
        saturday = now.date() - timedelta(days=2)
        sunday = saturday + timedelta(days=1)
        for t in self.notebook.entries("thread", 60):
            start = str(t.meta.get("start", ""))[:10]
            if saturday.isoformat() <= start <= sunday.isoformat():
                self._mark("weekend", now.date())
                return False  # a thread from the weekend asks about it better
        start = datetime.combine(saturday, datetime.min.time()).replace(hour=9, tzinfo=now.tzinfo)
        when = When(start, start + timedelta(days=1, hours=12), "the weekend", "weekend")
        written = self.notebook.write_thread("the weekend", when, now, by="monday")
        self._mark("weekend", now.date())
        return written is not None

    def _interview(self, now: datetime) -> bool:
        life = self.settings().life
        if not life.interview or self._done("interview", now.date()) or self._low():
            return False
        if not ASK_FROM <= now.hour < ASK_UNTIL or not self._present():
            return False
        if in_quiet_hours(now, life.quiet_from, life.quiet_until):
            return False
        if not self._talking(now):
            return False
        if any(w.meta.get("interview") for w in self.notebook.unsaid_wants()):
            return False  # still to ask the last one
        question = self.next_question()
        if question is None:
            return False
        owner = self.settings().persona.owner
        self.notebook.write(
            "want",
            f"Ask {owner}: {question.ask}",
            again=True,
            interview=question.key,
            strength=ASK_PRESS,
        )
        self._mark("interview", now.date())
        return True

    # Getting to know Dan

    def next_question(self) -> Question | None:
        """The first question he hasn't asked twice and doesn't know the answer to."""
        asked = self._state()["asked"]
        for q in QUESTIONS:
            if asked.get(q.key, 0) < ASK_TIMES and not self.known(q):
                return q
        return None

    def known(self, q: Question) -> bool:
        """Does a fact or the register already answer ``q``?"""
        owner = self.settings().persona.owner
        about = re.compile(q.about.replace("{owner}", re.escape(owner)), re.I)
        texts = [f.text for f in self.memory.facts()]
        texts += [f"{t.name}: {t.about} {' '.join(t.aliases)}" for t in self.register.all()]
        for text in texts:
            if about.search(text) and (not q.needs_name or names_in(text, owner)):
                return True
        return False

    def name_answer(self, key: str, text: str) -> str:
        """A fact from a short answer to a name question: "Milo, she's a menace" to
        "what's the cat called?" is "Milo is Dan's cat." ("" if it isn't that)."""
        q = next((q for q in QUESTIONS if q.key == key), None)
        if q is None or not q.relation or len(text.split()) > ANSWER_WORDS:
            return ""
        if NO_NAME.search(text):
            return ""
        owner = self.settings().persona.owner
        found = names_in(text, owner)
        words = re.findall(r"[A-Za-z]+", text)
        if not found and len(words) == 1 and words[0].lower() not in NOT_NAMES:
            found = [words[0].capitalize()]
        if len(found) != 1:
            return ""
        return f"{found[0]} is {owner}'s {q.relation}."

    def question(self, item: Item) -> str:
        """The question a getting-to-know-you want asks."""
        q = next((q for q in QUESTIONS if q.key == item.meta.get("interview")), None)
        return q.ask if q else ""
