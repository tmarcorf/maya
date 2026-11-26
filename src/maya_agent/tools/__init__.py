from __future__ import annotations

from livekit.agents import llm

from ..config import AppSettings
from .market import build_market_tool
from .weather import build_weather_tool
from .web_extract import build_web_extract_tool
from .web_search import build_web_search_tool

__all__ = ["build_tools"]


def build_tools(settings: AppSettings) -> list[llm.Tool]:
    tools: list[llm.Tool] = []

    if settings.web_search.enabled:
        tools.append(build_web_search_tool(settings.web_search))

    if settings.web_extract.enabled:
        tools.append(
            build_web_extract_tool(
                settings.web_extract,
                settings.web_search.api_key,
            )
        )

    tools.append(build_weather_tool())
    tools.append(build_market_tool())
    return tools
