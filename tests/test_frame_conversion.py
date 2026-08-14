"""Spec §19 item 4 — Hermes chunks become Pipecat frames; tool progress is
never spoken (§15)."""

from __future__ import annotations

import json

import respx
from conftest import (
    HERMES_COMPLETIONS_URL,
    chunk,
    make_context,
    make_service,
    sse,
)
from pipecat.frames.frames import (
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMServiceMetadataFrame,
    LLMTextFrame,
)
from pipecat.tests.utils import run_test


@respx.mock
async def test_chunks_become_llm_text_frames():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=sse((None, chunk("Olá")), (None, chunk(" mundo")), (None, "[DONE]")),
        )
    )
    service = make_service()

    down, _up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMTextFrame,
            LLMTextFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    texts = [frame.text for frame in down if isinstance(frame, LLMTextFrame)]
    assert texts == ["Olá", " mundo"]


@respx.mock
async def test_tool_progress_is_filtered_from_speech():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=sse(
                (None, chunk("Vou")),
                ("hermes.tool.progress", '{"tool_name":"bash","delta":"ls"}'),
                (None, chunk(" verificar")),
                (None, "[DONE]"),
            ),
        )
    )
    service = make_service()

    down, _up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMTextFrame,
            LLMTextFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    texts = [frame.text for frame in down if isinstance(frame, LLMTextFrame)]
    # The tool progress payload never became an LLMTextFrame (§15).
    assert "".join(texts) == "Vou verificar"


@respx.mock
async def test_request_payload_contains_model_and_stream():
    route = respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(200, content=sse((None, "[DONE]")))
    )
    service = make_service()

    await run_test(service, frames_to_send=[LLMContextFrame(context=make_context())])

    assert len(route.calls) == 1
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "hermes-agent"
    assert body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": "oi"}]


@respx.mock
async def test_only_last_user_message_is_sent():
    """History lives in the Hermes session — only the new user message goes
    on the wire (§8)."""
    route = respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(200, content=sse((None, "[DONE]")))
    )
    service = make_service()

    from pipecat.processors.aggregators.llm_context import LLMContext

    context = LLMContext()
    context.add_message({"role": "user", "content": "pergunta 1"})
    context.add_message({"role": "assistant", "content": "resposta 1"})
    context.add_message({"role": "user", "content": "pergunta 2"})

    await run_test(service, frames_to_send=[LLMContextFrame(context=context)])

    body = json.loads(route.calls[0].request.content)
    assert body["messages"] == [{"role": "user", "content": "pergunta 2"}]
