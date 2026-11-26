from __future__ import annotations

from typing import Any

import pytest
from livekit.agents import ToolError

from maya_agent.tools.weather import (
    CITY_NOT_FOUND_ERROR,
    FORECAST_URL,
    GEOCODING_URL,
    WEATHER_UNAVAILABLE_ERROR,
    build_weather_forecast_tool,
    build_weather_tool,
)


def _location_payload() -> dict[str, Any]:
    return {
        "results": [
            {
                "name": "São Paulo",
                "country": "Brasil",
                "latitude": -23.55,
                "longitude": -46.63,
            }
        ]
    }


@pytest.mark.asyncio
async def test_weather_success_normalizes_response() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, params))
        if url == GEOCODING_URL:
            return _location_payload()
        assert url == FORECAST_URL
        return {
            "current": {
                "temperature_2m": 21.4,
                "apparent_temperature": 22.0,
                "weather_code": 2,
                "wind_speed_10m": 10.5,
                "relative_humidity_2m": 80,
                "time": "2026-11-25T15:00",
            }
        }

    tool = build_weather_tool(request=request)

    result = await tool(city="  São Paulo  ")

    assert result == {
        "city": "São Paulo",
        "country": "Brasil",
        "temperature_c": 21.4,
        "feels_like_c": 22.0,
        "condition": "parcialmente nublado",
        "wind_kmh": 10.5,
        "humidity_percent": 80.0,
        "observed_at": "2026-11-25T15:00",
    }
    assert calls[0] == (
        GEOCODING_URL,
        {"name": "São Paulo", "count": 1, "language": "pt", "format": "json"},
    )
    assert calls[1][0] == FORECAST_URL
    assert calls[1][1]["latitude"] == -23.55
    assert calls[1][1]["longitude"] == -46.63
    assert calls[1][1]["timezone"] == "auto"


@pytest.mark.asyncio
async def test_weather_handles_missing_current_fields_gracefully() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url == GEOCODING_URL:
            return _location_payload()
        return {"current": {"weather_code": 0}}

    result = await build_weather_tool(request=request)(city="São Paulo")

    assert result["temperature_c"] is None
    assert result["feels_like_c"] is None
    assert result["wind_kmh"] is None
    assert result["humidity_percent"] is None
    assert result["observed_at"] is None
    assert result["condition"] == "céu limpo"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, "céu limpo"),
        (1, "predominantemente limpo"),
        (2, "parcialmente nublado"),
        (3, "nublado"),
        (45, "neblina"),
        (51, "garoa leve"),
        (61, "chuva leve"),
        (71, "neve leve"),
        (80, "pancadas de chuva leve"),
        (95, "tempestade"),
        (99, "tempestade com granizo forte"),
        (123, "condições desconhecidas"),
    ],
)
@pytest.mark.asyncio
async def test_weather_maps_wmo_weather_code(code: int, expected: str) -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url == GEOCODING_URL:
            return _location_payload()
        return {"current": {"weather_code": code}}

    result = await build_weather_tool(request=request)(city="São Paulo")

    assert result["condition"] == expected


@pytest.mark.asyncio
async def test_weather_city_not_found_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"results": []}

    tool = build_weather_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool(city="Atlântida")

    assert str(exc_info.value) == CITY_NOT_FOUND_ERROR


@pytest.mark.asyncio
async def test_weather_missing_current_payload_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url == GEOCODING_URL:
            return _location_payload()
        return {"current": None}

    tool = build_weather_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool(city="São Paulo")

    assert str(exc_info.value) == WEATHER_UNAVAILABLE_ERROR


@pytest.mark.asyncio
async def test_weather_request_failure_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url == GEOCODING_URL:
            return _location_payload()
        raise RuntimeError("offline")

    tool = build_weather_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool(city="São Paulo")

    assert str(exc_info.value) == WEATHER_UNAVAILABLE_ERROR


@pytest.mark.asyncio
async def test_weather_forecast_normalizes_daily_data() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, params))
        if url == GEOCODING_URL:
            return _location_payload()
        return {
            "daily": {
                "time": ["2026-11-26", "2026-11-27"],
                "weather_code": [2, 61],
                "temperature_2m_max": [18.5, 16.0],
                "temperature_2m_min": [9.0, 8.0],
                "precipitation_probability_max": [20, 80],
                "wind_speed_10m_max": [12.0, 20.0],
            }
        }

    tool = build_weather_forecast_tool(request=request)

    result = await tool(city="Berlim", days=2)

    assert result == {
        "city": "São Paulo",
        "country": "Brasil",
        "days": [
            {
                "date": "2026-11-26",
                "condition": "parcialmente nublado",
                "max_c": 18.5,
                "min_c": 9.0,
                "precipitation_probability_percent": 20.0,
                "wind_max_kmh": 12.0,
            },
            {
                "date": "2026-11-27",
                "condition": "chuva leve",
                "max_c": 16.0,
                "min_c": 8.0,
                "precipitation_probability_percent": 80.0,
                "wind_max_kmh": 20.0,
            },
        ],
    }
    assert calls[1][0] == FORECAST_URL
    assert calls[1][1]["forecast_days"] == 2
    assert "daily" in calls[1][1]


@pytest.mark.asyncio
async def test_weather_forecast_missing_daily_data_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url == GEOCODING_URL:
            return _location_payload()
        return {"daily": None}

    tool = build_weather_forecast_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool(city="São Paulo")

    assert str(exc_info.value) == WEATHER_UNAVAILABLE_ERROR
