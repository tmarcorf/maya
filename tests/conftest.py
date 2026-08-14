"""Shared fixtures and helpers for Polaris tests."""

from __future__ import annotations

import pytest
from pipecat.processors.aggregators.llm_context import LLMContext

from config.settings import Settings
from pipeline.hermes import HermesLLMService, HermesSessionManager

HERMES_BASE_URL = "http://127.0.0.1:8642/v1"
HERMES_COMPLETIONS_URL = f"{HERMES_BASE_URL}/chat/completions"


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Prevent a developer `.env` file from overriding test env vars."""
    monkeypatch.setattr("config.settings.load_dotenv", lambda **kwargs: None)


def make_settings(**overrides) -> Settings:
    """Build a Settings instance with test defaults."""
    values: dict = {
        "hermes_base_url": HERMES_BASE_URL,
        "hermes_api_key": "test-key",
        "hermes_model": "hermes-agent",
        "hermes_app_session_id": "voice-session-test",
        "stt_model": "small",
        "stt_device": "cpu",
        "stt_compute_type": "int8",
        "stt_language": "pt",
        "tts_provider": "kokoro",
        "tts_language": "pt",
        "tts_voice": "pf_dora",
        "log_level": "INFO",
    }
    values.update(overrides)
    return Settings(**values)


def make_service(
    session_manager: HermesSessionManager | None = None,
    **settings_overrides,
) -> HermesLLMService:
    """Build a HermesLLMService wired with test settings."""
    settings = make_settings(**settings_overrides)
    return HermesLLMService(
        base_url=settings.hermes_base_url,
        api_key=settings.hermes_api_key,
        model=settings.hermes_model,
        session_manager=session_manager
        or HermesSessionManager(settings.hermes_app_session_id),
    )


def make_context(text: str = "oi") -> LLMContext:
    """Build an LLMContext containing a single user message."""
    context = LLMContext()
    context.add_message({"role": "user", "content": text})
    return context


def chunk(text: str) -> str:
    """A chat.completion.chunk SSE data payload with a text delta."""
    import json

    return json.dumps(
        {
            "id": "cmpl-test",
            "object": "chat.completion.chunk",
            "model": "hermes-agent",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
        }
    )


def sse(*frames: tuple[str | None, str]) -> str:
    """Serialize (event, data) pairs into an SSE body."""
    parts: list[str] = []
    for event, data in frames:
        if event:
            parts.append(f"event: {event}\ndata: {data}\n\n")
        else:
            parts.append(f"data: {data}\n\n")
    return "".join(parts)
