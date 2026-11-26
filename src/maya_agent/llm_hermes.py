from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aiohttp
from livekit.agents import APIConnectionError, APIConnectOptions, APIStatusError, llm
from livekit.agents.llm.chat_context import Instructions
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from .config import HermesSettings

logger = logging.getLogger("maya.hermes")

PROGRESS_THROTTLE_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class HermesRequest:
    url: str
    headers: dict[str, str]
    payload: dict[str, Any]


StreamTransport = Callable[
    [HermesRequest, float],
    AbstractAsyncContextManager[AsyncIterable[bytes]],
]


@asynccontextmanager
async def aiohttp_stream(
    request: HermesRequest,
    timeout: float,
) -> AsyncIterator[AsyncIterable[bytes]]:
    timeout_config = aiohttp.ClientTimeout(total=timeout, connect=10.0, sock_read=None)
    try:
        async with aiohttp.ClientSession(timeout=timeout_config) as session, session.post(
            request.url,
            json=request.payload,
            headers=request.headers,
        ) as response:
            if response.status != 200:
                body = await response.text()
                raise APIStatusError(
                    f"Hermes API error {response.status}: {body[:500]}",
                    status_code=response.status,
                    body=body,
                    retryable=response.status in {408, 409, 425, 429, 500, 502, 503, 504},
                )
            yield response.content
    except (APIStatusError, APIConnectionError):
        raise
    except TimeoutError as exc:
        raise APIConnectionError(f"Hermes request timed out: {exc}", retryable=False) from exc
    except (aiohttp.ClientError, ConnectionError) as exc:
        raise APIConnectionError(f"Hermes connection failed: {exc}") from exc


def build_hermes_messages(
    chat_ctx: llm.ChatContext,
    voice_instruction: str,
) -> list[dict[str, str]]:
    system_parts: list[str] = []
    instruction_parts: list[str] = []
    last_user_text: str | None = None

    for item in chat_ctx.items:
        if isinstance(item, llm.ChatMessage):
            text = item.raw_text_content
            if not text:
                continue
            if item.role in ("system", "developer"):
                system_parts.append(text)
            elif item.role == "user":
                last_user_text = text
        elif isinstance(item, Instructions):
            rendered = item.render()
            if rendered:
                instruction_parts.append(rendered)

    if not system_parts and voice_instruction:
        system_parts.append(voice_instruction)

    if last_user_text is None:
        last_user_text = "\n".join(instruction_parts) or "Inicie a conversa."
    elif instruction_parts:
        system_parts.extend(instruction_parts)

    messages = [{"role": "system", "content": part} for part in system_parts]
    messages.append({"role": "user", "content": last_user_text})
    return messages


