"""Spec §19 item 2 — pipeline creation with the spec §13 ordering."""

from __future__ import annotations

from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregator,
    LLMUserAggregator,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.turns.user_start.wake_phrase_user_turn_start_strategy import (
    WakePhraseUserTurnStartStrategy,
)

from pipeline.hermes import HermesSessionManager
from pipeline.voice_pipeline import (
    _expand_wake_phrases,
    build_pipeline,
    build_services,
)
from tests.conftest import make_settings


class _FakeTransport:
    """Mimics the transport interface used by build_pipeline."""

    def __init__(self):
        self._input = FrameProcessor()
        self._output = FrameProcessor()

    def input(self) -> FrameProcessor:
        return self._input

    def output(self) -> FrameProcessor:
        return self._output


def test_build_pipeline_spec_order():
    transport = _FakeTransport()
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    context = LLMContext()

    # vad_analyzer=None skips loading the Silero model in tests.
    pipeline = build_pipeline(transport, stt, llm, tts, context, vad_analyzer=None)

    assert isinstance(pipeline, Pipeline)
    processors = pipeline.processors
    # PipelineSource, [spec §13 chain], PipelineSink
    assert len(processors) == 9
    assert processors[1] is transport.input()
    assert processors[2] is stt
    assert isinstance(processors[3], LLMUserAggregator)
    assert processors[4] is llm
    assert processors[5] is tts
    assert processors[6] is transport.output()
    assert isinstance(processors[7], LLMAssistantAggregator)


def test_build_pipeline_defaults_to_silero_vad():
    """The production path attaches a VAD analyzer for turn detection (§4)."""
    transport = _FakeTransport()
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    context = LLMContext()

    pipeline = build_pipeline(transport, stt, llm, tts, context)

    user_aggregator = pipeline.processors[3]
    assert user_aggregator._params.vad_analyzer is not None


def test_expand_wake_phrases_adds_polares_variants():
    phrases = ["E aí, Polaris", "Ei, polares", "Olá"]
    assert _expand_wake_phrases(phrases) == [
        "e aí, polaris",
        "e aí, polares",
        "ei, polares",
        "ei, polaris",
        "olá",
    ]


def test_expand_wake_phrases_dedups():
    # "Polares" already covers both spellings of the name (case-insensitive).
    assert _expand_wake_phrases(["Polaris", "Polares"]) == ["polaris", "polares"]


def test_build_pipeline_wake_word_enabled():
    transport = _FakeTransport()
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    context = LLMContext()

    pipeline = build_pipeline(
        transport,
        stt,
        llm,
        tts,
        context,
        vad_analyzer=None,
        wake_word_enabled=True,
        wake_phrases=["E aí, Polaris", "Ei, Polaris"],
        wake_timeout=30.0,
    )

    user_aggregator = pipeline.processors[3]
    start_strategies = user_aggregator._params.user_turn_strategies.start
    wake_strategy = start_strategies[0]
    assert isinstance(wake_strategy, WakePhraseUserTurnStartStrategy)
    assert wake_strategy._phrases == [
        "e aí, polaris",
        "e aí, polares",
        "ei, polaris",
        "ei, polares",
    ]
    assert wake_strategy._timeout == 30.0
    # Wake first, then the two pipecat defaults.
    assert len(start_strategies) == 3


def test_build_pipeline_no_wake_word_keeps_defaults():
    transport = _FakeTransport()
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    context = LLMContext()

    pipeline = build_pipeline(transport, stt, llm, tts, context, vad_analyzer=None)

    user_aggregator = pipeline.processors[3]
    # None means the pipecat defaults are used (current behavior, untouched).
    assert user_aggregator._params.user_turn_strategies is None


def test_build_services_picks_elevenlabs_tts():
    """TTS_PROVIDER=elevenlabs selects the ElevenLabs service.

    Safe in tests: the ElevenLabs service constructor does not connect to
    the network nor validate the API key — both happen on start().
    """
    settings = make_settings(
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-test-key",
        elevenlabs_voice_id="el-voice",
    )
    _, _, _, tts, _, _ = build_services(
        settings,
        transport=_FakeTransport(),
        stt=FrameProcessor(),
        llm=FrameProcessor(),
        context=LLMContext(),
        session_manager=HermesSessionManager("voice-session-test"),
    )
    assert isinstance(tts, ElevenLabsTTSService)
    assert tts._settings.voice == "el-voice"
    assert tts._settings.model == "eleven_flash_v2_5"
    # Language.PT_BR is converted to the service string "pt" at init.
    assert tts._settings.language == "pt"
