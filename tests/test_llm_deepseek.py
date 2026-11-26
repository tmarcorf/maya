from __future__ import annotations

from livekit.plugins import openai

from maya_agent.config import DeepSeekSettings
from maya_agent.llm_deepseek import build_deepseek_llm


def test_build_deepseek_llm() -> None:
    settings = DeepSeekSettings(
        api_key="test-key",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        temperature=0.6,
    )

    llm = build_deepseek_llm(settings)

    assert isinstance(llm, openai.LLM)
    assert llm.model == "deepseek-flash"
