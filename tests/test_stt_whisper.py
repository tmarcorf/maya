from __future__ import annotations

import pytest
from livekit import rtc
from livekit.agents import APIConnectOptions

from maya_agent.config import WhisperSettings
from maya_agent.stt_whisper import WhisperSTT, build_whisper_stt


class FakeTranscriber:
    def __init__(self, text: str = "Oi, tudo bem?") -> None:
        self.text = text
        self.languages: list[str | None] = []
        self.prewarmed = False

    @property
    def model(self) -> str:
        return "fake-whisper"

    def prewarm(self) -> None:
        self.prewarmed = True

    def transcribe(self, wav_bytes: bytes, language: str | None) -> str:
        self.languages.append(language)
        return self.text


def _frame(seconds: float = 0.2) -> rtc.AudioFrame:
    samples = int(16_000 * seconds)
    return rtc.AudioFrame(
        data=b"\x00\x00" * samples,
        sample_rate=16_000,
        num_channels=1,
        samples_per_channel=samples,
    )


@pytest.mark.asyncio
async def test_recognize_uses_configured_language() -> None:
    transcriber = FakeTranscriber("Oi, tudo bem?")
    stt = WhisperSTT(transcriber=transcriber, language="pt-BR")

    event = await stt._recognize_impl([_frame()], conn_options=APIConnectOptions())

    assert event.alternatives[0].text == "Oi, tudo bem?"
    assert event.alternatives[0].language == "pt"
    assert transcriber.languages == ["pt"]


@pytest.mark.asyncio
async def test_recognize_prefers_explicit_language() -> None:
    transcriber = FakeTranscriber()
    stt = WhisperSTT(transcriber=transcriber, language="pt-BR")

    await stt._recognize_impl([_frame()], language="en-US", conn_options=APIConnectOptions())

    assert transcriber.languages == ["en"]


@pytest.mark.asyncio
async def test_empty_transcript_returns_no_alternatives() -> None:
    stt = WhisperSTT(transcriber=FakeTranscriber(""), language="pt")

    event = await stt._recognize_impl([_frame()], conn_options=APIConnectOptions())

    assert event.alternatives == []


def test_prewarm_delegates_to_transcriber() -> None:
    transcriber = FakeTranscriber()
    stt = WhisperSTT(transcriber=transcriber, language="pt")

    stt.prewarm()

    assert transcriber.prewarmed is True


def test_build_whisper_stt_uses_model_name() -> None:
    stt = build_whisper_stt(
        WhisperSettings(model="tiny", device="cpu", compute_type="int8"),
        language="pt",
    )

    assert isinstance(stt, WhisperSTT)
    assert stt.model == "faster-whisper-tiny"
    assert stt.provider == "local"
