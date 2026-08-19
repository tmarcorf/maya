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


def test_qwen3_defaults_when_unset(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.delenv("QWEN3_MODEL", raising=False)
    monkeypatch.delenv("QWEN3_DEVICE", raising=False)
    monkeypatch.delenv("QWEN3_DTYPE", raising=False)
    monkeypatch.delenv("QWEN3_SPEAKER", raising=False)

    settings = load_settings()

    assert settings.qwen3_model == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert settings.qwen3_device == "cuda"
    assert settings.qwen3_dtype == "bfloat16"
    assert settings.qwen3_attn_implementation is None
    assert settings.qwen3_speaker == "Ryan"
    assert settings.qwen3_instruct == ""
    assert settings.qwen3_ref_audio == ""
    assert settings.qwen3_ref_text == ""
    assert settings.qwen3_max_new_tokens == 4096
    assert settings.qwen3_top_p is None


def test_qwen3_settings_loaded(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    monkeypatch.setenv("QWEN3_DEVICE", "cuda:0")
    monkeypatch.setenv("QWEN3_DTYPE", "float16")
    monkeypatch.setenv("QWEN3_ATTN_IMPLEMENTATION", "flash_attention_2")
    monkeypatch.setenv("QWEN3_SPEAKER", "Vivian")
    monkeypatch.setenv("QWEN3_INSTRUCT", "Fale devagar.")
    monkeypatch.setenv("QWEN3_REF_AUDIO", "https://example.com/ref.wav")
    monkeypatch.setenv("QWEN3_REF_TEXT", "Olá mundo.")
    monkeypatch.setenv("QWEN3_MAX_NEW_TOKENS", "2048")
    monkeypatch.setenv("QWEN3_TOP_P", "0.9")

    settings = load_settings()

    assert settings.qwen3_model == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert settings.qwen3_device == "cuda:0"
    assert settings.qwen3_dtype == "float16"
    assert settings.qwen3_attn_implementation == "flash_attention_2"
    assert settings.qwen3_speaker == "Vivian"
    assert settings.qwen3_instruct == "Fale devagar."
    assert settings.qwen3_ref_audio == "https://example.com/ref.wav"
    assert settings.qwen3_ref_text == "Olá mundo."
    assert settings.qwen3_max_new_tokens == 2048
    assert settings.qwen3_top_p == 0.9


def test_qwen3_base_requires_ref_audio(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    with pytest.raises(ValueError, match="QWEN3_REF_AUDIO"):
        load_settings()


def test_qwen3_ref_audio_rejected_with_customvoice(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_REF_AUDIO", "https://example.com/ref.wav")
    with pytest.raises(ValueError, match="QWEN3_REF_AUDIO"):
        load_settings()


def test_qwen3_ref_audio_file_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
    monkeypatch.setenv("QWEN3_REF_AUDIO", "/no/such/file.wav")
    with pytest.raises(ValueError, match="not found"):
        load_settings()

    # A real local file (or a URL) passes validation.
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    monkeypatch.setenv("QWEN3_REF_AUDIO", str(ref))
    assert load_settings().qwen3_ref_audio == str(ref)


def test_qwen3_invalid_device_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_DEVICE", "weird")
    with pytest.raises(ValueError, match="QWEN3_DEVICE"):
        load_settings()


def test_qwen3_invalid_dtype_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_DTYPE", "int4")
    with pytest.raises(ValueError, match="QWEN3_DTYPE"):
        load_settings()


def test_qwen3_invalid_attn_implementation_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_ATTN_IMPLEMENTATION", "eager_x")
    with pytest.raises(ValueError, match="QWEN3_ATTN_IMPLEMENTATION"):
        load_settings()


def test_qwen3_invalid_max_new_tokens_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_MAX_NEW_TOKENS", "abc")
    with pytest.raises(ValueError, match="QWEN3_MAX_NEW_TOKENS"):
        load_settings()


def test_qwen3_invalid_top_p_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("TTS_PROVIDER", "qwen3")
    monkeypatch.setenv("QWEN3_TOP_P", "abc")
    with pytest.raises(ValueError, match="QWEN3_TOP_P"):
        load_settings()


def test_wake_word_defaults_when_unset(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.delenv("WAKE_WORD_ENABLED", raising=False)
    monkeypatch.delenv("WAKE_WORD_PHRASES", raising=False)
    monkeypatch.delenv("WAKE_WORD_TIMEOUT", raising=False)

    settings = load_settings()

    assert settings.wake_word_enabled is False
    assert settings.wake_word_phrases == ["E aí, Polaris", "Ei, Polaris", "Polaris, tá aí?"]
    assert settings.wake_word_timeout == 10.0


def test_wake_word_enabled_and_phrases(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("WAKE_WORD_ENABLED", "yes")
    monkeypatch.setenv("WAKE_WORD_PHRASES", " Ei, Polaris ;; Polaris, tá aí? ")
    monkeypatch.setenv("WAKE_WORD_TIMEOUT", "30")

    settings = load_settings()

    assert settings.wake_word_enabled is True
    assert settings.wake_word_phrases == ["Ei, Polaris", "Polaris, tá aí?"]
    assert settings.wake_word_timeout == 30.0


def test_wake_word_enabled_requires_phrases(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("WAKE_WORD_ENABLED", "true")
    monkeypatch.setenv("WAKE_WORD_PHRASES", " ; ")
    with pytest.raises(ValueError, match="WAKE_WORD_PHRASES"):
        load_settings()


def test_filler_defaults_when_env_unset(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.delenv("FILLER_ENABLED", raising=False)
    monkeypatch.delenv("FILLER_SILENCE_TIMEOUT", raising=False)
    monkeypatch.delenv("FILLER_MIN_INTERVAL", raising=False)
    monkeypatch.delenv("FILLER_MAX_PER_TURN", raising=False)
    monkeypatch.delenv("FILLER_GENERIC_PHRASES", raising=False)
    monkeypatch.delenv("FILLER_SILENCE_PHRASES", raising=False)
    monkeypatch.delenv("FILLER_TOOL_PHRASES", raising=False)

    settings = load_settings()

    # Fillers are on by default (unlike the wake word).
    assert settings.filler_enabled is True
    assert settings.filler_silence_timeout == 7.0
    assert settings.filler_min_interval == 4.0
    assert settings.filler_max_per_turn == 3
    assert settings.filler_generic_phrases == [
        "Hmm, deixa eu ver",
        "Blz, vou olhar",
        "Só um instante",
        "Vou verificar isso",
    ]
    assert settings.filler_silence_phrases == [
        "só mais um instante",
        "ainda estou nisso",
        "já já te falo",
    ]
    assert settings.filler_tool_phrases["terminal"] == "vou mexer no terminal"
    assert settings.filler_tool_phrases["browser"] == "vou abrir o navegador"


def test_filler_settings_loaded(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("FILLER_ENABLED", "false")
    monkeypatch.setenv("FILLER_SILENCE_TIMEOUT", "9")
    monkeypatch.setenv("FILLER_MIN_INTERVAL", "2")
    monkeypatch.setenv("FILLER_MAX_PER_TURN", "5")
    monkeypatch.setenv("FILLER_GENERIC_PHRASES", " Frase um ;; Frase dois ")
    monkeypatch.setenv("FILLER_SILENCE_PHRASES", " ; continua ;")
    monkeypatch.setenv("FILLER_TOOL_PHRASES", "terminal=vou mexer;browser=vou olhar")

    settings = load_settings()

    assert settings.filler_enabled is False
    assert settings.filler_silence_timeout == 9.0
    assert settings.filler_min_interval == 2.0
    assert settings.filler_max_per_turn == 5
    assert settings.filler_generic_phrases == ["Frase um", "Frase dois"]
    assert settings.filler_silence_phrases == ["continua"]
    assert settings.filler_tool_phrases == {
        "terminal": "vou mexer",
        "browser": "vou olhar",
    }


def test_filler_invalid_timeout_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("FILLER_SILENCE_TIMEOUT", "abc")
    with pytest.raises(ValueError, match="FILLER_SILENCE_TIMEOUT"):
        load_settings()


def test_filler_invalid_min_interval_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("FILLER_MIN_INTERVAL", "abc")
    with pytest.raises(ValueError, match="FILLER_MIN_INTERVAL"):
        load_settings()


def test_filler_invalid_max_per_turn_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("FILLER_MAX_PER_TURN", "abc")
    with pytest.raises(ValueError, match="FILLER_MAX_PER_TURN"):
        load_settings()


def test_filler_enabled_requires_generic_phrases(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("FILLER_ENABLED", "true")
    monkeypatch.setenv("FILLER_GENERIC_PHRASES", " ; ")
    with pytest.raises(ValueError, match="FILLER_GENERIC_PHRASES"):
        load_settings()


def test_filler_tool_phrases_malformed_entry_raises(monkeypatch):
    monkeypatch.setenv("HERMES_API_KEY", "secret-123")
    monkeypatch.setenv("FILLER_TOOL_PHRASES", "semIgual")
    with pytest.raises(ValueError, match="FILLER_TOOL_PHRASES"):
        load_settings()
