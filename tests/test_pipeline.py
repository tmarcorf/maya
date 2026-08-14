"""Spec §19 item 2 — pipeline creation with the spec §13 ordering."""

from __future__ import annotations

from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregator,
    LLMUserAggregator,
)
from pipecat.processors.frame_processor import FrameProcessor

from pipeline.voice_pipeline import build_pipeline


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
