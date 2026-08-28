"""Voice pipeline for Maya.

Order mirrors the official Pipecat local-agent example (spec §13), with the
desktop bridge observers inserted:

    transport.input() → stt → [transcript_observer] → user_aggregator → llm → tts
        → [observer] → transport.output() → assistant_aggregator

The main observer needs to sit between the TTS service and the output
transport — not at the end — because the assistant aggregator consumes
LLMFullResponseStartFrame/EndFrame without re-pushing them, while the TTS
service re-emits them downstream along with the full TTS stream
(TTSStartedFrame, TTSAudioRawFrame, TTSTextFrame, TTSStoppedFrame) that the
bridge's voice state machine and audio levels depend on.

The transcript observer must sit between the STT service and the user
aggregator: the aggregator consumes TranscriptionFrame (append-only) without
re-pushing it, so an observer placed downstream would never see it.

Barge-in comes from native mechanisms (spec §9): the VAD analyzer attached to
the user aggregator detects speech during the bot turn, the pipeline cancels
the in-flight LLM processing, and HermesLLMService closes the HTTP stream —
which tells Hermes to cancel the agent turn it was running.
"""

from __future__ import annotations

import re
import unicodedata

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
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transcriptions.language import Language
from pipecat.workers.runner import WorkerRunner

from config.settings import DEFAULT_WAKE_WORD_TIMEOUT, Settings
from pipeline.bridge import BridgeServer, UserTranscriptObserver, VoiceBridge
from pipeline.hermes import HermesLLMService, HermesSessionManager
from pipeline.wake_controller import WakeWordController
from pipeline.wake_strategy import ToggleableWakePhraseStrategy

# Kokoro's native sample rate — avoids a resampling step in the TTS service.
VOICE_AGENT_SAMPLE_RATE = 24000


def _tts_language(settings: Settings) -> Language:
    """Map TTS_LANGUAGE to a Language; Brazilian Portuguese is the default."""
    value = settings.tts_language.strip().lower()
    if value in ("pt", "pt-br"):
        return Language.PT_BR
    return Language(value)


