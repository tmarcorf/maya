from __future__ import annotations

from maya_agent.config import TurnSettings, load_settings
from maya_agent.session import build_agent, build_turn_handling


def test_build_turn_handling_wires_settings() -> None:
    settings = TurnSettings(
        detector_version="v1-mini",
        endpointing_mode="dynamic",
        min_endpointing_delay=0.2,
        max_endpointing_delay=1.8,
        min_interruption_duration=0.3,
    )

    options = build_turn_handling(settings)

    assert options["endpointing"]["mode"] == "dynamic"
    assert options["endpointing"]["min_delay"] == 0.2
    assert options["endpointing"]["max_delay"] == 1.8
    assert options["interruption"]["enabled"] is True
    assert options["interruption"]["mode"] == "vad"
    assert options["interruption"]["min_duration"] == 0.3


def _settings(tmp_path, *, web_search_enabled: bool, apps_enabled: bool = False):
    prompt_path = tmp_path / "maya.md"
    prompt_path.write_text("Persona de teste.", encoding="utf-8")
    return load_settings(
        {
            "DEEPSEEK_API_KEY": "deepseek-key",
            "ELEVENLABS_API_KEY": "elevenlabs-key",
            "ELEVENLABS_VOICE_ID": "voice-id",
            "MAYA_PROMPT_PATH": str(prompt_path),
            "WEB_SEARCH_ENABLED": "true" if web_search_enabled else "false",
            "APPS_ENABLED": "true" if apps_enabled else "false",
        }
    )


def test_build_agent_includes_all_tools_when_web_search_enabled(tmp_path) -> None:
    agent = build_agent(_settings(tmp_path, web_search_enabled=True))

    assert [tool.info.name for tool in agent.tools] == [
        "web_search",
        "web_extract",
        "get_current_datetime",
        "calculate",
        "wikipedia",
        "get_weather",
        "get_weather_forecast",
        "get_market_summary",
        "get_stock_quote",
    ]


def test_build_agent_keeps_non_search_tools_when_web_search_disabled(tmp_path) -> None:
    agent = build_agent(_settings(tmp_path, web_search_enabled=False))

    assert [tool.info.name for tool in agent.tools] == [
        "web_extract",
        "get_current_datetime",
        "calculate",
        "wikipedia",
        "get_weather",
        "get_weather_forecast",
        "get_market_summary",
        "get_stock_quote",
    ]


def test_build_agent_includes_open_app_when_enabled(tmp_path) -> None:
    agent = build_agent(
        _settings(
            tmp_path,
            web_search_enabled=True,
            apps_enabled=True,
        )
    )

    names = [tool.info.name for tool in agent.tools]
    assert "find_apps" in names
    assert "open_app" in names
