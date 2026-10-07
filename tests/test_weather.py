import asyncio

import httpx
import pytest

from kit.weather import Weather, WeatherError, describe

PERTHS = {
    "results": [
        {
            "name": "Perth",
            "latitude": 56.4,
            "longitude": -3.4,
            "country": "United Kingdom",
            "admin1": "Scotland",
            "population": 47000,
        },
        {
            "name": "Perth",
            "latitude": -31.95,
            "longitude": 115.86,
            "country": "Australia",
            "admin1": "Western Australia",
            "population": 1900000,
        },
        {
            "name": "Perth",
            "latitude": -41.57,
            "longitude": 147.17,
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
        return httpx.Response(200, json=PERTHS)
    return httpx.Response(200, json=FORECAST)


def test_finds_perth_wa_not_scotland_or_tasmania():
    seen = []
    w = weather_with(server, seen)
    place = asyncio.run(w.find("Perth, WA", "AU"))
    assert place.name == "Perth, Western Australia" and place.latitude == -31.95
    assert seen[0].url.params["name"] == "Perth" and seen[0].url.params["countryCode"] == "AU"
    # Without a state hint, the biggest Perth wins.
    assert asyncio.run(w.find("Perth")).longitude == 115.86


def test_places_are_looked_up_once():
    seen = []
    w = weather_with(server, seen)
    asyncio.run(w.forecast("Perth, WA", "AU"))
    asyncio.run(w.forecast("Perth, WA", "AU"))
    assert [r.url.host for r in seen].count("geocoding-api.open-meteo.com") == 1


def test_forecast_reads_well():
    seen = []
    text = asyncio.run(weather_with(server, seen).forecast("Perth, WA", "AU"))
    assert seen[1].url.params["latitude"] == "-31.95"
    assert text.startswith("Forecast for Perth, Western Australia from Open-Meteo")
    assert "Now: 16°C, feels like 15°C, mostly clear" in text
    assert "Next 24 hours:" in text and "Wed 12 AM" in text
    assert "Wednesday 07 Oct: light rain, 13°C to 21°C, 70% chance of rain (4.2 mm)" in text


def test_describe_copes_with_missing_parts():
    assert describe("Perth", {}).startswith("Forecast for Perth")


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
        asyncio.run(weather_with(handler).forecast("Perth, WA"))


def test_no_location_set():
    with pytest.raises(WeatherError, match="persona.location"):
        asyncio.run(weather_with(server).forecast(""))
