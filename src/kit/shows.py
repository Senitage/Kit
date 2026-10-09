"""What Kit's face can show besides his eyes: the time, the date, the weather.

Ask Kit the time and his eyes turn into the time; ask about the weather and it
rains on him (or the sun comes out) and his eyes show the temperature. The brain
decides from what Dan asked and sends a ``show`` event with the facts, so every
body draws the same thing its own way: the desk app paints it on Glow
(``kit.desk.scenes``), and the arm's face screen can later do the same.

Adding a show is two steps: a kind here (what Dan asks, and the facts to send)
and a scene in ``kit.desk.scenes`` (how it looks). A body that doesn't know a
kind just ignores it.

Shows are picked by words, not by the model, so they're instant and free, and
the facts (the clock, the forecast) are never made up.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from kit.weather import Today

TIME_Q = re.compile(
    r"\b(what'?s the time|what is the time|what time is it|what'?s the time now|"
    r"got the time|time is it|tell me the time|time check)\b",
    re.IGNORECASE,
)
DATE_Q = re.compile(
    r"\b(what'?s the date|what is the date|what date is it|today'?s date|"
    r"what day is it|what'?s today|what is today|what day of the week)\b",
    re.IGNORECASE,
)
WEATHER_Q = re.compile(
    r"\b(weather|forecast|umbrella|rain(ing|y)?|showers|sunny|windy|storms?|snow(ing)?|"
    r"how (hot|cold|warm) (is it|will it be|is it going to be)|"
    # "What's the temperature?", not "what's the temperature of the leach tank?"
    r"what'?s the temp(erature)?(?!\s+(of|in|on|at|for)\b))\b",
    re.IGNORECASE,
)
TOMORROW = re.compile(r"\b(tomorrow|tmrw)\b", re.IGNORECASE)
# Somewhere else ("the weather in Sydney"): his face shows home's weather, so none.
ELSEWHERE = re.compile(r"\b(?:in|at|for|over in|up in|down in) ([A-Z][a-zA-Z]+)")
# Days further off, or a week: one picture can't say that.
LATER = re.compile(
    r"\b(weekend|this week|next week|next few days|"
    r"(mon|tues|wednes|thurs|fri|satur|sun)day)\b",
    re.IGNORECASE,
)

# What the face draws, from the forecast's words (kit.weather.CODES).
SKIES = (
    ("thunder", "storm"),
    ("snow", "rain"),  # rare where Kit lives: something falling will do
    ("rain", "rain"),
    ("drizzle", "rain"),
    ("shower", "rain"),
    ("fog", "fog"),
    ("overcast", "cloud"),
    ("partly", "part_cloud"),
    ("mostly clear", "sun"),
    ("clear", "sun"),
)
NIGHT_FROM, NIGHT_UNTIL = 19, 6  # hours: a clear sky after dark shows the moon
WET = ("rain", "storm")  # skies that win over heat and wind
HOT_C = 35.0  # a hot day, unless the settings say (face.hot_c)
WINDY_KMH = 35.0  # a windy day: a strong breeze, the Fremantle Doctor on a good day


class Forecasts(Protocol):
    async def today(self, place: str, country: str = "", ahead: int = 0) -> Today: ...


def asked_for(text: str, home: str = "") -> tuple[str, int] | None:
    """The show Dan's message asks for, and for the weather how many days ahead,
    or None. "Weather in Sydney" and "this weekend" aren't shown: the face only
    does home, today or tomorrow."""
    if TIME_Q.search(text):
        return "time", 0
    if DATE_Q.search(text):
        return "date", 0
    if WEATHER_Q.search(text):
        if LATER.search(text):
            return None
        town = home.partition(",")[0].strip().lower()
        for place in ELSEWHERE.findall(text):
            if place.lower() != town:
                return None
        return "weather", 1 if TOMORROW.search(text) else 0
    return None


def time_show(now: datetime) -> dict:
    """The time as a clock reads it: "3:07" and "pm"."""
    hour = now.hour % 12 or 12
    return {
        "kind": "time",
        "text": f"{hour}:{now.minute:02d}",
        "small": "am" if now.hour < 12 else "pm",
    }


def date_show(now: datetime) -> dict:
    """The date: "THU" over "9 OCT"."""
    return {"kind": "date", "small": f"{now:%a}".upper(), "text": f"{now.day} {now:%b}".upper()}


def sky_kind(sky: str, night: bool = False) -> str:
    sky = sky.lower()
    kind = next((k for word, k in SKIES if word in sky), "cloud")
    if night and kind in ("sun", "part_cloud"):
        return "moon"
    return kind


def weather_show(today: Today, now: datetime, ahead: int = 0, hot_c: float = HOT_C) -> dict:
    """The sky and a temperature: now's for today, the top for tomorrow. A dry day
    at ``hot_c`` or more is "hot"; otherwise a dry one with wind is "wind"."""
    temp = today.now_c if ahead == 0 and today.now_c is not None else today.top_c
    night = ahead == 0 and (now.hour >= NIGHT_FROM or now.hour < NIGHT_UNTIL)
    sky = sky_kind(today.sky, night)
    if sky not in WET:
        if temp is not None and temp >= hot_c:
            sky = "hot"
        elif today.wind_kmh is not None and today.wind_kmh >= WINDY_KMH:
            sky = "wind"
    show = {
        "kind": "weather",
        "sky": sky,
        "words": today.sky,
        "small": "tomorrow" if ahead else "",
    }
    if temp is not None:
        show["text"] = f"{round(temp)}°"
    return show


async def show_for(
    text: str,
    now: datetime,
    weather: Forecasts | None,
    home: str,
    country: str = "",
    hot_c: float = HOT_C,
) -> dict | None:
    """What the face should show for Dan's message, with the facts, or None."""
    asked = asked_for(text, home)
    if asked is None:
        return None
    kind, ahead = asked
    if kind == "time":
        return time_show(now)
    if kind == "date":
        return date_show(now)
    if weather is None or not home:
        return None
    today = await weather.today(home, country, ahead=ahead)
    return weather_show(today, now, ahead, hot_c)
