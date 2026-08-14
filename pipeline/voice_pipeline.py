"""Voice pipeline for Polaris.

Order mirrors the official Pipecat local-agent example (spec §13):

    transport.input() → stt → user_aggregator → llm → tts
        → transport.output() → assistant_aggregator

Barge-in comes from native mechanisms (spec §9): the VAD analyzer attached to
the user aggregator detects speech during the bot turn, the pipeline cancels
the in-flight LLM processing, and HermesLLMService closes the HTTP stream —
which tells Hermes to cancel the agent turn it was running.
"""

from __future__ import annotations

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from pipecat.workers.runner import WorkerRunner

from config.settings import Settings
from pipeline.hermes import HermesLLMService, HermesSessionManager

# Kokoro's native sample rate — avoids a resampling step in the TTS service.
VOICE_AGENT_SAMPLE_RATE = 24000


def _tts_language(settings: Settings) -> Language:
    """Map TTS_LANGUAGE to a Language; Brazilian Portuguese is the default."""
    value = settings.tts_language.strip().lower()
    if value in ("pt", "pt-br"):
        return Language.PT_BR
    return Language(value)


def _build_tts_service(settings: Settings):
    """Instantiate the TTS service selected by TTS_PROVIDER.

    Kokoro runs locally; ElevenLabs streams audio over a WebSocket
    (multi-stream-input) and needs internet + an API key. Imported lazily
    so tests never pay for the module import.
    """
    if settings.tts_provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            settings=ElevenLabsTTSService.Settings(
                voice=settings.elevenlabs_voice_id,
                model=settings.elevenlabs_model_id,
                # eleven_flash_v2_5 is multilingual: EL appends
                # language_code=pt to the WS URL. Ignored (with a warning)
                # if a non-multilingual model is configured.
                language=_tts_language(settings),
            ),
            sample_rate=VOICE_AGENT_SAMPLE_RATE,
        )
    return KokoroTTSService(
        settings=KokoroTTSService.Settings(
            voice=settings.tts_voice,
            language=_tts_language(settings),
        ),
        sample_rate=VOICE_AGENT_SAMPLE_RATE,
    )


def build_transport(settings: Settings):
    """Local microphone/speaker transport (imported lazily: needs PyAudio)."""
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    return LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            input_device_index=settings.audio_in_device,
            output_device_index=settings.audio_out_device,
        )
    )


def build_services(
    settings: Settings,
    *,
    transport=None,
    stt=None,
    llm=None,
    tts=None,
    context=None,
    session_manager=None,
):
    """Instantiate the Polaris services.

    Every component can be injected so tests can build the pipeline with
    fakes instead of loading Whisper/Kokoro models.
    """
    if transport is None:
        transport = build_transport(settings)
    if stt is None:
        stt = WhisperSTTService(
            device=settings.stt_device,
            compute_type=settings.stt_compute_type,
            settings=WhisperSTTService.Settings(
                model=settings.stt_model,
                # None means "auto-detect the spoken language".
                language=Language(settings.stt_language) if settings.stt_language else None,
                no_speech_prob=0.4,
            ),
        )
    if session_manager is None:
        session_manager = HermesSessionManager(settings.hermes_app_session_id)
    if llm is None:
        llm = HermesLLMService(
            base_url=settings.hermes_base_url,
            api_key=settings.hermes_api_key,
            model=settings.hermes_model,
            session_manager=session_manager,
        )
    if tts is None:
        # Sentence-level aggregation is built into TTSService (default
        # TextAggregationMode.SENTENCE), so LLM chunks flow to speech as
        # soon as a sentence is complete — no full-response wait (§3).
        tts = _build_tts_service(settings)
    if context is None:
        context = LLMContext()
    return transport, stt, llm, tts, context, session_manager


_UNSET = object()


def build_pipeline(transport, stt, llm, tts, context, *, vad_analyzer=_UNSET):
    """Assemble the Pipeline with the spec §13 ordering.

    The VAD analyzer on the user aggregator provides turn detection and
    barge-in detection (§4, §9). Tests can pass ``vad_analyzer=None`` to
    skip loading the Silero model.
    """
    if vad_analyzer is _UNSET:
        vad_analyzer = SileroVADAnalyzer()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=vad_analyzer),
    )
    return Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )


async def run_voice_agent(
    settings: Settings,
    *,
    transport=None,
    stt=None,
    llm=None,
    tts=None,
    context=None,
    session_manager=None,
) -> None:
    """Build the pipeline and run Polaris until shutdown."""
    if any(component is None for component in (transport, stt, llm, tts, context)):
        transport, stt, llm, tts, context, session_manager = build_services(
            settings,
            transport=transport,
            stt=stt,
            llm=llm,
            tts=tts,
            context=context,
            session_manager=session_manager,
        )

    pipeline = build_pipeline(transport, stt, llm, tts, context)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        # Never tear the agent down after silence — Polaris stays listening.
        idle_timeout_secs=None,
        conversation_id=settings.hermes_app_session_id,
    )

    runner = WorkerRunner()
    await runner.add_workers(worker)
    await worker.queue_frames([LLMRunFrame()])

    logger.info(
        f"Polaris is listening (app session {settings.hermes_app_session_id}, "
        f"Hermes at {settings.hermes_base_url}). Press Ctrl+C to stop."
    )
    await runner.run()
