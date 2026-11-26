from __future__ import annotations

import pytest
from livekit.agents import ToolError

from maya_agent.config import WebExtractSettings
from maya_agent.tools.web_extract import (
    ExtractResult,
    TavilyExtractClient,
    WebExtractError,
    extract_web,
)


class FakeClient:
    def __init__(
        self,
        results: list[ExtractResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
        self.calls: list[list[str]] = []

    async def extract(self, urls: list[str]) -> list[ExtractResult]:
        self.calls.append(urls)
        if self.error is not None:
            raise self.error
        return self.results


@pytest.mark.asyncio
async def test_extract_web_normalizes_deduplicates_and_limits_urls() -> None:
    client = FakeClient(
        [
            ExtractResult("https://a.test", "A", "a" * 500),
            ExtractResult("https://b.test", "B", "b"),
        ]
    )

    result = await extract_web(
        client,
        [
            " https://a.test ",
            "https://a.test",
            "ftp://invalid.test",
            "https://b.test",
            "https://c.test",
        ],
        max_urls=2,
        max_chars=100,
    )

    assert client.calls == [["https://a.test", "https://b.test"]]
    assert result["pages"] == [
        {"url": "https://a.test", "title": "A", "content": "a" * 100},
        {"url": "https://b.test", "title": "B", "content": "b"},
    ]


@pytest.mark.asyncio
async def test_extract_web_requires_valid_url() -> None:
    with pytest.raises(ToolError):
        await extract_web(FakeClient(), ["ftp://invalid.test"], 2, 100)


@pytest.mark.asyncio
async def test_extract_web_client_error_raises_tool_error() -> None:
    with pytest.raises(ToolError):
        await extract_web(
            FakeClient(error=WebExtractError("offline")),
            ["https://example.com"],
            2,
            100,
        )


@pytest.mark.asyncio
async def test_tavily_extract_client_normalizes_payload_and_results() -> None:
    seen_payloads: list[dict[str, object]] = []

    async def request(payload: dict[str, object]) -> dict[str, object]:
        seen_payloads.append(payload)
        return {
            "results": [
                {
                    "url": "https://a.test",
                    "title": "  A  ",
                    "raw_content": "  conteúdo   a  ",
                },
                {
                    "url": "https://b.test",
                    "title": "",
                    "content": "b" * 500,
                },
                {"url": "https://empty.test", "title": "Empty", "raw_content": ""},
                {"title": "No URL", "raw_content": "ignored"},
            ]
        }

    client = TavilyExtractClient(
        api_key="test-key",
        timeout_seconds=8,
        max_chars=100,
        request=request,
    )

    results = await client.extract(["https://a.test", "https://b.test"])

    assert seen_payloads == [
        {
            "urls": ["https://a.test", "https://b.test"],
            "include_images": False,
            "extract_depth": "basic",
        }
    ]
    assert results == [
        ExtractResult("https://a.test", "A", "conteúdo a"),
        ExtractResult("https://b.test", "https://b.test", "b" * 100),
    ]


@pytest.mark.asyncio
async def test_tavily_extract_client_raises_when_no_usable_content() -> None:
    async def request(payload: dict[str, object]) -> dict[str, object]:
        return {"results": [{"url": "https://empty.test", "raw_content": ""}]}

    client = TavilyExtractClient(
        api_key="test-key",
        timeout_seconds=8,
        max_chars=100,
        request=request,
    )

    with pytest.raises(WebExtractError):
        await client.extract(["https://empty.test"])


@pytest.mark.asyncio
async def test_tavily_extract_client_caches_repeated_extractions() -> None:
    calls = 0

    async def request(payload: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"results": [{"url": "https://a.test", "title": "A", "raw_content": "content"}]}

    client = TavilyExtractClient(
        api_key="test-key",
        timeout_seconds=8,
        max_chars=100,
        request=request,
        cache_ttl_seconds=60,
    )

    first = await client.extract(["https://a.test"])
    second = await client.extract(["https://a.test"])

    assert first == second
    assert calls == 1


def test_tavily_extract_headers_use_bearer_when_key_is_present() -> None:
    settings = WebExtractSettings(
        enabled=True,
        max_urls=2,
        max_chars=100,
        timeout_seconds=8,
        cache_ttl_minutes=10,
    )
    client = TavilyExtractClient(
        api_key="test-key",
        timeout_seconds=settings.timeout_seconds,
        max_chars=settings.max_chars,
    )

    headers = client._headers()

    assert headers["Authorization"] == "Bearer test-key"
    assert "X-Tavily-Access-Mode" not in headers


def test_tavily_extract_headers_use_keyless_mode_without_key() -> None:
    client = TavilyExtractClient(
        api_key="",
        timeout_seconds=8,
        max_chars=100,
    )

    headers = client._headers()

    assert headers["X-Tavily-Access-Mode"] == "keyless"
    assert "Authorization" not in headers
