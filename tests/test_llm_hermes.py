from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager

from livekit.agents import APIConnectOptions, llm
from livekit.agents.llm.chat_context import Instructions

from maya_agent.config import HermesSettings
from maya_agent.llm_hermes import (
    HermesLLM,
    HermesRequest,
    build_hermes_messages,
)


def _settings() -> HermesSettings:
    return HermesSettings(
        base_url="http://127.0.0.1:8642/p/maya-voice/v1",
        api_key="hermes-key",
        model="hermes-agent",
        session_key="maya-user",
        max_retries=1,
        timeout_seconds=180.0,
        approval_enabled=True,
        approval_port=8765,
    )


def test_build_hermes_messages_keeps_only_last_user_turn() -> None:
    ctx = llm.ChatContext()
    ctx.add_message(role="system", content="Formato de voz.")
    ctx.add_message(role="user", content="primeira fala")
    ctx.add_message(role="assistant", content="resposta antiga")
    ctx.add_message(role="user", content="fala atual")

    messages = build_hermes_messages(ctx, "fallback")

    assert messages == [
        {"role": "system", "content": "Formato de voz."},
        {"role": "user", "content": "fala atual"},
    ]


def test_build_request_sets_session_headers() -> None:
    hermes = HermesLLM(_settings(), session_id="room-1", voice_instruction="voz")
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="oi")

    request = hermes.build_request(ctx)

    assert request.url == "http://127.0.0.1:8642/p/maya-voice/v1/chat/completions"
    assert request.headers["X-Hermes-Session-Id"] == "room-1"
    assert request.headers["X-Hermes-Session-Key"] == "maya-user"
    assert request.payload["stream"] is True


async def test_stream_forwards_content_progress_and_approval() -> None:
    requests: list[HermesRequest] = []

    @asynccontextmanager
    async def fake_stream(request: HermesRequest, timeout: float) -> AsyncIterable[bytes]:
        requests.append(request)
        lines = [
            b"event: hermes.tool.progress\n",
            b'data: {"tool":"terminal","label":"Running ls","status":"running"}\n',
            b"\n",
            b"event: approval.request\n",
            b'data: {"run_id":"run-1","request_id":"req-1","choices":["once","deny"]}\n',
            b"\n",
            b'data: {"id":"chatcmpl-1","choices":[{"index":0,'
            b'"delta":{"role":"assistant","content":"Ol\xc3\xa1"}}]}\n',
            b"\n",
            b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":" mundo"}}]}\n',
            b"\n",
            b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
            b'"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        async def line_iter() -> AsyncIterable[bytes]:
            for line in lines:
                yield line

        yield line_iter()

    hermes = HermesLLM(
        _settings(),
        session_id="room-1",
        voice_instruction="voz",
        stream=fake_stream,
    )
    progress: list[dict] = []
    approvals: list[dict] = []
    hermes.on("progress", progress.append)
    hermes.on("approval", approvals.append)

    ctx = llm.ChatContext()
    ctx.add_message(role="system", content="Formato de voz.")
    ctx.add_message(role="user", content="primeira fala")
    ctx.add_message(role="assistant", content="resposta antiga")
    ctx.add_message(role="user", content="fala atual")

    stream = hermes.chat(
        chat_ctx=ctx,
        tools=[],
        conn_options=APIConnectOptions(max_retry=0),
    )
    chunks = [chunk async for chunk in stream]

    content = "".join(
        chunk.delta.content
        for chunk in chunks
        if chunk.delta is not None and chunk.delta.content
    )
    assert content == "Olá mundo"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 12
    assert progress and progress[0]["tool"] == "terminal"
    assert approvals == [{"run_id": "run-1", "request_id": "req-1", "choices": ["once", "deny"]}]
    assert requests[0].payload["messages"] == [
        {"role": "system", "content": "Formato de voz."},
        {"role": "user", "content": "fala atual"},
    ]


async def test_stream_continues_after_interruption() -> None:
    completed = asyncio.Event()

    @asynccontextmanager
    async def slow_stream(request: HermesRequest, timeout: float) -> AsyncIterable[bytes]:
        async def line_iter() -> AsyncIterable[bytes]:
            yield b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"a"}}]}\n'
            yield b"\n"
            await asyncio.sleep(0.05)
            yield b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"b"}}]}\n'
            yield b"\n"
            completed.set()

        yield line_iter()

    hermes = HermesLLM(
        _settings(),
        session_id="room-1",
        voice_instruction="voz",
        stream=slow_stream,
    )
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="oi")
    stream = hermes.chat(
        chat_ctx=ctx,
        tools=[],
        conn_options=APIConnectOptions(max_retry=0),
    )

    first = await anext(stream)
    assert first.delta is not None
    assert first.delta.content == "a"

    await stream.aclose()
    await asyncio.wait_for(completed.wait(), timeout=1.0)
    await asyncio.sleep(0)
    await hermes.aclose()


def test_build_hermes_messages_uses_greeting_instructions() -> None:
    ctx = llm.ChatContext([Instructions("Cumprimente o usuário.")])

    messages = build_hermes_messages(ctx, "voz")

    assert messages == [
        {"role": "system", "content": "voz"},
        {"role": "user", "content": "Cumprimente o usuário."},
    ]


async def test_progress_after_content_is_ignored() -> None:
    @asynccontextmanager
    async def fake_stream(request: HermesRequest, timeout: float) -> AsyncIterable[bytes]:
        lines = [
            b'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"content":"Ol\xc3\xa1"}}]}\n',
            b"\n",
            b"event: hermes.tool.progress\n",
            b'data: {"tool":"terminal","label":"Running ls","status":"running"}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        async def line_iter() -> AsyncIterable[bytes]:
            for line in lines:
                yield line

        yield line_iter()

    hermes = HermesLLM(
        _settings(),
        session_id="room-1",
        voice_instruction="voz",
        stream=fake_stream,
    )
    progress: list[dict] = []
    hermes.on("progress", progress.append)
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="oi")
    stream = hermes.chat(
        chat_ctx=ctx,
        tools=[],
        conn_options=APIConnectOptions(max_retry=0),
    )
    chunks = [chunk async for chunk in stream]
    text = "".join(
        chunk.delta.content
        for chunk in chunks
        if chunk.delta is not None and chunk.delta.content
    )

    assert text == "Olá"
    assert progress == []


async def test_tool_completion_emits_progress_done() -> None:
    @asynccontextmanager
    async def fake_stream(request: HermesRequest, timeout: float) -> AsyncIterable[bytes]:
        lines = [
            b"event: hermes.tool.progress\n",
            b'data: {"tool":"terminal","toolCallId":"call-1","status":"running"}\n',
            b"\n",
            b"event: hermes.tool.progress\n",
            b'data: {"tool":"terminal","toolCallId":"call-1","status":"completed"}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]

        async def line_iter() -> AsyncIterable[bytes]:
            for line in lines:
                yield line

        yield line_iter()

    hermes = HermesLLM(
        _settings(),
        session_id="room-1",
        voice_instruction="voz",
        stream=fake_stream,
    )
    progress: list[dict] = []
    done: list[dict] = []
    hermes.on("progress", progress.append)
    hermes.on("progress_done", done.append)
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content="oi")
    stream = hermes.chat(
        chat_ctx=ctx,
        tools=[],
        conn_options=APIConnectOptions(max_retry=0),
    )
    _ = [chunk async for chunk in stream]

    assert len(progress) == 1
    assert done == [{}]
