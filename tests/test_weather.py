import asyncio

import httpx
import pytest

from kit.weather import Weather, WeatherError, describe

RICHMONDS = {
    "results": [
        {
            "name": "Richmond",
            "latitude": 54.4,
            "longitude": -1.74,
            "country": "United Kingdom",
            "admin1": "England",
            "population": 47000,
        },
        {
            "name": "Richmond",
            "latitude": -33.6,
            "longitude": 150.75,
            "country": "Australia",
            "admin1": "New South Wales",
            "population": 1900000,
        },
        {
            "name": "Richmond",
            "latitude": -42.73,
            "longitude": 147.44,
            "country": "Australia",
            "admin1": "Tasmania",
            "population": 3000,
        },
    ]
}

FORECAST = {
    "current": {
        "time": "2026-10-06T21:15",
        "temperature_2m": 16.4,
        "apparent_temperature": 15.1,
        "relative_humidity_2m": 72,
        "weather_code": 1,
        "wind_speed_10m": 11.2,
        "wind_gusts_10m": 20.0,
        "precipitation": 0.0,
    },
    "hourly": {
        "time": [f"2026-10-06T{h:02d}:00" for h in range(24)]
        + [f"2026-10-07T{h:02d}:00" for h in range(24)],
        "temperature_2m": [15.0 + (h % 24) / 4 for h in range(48)],
        "precipitation_probability": [10] * 48,
        "weather_code": [2] * 48,
    },
    "daily": {
        "time": ["2026-10-06", "2026-10-07", "2026-10-08"],
        "weather_code": [1, 61, 3],
        "temperature_2m_max": [24.2, 21.0, 22.5],
        "temperature_2m_min": [12.1, 13.4, 11.0],
        "precipitation_probability_max": [5, 70, 20],
        "precipitation_sum": [0.0, 4.2, 0.0],
        "uv_index_max": [7.1, 5.0, 6.4],
        "wind_speed_10m_max": [24.0, 41.5, 18.0],
    },
}


def weather_with(handler, seen=None):
    def record(request):
        if seen is not None:
            seen.append(request)
        return handler(request)

    return Weather(httpx.AsyncClient(transport=httpx.MockTransport(record)))


def server(request):
    if "geocoding" in request.url.host:
        return httpx.Response(200, json=RICHMONDS)
    return httpx.Response(200, json=FORECAST)


def test_today_carries_the_wind():
    seen = []
    weather = weather_with(server, seen)
    today = asyncio.run(weather.today("Richmond, NSW", "AU"))
    assert today.wind_kmh == 11.2 and today.now_c == 16.4
    tomorrow = asyncio.run(weather.today("Richmond, NSW", "AU", ahead=1))
    assert tomorrow.wind_kmh == 41.5 and tomorrow.sky == "light rain"
    asked = seen[-1].url.params
    assert "wind_speed_10m" in asked["current"] and "wind_speed_10m_max" in asked["daily"]
    assert asked["wind_speed_unit"] == "kmh"


def test_finds_richmond_nsw_not_england_or_tasmania():
    seen = []
    w = weather_with(server, seen)
    place = asyncio.run(w.find("Richmond, NSW", "AU"))
    assert place.name == "Richmond, New South Wales" and place.latitude == -33.6
    assert seen[0].url.params["name"] == "Richmond" and seen[0].url.params["countryCode"] == "AU"
    # Without a state hint, the biggest Richmond wins.
    assert asyncio.run(w.find("Richmond")).longitude == 150.75


def test_places_are_looked_up_once():
    seen = []
    w = weather_with(server, seen)
    asyncio.run(w.forecast("Richmond, NSW", "AU"))
    asyncio.run(w.forecast("Richmond, NSW", "AU"))
    assert [r.url.host for r in seen].count("geocoding-api.open-meteo.com") == 1


def test_forecast_reads_well():
    seen = []
    text = asyncio.run(weather_with(server, seen).forecast("Richmond, NSW", "AU"))
    assert seen[1].url.params["latitude"] == "-33.6"
    assert text.startswith("Forecast for Richmond, New South Wales from Open-Meteo")
    assert "Now: 16°C, feels like 15°C, mostly clear" in text
    assert "Next 24 hours:" in text and "Wed 12 AM" in text
    assert "Wednesday 07 Oct: light rain, 13°C to 21°C, 70% chance of rain (4.2 mm)" in text


def test_describe_copes_with_missing_parts():
    assert describe("Richmond", {}).startswith("Forecast for Richmond")


@pytest.mark.parametrize(
    "handler, words",
    [
        (lambda r: httpx.Response(500), r"error \(500\)"),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), "couldn't reach"),
        (lambda r: httpx.Response(200, json={"results": []}), "couldn't find"),
    ],
)
def test_failures_are_plain_words(handler, words):
    with pytest.raises(WeatherError, match=words):
        asyncio.run(weather_with(handler).forecast("Richmond, NSW"))


def test_no_location_set():
    with pytest.raises(WeatherError, match="persona.location"):
        asyncio.run(weather_with(server).forecast(""))
