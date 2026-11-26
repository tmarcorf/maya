from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import aiohttp
from livekit.agents import ToolError, function_tool, llm
from livekit.agents.utils.http_context import http_session

logger = logging.getLogger("maya.market")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
REQUEST_TIMEOUT_SECONDS = 8.0
MARKET_UNAVAILABLE_ERROR = "Não consegui obter os dados de mercado agora."

MARKET_INDICES: tuple[tuple[str, str], ...] = (
    ("Ibovespa", "^BVSP"),
    ("S&P 500", "^GSPC"),
    ("Nasdaq", "^IXIC"),
    ("Dow Jones", "^DJI"),
)

RequestFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MarketError(Exception):
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


def chart_url(symbol: str) -> str:
    return f"{CHART_URL}/{quote(symbol, safe='')}"


def _format_as_of(value: Any) -> str | None:
    timestamp = _as_int(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


async def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    session = http_session()
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    headers = {"User-Agent": "Mozilla/5.0"}
    async with session.get(url, params=params, headers=headers, timeout=timeout) as response:
        if response.status >= 400:
            body = await response.text()
            raise MarketError(f"market request failed with HTTP {response.status}: {body[:300]}")
        try:
            return await response.json()
        except Exception as exc:
            raise MarketError("market response was not valid JSON") from exc


def _extract_index(data: Any, name: str, symbol: str) -> tuple[dict[str, Any], Any]:
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict) or chart.get("error"):
        raise ToolError(MARKET_UNAVAILABLE_ERROR)

    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ToolError(MARKET_UNAVAILABLE_ERROR)

    meta = results[0].get("meta")
    if not isinstance(meta, dict):
        raise ToolError(MARKET_UNAVAILABLE_ERROR)

    price = _as_float(meta.get("regularMarketPrice"))
    if price is None:
        raise ToolError(MARKET_UNAVAILABLE_ERROR)

    change = _as_float(meta.get("regularMarketChange"))
    if change is None:
        change = _as_float(meta.get("fulldayChange"))
    if change is None:
        previous_close = _as_float(meta.get("chartPreviousClose"))
        if previous_close is not None:
            change = price - previous_close

    change_percent = _as_float(meta.get("regularMarketChangePercent"))
    if change_percent is None:
        change_percent = _as_float(meta.get("fulldayChangePercent"))

    index = {
        "name": (_clean_text(meta.get("shortName")) or _clean_text(meta.get("longName")) or name),
        "symbol": _clean_text(meta.get("symbol")) or symbol,
        "price": price,
        "change": change,
        "change_percent": change_percent,
        "currency": _clean_text(meta.get("currency")) or None,
    }
    return index, meta.get("regularMarketTime")


async def fetch_market_summary(request: RequestFn) -> dict[str, Any]:
    indices: list[dict[str, Any]] = []
    as_of: str | None = None

    for position, (name, symbol) in enumerate(MARKET_INDICES):
        try:
            data = await request(chart_url(symbol), {"interval": "1d", "range": "1d"})
        except Exception as exc:
            logger.warning("market request failed for %s: %s", symbol, exc)
            raise ToolError(MARKET_UNAVAILABLE_ERROR) from exc

        index, market_time = _extract_index(data, name, symbol)
        if position == 0:
            as_of = _format_as_of(market_time)
        indices.append(index)

    return {"as_of": as_of, "indices": indices}


def build_market_tool(request: RequestFn | None = None) -> llm.Tool:
    request_fn = request or _request_json

    @function_tool(name="get_market_summary")
    async def get_market_summary() -> dict[str, Any]:
        """Get a summary of the main Brazilian and US stock market indices.

        Use when the user asks how the stock market or the main indices are
        doing today. Returns the last price, change, change percentage and
        currency for Ibovespa, S&P 500, Nasdaq and Dow Jones.
        """
        return await fetch_market_summary(request_fn)

    return get_market_summary
