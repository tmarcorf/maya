"""Central configuration for the Maya voice agent.

Loads values from environment variables / `.env` (via python-dotenv) and
exposes a single immutable `Settings` object. No credentials are hardcoded
here — see `.env.example`.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

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
DEFAULT_ELEVENLABS_MODEL = "eleven_flash_v2_5"
SUPPORTED_TTS_PROVIDERS = ("kokoro", "elevenlabs")
DEFAULT_WAKE_WORD_ENABLED = False
DEFAULT_WAKE_WORD_TIMEOUT = 10.0
# Semicolon-separated (commas appear inside the phrases themselves).
DEFAULT_WAKE_WORD_PHRASES = "E aí, Maya;Ei, Maya;Maya, tá aí?"
# Local WebSocket the desktop app (Electron) connects to for live events.
DEFAULT_BRIDGE_WS_PORT = 8686
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
    # ElevenLabs (used only when tts_provider == "elevenlabs").
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = DEFAULT_ELEVENLABS_MODEL
    # Wake word (transcript-based; uses the local STT).
    wake_word_enabled: bool = False
    wake_word_phrases: list[str] = field(default_factory=list)
    wake_word_timeout: float = DEFAULT_WAKE_WORD_TIMEOUT
    # Desktop bridge: local WS port for live events + control commands.
    bridge_ws_port: int = DEFAULT_BRIDGE_WS_PORT


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
    if tts_provider not in SUPPORTED_TTS_PROVIDERS:
        raise ValueError(
            f"TTS_PROVIDER '{tts_provider}' is not supported "
            f"(supported: {', '.join(SUPPORTED_TTS_PROVIDERS)})."
        )

    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if tts_provider == "elevenlabs":
        # The pipecat ElevenLabs service does not validate the key at
        # construction (only on the WS handshake), so fail fast here.
        if not elevenlabs_api_key:
            raise ValueError(
                "ELEVENLABS_API_KEY is not set. It is required when "
                "TTS_PROVIDER=elevenlabs (get a key at https://elevenlabs.io)."
            )
        if not elevenlabs_voice_id:
            raise ValueError(
                "ELEVENLABS_VOICE_ID is not set. It is required when "
                "TTS_PROVIDER=elevenlabs (premade voice id, e.g. "
                "21m00Tcm4TlvDq8ikWAM, or your cloned voice id)."
            )

    wake_word_enabled = (
        os.getenv("WAKE_WORD_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")
    )
    wake_word_phrases = [
        phrase.strip()
        for phrase in os.getenv("WAKE_WORD_PHRASES", DEFAULT_WAKE_WORD_PHRASES).split(";")
        if phrase.strip()
    ]
    if wake_word_enabled and not wake_word_phrases:
        raise ValueError(
            "WAKE_WORD_PHRASES is empty. It is required when WAKE_WORD_ENABLED=true "
            "(semicolon-separated list, e.g. 'E aí, Maya;Ei, Maya')."
        )
    try:
        wake_word_timeout = float(
            os.getenv("WAKE_WORD_TIMEOUT", str(DEFAULT_WAKE_WORD_TIMEOUT))
        )
    except ValueError:
        raise ValueError("WAKE_WORD_TIMEOUT must be a number (seconds).") from None

    bridge_ws_port_raw = os.getenv("BRIDGE_WS_PORT", "").strip()
    bridge_ws_port = DEFAULT_BRIDGE_WS_PORT
    if bridge_ws_port_raw:
        try:
            bridge_ws_port = int(bridge_ws_port_raw)
        except ValueError:
            raise ValueError("BRIDGE_WS_PORT must be an integer.") from None
        if not 0 < bridge_ws_port < 65536:
            raise ValueError("BRIDGE_WS_PORT must be between 1 and 65535.")

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
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
        elevenlabs_model_id=os.getenv("ELEVENLABS_MODEL_ID", DEFAULT_ELEVENLABS_MODEL),
        wake_word_enabled=wake_word_enabled,
        wake_word_phrases=wake_word_phrases,
        wake_word_timeout=wake_word_timeout,
        bridge_ws_port=bridge_ws_port,
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        audio_in_device=_int_or_none(os.getenv("AUDIO_IN_DEVICE")),
        audio_out_device=_int_or_none(os.getenv("AUDIO_OUT_DEVICE")),
    )
