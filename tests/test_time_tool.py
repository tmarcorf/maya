from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from maya_agent.tools.time_tool import build_time_tool


@pytest.mark.asyncio
async def test_time_tool_returns_local_datetime_in_portuguese() -> None:
    fixed = datetime(2026, 11, 25, 14, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
    tool = build_time_tool(
        "America/Sao_Paulo",
        language="pt",
        now=lambda: fixed,
    )

    result = await tool()

    assert result == {
        "iso": "2026-11-25T14:30:00-03:00",
        "date": "2026-11-25",
        "time": "14:30",
        "weekday": "quarta-feira",
        "timezone": "America/Sao_Paulo",
        "utc_offset": "-0300",
    }


@pytest.mark.asyncio
async def test_time_tool_uses_english_weekdays() -> None:
    fixed = datetime(2026, 11, 25, 14, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    tool = build_time_tool(
        "Europe/Berlin",
        language="en",
        now=lambda: fixed,
    )

    result = await tool()

    assert result["weekday"] == "Wednesday"
    assert result["timezone"] == "Europe/Berlin"
