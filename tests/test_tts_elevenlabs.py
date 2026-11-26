from __future__ import annotations

from livekit.plugins import elevenlabs

from maya_agent.config import ElevenLabsSettings
from maya_agent.tts_elevenlabs import build_elevenlabs_tts


def test_build_elevenlabs_tts() -> None:
    settings = ElevenLabsSettings(
        api_key="test-key",
        voice_id="voice-id",
        model_id="eleven_flash_v2_5",
    )

    tts = build_elevenlabs_tts(settings, language="pt")

    assert isinstance(tts, elevenlabs.TTS)
    assert tts.model == "eleven_flash_v2_5"
