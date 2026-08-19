"""Central configuration for the Polaris voice agent.

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
DEFAULT_QWEN3_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_QWEN3_DEVICE = "cuda"
DEFAULT_QWEN3_DTYPE = "bfloat16"
DEFAULT_QWEN3_SPEAKER = "Ryan"
DEFAULT_QWEN3_MAX_NEW_TOKENS = 4096
QWEN3_DTYPES = ("float16", "bfloat16", "float32")
# "cuda:<n>" is also accepted (validated with a startswith check).
QWEN3_DEVICES = ("cuda", "cpu", "auto")
QWEN3_ATTN_IMPLEMENTATIONS = ("sdpa", "flash_attention_2")
SUPPORTED_TTS_PROVIDERS = ("kokoro", "elevenlabs", "qwen3")
DEFAULT_WAKE_WORD_ENABLED = False
DEFAULT_WAKE_WORD_TIMEOUT = 10.0
# Semicolon-separated (commas appear inside the phrases themselves).
DEFAULT_WAKE_WORD_PHRASES = "E aí, Polaris;Ei, Polaris;Polaris, tá aí?"
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
    # Qwen3-TTS (used only when tts_provider == "qwen3"). Local PyTorch model
    # — requires a CUDA GPU; the checkpoint is downloaded from the Hugging
    # Face hub on first use. "-Base" checkpoints synthesize a cloned voice
    # and therefore require qwen3_ref_audio.
    qwen3_model: str = DEFAULT_QWEN3_MODEL
    qwen3_device: str = DEFAULT_QWEN3_DEVICE
    qwen3_dtype: str = DEFAULT_QWEN3_DTYPE
    qwen3_attn_implementation: str | None = None
    qwen3_speaker: str = DEFAULT_QWEN3_SPEAKER
    qwen3_instruct: str = ""
    qwen3_ref_audio: str = ""
    qwen3_ref_text: str = ""
    qwen3_max_new_tokens: int = DEFAULT_QWEN3_MAX_NEW_TOKENS
    qwen3_top_p: float | None = None
    # Wake word (transcript-based; uses the local STT).
    wake_word_enabled: bool = False
    wake_word_phrases: list[str] = field(default_factory=list)
    wake_word_timeout: float = DEFAULT_WAKE_WORD_TIMEOUT


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

    qwen3_model = os.getenv("QWEN3_MODEL", DEFAULT_QWEN3_MODEL).strip()
    qwen3_device = os.getenv("QWEN3_DEVICE", DEFAULT_QWEN3_DEVICE).strip().lower()
    qwen3_dtype = os.getenv("QWEN3_DTYPE", DEFAULT_QWEN3_DTYPE).strip().lower()
    qwen3_attn_implementation = (
        os.getenv("QWEN3_ATTN_IMPLEMENTATION", "").strip().lower() or None
    )
    qwen3_speaker = os.getenv("QWEN3_SPEAKER", DEFAULT_QWEN3_SPEAKER).strip()
    qwen3_instruct = os.getenv("QWEN3_INSTRUCT", "").strip()
    qwen3_ref_audio = os.getenv("QWEN3_REF_AUDIO", "").strip()
    qwen3_ref_text = os.getenv("QWEN3_REF_TEXT", "").strip()
    try:
        qwen3_max_new_tokens = int(
            os.getenv("QWEN3_MAX_NEW_TOKENS", str(DEFAULT_QWEN3_MAX_NEW_TOKENS))
        )
    except ValueError:
        raise ValueError("QWEN3_MAX_NEW_TOKENS must be an integer.") from None
    qwen3_top_p_raw = os.getenv("QWEN3_TOP_P", "").strip()
    qwen3_top_p = None
    if qwen3_top_p_raw:
        try:
            qwen3_top_p = float(qwen3_top_p_raw)
        except ValueError:
            raise ValueError("QWEN3_TOP_P must be a number (0-1).") from None
    if tts_provider == "qwen3":
        # Fail fast on misconfiguration before the heavy torch import and
        # model download happen (the service itself loads at startup).
        if qwen3_dtype not in QWEN3_DTYPES:
            raise ValueError(
                f"QWEN3_DTYPE '{qwen3_dtype}' is not supported "
                f"(supported: {', '.join(QWEN3_DTYPES)})."
            )
        if qwen3_device not in QWEN3_DEVICES and not qwen3_device.startswith("cuda:"):
            raise ValueError(
                f"QWEN3_DEVICE '{qwen3_device}' is not supported "
                f"(supported: {', '.join(QWEN3_DEVICES)} or cuda:<n>)."
            )
        if qwen3_attn_implementation not in (None, *QWEN3_ATTN_IMPLEMENTATIONS):
            raise ValueError(
                "QWEN3_ATTN_IMPLEMENTATION must be empty, 'sdpa' or "
                "'flash_attention_2'."
            )
        if "Base" in qwen3_model:
            # -Base checkpoints synthesize a cloned voice from a reference
            # clip (~3s), which must be provided.
            if not qwen3_ref_audio:
                raise ValueError(
                    "QWEN3_REF_AUDIO is not set. It is required when "
                    "TTS_PROVIDER=qwen3 and QWEN3_MODEL is a -Base checkpoint."
                )
        elif qwen3_ref_audio:
            raise ValueError(
                "QWEN3_REF_AUDIO only applies to -Base checkpoints; remove it "
                "when using a CustomVoice model."
            )
        if qwen3_ref_audio and not qwen3_ref_audio.startswith(("http://", "https://")) \
                and not os.path.isfile(qwen3_ref_audio):
            raise ValueError(f"QWEN3_REF_AUDIO file not found: {qwen3_ref_audio}")

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
            "(semicolon-separated list, e.g. 'E aí, Polaris;Ei, Polaris')."
        )
    try:
        wake_word_timeout = float(
            os.getenv("WAKE_WORD_TIMEOUT", str(DEFAULT_WAKE_WORD_TIMEOUT))
        )
    except ValueError:
        raise ValueError("WAKE_WORD_TIMEOUT must be a number (seconds).") from None

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
        qwen3_model=qwen3_model,
        qwen3_device=qwen3_device,
        qwen3_dtype=qwen3_dtype,
        qwen3_attn_implementation=qwen3_attn_implementation,
        qwen3_speaker=qwen3_speaker,
        qwen3_instruct=qwen3_instruct,
        qwen3_ref_audio=qwen3_ref_audio,
        qwen3_ref_text=qwen3_ref_text,
        qwen3_max_new_tokens=qwen3_max_new_tokens,
        qwen3_top_p=qwen3_top_p,
        wake_word_enabled=wake_word_enabled,
        wake_word_phrases=wake_word_phrases,
        wake_word_timeout=wake_word_timeout,
        log_level=os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL),
        audio_in_device=_int_or_none(os.getenv("AUDIO_IN_DEVICE")),
        audio_out_device=_int_or_none(os.getenv("AUDIO_OUT_DEVICE")),
    )
