"""What Kit's face shows besides his eyes (kit.shows)."""

import asyncio
from datetime import datetime

import pytest

from fakes import FakeWeather, collect, reply
from kit.settings import Settings
from kit.shows import asked_for, date_show, show_for, sky_kind, time_show, weather_show
from kit.weather import Today

HOME = "Richmond, NSW"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What time is it?", ("time", 0)),
        ("hey kit what's the time", ("time", 0)),
        ("What's the date today?", ("date", 0)),
        ("what day is it", ("date", 0)),
        ("What's the weather like?", ("weather", 0)),
        ("Is it going to rain tomorrow?", ("weather", 1)),
        ("What's the weather in Richmond?", ("weather", 0)),
        ("What's the temperature?", ("weather", 0)),
        ("What's the weather in Sydney?", None),  # not home: his face shows home
        ("Weather this weekend?", None),  # further than one picture can say
        ("What's the temperature of the leach tank?", None),
        ("What temperature does the leach tank run at?", None),
        ("Morning Kit", None),
        ("Have you got time for a quick question?", None),
    ],
)
def test_what_dan_asks_picks_the_show(text, expected):
    assert asked_for(text, HOME) == expected


def test_the_time_and_date_read_like_a_clock_and_a_calendar():
    now = datetime(2026, 10, 9, 15, 7)
    assert time_show(now) == {"kind": "time", "text": "3:07", "small": "pm"}
    assert time_show(datetime(2026, 10, 9, 0, 30))["text"] == "12:30"
    assert date_show(now) == {"kind": "date", "small": "FRI", "text": "9 OCT"}


def test_the_weather_shows_the_sky_and_a_temperature():
    today = Today("Richmond", 17.6, "light rain", 21.0, 9.0, 80)
    noon = datetime(2026, 10, 9, 12)
    assert weather_show(today, noon) == {
        "kind": "weather",
        "sky": "rain",
        "words": "light rain",
        "small": "",
        "text": "18°",
    }
    tomorrow = Today("Richmond", None, "clear", 26.0, 12.0, 0)
    assert weather_show(tomorrow, noon, ahead=1)["text"] == "26°"
    assert sky_kind("clear", night=True) == "moon"
    assert sky_kind("thunderstorms with hail") == "storm"
    assert sky_kind("partly cloudy") == "part_cloud"
    assert sky_kind("something new") == "cloud"


def test_a_hot_or_windy_dry_day_shows_as_one_and_rain_wins():
    noon = datetime(2026, 10, 9, 12)

    def sky(words, now_c, wind=None, hot_c=35.0, at=noon):
        return weather_show(Today("Richmond", now_c, words, 30.0, 9.0, 0, wind), at, hot_c=hot_c)

    assert sky("clear", 38.4)["sky"] == "hot" and sky("clear", 38.4)["text"] == "38°"
    assert sky("clear", 35.0)["sky"] == "hot"  # from the setting up
    assert sky("clear", 34.9)["sky"] == "sun"
    assert sky("clear", 31.0, hot_c=30.0)["sky"] == "hot"  # face.hot_c moves it
    assert sky("partly cloudy", 22.0, wind=35.0)["sky"] == "wind"
    assert sky("partly cloudy", 22.0, wind=34.0)["sky"] == "part_cloud"
    assert sky("clear", 37.0, wind=50.0)["sky"] == "hot"  # a hot windy day is still hot
    assert sky("heavy rain", 36.0, wind=60.0)["sky"] == "rain"
    assert sky("thunderstorms", 36.0, wind=60.0)["sky"] == "storm"
    assert sky("clear", 20.0, wind=40.0, at=datetime(2026, 10, 9, 22))["sky"] == "wind"
    assert sky("fog", 9.0)["sky"] == "fog" and sky("freezing fog", 2.0)["sky"] == "fog"
    assert sky_kind("light snow") == "rain"  # no snow in Richmond: it falls like rain


def test_a_weather_show_needs_the_forecast():
    now = datetime(2026, 10, 9, 12)
    assert asyncio.run(show_for("weather?", now, None, HOME)) is None
    show = asyncio.run(show_for("Will it rain tomorrow?", now, FakeWeather(), HOME, "AU"))
    assert show["sky"] == "rain" and show["text"] == "19°" and show["small"] == "tomorrow"


def test_the_brain_sends_a_show_with_the_reply(memory_brain):
    brain = memory_brain(reply("It's just after three."))
    events = collect(brain.chat("What's the time, Kit?"))
    kinds = [e["type"] for e in events]
    assert "show" in kinds and kinds.index("show") < kinds.index("reply")
    assert next(e for e in events if e["type"] == "show")["show"]["kind"] == "time"


def test_a_failed_forecast_shows_nothing_and_he_still_answers(memory_brain):
    brain = memory_brain(reply("Can't see the sky right now."))
    brain.weather = FakeWeather(fail=True)
    events = collect(brain.chat("What's the weather doing?"))
    kinds = [e["type"] for e in events]
    assert "show" not in kinds and "reply" in kinds


@pytest.fixture
def memory_brain(paths):
    from fakes import Clock, FakeAnthropic, FakeEmbedder, FakeModel, make_cloud
    from kit.brain import Brain
    from kit.memory import Memory
    from kit.recall import Recall

    memory = Memory(paths.state_dir / "memory.db", Clock())
    s = Settings.model_validate(
        {"memory": {"min_similarity": 0.3}, "persona": {"location": HOME, "country": "AU"}}
    )

    def make(*outputs, model=FakeModel):
        model = model(*outputs)
        recall = Recall(memory, FakeEmbedder(), lambda: s)
        return Brain(lambda: s, memory, model, make_cloud(memory, FakeAnthropic()), recall)

    yield make
    memory.close()


def test_a_forecast_that_lands_while_he_answers_is_still_shown(memory_brain):
    from fakes import FakeModel
    from kit.weather import Today

    class SlowWeather(FakeWeather):
        async def today(self, place, country="", ahead=0):
            await asyncio.sleep(0.05)  # done while he's answering, not before
            return Today(place, 17.0, "partly cloudy", 21.0, 9.0, 10)

    class SlowModel(FakeModel):
        async def stream(self, *args, **kwargs):
            await asyncio.sleep(0.2)
            async for part in super().stream(*args, **kwargs):
                yield part

    brain = memory_brain(reply("Partly cloudy, about 17."), model=SlowModel)
    brain.weather = SlowWeather()
    events = collect(brain.chat("What's the weather like today?"))
    kinds = [e["type"] for e in events]
    assert kinds.count("show") == 1 and kinds.index("show") > kinds.index("reply")
    assert next(e for e in events if e["type"] == "show")["show"]["text"] == "17°"
