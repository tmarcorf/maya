"""Spec §19 item 6 — HTTP error handling: ErrorFrame upstream, turn closed,
no crash."""

from __future__ import annotations

import respx
from conftest import HERMES_COMPLETIONS_URL, make_context, make_service
from pipecat.frames.frames import (
    ErrorFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMServiceMetadataFrame,
)
from pipecat.tests.utils import run_test


@respx.mock
async def test_401_emits_error_frame_and_closes_turn():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(401, json={"error": {"message": "invalid api key"}})
    )
    service = make_service()

    down, up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame, ErrorFrame],
    )

    assert isinstance(down[-1], LLMFullResponseEndFrame)
    assert isinstance(up[-1], ErrorFrame)


@respx.mock
async def test_500_emits_error_frame_and_closes_turn():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(500, content=b"internal boom")
    )
    service = make_service()

    down, up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame, ErrorFrame],
    )

    assert isinstance(down[-1], LLMFullResponseEndFrame)
    assert isinstance(up[-1], ErrorFrame)
