from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from livekit.agents import function_tool, llm

_WEEKDAYS = {
    "pt": (
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo",
    ),
    "en": (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ),
}


def build_time_tool(
    timezone: str,
    language: str = "pt",
    now: Callable[[], datetime] | None = None,
) -> llm.Tool:
    zone = ZoneInfo(timezone)
    weekdays = _WEEKDAYS.get(language, _WEEKDAYS["en"])

    def current_time() -> datetime:
        if now is not None:
            value = now()
            return value.astimezone(zone) if value.tzinfo else value.replace(tzinfo=zone)
        return datetime.now(zone)

    @function_tool(name="get_current_datetime")
    async def get_current_datetime() -> dict[str, Any]:
        """Get the current local date, time, weekday and timezone.

        Use whenever the answer depends on what day or time it is now, such as
        "today", "tomorrow" or the current weekday.
        """
        current = current_time()
        return {
            "iso": current.isoformat(),
            "date": current.date().isoformat(),
            "time": current.strftime("%H:%M"),
            "weekday": weekdays[current.weekday()],
            "timezone": timezone,
            "utc_offset": current.strftime("%z"),
        }

    return get_current_datetime
