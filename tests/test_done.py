"""Spec §19 item 5 — the [DONE] marker terminates the stream cleanly."""

from __future__ import annotations

import respx
from conftest import HERMES_COMPLETIONS_URL, chunk, make_context, make_service, sse
from pipecat.frames.frames import (
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMServiceMetadataFrame,
    LLMTextFrame,
)
from pipecat.tests.utils import run_test


@respx.mock
async def test_stream_stops_at_done_and_ignores_trailing_data():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=sse(
                (None, chunk("Olá")),
                (None, "[DONE]"),
                (None, chunk("isto não deve aparecer")),
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
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    assert len([f for f in down if isinstance(f, LLMTextFrame)]) == 1
    assert isinstance(down[-1], LLMFullResponseEndFrame)


@respx.mock
async def test_done_only_stream_closes_turn_without_text():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(200, content=sse((None, "[DONE]")))
    )
    service = make_service()

    down, _up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    assert not [f for f in down if isinstance(f, LLMTextFrame)]
    assert isinstance(down[-1], LLMFullResponseEndFrame)
