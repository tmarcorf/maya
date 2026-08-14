"""Central configuration for the Polaris voice agent.

Loads values from environment variables / `.env` (via python-dotenv) and
exposes a single immutable `Settings` object. No credentials are hardcoded
here — see `.env.example`.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_HERMES_BASE_URL = "http://127.0.0.1:8642/v1"
DEFAULT_HERMES_MODEL = "hermes-agent"
DEFAULT_STT_MODEL = "small"
DEFAULT_STT_DEVICE = "cpu"
DEFAULT_STT_COMPUTE_TYPE = "int8"
DEFAULT_STT_LANGUAGE = "pt"
DEFAULT_TTS_PROVIDER = "kokoro"
DEFAULT_TTS_LANGUAGE = "pt"
DEFAULT_TTS_VOICE = "pf_dora"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, populated from the environment."""

    hermes_base_url: str
    hermes_api_key: str
    hermes_model: str
    # App-level session id ("voice-session-<uuid>") used to talk to Hermes.
    hermes_app_session_id: str
    stt_model: str
    stt_device: str
    stt_compute_type: str
    # None means "let Whisper auto-detect the language".
    stt_language: str | None
    tts_provider: str
    tts_language: str
    tts_voice: str
    log_level: str
    # PyAudio device indices (None = system default).
    audio_in_device: int | None = None
    audio_out_device: int | None = None


def _int_or_none(raw: str | None) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def load_settings() -> Settings:
    """Load settings from `.env` / environment variables, with validation."""
    load_dotenv(override=True)

    api_key = os.getenv("HERMES_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "HERMES_API_KEY is not set. Copy .env.example to .env and fill it in."
        )

    # Empty STT_LANGUAGE means auto-detection.
    stt_language = os.getenv("STT_LANGUAGE", DEFAULT_STT_LANGUAGE).strip() or None

    tts_provider = os.getenv("TTS_PROVIDER", DEFAULT_TTS_PROVIDER).strip().lower()
    if tts_provider != DEFAULT_TTS_PROVIDER:
        raise ValueError(
            f"TTS_PROVIDER '{tts_provider}' is not supported yet (only '{DEFAULT_TTS_PROVIDER}')."
        )

    # Stable app session id, per spec §8: "voice-session-<uuid>".
    app_session_id = os.getenv("HERMES_SESSION_ID", "").strip()
    if not app_session_id:
        app_session_id = f"voice-session-{uuid.uuid4()}"

    return Settings(
        hermes_base_url=os.getenv("HERMES_BASE_URL", DEFAULT_HERMES_BASE_URL).rstrip("/"),
        hermes_api_key=api_key,
        hermes_model=os.getenv("HERMES_MODEL", DEFAULT_HERMES_MODEL),
        hermes_app_session_id=app_session_id,
        stt_model=os.getenv("STT_MODEL", DEFAULT_STT_MODEL),
        stt_device=os.getenv("STT_DEVICE", DEFAULT_STT_DEVICE),
        stt_compute_type=os.getenv("STT_COMPUTE_TYPE", DEFAULT_STT_COMPUTE_TYPE),
        stt_language=stt_language,
        tts_provider=tts_provider,
        tts_language=os.getenv("TTS_LANGUAGE", DEFAULT_TTS_LANGUAGE),
        tts_voice=os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE),
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        audio_in_device=_int_or_none(os.getenv("AUDIO_IN_DEVICE")),
        audio_out_device=_int_or_none(os.getenv("AUDIO_OUT_DEVICE")),
    )
