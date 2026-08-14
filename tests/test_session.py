"""Spec §19 item 7 — Hermes session handling via X-Hermes-Session-Id (§8)."""

from __future__ import annotations

import respx
from conftest import HERMES_COMPLETIONS_URL, chunk, make_context, make_service, sse
from pipecat.frames.frames import LLMContextFrame
from pipecat.tests.utils import run_test

from pipeline.hermes import HermesSessionManager


def test_app_session_id_is_stable():
    manager = HermesSessionManager("voice-session-abc")
    assert manager.app_session_id == "voice-session-abc"


def test_no_hermes_session_before_first_response():
    manager = HermesSessionManager("voice-session-abc")
    assert manager.header_value() is None
    assert manager.current_hermes_session_id() is None


def test_echoed_session_id_is_captured():
    manager = HermesSessionManager("voice-session-abc")
    manager.set_session_id_from_response("hermes-session-42")
    assert manager.header_value() == "hermes-session-42"
    assert manager.current_hermes_session_id() == "hermes-session-42"


def test_blank_echoed_header_is_ignored():
    manager = HermesSessionManager("voice-session-abc")
    manager.set_session_id_from_response("   ")
    assert manager.header_value() is None


@respx.mock
async def test_first_request_has_no_session_header_second_reuses_echo():
    route = respx.post(HERMES_COMPLETIONS_URL)
    route.side_effect = [
        respx.MockResponse(
            200,
            content=sse((None, chunk("primeira resposta")), (None, "[DONE]")),
            headers={"X-Hermes-Session-Id": "hs-1"},
        ),
        respx.MockResponse(
            200,
            content=sse((None, chunk("segunda resposta")), (None, "[DONE]")),
            headers={"X-Hermes-Session-Id": "hs-1"},
        ),
    ]
    session_manager = HermesSessionManager("voice-session-test")
    service = make_service(session_manager=session_manager)

    await run_test(
        service, frames_to_send=[LLMContextFrame(context=make_context("primeira"))]
    )
    await run_test(
        service, frames_to_send=[LLMContextFrame(context=make_context("segunda"))]
    )

    assert len(route.calls) == 2
    # First request: no header — Hermes creates the session and echoes the id.
    assert "X-Hermes-Session-Id" not in route.calls[0].request.headers
    # Second request: the echoed id is reused.
    assert route.calls[1].request.headers["X-Hermes-Session-Id"] == "hs-1"
    assert session_manager.current_hermes_session_id() == "hs-1"
