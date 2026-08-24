"""Spec §19 item 1 — configuration."""

from __future__ import annotations

import pytest

from config.settings import load_settings


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("HERMES_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("HERMES_MODEL", "my-model")
    monkeypatch.setenv("HERMES_SESSION_ID", "voice-session-fixed")
    monkeypatch.setenv("STT_MODEL", "base")
    monkeypatch.setenv("STT_DEVICE", "cpu")
    monkeypatch.setenv("STT_COMPUTE_TYPE", "float16")
    monkeypatch.setenv("STT_LANGUAGE", "pt")
    monkeypatch.setenv("TTS_VOICE", "pm_alex")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AUDIO_IN_DEVICE", "3")
    monkeypatch.setenv("AUDIO_OUT_DEVICE", "4")

    settings = load_settings()

    assert settings.hermes_api_key == "secret-123"
    assert settings.hermes_base_url == "http://localhost:9999/v1"
    assert settings.hermes_model == "my-model"
    assert settings.hermes_app_session_id == "voice-session-fixed"
    assert settings.stt_model == "base"
    assert settings.stt_device == "cpu"
    assert settings.stt_compute_type == "float16"
    assert settings.stt_language == "pt"
    assert settings.tts_voice == "pm_alex"
    assert settings.log_level == "DEBUG"
    assert settings.audio_in_device == 3
    assert settings.audio_out_device == 4


def test_defaults_when_env_unset(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.delenv("STT_MODEL", raising=False)
    monkeypatch.delenv("TTS_VOICE", raising=False)
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)

    settings = load_settings()

    assert settings.hermes_base_url == "http://127.0.0.1:8642/v1"
    assert settings.hermes_model == "hermes-agent"
    assert settings.stt_model == "small"
    assert settings.stt_language == "pt"
    assert settings.tts_voice == "pf_dora"
    assert settings.log_level == "INFO"
    assert settings.audio_in_device is None
    # A stable app session id is generated when HERMES_SESSION_ID is empty.
    assert settings.hermes_app_session_id.startswith("voice-session-")
    assert len(settings.hermes_app_session_id) > len("voice-session-")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("HERMES_API_KEY", raising=False)
    monkeypatch.setenv("HERMES_API_KEY", "   ")
    with pytest.raises(ValueError, match="HERMES_API_KEY"):
        load_settings()


def test_empty_stt_language_means_auto_detect(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("STT_LANGUAGE", "")
    settings = load_settings()
    assert settings.stt_language is None


def test_unknown_tts_provider_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "whisper-turbo")
    with pytest.raises(ValueError, match="not supported"):
        load_settings()


def test_elevenlabs_requires_api_key(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        load_settings()


def test_elevenlabs_requires_voice_id(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    with pytest.raises(ValueError, match="ELEVENLABS_VOICE_ID"):
        load_settings()


def test_elevenlabs_settings_loaded(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "el-voice")

    settings = load_settings()

    assert settings.tts_provider == "elevenlabs"
    assert settings.elevenlabs_api_key == "el-key"
    assert settings.elevenlabs_voice_id == "el-voice"
    assert settings.elevenlabs_model_id == "eleven_flash_v2_5"  # default


def test_elevenlabs_model_override(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "el-voice")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_turbo_v2_5")

    assert load_settings().elevenlabs_model_id == "eleven_turbo_v2_5"


def test_wake_word_defaults_when_unset(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.delenv("WAKE_WORD_ENABLED", raising=False)
    monkeypatch.delenv("WAKE_WORD_PHRASES", raising=False)
    monkeypatch.delenv("WAKE_WORD_TIMEOUT", raising=False)

    settings = load_settings()

    assert settings.wake_word_enabled is False
    assert settings.wake_word_phrases == ["E aí, Maya", "Ei, Maya", "Maya, tá aí?"]
    assert settings.wake_word_timeout == 10.0


def test_wake_word_enabled_and_phrases(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("WAKE_WORD_ENABLED", "yes")
    monkeypatch.setenv("WAKE_WORD_PHRASES", " Ei, Maya ;; Maya, tá aí? ")
    monkeypatch.setenv("WAKE_WORD_TIMEOUT", "30")

    settings = load_settings()

    assert settings.wake_word_enabled is True
    assert settings.wake_word_phrases == ["Ei, Maya", "Maya, tá aí?"]
    assert settings.wake_word_timeout == 30.0


def test_wake_word_enabled_requires_phrases(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("WAKE_WORD_ENABLED", "true")
    monkeypatch.setenv("WAKE_WORD_PHRASES", " ; ")
    with pytest.raises(ValueError, match="WAKE_WORD_PHRASES"):
        load_settings()


def test_bridge_ws_port_default_and_override(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.delenv("BRIDGE_WS_PORT", raising=False)
    assert load_settings().bridge_ws_port == 8686

    monkeypatch.setenv("BRIDGE_WS_PORT", "9001")
    assert load_settings().bridge_ws_port == 9001


def test_bridge_ws_port_invalid_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")

    monkeypatch.setenv("BRIDGE_WS_PORT", "abc")
    with pytest.raises(ValueError, match="BRIDGE_WS_PORT"):
        load_settings()

    monkeypatch.setenv("BRIDGE_WS_PORT", "0")
    with pytest.raises(ValueError, match="BRIDGE_WS_PORT"):
        load_settings()

    monkeypatch.setenv("BRIDGE_WS_PORT", "70000")
    with pytest.raises(ValueError, match="BRIDGE_WS_PORT"):
        load_settings()
