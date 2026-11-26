from __future__ import annotations

from livekit.agents import tts as tts_base
from livekit.plugins import elevenlabs

from .config import ElevenLabsSettings


def build_elevenlabs_tts(settings: ElevenLabsSettings, language: str) -> tts_base.TTS:
    return elevenlabs.TTS(
        voice_id=settings.voice_id,
        model=settings.model_id,
        api_key=settings.api_key,
        language=language,
    )
