from __future__ import annotations

import pytest
from livekit.agents import ToolError

from maya_agent.config import WebSearchSettings
from maya_agent.tools.web_search import (
    SearchResponse,
    SearchResult,
    TavilySearchClient,
    WebSearchError,
    build_tools,
    search_web,
)


class FakeClient:
    def __init__(
        self,
        response: SearchResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or SearchResponse(answer=None, results=[])
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int) -> SearchResponse:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_search_web_normalizes_and_truncates() -> None:
    client = FakeClient(
        SearchResponse(
            answer="Resposta curta.",
            results=[SearchResult("Title", "https://example.com", "a" * 500)],
        )
    )

    result = await search_web(client, "  notícias   de hoje  ", 3)

    assert result["query"] == "notícias de hoje"
    assert result["answer"] == "Resposta curta."
    assert result["results"][0]["snippet"] == "a" * 400
    assert client.calls == [("notícias de hoje", 3)]


@pytest.mark.asyncio
async def test_search_web_limits_results() -> None:
    client = FakeClient(
        SearchResponse(
            answer=None,
            results=[
                SearchResult("A", "https://a.test", "a"),
                SearchResult("B", "https://b.test", "b"),
            ],
        )
    )

    result = await search_web(client, "teste", 1)

    assert len(result["results"]) == 1
    assert result["results"][0]["url"] == "https://a.test"


@pytest.mark.asyncio
async def test_search_web_empty_query_raises_tool_error() -> None:
    with pytest.raises(ToolError):
        await search_web(FakeClient(), "   ", 3)


@pytest.mark.asyncio
async def test_search_web_client_error_raises_tool_error() -> None:
    with pytest.raises(ToolError):
        await search_web(FakeClient(error=WebSearchError("offline")), "teste", 3)


@pytest.mark.asyncio
async def test_search_web_empty_response_is_valid() -> None:
    result = await search_web(FakeClient(), "sem resultados", 3)

    assert result["answer"] is None
    assert result["results"] == []


@pytest.mark.asyncio
async def test_tavily_client_normalizes_and_builds_payload() -> None:
    seen_payloads: list[dict[str, object]] = []

    async def request(payload: dict[str, object]) -> dict[str, object]:
        seen_payloads.append(payload)
        return {
            "answer": "  Ibovespa subiu 1,58%.  ",
            "results": [
                {"title": "A", "url": "https://a.test", "content": " primeiro "},
                {"title": "A duplicado", "url": "https://a.test", "content": "ignorar"},
                {"title": "B", "url": "https://b.test", "content": "segundo"},
                {"title": "Sem URL", "content": "ignorar"},
            ],
        }

    client = TavilySearchClient(api_key="test-key", timeout_seconds=8, request=request)

    response = await client.search("mercado hoje", 3)

    assert response.answer == "Ibovespa subiu 1,58%."
    assert [result.url for result in response.results] == [
        "https://a.test",
        "https://b.test",
    ]
    assert response.results[0].snippet == "primeiro"
    assert seen_payloads == [
        {
            "query": "mercado hoje",
            "max_results": 3,
            "search_depth": "fast",
            "include_answer": "basic",
            "include_raw_content": False,
            "include_images": False,
        }
    ]


@pytest.mark.asyncio
async def test_tavily_client_propagates_search_errors() -> None:
    async def request(payload: dict[str, object]) -> dict[str, object]:
        raise WebSearchError("rate limited")

    client = TavilySearchClient(api_key="test-key", timeout_seconds=8, request=request)

    with pytest.raises(WebSearchError):
        await client.search("teste", 3)


def test_tavily_headers_use_bearer_when_key_is_present() -> None:
    client = TavilySearchClient(api_key="test-key", timeout_seconds=8)

    headers = client._headers()

    assert headers["Authorization"] == "Bearer test-key"
    assert "X-Tavily-Access-Mode" not in headers


def test_tavily_headers_use_keyless_mode_without_key() -> None:
    client = TavilySearchClient(api_key="", timeout_seconds=8)

    headers = client._headers()

    assert headers["X-Tavily-Access-Mode"] == "keyless"
    assert "Authorization" not in headers


def test_build_tools_returns_nothing_when_disabled() -> None:
    settings = WebSearchSettings(enabled=False, api_key="", max_results=3, timeout_seconds=8)

    assert build_tools(settings) == []


def test_build_tools_exposes_web_search_when_enabled() -> None:
    settings = WebSearchSettings(enabled=True, api_key="test-key", max_results=3, timeout_seconds=8)

    tools = build_tools(settings)

    assert len(tools) == 1
    assert tools[0].info.name == "web_search"
