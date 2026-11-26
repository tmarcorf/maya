from __future__ import annotations

import pytest

from maya_agent.config import PROJECT_ROOT, load_settings

BASE_ENV = {
    "DEEPSEEK_API_KEY": "deepseek-key",
    "ELEVENLABS_API_KEY": "elevenlabs-key",
    "ELEVENLABS_VOICE_ID": "voice-id",
}


def test_defaults() -> None:
    settings = load_settings(BASE_ENV)

    assert settings.maya.language == "pt-BR"
    assert settings.maya.language_code == "pt"
    assert settings.maya.language_name == "Brazilian Portuguese"
    assert settings.maya.prompt_path == PROJECT_ROOT / "prompts" / "maya.md"
    assert settings.maya.timezone == "America/Sao_Paulo"
    assert settings.whisper.model == "medium"
    assert settings.whisper.device == "auto"
    assert settings.whisper.compute_type == "default"
    assert settings.deepseek.model == "deepseek-flash"
    assert settings.deepseek.base_url == "https://api.deepseek.com"
    assert settings.deepseek.temperature == 0.6
    assert settings.elevenlabs.model_id == "eleven_flash_v2_5"
    assert settings.turn.detector_version == "v1-mini"
    assert settings.turn.endpointing_mode == "fixed"
    assert settings.turn.min_endpointing_delay == 0.3
    assert settings.turn.max_endpointing_delay == 2.5
    assert settings.web_search.enabled is False
    assert settings.web_search.api_key == ""
    assert settings.web_search.max_results == 3
    assert settings.web_search.timeout_seconds == 8.0
    assert settings.web_search.cache_ttl_minutes == 10
    assert settings.web_extract.enabled is True
    assert settings.web_extract.max_urls == 2
    assert settings.web_extract.max_chars == 6000
    assert settings.web_extract.timeout_seconds == 8.0
    assert settings.web_extract.cache_ttl_minutes == 10
    assert settings.apps.enabled is False
    assert settings.apps.launch_timeout_seconds == 5.0


def test_apps_can_be_enabled() -> None:
    settings = load_settings(
        {**BASE_ENV, "APPS_ENABLED": "true", "APPS_LAUNCH_TIMEOUT_SECONDS": "3"}
    )

    assert settings.apps.enabled is True
    assert settings.apps.launch_timeout_seconds == 3.0


def test_apps_timeout_is_validated() -> None:
    with pytest.raises(ValueError, match="APPS_LAUNCH_TIMEOUT_SECONDS"):
        load_settings({**BASE_ENV, "APPS_LAUNCH_TIMEOUT_SECONDS": "0"})


def test_timezone_can_be_overridden() -> None:
    settings = load_settings({**BASE_ENV, "MAYA_TIMEZONE": "Europe/Berlin"})

    assert settings.maya.timezone == "Europe/Berlin"


def test_invalid_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="MAYA_TIMEZONE"):
        load_settings({**BASE_ENV, "MAYA_TIMEZONE": "Mars/Olympus"})


def test_web_search_can_be_enabled_without_a_key() -> None:
    settings = load_settings({**BASE_ENV, "WEB_SEARCH_ENABLED": "true"})

    assert settings.web_search.enabled is True
    assert settings.web_search.api_key == ""


def test_tavily_key_is_loaded() -> None:
    settings = load_settings(
        {
            **BASE_ENV,
            "WEB_SEARCH_ENABLED": "true",
            "TAVILY_API_KEY": "tvly-test",
        }
    )

    assert settings.web_search.api_key == "tvly-test"


def test_web_search_max_results_is_validated() -> None:
    with pytest.raises(ValueError, match="WEB_SEARCH_MAX_RESULTS"):
        load_settings({**BASE_ENV, "WEB_SEARCH_MAX_RESULTS": "0"})


def test_web_search_timeout_is_validated() -> None:
    with pytest.raises(ValueError, match="WEB_SEARCH_TIMEOUT_SECONDS"):
        load_settings({**BASE_ENV, "WEB_SEARCH_TIMEOUT_SECONDS": "1"})


