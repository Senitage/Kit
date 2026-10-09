"""When things are, in the words people use: "Thursday arvo", "at 2 pm", "tonight",
"the weekend", "next week".

Kit uses it to follow what's coming up in Dan's life (threads in kit.notebook): to
know when something is, when to ask how it went, and when to bring something up
that Dan asked him to ("check in after my 2 pm"). Plain Python with the clock
passed in, so tests can say what day it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# Parts of the day, as (start, end) in hours. "Tonight" is the evening and night.
PARTS = {
    "morning": (7.0, 11.5),
    "lunchtime": (11.5, 13.5),
    "arvo": (13.5, 17.0),
    "evening": (17.0, 21.0),
    "night": (19.0, 23.0),
}
PART_NAMES = {
    "morning": "morning",
    "lunch": "lunchtime",
    "lunchtime": "lunchtime",
    "arvo": "arvo",
    "afternoon": "arvo",
    "evening": "evening",
    "night": "night",
    "tonight": "night",
    "tonite": "night",
}
PART_SHOWN = {
    "morning": "morning",
    "lunchtime": "lunchtime",
    "arvo": "afternoon",
    "evening": "evening",
    "night": "night",
}
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "tues": 1,
    "wednesday": 2,
    "weds": 2,
    "thursday": 3,
    "thurs": 3,
    "thur": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sunday": 6,
}
MONTHS = {
    m: n
    for n, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_DAY = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_PART = "morning|lunchtime|lunch|arvo|afternoon|evening|night"
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))

DAY_WORDS = re.compile(
    rf"\b(?:(?P<which>next|this|on|coming|last)\s+)?(?P<wd>{_DAY})\b"
    rf"(?:\s+(?P<wdpart>{_PART}))?(?:\s+week\b(?P<week_on>))?"
    rf"|\b(?P<tomorrow>tomorrow|tmrw|tmw)\b(?:\s+(?P<tpart>{_PART}))?"
    r"|\b(?P<yesterday>yesterday)\b"
    rf"|\b(?:this|today)\s+(?P<thispart>{_PART})\b"
    r"|\b(?P<tonight>tonight|tonite)\b"
    r"|\b(?P<lastnight>last night)\b"
    r"|\b(?P<today>today)\b"
    r"|\b(?:(?P<wkwhich>this|next|the|over the|on the|last)\s+)?(?P<weekend>weekend)\b"
    r"|\b(?P<nextweek>next week)\b"
    r"|\b(?P<lastweek>last week)\b",
    re.IGNORECASE,
)
# "at 2 pm", "2:30", "half past 3" is too much; "noon", "midday".
CLOCK = re.compile(
    r"\b(?P<after>after (?:my |the |our )?)?(?:at |by |around |about |from )?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)(?=\W|$)"
    r"|\b(?P<after2>after (?:my |the |our )?)?(?:at |by |around |about )"
    r"(?:(?P<h2>\d{1,2}):(?P<m2>\d{2})\b|(?P<h3>1[0-2]|[1-9])(?:\s*o'?clock)?(?=\s*(?:$|[.,!?;:)]|"
    r"-?ish\b|tonight\b|today\b|tomorrow\b|this\b|on\b|for\b|and\b|then\b|with\b|so\b|to\b)))"
    r"|\b(?P<after3>after )?(?P<noon>noon|midday)\b",
    re.IGNORECASE,
)
AFTER_PART = re.compile(r"\bafter (?P<what>work|lunch|school|dinner|tea)\b", re.I)
AFTER_HOURS = {"work": 17.5, "lunch": 13.5, "school": 15.5, "dinner": 19.5, "tea": 19.5}
IN_THE_MORNING = re.compile(r"\b(in the morning|first thing)\b", re.I)
DATE = re.compile(
    rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH})\.?(?:\s+(?P<y>\d{{4}}))?\b"
    rf"|\b(?P<mon2>{_MONTH})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y2>\d{{4}}))?\b"
    r"|\b(?P<iso>\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
# "Thursday the 15th": a day of the month, with no month.
ORDINAL = re.compile(r"\bthe\s+(?P<d>\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)
NEXT_WEEK = re.compile(r"\bnext week\b", re.IGNORECASE)
# A clock event is taken to last this long, for asking how it went after.
CLOCK_EVENT = timedelta(hours=1)
AFTER_CLOCK = timedelta(minutes=30)  # "check in after my 2 pm": about 2:30


@dataclass(frozen=True)
class When:
    """When something is: ``start`` to ``end``. ``span`` says how it was put:
    "clock" (at 2 pm), "part" (Thursday arvo, tonight), "day" (Thursday), "weekend"
    or "week". ``after`` is true for "after my 2 pm" or "after work"."""

    start: datetime
    end: datetime
    words: str
    span: str
    after: bool = False
    part: str = ""  # with span "part": morning, lunchtime, arvo, evening or night

    def past(self, now: datetime) -> bool:
        return self.end <= now

    def shown(self, now: datetime) -> str:
        """In words for a prompt: "Thursday afternoon", "today at 2:00 pm"."""
        day = _day_words(self.start.date(), now.date())
        if self.span == "clock":
            return f"{day} at {_clock(self.start)}"
        if self.span == "part":
            part = PART_SHOWN.get(self.part, self.part)
            if day in ("today", "yesterday") and self.part == "night":
                return "tonight" if day == "today" else "last night"
            return f"this {part}" if day == "today" else f"{day} {part}"
        if self.span == "weekend":
            return "the weekend" if (self.start.date() - now.date()).days < 7 else "that weekend"
        if self.span == "week":
            return f"the week of {self.start.day} {self.start:%B}"
        return day


def _clock(t: datetime) -> str:
    return f"{t:%I:%M %p}".lstrip("0").lower()


def _day_words(day: date, today: date) -> str:
    days = (day - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    if 1 < days < 7:
        return f"{day:%A}"
    if -7 < days < 0:
        return f"last {day:%A}"
    return f"{day:%A} {day.day} {day:%B}"


def _at(day: date, hours: float, like: datetime) -> datetime:
    h = int(hours)
    t = datetime.combine(day, time(min(h, 23), int(round((hours - h) * 60)) % 60))
    return t.replace(tzinfo=like.tzinfo)


def _wake(wake: str) -> float:
    h, m = wake.split(":")
    return int(h) + int(m) / 60


def _part(day: date, part: str, now: datetime, wake: str = "07:00") -> tuple[datetime, datetime]:
    start, end = PARTS[part]
    if part == "morning":
        start = _wake(wake)
    return _at(day, start, now), _at(day, end, now)


def _coming(weekday: int, today: date, which: str) -> date:
    """The day ``weekday`` that "Thursday" means: this week's, or today if it's
    today; "next Thursday" is the one in next week; "last Thursday" the one gone."""
    ahead = (weekday - today.weekday()) % 7
    if which == "last":
        return today - timedelta(days=(today.weekday() - weekday) % 7 or 7)
    if which == "next":
        monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return monday + timedelta(days=weekday)
    return today + timedelta(days=ahead)


def _hour(h: int, m: int, ap: str, now: datetime, day: date) -> float:
    """The hour "at 5" means on ``day``: 1 to 6 is the afternoon; 7 to 11 is the
    morning, unless it's today and the morning's one has gone."""
    ap = ap.replace(".", "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif not ap:
        if 1 <= h <= 6:
            h += 12
        elif 7 <= h <= 11 and day == now.date():
            if now.hour + now.minute / 60 >= h + m / 60 + 0.5:
                h += 12
    return h + m / 60


def _date_written(text: str, now: datetime) -> date | None:
    """A calendar date written out: "27 October 2026", "October 27", "2026-10-27",
    or "the 15th" (the next 15th). One with no year is the next from a month ago."""
    m = DATE.search(text)
    if m is None:
        o = ORDINAL.search(text)
        if o is None:
            return None
        day, month, year = int(o.group("d")), now.month, now.year
        for _ in range(2):
            try:
                found = date(year, month, day)
            except ValueError:
                found = None
            if found is not None and found >= now.date():
                return found
            month, year = (1, year + 1) if month == 12 else (month + 1, year)
        return None
    g = m.groupdict()
    try:
        if g["iso"]:
            return date.fromisoformat(g["iso"])
        month = MONTHS[(g["mon"] or g["mon2"]).lower().rstrip(".")]
        day = int(g["d"] or g["d2"])
        year = g["y"] or g["y2"]
        if year:
            return date(int(year), month, day)
        found = date(now.year, month, day)
        if found < now.date() - timedelta(days=30):
            found = date(now.year + 1, month, day)
        return found
    except ValueError:
        return None


def find_when(text: str, now: datetime, wake: str = "07:00") -> When | None:
    """When ``text`` says something is, or None. Times without a day are today
    (they may be gone already: callers decide). "Thursday" is the coming one, and
    "tomorrow" said before wake-up is the morning coming. A date written out
    ("Thursday the 15th") wins over the weekday."""
    today = now.date()
    early = now.hour + now.minute / 60 < _wake(wake)  # after midnight, before wake-up
    written = _date_written(text, now)
    day_m = DAY_WORDS.search(text)
    clock_m = CLOCK.search(text)
    after_part = AFTER_PART.search(text)
    words = []
    day: date | None = None
    part = ""
    span = ""
    after = False
    if day_m is not None:
        g = day_m.groupdict()
        words.append(day_m.group(0))
        if g["wd"]:
            which = (g["which"] or "").lower()
            if not which and NEXT_WEEK.search(text):  # "footy Saturday next week"
                which = "next"
            day = _coming(WEEKDAYS[g["wd"].lower()], today, which)
            if g["week_on"] is not None:  # "Thursday week": a week on
                day += timedelta(days=7)
            part = PART_NAMES.get((g["wdpart"] or "").lower(), "")
            span = "day"
        elif g["tomorrow"]:
            day, span = today + timedelta(days=0 if early else 1), "day"
            part = PART_NAMES.get((g["tpart"] or "").lower(), "")
        elif g["yesterday"]:
            day, span = today - timedelta(days=1), "day"
        elif g["thispart"]:
            day, part, span = today, PART_NAMES[g["thispart"].lower()], "day"
        elif g["tonight"]:
            day, part, span = today, "night", "day"
        elif g["lastnight"]:
            day, part, span = today - timedelta(days=1), "night", "day"
        elif g["today"]:
            day, span = today, "day"
        elif g["weekend"]:
            which = (g["wkwhich"] or "").lower()
            saturday = today + timedelta(days=(5 - today.weekday()) % 7)
            if today.weekday() == 6:  # Sunday: this weekend is today
                saturday = today - timedelta(days=1)
            if which == "next":
                saturday += timedelta(days=7)
            if which == "last":
                saturday = today - timedelta(days=(today.weekday() - 5) % 7 or 7)
            start = _at(saturday, _wake(wake), now)
            end = _at(saturday + timedelta(days=1), PARTS["evening"][1], now)
            return When(start, end, day_m.group(0), "weekend")
        elif g["nextweek"] or g["lastweek"]:
            monday = today - timedelta(days=today.weekday())
            monday += timedelta(days=7 if g["nextweek"] else -7)
            start = _at(monday, _wake(wake), now)
            end = _at(monday + timedelta(days=6), PARTS["evening"][1], now)
            return When(start, end, day_m.group(0), "week")
    if written is not None:
        words.append((DATE.search(text) or ORDINAL.search(text)).group(0))
        day = written
        span = span or "day"
    if clock_m is not None:
        g = clock_m.groupdict()
        on = day or today
        if g["noon"]:
            hours, after = 12.0, bool(g["after3"])
        elif g["h"] is not None:
            hours = _hour(int(g["h"]), int(g["m"] or 0), g["ap"], now, on)
            after = bool(g["after"])
        else:
            hours = _hour(int(g["h2"] or g["h3"]), int(g["m2"] or 0), "", now, on)
            after = bool(g["after2"])
        if 0 <= hours < 24:
            words.append(clock_m.group(0).strip())
            start = _at(day or today, hours, now)
            return When(start, start + CLOCK_EVENT, " ".join(words), "clock", after)
    if not part and after_part is not None:  # "after work": about half five
        words.append(after_part.group(0))
        start = _at(day or today, AFTER_HOURS[after_part.group("what").lower()], now)
        return When(start, start + CLOCK_EVENT, " ".join(words), "clock")
    if not part and day is None and IN_THE_MORNING.search(text):
        day, part = (today if early else today + timedelta(days=1)), "morning"
        words.append(IN_THE_MORNING.search(text).group(0))
    if day is None and not part:
        return None
    day = day or today
    if part:
        start, end = _part(day, part, now, wake)
        return When(start, end, " ".join(words), "part", after, part)
    start = _at(day, _wake(wake), now)
    return When(start, _at(day, PARTS["evening"][1], now), " ".join(words), span or "day")


def follow_up(w: When, wake: str = "07:00") -> datetime:
    """When to ask how something went: once it's over. An afternoon thing is asked
    about that evening, an evening or a whole day the next morning, a weekend on
    Monday morning, a week the Monday after."""
    like = w.start
    if w.span == "clock":
        return w.end
    if w.span == "part" and w.part in ("morning", "lunchtime", "arvo"):
        return w.end
    if w.span == "weekend":
        return _at(w.end.date() + timedelta(days=1), _wake(wake), like)
    if w.span == "week":
        return _at(w.end.date() + timedelta(days=1), _wake(wake), like)
    return _at(w.start.date() + timedelta(days=1), _wake(wake), like)


def asked_for(w: When, now: datetime, wake: str = "07:00") -> datetime:
    """When Dan asked to be asked: "ask me this arvo" is the start of the arvo,
    "check in after my 2 pm" about 2:30, "after work" the end of it. A time already
    gone today means tomorrow; a part of the day already under way ("remind me
    tonight", said at 8 pm) means now."""
    if w.span == "clock":
        due = w.start + AFTER_CLOCK if w.after else w.start
    elif w.after:
        due = w.end
    elif w.span == "weekend":
        due = w.start + timedelta(hours=2)
    else:
        due = w.start
    today = w.start.date() == now.date()
    if today and w.span == "clock" and due < now - timedelta(minutes=5):
        due += timedelta(days=1)
    elif today and w.span == "part" and w.end <= now:
        due += timedelta(days=1)
    return max(due, now)


def date_in(text: str, now: datetime) -> date | None:
    """A calendar date written in ``text`` ("27 October 2026", "October 27",
    "2026-10-27", "the 15th"), else a day word ("Thursday", "tomorrow")."""
    written = _date_written(text, now)
    if written is not None:
        return written
    w = find_when(text, now)
    return w.start.date() if w is not None else None


def strip_when(text: str) -> str:
    """``text`` without its time words: "dentist Thursday arvo" is "dentist"."""
    for pattern in (DAY_WORDS, CLOCK, AFTER_PART, IN_THE_MORNING, DATE, ORDINAL, NEXT_WEEK):
        text = pattern.sub(" ", text)
    return " ".join(text.split())


def label(w: When) -> str:
    """When, in words that stay true as the days go by: "Thursday afternoon",
    "Thursday at 2:00 pm", "the weekend of 10 October"."""
    day = f"{w.start:%A}"
    if w.span == "clock":
        return f"{day} at {_clock(w.start)}"
    if w.span == "part":
        return f"{day} {PART_SHOWN.get(w.part, w.part)}"
    if w.span == "weekend":
        return f"the weekend of {w.start.day} {w.start:%B}"
    if w.span == "week":
        return f"the week of {w.start.day} {w.start:%B}"
    return day


def on_day(day: date, part: str, like: datetime, wake: str = "07:00") -> When:
    """A When for ``day`` and a part of it ("morning", "arvo", "evening", "night";
    anything else is the whole day), e.g. from a date the reflection gave."""
    part = PART_NAMES.get(part.lower().strip(), "")
    if part:
        start, end = _part(day, part, like, wake)
        return When(start, end, f"{day:%A} {PART_SHOWN[part]}", "part", part=part)
    start = _at(day, _wake(wake), like)
    return When(start, _at(day, PARTS["evening"][1], like), f"{day:%A}", "day")
