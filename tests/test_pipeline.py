"""Spec §19 item 2 — pipeline creation with the spec §13 ordering."""

from __future__ import annotations

import pytest
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
from pipeline.wake_controller import WakeWordController
from pipeline.wake_strategy import ToggleableWakePhraseStrategy
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


def test_expand_wake_phrases_adds_maia_variants():
    phrases = ["E aí, Maya", "Ei, maia", "Olá"]
    assert _expand_wake_phrases(phrases) == [
        "e aí maya",
        "e ai maya",
        "e aí maia",
        "e ai maia",
        "ei maia",
        "ei maya",
        "olá",
        "ola",
    ]


def test_expand_wake_phrases_dedups():
    # "Maia" already covers both spellings of the name (case-insensitive).
    assert _expand_wake_phrases(["Maya", "Maia"]) == ["maya", "maia"]


class _StubTaskManager:
    """Minimal task manager so _check_wake_phrase can fire the detected event."""

    def create_task(self, _coro, _name=None):
        return None


def test_wake_phrases_match_realistic_stt_output():
    """The pipecat strategy strips punctuation from transcriptions but builds
    its patterns from the phrases — expanded phrases must match anyway."""
    phrases = _expand_wake_phrases(["E aí, Maya", "Ei, Maya", "Maya, tá aí?"])
    strategy = WakePhraseUserTurnStartStrategy(phrases=phrases, timeout=10)
    strategy._task_manager = _StubTaskManager()

    for transcription in (
        "E aí, Maya",
        "e aí maia",  # Whisper mishears the assistant's name.
        "e ai maya",  # Whisper drops the accent.
        "Ei, Maya",
        "Maya tá aí",
        "maia ta ai",  # accent + name misspelling.
    ):
        assert strategy._check_wake_phrase(transcription), transcription

    # Unrelated speech must not wake the agent.
    assert not strategy._check_wake_phrase("Que horas são?")


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
        wake_phrases=["E aí, Maya", "Ei, Maya"],
        wake_timeout=30.0,
    )

    user_aggregator = pipeline.processors[3]
    start_strategies = user_aggregator._params.user_turn_strategies.start
    wake_strategy = start_strategies[0]
    assert isinstance(wake_strategy, WakePhraseUserTurnStartStrategy)
    assert wake_strategy._phrases == [
        "e aí maya",
        "e ai maya",
        "e aí maia",
        "e ai maia",
        "ei maya",
        "ei maia",
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


def test_build_pipeline_wake_controller_always_adds_toggleable_strategy():
    """The toggleable strategy is first even when the wake word starts OFF —
    the desktop app can enable it at runtime."""
    from pipeline.bridge import VoiceBridge

    transport = _FakeTransport()
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    context = LLMContext()
    controller = WakeWordController(enabled=False)
    observer = VoiceBridge(wake_controller=controller)

    pipeline = build_pipeline(
        transport,
        stt,
        llm,
        tts,
        context,
        vad_analyzer=None,
        wake_word_enabled=False,
        wake_phrases=["E aí, Maya"],
        wake_controller=controller,
        observer=observer,
    )

    user_aggregator = pipeline.processors[3]
    start_strategies = user_aggregator._params.user_turn_strategies.start
    assert isinstance(start_strategies[0], ToggleableWakePhraseStrategy)
    assert len(start_strategies) == 3  # wake + the two pipecat defaults

    # The observer sits between the TTS service and the output transport
    # (processors[0] is the source and processors[-1] the sink).
    processors = pipeline.processors
    assert len(processors) == 10
    assert processors[6] is observer
    assert processors[7] is transport.output()
    assert isinstance(processors[8], LLMAssistantAggregator)


def test_build_pipeline_transcript_observer_between_stt_and_aggregator():
    from pipeline.bridge import UserTranscriptObserver, VoiceBridge

    transport = _FakeTransport()
    stt, llm, tts = FrameProcessor(), FrameProcessor(), FrameProcessor()
    context = LLMContext()
    controller = WakeWordController(enabled=False)
    observer = VoiceBridge(wake_controller=controller)
    transcript_observer = UserTranscriptObserver()

    pipeline = build_pipeline(
        transport,
        stt,
        llm,
        tts,
        context,
        vad_analyzer=None,
        wake_controller=controller,
        observer=observer,
        transcript_observer=transcript_observer,
    )

    processors = pipeline.processors
    assert len(processors) == 11
    assert processors[1] is transport.input()
    assert processors[2] is stt
    assert processors[3] is transcript_observer
    assert isinstance(processors[4], LLMUserAggregator)
    assert processors[5] is llm
    assert processors[6] is tts
    assert processors[7] is observer
    assert processors[8] is transport.output()
    assert isinstance(processors[9], LLMAssistantAggregator)


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
