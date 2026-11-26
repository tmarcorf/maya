from __future__ import annotations

from typing import Any

import pytest
from livekit.agents import ToolError

from maya_agent.tools.wikipedia import build_wikipedia_tool


def _search_payload(title: str = "Berlim") -> dict[str, Any]:
    return {"query": {"search": [{"title": title}]}}


def _page_payload(
    title: str = "Berlim", extract: str = "Berlim é a capital da Alemanha."
) -> dict[str, Any]:
    return {"query": {"pages": {"1": {"title": title, "extract": extract}}}}


@pytest.mark.asyncio
async def test_wikipedia_success_returns_summary_and_url() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append((url, params))
        if params.get("list") == "search":
            return _search_payload()
        return _page_payload()

    tool = build_wikipedia_tool("pt", request=request)

    result = await tool(query="  capital da Alemanha  ")

    assert result == {
        "title": "Berlim",
        "summary": "Berlim é a capital da Alemanha.",
        "url": "https://pt.wikipedia.org/wiki/Berlim",
        "language": "pt",
    }
    assert calls[0][0] == "https://pt.wikipedia.org/w/api.php"
    assert calls[0][1]["srsearch"] == "capital da Alemanha"
    assert calls[1][1]["titles"] == "Berlim"


@pytest.mark.asyncio
async def test_wikipedia_encodes_title_url() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("list") == "search":
            return _search_payload("São Paulo")
        return _page_payload("São Paulo", "São Paulo é uma cidade.")

    result = await build_wikipedia_tool("pt", request=request)(query="São Paulo")

    assert result["url"] == "https://pt.wikipedia.org/wiki/S%C3%A3o_Paulo"


@pytest.mark.asyncio
async def test_wikipedia_without_results_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"query": {"search": []}}

    with pytest.raises(ToolError):
        await build_wikipedia_tool("pt", request=request)(query="inexistente")


@pytest.mark.asyncio
async def test_wikipedia_without_extract_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("list") == "search":
            return _search_payload()
        return {"query": {"pages": {"1": {"title": "Berlim", "extract": ""}}}}

    with pytest.raises(ToolError):
        await build_wikipedia_tool("pt", request=request)(query="Berlim")


@pytest.mark.asyncio
async def test_wikipedia_request_error_raises_tool_error() -> None:
    async def request(url: str, params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("offline")

    with pytest.raises(ToolError):
        await build_wikipedia_tool("pt", request=request)(query="Berlim")
