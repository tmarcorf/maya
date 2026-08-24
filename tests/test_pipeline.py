"""Spec §19 item 2 — pipeline creation with the spec §13 ordering."""

from __future__ import annotations

import numpy as np
import pytest
from pipecat.frames.frames import TTSAudioRawFrame
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
from pipeline.qwen3_tts import Qwen3TTSService
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


class _FakeQwenModel:
    """Mimics qwen_tts.Qwen3TTSModel without torch (see _load_qwen_model).

    Stores ``speakers`` exactly as passed: None is meaningful (non-CustomVoice
    checkpoints expose no speaker list).
    """

    def __init__(self, speakers=None, wavs=None, sr=24000):
        self._speakers = speakers
        self._wavs = wavs
        self._sr = sr

    def get_supported_speakers(self):
        return self._speakers

    def create_voice_clone_prompt(self, ref_audio=None, ref_text=None, x_vector_only_mode=False):
        """Mirrors qwen_tts; returns a dict the service treats as opaque."""
        self.last_prompt_kwargs = {
            "ref_audio": ref_audio,
            "ref_text": ref_text,
            "x_vector_only_mode": x_vector_only_mode,
        }
        return {"frozen": True, **self.last_prompt_kwargs}

    def generate_voice_clone(
        self,
        text,
        language=None,
        ref_audio=None,
        ref_text=None,
        x_vector_only_mode=False,
        voice_clone_prompt=None,
        non_streaming_mode=True,
        **kwargs,
    ):
        """Mirrors the real qwen_tts signature; records how it was called."""
        self.last_clone_call = {
            "ref_audio": ref_audio,
            "ref_text": ref_text,
            "x_vector_only_mode": x_vector_only_mode,
            "voice_clone_prompt": voice_clone_prompt,
        }
        return self._wavs, self._sr

    def generate_custom_voice(
        self, text, speaker, language=None, instruct=None, non_streaming_mode=True, **kwargs
    ):
        """Mirrors the real qwen_tts signature (speaker before language)."""
        return self._wavs, self._sr


def _fake_qwen_model(monkeypatch, speakers=None, wavs=None, sr=24000):
    """Install a fake model via monkeypatch (None defaults to ["Ryan"])."""
    model = _FakeQwenModel(
        speakers=speakers if speakers is not None else ["Ryan"],
        wavs=wavs,
        sr=sr,
    )
    monkeypatch.setattr("pipeline.qwen3_tts._load_qwen_model", lambda *a, **k: model)
    return model


def test_build_services_picks_qwen3_tts(monkeypatch):
    """TTS_PROVIDER=qwen3 selects the Qwen3 service, without torch in tests.

    Safe: `pipeline.qwen3_tts` only imports light modules at module level;
    the heavy torch/qwen-tts import lives inside _load_qwen_model, which is
    monkeypatched here.
    """
    _fake_qwen_model(monkeypatch)
    settings = make_settings(tts_provider="qwen3")
    _, _, _, tts, _, _ = build_services(
        settings,
        transport=_FakeTransport(),
        stt=FrameProcessor(),
        llm=FrameProcessor(),
        context=LLMContext(),
        session_manager=HermesSessionManager("voice-session-test"),
    )
    assert isinstance(tts, Qwen3TTSService)
    assert tts._settings.voice == "Ryan"
    # Language.PT_BR is converted to the qwen-tts name at init.
    assert tts._settings.language == "Portuguese"
    assert tts._init_sample_rate == 24000


def test_qwen3_service_rejects_unknown_speaker(monkeypatch):
    _fake_qwen_model(monkeypatch, speakers=["Ryan"])
    with pytest.raises(ValueError, match="QWEN3_SPEAKER"):
        Qwen3TTSService(
            model_id="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
            settings=Qwen3TTSService.Settings(voice="Nobody"),
            sample_rate=24000,
        )


def test_qwen3_service_normalizes_speaker_case(monkeypatch):
    """The hub lists speakers in lowercase; the model card uses Title Case."""
    _fake_qwen_model(monkeypatch, speakers=["ryan", "serena"])
    service = Qwen3TTSService(
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        settings=Qwen3TTSService.Settings(voice="Ryan"),
        sample_rate=24000,
    )
    assert service._speaker == "ryan"


