"""Integration between Pipecat and the Hermes Agent API server.

Hermes exposes an OpenAI-compatible streaming endpoint at
``POST {base_url}/chat/completions``, but its SSE stream also carries custom
events (``event: hermes.tool.progress``) that the OpenAI SDK would reject.
This module therefore consumes the stream directly with ``httpx`` and converts
text deltas into Pipecat LLM frames.

Conversation history lives exclusively in the Hermes session
(``X-Hermes-Session-Id``) — Pipecat only forwards the new user message on each
turn (spec §8). Tool progress events are logged as observability signals,
forwarded downstream as ``ToolActivityFrame`` control frames for UI mirroring,
and are never sent to the TTS (spec §15).

Validated against Hermes Agent v0.20.1 (``gateway/platforms/api_server.py``):
- SSE frame format: ``event: <name>\\ndata: <json>\\n\\n``
- tool progress: ``event: hermes.tool.progress`` with a JSON payload
- end of stream: ``data: [DONE]``
- keepalive: ``: keepalive`` comment lines
- session continuity: ``X-Hermes-Session-Id`` request header, echoed in the
  response headers; closing the HTTP connection cancels the agent turn.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from dataclasses import dataclass

import httpx
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from pipeline.frames import ToolActivityFrame
from utils.logging import log_metric

HERMES_TOOL_PROGRESS_EVENT = "hermes.tool.progress"
DONE_MARKER = "[DONE]"


# ---------------------------------------------------------------------------
# Pure SSE parsing (no I/O — unit-testable with plain strings)
# ---------------------------------------------------------------------------


@dataclass
class HermesSSEChunk:
    """A single SSE frame: optional ``event`` line plus joined ``data``."""

    event: str | None = None
    data: str = ""


@dataclass
class HermesChatChunk:
    """A parsed chat-completions chunk.

    Exactly one of ``text_delta`` / ``tool_progress`` / ``done`` carries a
    value for a meaningful chunk.
    """

    text_delta: str | None = None
    finish_reason: str | None = None
    done: bool = False
    tool_progress: dict | None = None


async def parse_sse_lines(
    lines: Iterable[str] | AsyncIterable[str],
) -> AsyncIterator[HermesSSEChunk]:
    """Group raw SSE lines into frames.

    Accepts either a sync or an async source of raw lines. Handles multi-line
    ``data:``, ignores comment/keepalive lines (``: ...``) and flushes a
    trailing frame without a final blank line.
    """
    event: str | None = None
    data_lines: list[str] = []

    if hasattr(lines, "__aiter__"):
        async_line_source = lines
        source = _wrap_async_lines(async_line_source)  # type: ignore[arg-type]
    else:
        source = _wrap_async_lines(lines)  # type: ignore[arg-type]

    async for raw in source:
        line = raw.rstrip("\r")
        if not line:  # blank line = frame boundary
            if data_lines or event:
                yield HermesSSEChunk(event=event, data="\n".join(data_lines))
                event, data_lines = None, []
            continue
        if line.startswith(":"):  # SSE comment / keepalive
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        # Other fields (id:, retry:) are ignored.

    if data_lines or event:
        yield HermesSSEChunk(event=event, data="\n".join(data_lines))


async def _wrap_async_lines(
    lines: Iterable[str] | AsyncIterable[str],
) -> AsyncIterator[str]:
    """Yield lines from either a sync or an async iterable."""
    if hasattr(lines, "__aiter__"):
        async for raw in lines:  # type: ignore[union-attr]
            yield raw
    else:
        for raw in lines:  # type: ignore[union-attr]
            yield raw


def parse_chat_chunk(chunk: HermesSSEChunk) -> HermesChatChunk:
    """Parse one SSE chunk into a HermesChatChunk.

    Tolerant by design: unknown or malformed payloads are skipped instead of
    raising, so a single unexpected event cannot kill the stream.
    """
    if chunk.data == DONE_MARKER:
        return HermesChatChunk(done=True)

    if chunk.event == HERMES_TOOL_PROGRESS_EVENT:
        try:
            payload = json.loads(chunk.data) if chunk.data else {}
        except json.JSONDecodeError:
            payload = {"raw": chunk.data}
        return HermesChatChunk(tool_progress=payload)

    try:
        payload = json.loads(chunk.data)
    except json.JSONDecodeError:
        logger.debug(f"Hermes: skipping unparseable SSE data: {chunk.data[:200]}")
        return HermesChatChunk()

    choices = payload.get("choices") or []
    if not choices:
        return HermesChatChunk()
    delta = choices[0].get("delta") or {}
    return HermesChatChunk(
        text_delta=delta.get("content"),
        finish_reason=choices[0].get("finish_reason"),
    )


# ---------------------------------------------------------------------------
# Session management — the Hermes session is the single source of truth (§8)
# ---------------------------------------------------------------------------


class HermesSessionManager:
    """Tracks the Hermes session id for one voice conversation.

    The first request is sent without ``X-Hermes-Session-Id`` (Hermes creates
    a session and echoes the id in the response headers); every subsequent
    request reuses the captured id.
    """

    def __init__(self, app_session_id: str) -> None:
        self._app_session_id = app_session_id
        self._hermes_session_id: str | None = None

    @property
    def app_session_id(self) -> str:
        return self._app_session_id

    def header_value(self) -> str | None:
        """Value for the ``X-Hermes-Session-Id`` request header, if known."""
        return self._hermes_session_id

    def set_session_id_from_response(self, header: str | None) -> None:
        if header and header.strip():
            self._hermes_session_id = header.strip()

    def current_hermes_session_id(self) -> str | None:
        return self._hermes_session_id


# ---------------------------------------------------------------------------
# The bridge: an LLMService that talks to Hermes over HTTP/SSE
# ---------------------------------------------------------------------------


class HermesLLMService(LLMService):
    """Streams Hermes Agent responses as Pipecat LLM frames.

    Only the new user message is forwarded per turn; the conversation history
    is owned by the Hermes session. Tool progress events are logged and
    filtered out before they could reach the TTS.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "hermes-agent",
        session_manager: HermesSessionManager | None = None,
        settings: LLMSettings | None = None,
        connect_timeout_secs: float = 10.0,
        **kwargs,
    ):
        settings = settings or LLMSettings(
            model=model,
            system_instruction=None,
            temperature=None,
            max_tokens=None,
            top_p=None,
            top_k=None,
            frequency_penalty=None,
            presence_penalty=None,
            seed=None,
            filter_incomplete_user_turns=False,
            user_turn_completion_config=None,
        )
        if not settings.model:
            settings.model = model
        super().__init__(settings=settings, **kwargs)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._session_manager = session_manager
        self._connect_timeout_secs = connect_timeout_secs

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Mirror ``BaseOpenAILLMService.process_frame``.

        On ``LLMContextFrame``: wrap the completion with
        ``LLMFullResponseStartFrame`` / ``LLMFullResponseEndFrame`` and
        processing metrics. Any other frame is passed through downstream.
        Interruption is handled by the pipeline machinery, which cancels the
        in-flight task running this method (``asyncio.CancelledError`` skips
        the ``except Exception`` clause and still runs the ``finally`` block).
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame):
            try:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.start_processing_metrics()
                await self._process_context(frame.context)
            except httpx.TimeoutException as e:
                await self.push_error(error_msg="Hermes completion timeout", exception=e)
            except Exception as e:  # noqa: BLE001 — same pattern as BaseOpenAILLMService: any failure must close the turn, never crash the pipeline
                await self.push_error(error_msg=f"Error during Hermes completion: {e}", exception=e)
            finally:
                await self.stop_processing_metrics()
                await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)

    async def _process_context(self, context: LLMContext) -> None:
        """Send the new user message to Hermes and stream the reply."""
        user_msg = self._extract_user_message(context)
        if user_msg is None:
            logger.debug("Hermes: no user message in context; skipping request")
            return

        payload = {"model": self._model, "messages": [user_msg], "stream": True}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        session_header = self._session_manager.header_value() if self._session_manager else None
        if session_header:
            headers["X-Hermes-Session-Id"] = session_header

        await self.start_ttfb_metrics()
        start = time.perf_counter()
        ttfb_recorded = False

        logger.info(
            f"Hermes request started (session={session_header or 'new'}, "
            f"message={user_msg['content'][:80]!r})"
        )

        timeout = httpx.Timeout(connect=self._connect_timeout_secs, read=None, write=None, pool=None)
        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response,
            ):
                    if response.status_code != 200:
                        await self._handle_http_error(response)
                        return

                    if self._session_manager:
                        self._session_manager.set_session_id_from_response(
                            response.headers.get("X-Hermes-Session-Id")
                        )

                    async for chunk in self._stream_chunks(response):
                        if chunk.tool_progress is not None:
                            await self._push_tool_activity(chunk.tool_progress)
                            continue
                        if chunk.done:
                            logger.info(
                                f"Hermes response completed "
                                f"(finish_reason={chunk.finish_reason})"
                            )
                            break
                        if chunk.text_delta:
                            if not ttfb_recorded:
                                await self.stop_ttfb_metrics()
                                ttfb_recorded = True
                                log_metric(
                                    "hermes_ttft",
                                    (time.perf_counter() - start) * 1000.0,
                                    session=self._session_manager.app_session_id
                                    if self._session_manager
                                    else "n/a",
                                )
                                logger.info("Hermes response started")
                            await self._push_llm_text(chunk.text_delta)
        finally:
            if not ttfb_recorded:
                await self.stop_ttfb_metrics()
            log_metric(
                "hermes_total",
                (time.perf_counter() - start) * 1000.0,
                session=self._session_manager.app_session_id
                if self._session_manager
                else "n/a",
            )
            # Closing the client on barge-in closes the HTTP connection, which
            # is how Hermes cancels an in-flight agent turn.

    async def _stream_chunks(self, response: httpx.Response) -> AsyncIterator[HermesChatChunk]:
        async for sse_chunk in parse_sse_lines(response.aiter_lines()):
            parsed = parse_chat_chunk(sse_chunk)
            if parsed.text_delta is None and not parsed.done and parsed.tool_progress is None:
                continue  # empty / unparseable chunk
            yield parsed

    async def _handle_http_error(self, response: httpx.Response) -> None:
        body = (await response.aread()).decode("utf-8", errors="replace")
        detail = body[:300] or "(empty body)"
        logger.error(
            f"Hermes HTTP error {response.status_code} from "
            f"{self._base_url}/chat/completions: {detail}"
        )
        await self.push_error(
            error_msg=f"Hermes HTTP error {response.status_code}: {detail}"
        )

    async def _push_tool_activity(self, payload: dict) -> None:
        """Log the tool event and forward it as a control frame for the UI.

        The frame flows downstream (TTS and transports pass control frames
        through untouched) so the desktop bridge can publish it.
        """
        tool_name = payload.get("tool_name") or payload.get("tool") or "unknown"
        status = str(payload.get("status") or "")
        label = str(payload.get("delta") or payload.get("label") or "")[:200]
        logger.info(
            f"Hermes tool activity: tool={tool_name} status={status} detail={label!r}"
        )
        await self.push_frame(
            ToolActivityFrame(
                tool=tool_name,
                label=label,
                emoji=str(payload.get("emoji") or ""),
                tool_call_id=str(
                    payload.get("toolCallId") or payload.get("tool_call_id") or ""
                ),
                status=status,
            )
        )

    @staticmethod
    def _extract_user_message(context: LLMContext) -> dict | None:
        """Return the most recent user message in OpenAI format.

        The universal message format is an alias of OpenAI's
        ``ChatCompletionMessageParam`` (pipecat 1.7), so dicts pass through
        unchanged. Content may be a plain string or a multimodal part list;
        voice-only turns produce plain strings.
        """
        for message in reversed(context.get_messages()):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return message
            if isinstance(content, list):
                text_parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                text = " ".join(part for part in text_parts if part).strip()
                if text:
                    return {**message, "content": text}
        return None
