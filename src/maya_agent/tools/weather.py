from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from livekit.agents import ToolError, function_tool, llm
from livekit.agents.utils.http_context import http_session

logger = logging.getLogger("maya.weather")

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 8.0
CITY_NOT_FOUND_ERROR = "Não consegui encontrar o clima para essa cidade agora."
WEATHER_UNAVAILABLE_ERROR = "Não consegui obter os dados do clima agora."

RequestFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

_WMO_CONDITIONS = {
    0: "céu limpo",
    1: "predominantemente limpo",
    2: "parcialmente nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina com geada",
    51: "garoa leve",
    53: "garoa moderada",
    55: "garoa intensa",
    56: "garoa congelante leve",
    57: "garoa congelante intensa",
    61: "chuva leve",
    63: "chuva moderada",
    65: "chuva forte",
    66: "chuva congelante leve",
    67: "chuva congelante forte",
    71: "neve leve",
    73: "neve moderada",
    75: "neve forte",
    77: "grãos de neve",
    80: "pancadas de chuva leve",
    81: "pancadas de chuva moderada",
    82: "pancadas de chuva forte",
    85: "pancadas de neve leve",
    86: "pancadas de neve forte",
    95: "tempestade",
    96: "tempestade com granizo leve",
    99: "tempestade com granizo forte",
}


class WeatherError(Exception):
    pass


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def condition_from_wmo(code: int | None) -> str:
    if code is None:
        return "condições desconhecidas"
    return _WMO_CONDITIONS.get(code, "condições desconhecidas")


async def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    session = http_session()
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    async with session.get(url, params=params, timeout=timeout) as response:
        if response.status >= 400:
            body = await response.text()
            raise WeatherError(f"weather request failed with HTTP {response.status}: {body[:300]}")
        try:
            return await response.json()
        except Exception as exc:
            raise WeatherError("weather response was not valid JSON") from exc


async def fetch_weather(request: RequestFn, city: str) -> dict[str, Any]:
    query = _clean_text(city)
    if not query:
        raise ToolError(CITY_NOT_FOUND_ERROR)

    try:
        geocoding = await request(
            GEOCODING_URL,
            {"name": query, "count": 1, "language": "pt", "format": "json"},
        )
    except Exception as exc:
        logger.warning("weather geocoding request failed: %s", exc)
        raise ToolError(CITY_NOT_FOUND_ERROR) from exc

    results = geocoding.get("results") if isinstance(geocoding, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ToolError(CITY_NOT_FOUND_ERROR)

    location = results[0]
    latitude = _as_float(location.get("latitude"))
    longitude = _as_float(location.get("longitude"))
    if latitude is None or longitude is None:
        raise ToolError(CITY_NOT_FOUND_ERROR)

    try:
        forecast = await request(
            FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": (
                    "temperature_2m,apparent_temperature,weather_code,"
                    "wind_speed_10m,relative_humidity_2m"
                ),
                "timezone": "auto",
            },
        )
    except Exception as exc:
        logger.warning("weather forecast request failed: %s", exc)
        raise ToolError(WEATHER_UNAVAILABLE_ERROR) from exc

    current = forecast.get("current") if isinstance(forecast, dict) else None
    if not isinstance(current, dict):
        raise ToolError(WEATHER_UNAVAILABLE_ERROR)

    return {
        "city": _clean_text(location.get("name")) or query,
        "country": _clean_text(location.get("country")) or None,
        "temperature_c": _as_float(current.get("temperature_2m")),
        "feels_like_c": _as_float(current.get("apparent_temperature")),
        "condition": condition_from_wmo(_as_int(current.get("weather_code"))),
        "wind_kmh": _as_float(current.get("wind_speed_10m")),
        "humidity_percent": _as_float(current.get("relative_humidity_2m")),
        "observed_at": _clean_text(current.get("time")) or None,
    }


def build_weather_tool(request: RequestFn | None = None) -> llm.Tool:
    request_fn = request or _request_json

    @function_tool(name="get_weather")
    async def get_weather(city: str) -> dict[str, Any]:
        """Get the current weather for a city.

        Use when the user asks about the current weather, temperature or
        conditions in a specific place. Returns temperature, feels-like
        temperature, general condition, wind speed and humidity.
        """
        return await fetch_weather(request_fn, city)

    return get_weather