class HermesLLM(llm.LLM):
    def __init__(
        self,
        settings: HermesSettings,
        *,
        session_id: str,
        voice_instruction: str,
        stream: StreamTransport | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._session_id = session_id
        self._voice_instruction = voice_instruction
        self._stream = stream or aiohttp_stream
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def aclose(self) -> None:
        for task in tuple(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()
        await super().aclose()

    def track_background(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.add(task)

        def _done(done: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done)
            if done.cancelled():
                return
            error = done.exception()
            if error is not None:
                logger.warning("Hermes background turn failed", exc_info=error)

        task.add_done_callback(_done)

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def provider(self) -> str:
        return "hermes"

    @property
    def session_id(self) -> str:
        return self._session_id

    def build_request(self, chat_ctx: llm.ChatContext) -> HermesRequest:
        messages = build_hermes_messages(chat_ctx, self._voice_instruction)
        return HermesRequest(
            url=f"{self._settings.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Hermes-Session-Id": self._session_id,
                "X-Hermes-Session-Key": self._settings.session_key,
            },
            payload={
                "model": self._settings.model,
                "messages": messages,
                "stream": True,
            },
        )

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        **kwargs: Any,
    ) -> llm.LLMStream:
        max_retries = min(conn_options.max_retry, self._settings.max_retries)
        if max_retries != conn_options.max_retry:
            conn_options = APIConnectOptions(
                max_retry=max_retries,
                retry_interval=conn_options.retry_interval,
                timeout=conn_options.timeout,
                liveness_timeout=conn_options.liveness_timeout,
            )
        return HermesLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class HermesLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm_instance: HermesLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(llm_instance, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._hermes = llm_instance
        self._chunk_id = "hermes"
        self._final_usage: llm.CompletionUsage | None = None
        self._last_progress_at = 0.0
        self._content_started = False
        self._cancelled = False
        self._running_tools: set[str] = set()

    async def _run(self) -> None:
        request = self._hermes.build_request(self._chat_ctx)
        task = asyncio.create_task(
            self._run_stream(request),
            name="maya-hermes-llm-stream",
        )
        self._hermes.track_background(task)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            self._cancelled = True
            self._hermes.emit("cancelled", {})
            logger.info("Maya turn interrupted; Hermes continues in the background")
            raise

    async def _run_stream(self, request: HermesRequest) -> None:
        async with self._hermes._stream(
            request,
            self._hermes._settings.timeout_seconds,
        ) as lines:
            await self._consume(lines)
        if self._final_usage is not None:
            self._send(llm.ChatChunk(id=self._chunk_id, usage=self._final_usage))

    async def _consume(self, lines: AsyncIterable[bytes]) -> None:
        event = "message"
        data_lines: list[str] = []
        async for raw_line in lines:
            line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif line == "":
                if data_lines:
                    self._dispatch(event, "\n".join(data_lines))
                event = "message"
                data_lines = []
        if data_lines:
            self._dispatch(event, "\n".join(data_lines))

    def _dispatch(self, event: str, data: str) -> None:
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("ignoring non-JSON Hermes SSE event: %s", data[:200])
            return
        if not isinstance(payload, dict):
            return

        if event == "hermes.tool.progress":
            self._on_tool_progress(payload)
        elif event == "approval.request":
            self._on_approval(payload)
        elif event == "hermes.status":
            logger.debug("Hermes status: %s", payload.get("text") or payload.get("kind"))
        else:
            self._on_chunk(payload)

    def _on_chunk(self, payload: dict[str, Any]) -> None:
        chunk_id = payload.get("id")
        if isinstance(chunk_id, str) and chunk_id:
            self._chunk_id = chunk_id

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str) and content:
                    if not self._content_started:
                        content = content.lstrip()
                        if not content:
                            return
                        self._content_started = True
                        if not self._cancelled:
                            self._hermes.emit("content_started", {})
                    self._send(
                        llm.ChatChunk(
                            id=self._chunk_id,
                            delta=llm.ChoiceDelta(role="assistant", content=content),
                        )
                    )

        usage = payload.get("usage")
        if isinstance(usage, dict):
            self._final_usage = llm.CompletionUsage(
                completion_tokens=int(usage.get("completion_tokens") or 0),
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
            )

    def _on_tool_progress(self, payload: dict[str, Any]) -> None:
        status = payload.get("status")
        tool_id = str(payload.get("toolCallId") or payload.get("tool") or "tool")
        if status == "completed":
            self._running_tools.discard(tool_id)
            if not self._running_tools:
                self._hermes.emit("progress_done", {})
            return
        if status != "running":
            return
        self._running_tools.add(tool_id)
        if self._cancelled or self._content_started:
            return
        now = time.monotonic()
        if now - self._last_progress_at < PROGRESS_THROTTLE_SECONDS:
            return
        self._last_progress_at = now
        payload = {**payload, "timestamp": time.time()}
        self._hermes.emit("progress", payload)

    def _on_approval(self, payload: dict[str, Any]) -> None:
        if self._cancelled:
            payload = {**payload, "silent": True}
        self._hermes.emit("approval", payload)

    def _send(self, chunk: llm.ChatChunk) -> None:
        try:
            self._event_ch.send_nowait(chunk)
        except Exception:
            logger.debug("Hermes stream consumer is gone", exc_info=True)


def build_hermes_llm(
    settings: HermesSettings,
    *,
    session_id: str,
    voice_instruction: str,
    stream: StreamTransport | None = None,
) -> llm.LLM:
    return HermesLLM(
        settings,
        session_id=session_id,
        voice_instruction=voice_instruction,
        stream=stream,
    )
