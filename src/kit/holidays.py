"""The shape of Dan's week: Monday, Friday and Saturday mornings, and WA public
holidays (``life.week_thoughts``).

Kit's sense of time knew the clock and the date, but not that Friday arvo feels
different from Monday morning, or that the Labour Day long weekend is coming.
``week_moment`` gives him a line for a private thought on those mornings
(kit.life.Life.think_now), so his inner life follows the week the way Dan's does.

Plain date maths, no network: the WA list is worked out for any year (Easter by
the usual algorithm), with the WA rules for a holiday that falls on a weekend.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

MORNING = (7, 11)  # the hours a "morning" thought fits in


def easter(year: int) -> date:
    """Easter Sunday (the anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def _nth_monday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def _last_monday(year: int, month: int) -> date:
    nxt = date(year + month // 12, month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=last.weekday())


def wa_holidays(year: int) -> dict[date, str]:
    """Western Australia's public holidays for ``year``. A holiday on a weekend gives
    the next weekday off as well (Christmas and Boxing Day push each other along)."""
    sunday = easter(year)
    days: dict[date, str] = {
        date(year, 1, 1): "New Year's Day",
        date(year, 1, 26): "Australia Day",
        _nth_monday(year, 3, 1): "Labour Day",
        sunday - timedelta(days=2): "Good Friday",
        sunday: "Easter Sunday",
        sunday + timedelta(days=1): "Easter Monday",
        date(year, 4, 25): "Anzac Day",
        _nth_monday(year, 6, 1): "WA Day",
        _last_monday(year, 9): "the King's Birthday",
        date(year, 12, 25): "Christmas Day",
        date(year, 12, 26): "Boxing Day",
    }
    for day, name in sorted(list(days.items())):
        if name in ("Easter Sunday",) or day.weekday() < 5:
            continue
        extra = day + timedelta(days=1)
        while extra.weekday() >= 5 or extra in days:
            extra += timedelta(days=1)
        days[extra] = f"the day off for {name}"
    return days


def holiday(day: date) -> str:
    """The WA public holiday on ``day``, or ""."""
    return wa_holidays(day.year).get(day, "")


def week_moment(now: datetime, owner: str) -> tuple[str, str] | None:
    """A moment in the week worth a thought this morning: (its key for today, a line
    for the thinking prompt), or None."""
    if not MORNING[0] <= now.hour < MORNING[1]:
        return None
    today = now.date()
    name = holiday(today)
    if name:
        return (
            f"holiday {today.isoformat()}",
            f"It's {name}, a public holiday in WA: no work for most people today.",
        )
    friday = today.weekday() == 4
    ahead = holiday(today + timedelta(days=3 if friday else 1))
    if ahead and today.weekday() < 5:
        return (
            f"eve {today.isoformat()}",
            f"{'Monday' if friday else 'Tomorrow'} is {ahead}, a public holiday in WA: "
            f"{'a long weekend' if friday else 'a day off'} is coming.",
        )
    line = {
        0: f"It's Monday morning: the start of {owner}'s week.",
        4: "It's Friday: the weekend's nearly here.",
        5: "It's Saturday morning: the weekend.",
    }.get(today.weekday())
    return (f"week {today.isoformat()}", line) if line else None
