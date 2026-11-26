from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp
from livekit.agents import ToolError, function_tool, llm, utils

from ..config import WebExtractSettings
from .cache import TTLCache
from .text import clean_text, normalize_url, truncate

logger = logging.getLogger("maya.web_extract")

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


class WebExtractError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ExtractResult:
    url: str
    title: str
    content: str


class WebExtractClient(Protocol):
    async def extract(self, urls: list[str]) -> list[ExtractResult]: ...


RequestFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class TavilyExtractClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_chars: int,
        request: RequestFn | None = None,
        cache_ttl_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_chars = max_chars
        self._request = request
        self._cache: TTLCache[tuple[str, ...], list[ExtractResult]] | None = (
            TTLCache(cache_ttl_seconds, clock=clock) if cache_ttl_seconds > 0 else None
        )

    def _headers(self) -> dict[str, str]:
        headers = {"X-Client-Name": "maya-agent"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            headers["X-Tavily-Access-Mode"] = "keyless"
        return headers

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = utils.http_context.http_session()
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        async with session.post(
            TAVILY_EXTRACT_URL,
            json=payload,
            headers=self._headers(),
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                body = await response.text()
                raise WebExtractError(
                    f"Tavily extract returned HTTP {response.status}: {body[:300]}"
                )
            try:
                return await response.json()
            except Exception as exc:
                raise WebExtractError("Tavily extract returned invalid JSON") from exc

    async def extract(self, urls: list[str]) -> list[ExtractResult]:
        cache_key = tuple(urls)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        payload = {
            "urls": urls,
            "include_images": False,
            "extract_depth": "basic",
        }

        request = self._request or self._post
        try:
            data = await request(payload)
        except WebExtractError:
            raise
        except Exception as exc:
            raise WebExtractError(str(exc)) from exc

        raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            raise WebExtractError("Tavily extract returned no results")

        results: list[ExtractResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            url = clean_text(item.get("url"))
            content = clean_text(item.get("raw_content") or item.get("content"))
            if not url or not content:
                continue

            results.append(
                ExtractResult(
                    url=url,
                    title=clean_text(item.get("title")) or url,
                    content=truncate(content, self._max_chars),
                )
            )

        if not results:
            raise WebExtractError("Tavily extract returned no usable content")

        if self._cache is not None:
            self._cache.set(cache_key, results)
        return results


async def extract_web(
    client: WebExtractClient,
    urls: list[str],
    max_urls: int,
    max_chars: int,
) -> dict[str, Any]:
    cleaned_urls: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        url = normalize_url(raw_url)
        if url is None or url in seen:
            continue
        seen.add(url)
        cleaned_urls.append(url)
        if len(cleaned_urls) >= max_urls:
            break

    if not cleaned_urls:
        raise ToolError("Envie pelo menos uma URL http ou https válida para extrair.")

    started_at = time.perf_counter()
    try:
        results = await client.extract(cleaned_urls)
    except WebExtractError as exc:
        logger.warning("web_extract failed: %s", exc)
        raise ToolError("Não consegui extrair o conteúdo dessa página agora.") from exc
    except Exception as exc:
        logger.exception("web_extract unexpected failure")
        raise ToolError("Não consegui extrair o conteúdo dessa página agora.") from exc

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "web_extract pages=%d latency_ms=%.0f urls=%d",
        len(results),
        elapsed_ms,
        len(cleaned_urls),
    )

    return {
        "pages": [
            {
                "url": result.url,
                "title": truncate(result.title, 200),
                "content": truncate(result.content, max_chars),
            }
            for result in results
        ]
    }


def build_web_extract_tool(
    settings: WebExtractSettings,
    api_key: str,
    client: WebExtractClient | None = None,
) -> llm.Tool:
    extract_client = client or TavilyExtractClient(
        api_key=api_key,
        timeout_seconds=settings.timeout_seconds,
        max_chars=settings.max_chars,
        cache_ttl_seconds=settings.cache_ttl_minutes * 60,
    )

    @function_tool(name="web_extract")
    async def web_extract(urls: list[str]) -> dict[str, Any]:
        """Extract readable content from one or two web pages.

        Use after web_search when the snippets are not enough to answer. Pass
        only the most relevant URLs, usually one or two. Returns the page title
        and truncated text content.
        """
        return await extract_web(
            extract_client,
            urls,
            settings.max_urls,
            settings.max_chars,
        )

    return web_extract