def _normalize_wake_phrase(phrase: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace.

    Mirrors what the pipecat wake strategy does to the transcribed text
    before matching (``_strip_punctuation``): a phrase keeping punctuation
    here would build a regex that can never match the stripped transcription.
    """
    text = re.sub(r"[^\w\s]", "", phrase).lower()
    return re.sub(r"\s+", " ", text).strip()


def _strip_accents(text: str) -> str:
    """Remove diacritics ("tá" → "ta")."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _expand_wake_phrases(phrases: list[str]) -> list[str]:
    """Expand wake phrases into normalized variants that can actually match.

    The pipecat ``WakePhraseUserTurnStartStrategy`` strips punctuation from
    the transcribed text but builds its regexes from the phrases verbatim,
    so punctuation here would make the phrase unmatchable; accents are also
    required literally, while Whisper often drops them ("ta" for "tá").
    Each phrase is therefore normalized (punctuation removed, lowercased)
    and, when it has accents, an accent-stripped variant is added too. The
    maya↔maia expansion covers Whisper's frequent mishearing of the
    assistant's name. Order is kept and duplicates are dropped.
    """
    expanded: list[str] = []
    for phrase in phrases:
        for candidate in (
            phrase,
            re.sub(r"maya", "maia", phrase, flags=re.IGNORECASE),
            re.sub(r"maia", "maya", phrase, flags=re.IGNORECASE),
        ):
            for variant in (
                _normalize_wake_phrase(candidate),
                _normalize_wake_phrase(_strip_accents(candidate)),
            ):
                if variant and variant not in expanded:
                    expanded.append(variant)
    return expanded


def _build_tts_service(settings: Settings):
    """Instantiate the TTS service selected by TTS_PROVIDER.

    Kokoro runs locally (CPU); ElevenLabs streams audio over a WebSocket
    (multi-stream-input) and needs internet + an API key. Imported lazily so
    tests never pay for the module import.
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
    """Instantiate the Maya services.

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


def build_pipeline(
    transport,
    stt,
    llm,
    tts,
    context,
    *,
    vad_analyzer=_UNSET,
    wake_word_enabled: bool = False,
    wake_phrases: list[str] | None = None,
    wake_timeout: float = DEFAULT_WAKE_WORD_TIMEOUT,
    wake_controller: WakeWordController | None = None,
    observer: FrameProcessor | None = None,
    transcript_observer: FrameProcessor | None = None,
):
    """Assemble the Pipeline with the spec §13 ordering.

    The VAD analyzer on the user aggregator provides turn detection and
    barge-in detection (§4, §9). Tests can pass ``vad_analyzer=None`` to
    skip loading the Silero model.

    With a ``wake_controller``, a ``ToggleableWakePhraseStrategy`` is placed
    first in the turn-start strategies: while asleep the LLM never runs, and
    only a transcription matching one of ``wake_phrases`` starts a user
    turn. After ``wake_timeout`` seconds of inactivity the agent goes back
    to sleep. The strategy passes everything through while the controller
    is disabled, so the desktop app can toggle the wake word at runtime.
    With ``wake_word_enabled`` but no controller (tests/backward compat),
    the plain pipecat strategy is used instead.

    ``observer`` (the desktop bridge) sits between the TTS service and the
    output transport. The assistant aggregator consumes the LLM response
    boundary frames without re-pushing them, so an observer appended at the
    end would never see LLMFullResponseStartFrame and the bridge would never
    reach the ``speaking`` state. In this position it still sees every
    SystemFrame (mic audio, VAD/user frames) and the TTS stream re-emitted
    downstream by the TTS service; the Bot frames emitted by the output
    transport reach it via the upstream copies.

    ``transcript_observer`` (optional) sits between the STT service and the
    user aggregator and forwards each final transcription to the bridge as a
    ``user_transcript`` event. It must stay upstream of the aggregator,
    which consumes TranscriptionFrame without re-pushing it. When None
    nothing is inserted and the ordering matches the plain spec §13 chain.
    """
    if vad_analyzer is _UNSET:
        vad_analyzer = SileroVADAnalyzer()

    user_params = LLMUserAggregatorParams(vad_analyzer=vad_analyzer)
    if wake_controller is not None or wake_word_enabled:
        from pipecat.turns.user_turn_strategies import (
            UserTurnStrategies,
            default_user_turn_start_strategies,
        )

        if wake_controller is not None:
            strategy = ToggleableWakePhraseStrategy(
                controller=wake_controller,
                phrases=_expand_wake_phrases(wake_phrases or []),
                timeout=wake_timeout,
            )
        else:
            from pipecat.turns.user_start.wake_phrase_user_turn_start_strategy import (
                WakePhraseUserTurnStartStrategy,
            )

            strategy = WakePhraseUserTurnStartStrategy(
                phrases=_expand_wake_phrases(wake_phrases or []),
                timeout=wake_timeout,
            )

        @strategy.event_handler("on_wake_phrase_detected")
        async def _on_wake_phrase_detected(_strategy, phrase):
            logger.info(f"Wake phrase detectada: {phrase!r}")

        @strategy.event_handler("on_wake_phrase_timeout")
        async def _on_wake_phrase_timeout(_strategy):
            logger.info("Wake phrase timeout — Maya voltou a dormir.")

        user_params = LLMUserAggregatorParams(
            vad_analyzer=vad_analyzer,
            user_turn_strategies=UserTurnStrategies(
                start=[strategy, *default_user_turn_start_strategies()],
            ),
        )

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=user_params,
    )
    processors = [transport.input(), stt]
    if transcript_observer is not None:
        processors.append(transcript_observer)
    processors.extend([user_aggregator, llm, tts])
    if observer is not None:
        processors.append(observer)
    processors.extend([transport.output(), assistant_aggregator])
    return Pipeline(processors)


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
    """Build the pipeline and run Maya until shutdown."""
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

    wake_controller = WakeWordController(enabled=settings.wake_word_enabled)
    observer = VoiceBridge(
        wake_controller=wake_controller,
        session_manager=session_manager,
    )
    transcript_observer = UserTranscriptObserver()
    pipeline = build_pipeline(
        transport,
        stt,
        llm,
        tts,
        context,
        wake_word_enabled=settings.wake_word_enabled,
        wake_phrases=settings.wake_word_phrases,
        wake_timeout=settings.wake_word_timeout,
        wake_controller=wake_controller,
        observer=observer,
        transcript_observer=transcript_observer,
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        # Never tear the agent down after silence — Maya stays listening.
        idle_timeout_secs=None,
        conversation_id=settings.hermes_app_session_id,
    )

    # Palavra de working com a voz da Maya: Kokoro avulso, fora do pipeline
    # (o comando synthesize_word). ElevenLabs não suporta — a síntese avulsa
    # fica indisponível (ack not_available) e o app segue sem fala.
    word_tts = None
    if settings.tts_provider == "kokoro":
        from pipeline.word_tts import WordSynthesizer

        word_tts = WordSynthesizer(settings)

    bridge_server = BridgeServer(
        port=settings.bridge_ws_port,
        wake_controller=wake_controller,
        session_manager=session_manager,
        snapshot=observer.snapshot,
        # O comando send_user_message injeta texto no pipeline (chat).
        queue_frames=worker.queue_frames,
        word_tts=word_tts,
    )
    observer.set_publisher(bridge_server.publish)
    transcript_observer.set_publisher(bridge_server.publish)
    # The wake controller listener is wired inside bridge_server.start().

    runner = WorkerRunner()
    await runner.add_workers(worker)
    if not settings.wake_word_enabled:
        # Kickstart the first turn. With a wake word, the agent must stay
        # silent until the wake phrase is heard — turns start naturally
        # when the wake strategy triggers user turn start.
        await worker.queue_frames([LLMRunFrame()])

    await bridge_server.start()
    try:
        logger.info(
            f"Maya is listening (app session {settings.hermes_app_session_id}, "
            f"Hermes at {settings.hermes_base_url}). Press Ctrl+C to stop."
        )
        await runner.run()
    finally:
        await bridge_server.stop()
