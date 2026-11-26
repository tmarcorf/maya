from __future__ import annotations

from livekit.agents import llm as llm_base
from livekit.plugins import openai

from .config import DeepSeekSettings


def build_deepseek_llm(settings: DeepSeekSettings) -> llm_base.LLM:
    return openai.LLM(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
        extra_body={"thinking": {"type": "disabled"}},
    )
