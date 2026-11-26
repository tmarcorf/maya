from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp
from livekit.agents import ToolError, function_tool, llm, utils

from ..config import WebSearchSettings
from .cache import TTLCache
from .text import clean_text, truncate

logger = logging.getLogger("maya.web_search")

MAX_QUERY_CHARS = 300
MAX_SNIPPET_CHARS = 400
MAX_ANSWER_CHARS = 1200
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class WebSearchError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True, slots=True)
class SearchResponse:
    answer: str | None
    results: list[SearchResult]


class WebSearchClient(Protocol):
    async def search(self, query: str, limit: int) -> SearchResponse: ...


RequestFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class TavilySearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        request: RequestFn | None = None,
        cache_ttl_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._request = request
        self._cache: TTLCache[tuple[str, int], SearchResponse] | None = (
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
            TAVILY_SEARCH_URL,
            json=payload,
            headers=self._headers(),
            timeout=timeout,
        ) as response:
            if response.status >= 400:
                body = await response.text()
                raise WebSearchError(f"Tavily returned HTTP {response.status}: {body[:300]}")
            try:
                return await response.json()
            except Exception as exc:
                raise WebSearchError("Tavily returned invalid JSON") from exc

    async def search(self, query: str, limit: int) -> SearchResponse:
        limit = max(1, min(limit, 10))
        cache_key = (query, limit)
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        payload = {
            "query": query,
            "max_results": limit,
            "search_depth": "fast",
            "include_answer": "basic",
            "include_raw_content": False,
            "include_images": False,
        }

        request = self._request or self._post
        try:
            data = await request(payload)
        except WebSearchError:
            raise
        except Exception as exc:
            raise WebSearchError(str(exc)) from exc

        answer = clean_text(data.get("answer")) if isinstance(data, dict) else ""
        raw_results = data.get("results") if isinstance(data, dict) else None
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in raw_results[:limit] if isinstance(raw_results, list) else []:
            url = clean_text(item.get("url"))
            if not url or url in seen:
                continue

            seen.add(url)
            title = clean_text(item.get("title")) or url
            snippet = clean_text(item.get("content") or item.get("snippet"))
            results.append(SearchResult(title=title, url=url, snippet=snippet))

        response = SearchResponse(
            answer=truncate(answer, MAX_ANSWER_CHARS) if answer else None,
            results=results,
        )
        if self._cache is not None:
            self._cache.set(cache_key, response)
        return response


async def search_web(client: WebSearchClient, query: str, max_results: int) -> dict[str, Any]:
    cleaned_query = clean_text(query)
    if not cleaned_query:
        raise ToolError("Diga o que você quer pesquisar.")
    if len(cleaned_query) > MAX_QUERY_CHARS:
        cleaned_query = cleaned_query[:MAX_QUERY_CHARS].rstrip()

    started_at = time.perf_counter()
    try:
        response = await client.search(cleaned_query, max_results)
    except WebSearchError as exc:
        logger.warning("web_search failed: %s", exc)
        raise ToolError(
            "Não consegui pesquisar na web agora. Avise que não conseguiu verificar "
            "e não tente responder de memória."
        ) from exc
    except Exception as exc:
        logger.exception("web_search unexpected failure")
        raise ToolError(
            "Não consegui pesquisar na web agora. Avise que não conseguiu verificar "
            "e não tente responder de memória."
        ) from exc

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "web_search results=%d answer_chars=%d latency_ms=%.0f query_chars=%d",
        len(response.results),
        len(response.answer or ""),
        elapsed_ms,
        len(cleaned_query),
    )

    return {
        "query": cleaned_query,
        "answer": response.answer,
        "results": [
            {
                "title": truncate(result.title, 200),
                "url": result.url,
                "snippet": truncate(result.snippet, MAX_SNIPPET_CHARS),
            }
            for result in response.results[:max_results]
        ],
    }


def build_web_search_tool(
    settings: WebSearchSettings,
    client: WebSearchClient | None = None,
) -> llm.Tool:
    search_client = client or TavilySearchClient(
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
        cache_ttl_seconds=settings.cache_ttl_minutes * 60,
    )

    @function_tool(name="web_search")
    async def web_search(query: str) -> dict[str, Any]:
        """Search the web for recent news and general current information.

        Use when the user asks about recent events or facts that may have
        changed. Do not rely on it for live weather or market quotes; prefer a
        dedicated data tool when one is available. The query should be short and
        specific.
        """
        return await search_web(search_client, query, settings.max_results)

    return web_search


def build_tools(settings: WebSearchSettings) -> list[llm.Tool]:
    if not settings.enabled:
        return []
    return [build_web_search_tool(settings)]