def test_qwen3_service_rejects_model_without_speaker_list(monkeypatch):
    """Non-CustomVoice checkpoints expose no speakers (get returns None)."""
    model = _FakeQwenModel(speakers=None)
    monkeypatch.setattr("pipeline.qwen3_tts._load_qwen_model", lambda *a, **k: model)
    with pytest.raises(ValueError, match="speaker list"):
        Qwen3TTSService(
            model_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
            settings=Qwen3TTSService.Settings(voice="Ryan"),
            sample_rate=24000,
        )


async def test_qwen3_run_tts_yields_audio_frame(monkeypatch):
    """One aggregated sentence → one resampled audio frame.

    Metrics calls are no-ops outside a running pipeline (metrics_enabled is
    False by default); _sample_rate is set by StartFrame in production, so
    the test sets it directly.
    """
    sr = 24000
    _fake_qwen_model(monkeypatch, wavs=[np.zeros((1, sr), dtype=np.float32)], sr=sr)
    service = Qwen3TTSService(
        model_id="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        settings=Qwen3TTSService.Settings(voice="Ryan"),
        sample_rate=sr,
    )
    service._sample_rate = sr

    frames = [frame async for frame in service.run_tts("olá", "ctx-1")]

    assert len(frames) == 1
    frame = frames[0]
    assert isinstance(frame, TTSAudioRawFrame)
    assert frame.sample_rate == sr
    assert frame.num_channels == 1
    assert len(frame.audio) > 0


async def test_qwen3_frozen_timbre_prompt_built_once(monkeypatch):
    """-Base + ref_audio (no ref_text): prompt frozen at init, reused per call.

    The voice is locked at construction: x-vector (timbre-only) mode, and
    every synthesize call passes only the precomputed prompt — no
    per-sentence ref_audio/ref_text re-extraction.
    """
    sr = 24000
    model = _fake_qwen_model(
        monkeypatch,
        speakers=None,
        wavs=[np.zeros((1, sr), dtype=np.float32)],
        sr=sr,
    )
    service = Qwen3TTSService(
        model_id="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        settings=Qwen3TTSService.Settings(
            voice="",
            ref_audio="/tmp/ref.wav",
            ref_text=None,
        ),
        sample_rate=sr,
    )
    service._sample_rate = sr

    # Prompt extracted exactly once, in timbre-only mode.
    prompt = service._voice_clone_prompt
    assert prompt is not None
    assert prompt["frozen"] is True
    assert prompt["x_vector_only_mode"] is True
    assert model.last_prompt_kwargs["ref_text"] is None

    # Synthesize twice: both calls reuse the frozen prompt, no re-extraction.
    for _ in range(2):
        frames = [frame async for frame in service.run_tts("olá", "ctx-1")]
        assert len(frames) == 1 and isinstance(frames[0], TTSAudioRawFrame)

    assert model.last_clone_call["voice_clone_prompt"] is service._voice_clone_prompt
    assert model.last_clone_call["ref_audio"] is None
    assert model.last_clone_call["ref_text"] is None
    assert model.last_clone_call["x_vector_only_mode"] is False  # unused with prompt


def test_qwen3_frozen_icl_prompt_with_ref_text(monkeypatch):
    """-Base + ref_audio + ref_text: full ICL clone, also frozen at init."""
    sr = 24000
    model = _fake_qwen_model(
        monkeypatch,
        speakers=None,
        wavs=[np.zeros((1, sr), dtype=np.float32)],
        sr=sr,
    )
    service = Qwen3TTSService(
        model_id="Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        settings=Qwen3TTSService.Settings(
            voice="",
            ref_audio="/tmp/ref.wav",
            ref_text="This is the reference transcript.",
        ),
        sample_rate=sr,
    )

    assert service._voice_clone_prompt["x_vector_only_mode"] is False
    assert model.last_prompt_kwargs["ref_text"] == "This is the reference transcript."
