from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import aiohttp
from livekit.agents import ToolError, function_tool, llm
from livekit.agents.utils.http_context import http_session

from .text import clean_text, truncate

logger = logging.getLogger("maya.wikipedia")

REQUEST_TIMEOUT_SECONDS = 8.0
MAX_SUMMARY_CHARS = 1200

RequestFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class WikipediaError(Exception):
    pass


async def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    session = http_session()
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    headers = {"User-Agent": "maya-agent/0.1", "Accept": "application/json"}
    async with session.get(url, params=params, headers=headers, timeout=timeout) as response:
        if response.status >= 400:
            body = await response.text()
            raise WikipediaError(f"Wikipedia returned HTTP {response.status}: {body[:300]}")
        try:
            return await response.json()
        except Exception as exc:
            raise WikipediaError("Wikipedia returned invalid JSON") from exc


async def fetch_wikipedia(
    request: RequestFn,
    query: str,
    language: str,
) -> dict[str, Any]:
    cleaned_query = clean_text(query)
    if not cleaned_query:
        raise ToolError("Diga o que você quer procurar na Wikipedia.")

    base_url = f"https://{language}.wikipedia.org/w/api.php"
    try:
        search = await request(
            base_url,
            {
                "action": "query",
                "list": "search",
                "srsearch": cleaned_query,
                "srlimit": 1,
                "format": "json",
                "utf8": 1,
            },
        )
        results = (search.get("query") or {}).get("search") or []
        if not results:
            raise ToolError("Não encontrei um artigo sobre isso na Wikipedia.")
        title = clean_text(results[0].get("title"))
        if not title:
            raise ToolError("Não encontrei um artigo sobre isso na Wikipedia.")

        data = await request(
            base_url,
            {
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "titles": title,
                "redirects": 1,
                "format": "json",
                "utf8": 1,
            },
        )
    except ToolError:
        raise
    except Exception as exc:
        logger.warning("wikipedia request failed: %s", exc)
        raise ToolError("Não consegui consultar a Wikipedia agora.") from exc

    pages = (data.get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()), {}) if isinstance(pages, dict) else {}
    summary = clean_text(page.get("extract"))
    if not summary:
        raise ToolError("Não encontrei um resumo sobre isso na Wikipedia.")

    final_title = clean_text(page.get("title")) or title
    page_url = (
        f"https://{language}.wikipedia.org/wiki/{quote(final_title.replace(' ', '_'), safe='')}"
    )
    return {
        "title": final_title,
        "summary": truncate(summary, MAX_SUMMARY_CHARS),
        "url": page_url,
        "language": language,
    }


def build_wikipedia_tool(
    language: str,
    request: RequestFn | None = None,
) -> llm.Tool:
    request_fn = request or _request_json

    @function_tool(name="wikipedia")
    async def wikipedia(query: str) -> dict[str, Any]:
        """Look up a factual summary on Wikipedia.

        Use for encyclopedic facts about people, places, history, science and
        concepts. Prefer this over web search for stable background facts.
        """
        return await fetch_wikipedia(request_fn, query, language)

    return wikipedia