def test_web_search_boolean_is_validated() -> None:
    with pytest.raises(ValueError, match="WEB_SEARCH_ENABLED"):
        load_settings({**BASE_ENV, "WEB_SEARCH_ENABLED": "sometimes"})


def test_web_search_cache_ttl_is_validated() -> None:
    with pytest.raises(ValueError, match="WEB_SEARCH_CACHE_TTL_MINUTES"):
        load_settings({**BASE_ENV, "WEB_SEARCH_CACHE_TTL_MINUTES": "-1"})


def test_web_extract_settings_are_loaded() -> None:
    settings = load_settings(
        {
            **BASE_ENV,
            "WEB_EXTRACT_ENABLED": "false",
            "WEB_EXTRACT_MAX_URLS": "3",
            "WEB_EXTRACT_MAX_CHARS": "4000",
            "WEB_EXTRACT_TIMEOUT_SECONDS": "12",
            "WEB_EXTRACT_CACHE_TTL_MINUTES": "20",
        }
    )

    assert settings.web_extract.enabled is False
    assert settings.web_extract.max_urls == 3
    assert settings.web_extract.max_chars == 4000
    assert settings.web_extract.timeout_seconds == 12.0
    assert settings.web_extract.cache_ttl_minutes == 20


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WEB_EXTRACT_MAX_URLS", "0"),
        ("WEB_EXTRACT_MAX_CHARS", "100"),
        ("WEB_EXTRACT_TIMEOUT_SECONDS", "1"),
        ("WEB_EXTRACT_CACHE_TTL_MINUTES", "-1"),
    ],
)
def test_web_extract_values_are_validated(name: str, value: str) -> None:
    with pytest.raises(ValueError, match=name):
        load_settings({**BASE_ENV, name: value})


def test_language_is_normalized() -> None:
    settings = load_settings({**BASE_ENV, "MAYA_LANGUAGE": "pt_br"})

    assert settings.maya.language == "pt-BR"
    assert settings.maya.language_code == "pt"


def test_relative_prompt_path_is_resolved_from_project_root() -> None:
    settings = load_settings({**BASE_ENV, "MAYA_PROMPT_PATH": "custom/prompt.md"})

    assert settings.maya.prompt_path == PROJECT_ROOT / "custom" / "prompt.md"


def test_absolute_prompt_path_is_preserved(tmp_path) -> None:
    prompt_path = tmp_path / "prompt.md"
    settings = load_settings({**BASE_ENV, "MAYA_PROMPT_PATH": str(prompt_path)})

    assert settings.maya.prompt_path == prompt_path


def test_deepseek_key_is_required() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        load_settings({**BASE_ENV, "DEEPSEEK_API_KEY": ""})


def test_elevenlabs_key_is_required() -> None:
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        load_settings({**BASE_ENV, "ELEVENLABS_API_KEY": ""})


def test_elevenlabs_voice_is_required() -> None:
    with pytest.raises(ValueError, match="ELEVENLABS_VOICE_ID"):
        load_settings({**BASE_ENV, "ELEVENLABS_VOICE_ID": ""})


def test_endpointing_target_must_be_greater_than_minimum() -> None:
    with pytest.raises(ValueError, match="Endpointing delays"):
        load_settings(
            {
                **BASE_ENV,
                "MIN_ENDPOINTING_DELAY": "2.0",
                "MAX_ENDPOINTING_DELAY": "1.0",
            }
        )


def test_whisper_device_is_validated() -> None:
    with pytest.raises(ValueError, match="WHISPER_DEVICE"):
        load_settings({**BASE_ENV, "WHISPER_DEVICE": "gpu"})


def test_turn_detector_version_is_validated() -> None:
    with pytest.raises(ValueError, match="TURN_DETECTOR_VERSION"):
        load_settings({**BASE_ENV, "TURN_DETECTOR_VERSION": "v2"})


def test_temperature_range_is_validated() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_TEMPERATURE"):
        load_settings({**BASE_ENV, "DEEPSEEK_TEMPERATURE": "3"})
