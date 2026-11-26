from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from livekit.agents import ToolError

from maya_agent.tools.market import (
    MARKET_UNAVAILABLE_ERROR,
    build_market_tool,
    chart_url,
)

MARKET_TIME = 1764100000

MARKET_META: dict[str, dict[str, Any]] = {
    "^BVSP": {
        "shortName": "Ibovespa",
        "symbol": "^BVSP",
        "regularMarketPrice": 130000.0,
        "regularMarketChange": 500.0,
        "regularMarketChangePercent": 0.39,
        "currency": "BRL",
        "regularMarketTime": MARKET_TIME,
    },
    "^GSPC": {
        "longName": "S&P 500",
        "symbol": "^GSPC",
        "regularMarketPrice": 6000.0,
        "regularMarketChange": -10.0,
        "regularMarketChangePercent": -0.17,
        "currency": "USD",
        "regularMarketTime": MARKET_TIME + 1,
    },
    "^IXIC": {
        "shortName": "Nasdaq",
        "symbol": "^IXIC",
        "regularMarketPrice": 19000.0,
        "regularMarketChange": 25.0,
        "regularMarketChangePercent": 0.13,
        "currency": "USD",
        "regularMarketTime": MARKET_TIME + 2,
    },
    "^DJI": {
        "shortName": "Dow Jones",
        "symbol": "^DJI",
        "regularMarketPrice": 44000.0,
        "regularMarketChange": 100.0,
        "regularMarketChangePercent": 0.23,
        "currency": "USD",
        "regularMarketTime": MARKET_TIME + 3,
    },
}


def _payload(meta: dict[str, Any]) -> dict[str, Any]:
    return {"chart": {"result": [{"meta": meta}], "error": None}}


@pytest.mark.asyncio
async def test_market_success_returns_all_four_indices() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, params))
        for symbol, meta in MARKET_META.items():
            if url == chart_url(symbol):
                return _payload(meta)
        raise AssertionError(f"unexpected URL: {url}")

    tool = build_market_tool(request=request)

    result = await tool()

    expected_as_of = datetime.fromtimestamp(MARKET_TIME, tz=UTC).isoformat()
    assert result["as_of"] == expected_as_of
    assert result["indices"] == [
        {
            "name": "Ibovespa",
            "symbol": "^BVSP",
            "price": 130000.0,
            "change": 500.0,
            "change_percent": 0.39,
            "currency": "BRL",
        },
        {
            "name": "S&P 500",
            "symbol": "^GSPC",
            "price": 6000.0,
            "change": -10.0,
            "change_percent": -0.17,
            "currency": "USD",
        },
        {
            "name": "Nasdaq",
            "symbol": "^IXIC",
            "price": 19000.0,
            "change": 25.0,
            "change_percent": 0.13,
            "currency": "USD",
        },
        {
            "name": "Dow Jones",
            "symbol": "^DJI",
            "price": 44000.0,
            "change": 100.0,
            "change_percent": 0.23,
            "currency": "USD",
        },
    ]
    assert [call[0] for call in calls] == [
        chart_url("^BVSP"),
        chart_url("^GSPC"),
        chart_url("^IXIC"),
        chart_url("^DJI"),
    ]
    assert all(call[1] == {"interval": "1d", "range": "1d"} for call in calls)


@pytest.mark.asyncio
async def test_market_chart_error_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"chart": {"result": None, "error": {"code": "Not Found"}}}

    tool = build_market_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool()

    assert str(exc_info.value) == MARKET_UNAVAILABLE_ERROR


@pytest.mark.asyncio
async def test_market_missing_data_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"chart": {"result": [], "error": None}}

    tool = build_market_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool()

    assert str(exc_info.value) == MARKET_UNAVAILABLE_ERROR


@pytest.mark.asyncio
async def test_market_missing_price_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return _payload({"shortName": "Ibovespa", "symbol": "^BVSP"})

    tool = build_market_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool()

    assert str(exc_info.value) == MARKET_UNAVAILABLE_ERROR


@pytest.mark.asyncio
async def test_market_partial_failure_raises_tool_error_without_partial_result() -> None:
    calls: list[str] = []

    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        if url == chart_url("^BVSP"):
            return _payload(MARKET_META["^BVSP"])
        raise RuntimeError("second index failed")

    tool = build_market_tool(request=request)

    with pytest.raises(ToolError) as exc_info:
        await tool()

    assert str(exc_info.value) == MARKET_UNAVAILABLE_ERROR
    assert calls == [chart_url("^BVSP"), chart_url("^GSPC")]
