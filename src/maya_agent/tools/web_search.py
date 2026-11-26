from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp
from livekit.agents import ToolError, function_tool, llm, utils

from ..config import WebSearchSettings

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


def _clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


class TavilySearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        request: RequestFn | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._request = request

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

        answer = _clean_text(str(data.get("answer") or ""))
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in data.get("results", [])[:limit]:
            url = _clean_text(str(item.get("url") or ""))
            if not url or url in seen:
                continue

            seen.add(url)
            title = _clean_text(str(item.get("title") or "")) or url
            snippet = _clean_text(str(item.get("content") or item.get("snippet") or ""))
            results.append(SearchResult(title=title, url=url, snippet=snippet))

        return SearchResponse(
            answer=answer[:MAX_ANSWER_CHARS] if answer else None,
            results=results,
        )


async def search_web(client: WebSearchClient, query: str, max_results: int) -> dict[str, Any]:
    cleaned_query = _clean_text(query)
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
                "title": result.title[:200],
                "url": result.url,
                "snippet": result.snippet[:MAX_SNIPPET_CHARS],
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
