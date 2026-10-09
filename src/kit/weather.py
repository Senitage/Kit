"""The weather, from Open-Meteo (free, no key; in Australia it blends the BOM's
own models with others).

Web search is poor at forecasts: the BOM blocks automated page reads and search
results are often days old. So Kit asks a forecast service directly when Dan
asks about the weather, then answers from the numbers, usually with the local
model, so it's quick and free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURS_AHEAD = 24
HOUR_STEP = 3  # one line every three hours keeps the prompt short
DAYS = 3

# WMO weather codes, as Open-Meteo reports them.
CODES = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with heavy hail",
}


class WeatherError(Exception):
    """No forecast. The message is said to Dan as is."""


@dataclass
class Place:
    name: str
    latitude: float
    longitude: float


@dataclass
class Today:
    """Today's weather in numbers, for Kit's own use (a pastime, the weather bet)."""

    place: str
    now_c: float | None
    sky: str
    top_c: float | None
    low_c: float | None
    rain_chance: int | None


class Weather:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._places: dict[tuple[str, str], Place] = {}

    async def forecast(self, place: str, country: str = "") -> str:
        """The forecast for ``place`` as plain lines for the prompt."""
        where = await self.find(place, country)
        data = await self._get(
            FORECAST_URL,
            {
                "latitude": where.latitude,
                "longitude": where.longitude,
                "timezone": "auto",
                "forecast_days": DAYS,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,wind_speed_10m,wind_gusts_10m,precipitation",
                "hourly": "temperature_2m,precipitation_probability,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum,uv_index_max",
                "wind_speed_unit": "kmh",
            },
        )
        return describe(where.name, data)

    async def today(self, place: str, country: str = "") -> Today:
        """Today's weather as numbers: now, the sky, and the top and low."""
        where = await self.find(place, country)
        data = await self._get(
            FORECAST_URL,
            {
                "latitude": where.latitude,
                "longitude": where.longitude,
                "timezone": "auto",
                "forecast_days": 1,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            },
        )
        cur = data.get("current") or {}
        daily = data.get("daily") or {}

        def first(key: str):
            values = daily.get(key) or [None]
            return values[0]

        return Today(
            where.name,
            cur.get("temperature_2m"),
            _sky(cur.get("weather_code")),
            first("temperature_2m_max"),
            first("temperature_2m_min"),
            first("precipitation_probability_max"),
        )

    async def find(self, place: str, country: str = "") -> Place:
        """Where ``place`` is. "Richmond, NSW" is looked up as Richmond, preferring a match
        whose state starts with WA's letters, within ``country`` if given."""
        key = (place.strip().lower(), country.upper())
        if key in self._places:
            return self._places[key]
        name, _, hint = (p.strip() for p in place.partition(","))
        if not name:
            raise WeatherError("I don't know where you are yet. Set persona.location.")
        params: dict = {"name": name, "count": 10, "language": "en", "format": "json"}
        if country:
            params["countryCode"] = country.upper()
        results = (await self._get(GEOCODE_URL, params)).get("results") or []
        if not results:
            raise WeatherError(f"I couldn't find {place} on the map.")
        best = _best_match(results, hint)
        region = best.get("admin1") or best.get("country") or ""
        found = Place(
            ", ".join(p for p in (best["name"], region) if p), best["latitude"], best["longitude"]
        )
        self._places[key] = found
        return found

    async def _get(self, url: str, params: dict) -> dict:
        try:
            response = await self.client.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise WeatherError(
                f"The forecast service returned an error ({e.response.status_code})."
            ) from e
        except (httpx.HTTPError, ValueError) as e:
            raise WeatherError("I couldn't reach the forecast service. Is the internet up?") from e


def _best_match(results: list[dict], hint: str) -> dict:
    """The result whose state matches the hint (WA matches Western Australia by its
    initials), else the most populous one."""
    if hint:
        h = hint.lower().replace(".", "")
        for r in results:
            admin = (r.get("admin1") or "").lower()
            initials = "".join(w[0] for w in admin.split() if w)
            if h in (admin, initials) or admin.startswith(h):
                return r
    return max(results, key=lambda r: r.get("population") or 0)


def describe(place: str, data: dict) -> str:
    """Open-Meteo's answer as short lines."""
    cur = data.get("current") or {}
    now = cur.get("time", "")
    lines = [f"Forecast for {place} from Open-Meteo, local time {_clock(now)}:"]
    if cur:
        lines.append(
            f"Now: {_deg(cur.get('temperature_2m'))}, feels like "
            f"{_deg(cur.get('apparent_temperature'))}, {_sky(cur.get('weather_code'))}, "
            f"humidity {cur.get('relative_humidity_2m')}%, wind "
            f"{_num(cur.get('wind_speed_10m'))} km/h gusting {_num(cur.get('wind_gusts_10m'))}, "
            f"rain in the last hour {cur.get('precipitation', 0)} mm."
        )
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    start = next((i for i, t in enumerate(times) if t >= now[:13]), 0) if now else 0
    picks = range(start + HOUR_STEP, min(start + HOURS_AHEAD + 1, len(times)), HOUR_STEP)
    if picks:
        lines.append("Next 24 hours:")
        for i in picks:
            lines.append(
                f"- {_when(times[i])}: {_deg(hourly['temperature_2m'][i])}, "
                f"{_sky(hourly['weather_code'][i])}, "
                f"{hourly['precipitation_probability'][i]}% chance of rain"
            )
    daily = data.get("daily") or {}
    days = daily.get("time") or []
    if days:
        lines.append("Days:")
    for i, day in enumerate(days):
        lines.append(
            f"- {_day(day)}: {_sky(daily['weather_code'][i])}, "
            f"{_deg(daily['temperature_2m_min'][i])} to {_deg(daily['temperature_2m_max'][i])}, "
            f"{daily['precipitation_probability_max'][i]}% chance of rain "
            f"({daily['precipitation_sum'][i]} mm), UV {_num(daily['uv_index_max'][i])}"
        )
    return "\n".join(lines)


def _sky(code) -> str:
    return CODES.get(code, "unknown sky")


def _deg(value) -> str:
    return f"{_num(value)}°C"


def _num(value) -> str:
    return "?" if value is None else f"{value:.0f}"


def _clock(stamp: str) -> str:
    try:
        return f"{datetime.fromisoformat(stamp):%a %d %b, %I:%M %p}"
    except ValueError:
        return "unknown"


def _when(stamp: str) -> str:
    return f"{datetime.fromisoformat(stamp):%a %I %p}"


def _day(stamp: str) -> str:
    return f"{datetime.fromisoformat(stamp):%A %d %b}"
