from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from livekit.agents import Agent, AgentSession, TurnHandlingOptions, inference
from livekit.agents import vad as vad_base

from .approvals import ApprovalBroker
from .config import AppSettings, TurnSettings
from .instructions import build_instructions
from .llm_hermes import HermesLLM, StreamTransport, build_hermes_llm
from .stt_whisper import build_whisper_stt
from .tts_elevenlabs import build_elevenlabs_tts

PROGRESS_PHRASE = "Um instante."
APPROVAL_PHRASE = "Preciso de uma aprovação. Abri um painel no computador."
ERROR_PHRASE = "Tive um problema ao falar com o Hermes. Tente de novo em instantes."
PROGRESS_DELAY_SECONDS = 2.0

logger = logging.getLogger("maya.session")


def build_turn_handling(settings: TurnSettings) -> TurnHandlingOptions:
    return TurnHandlingOptions(
        turn_detection=inference.TurnDetector(version=settings.detector_version),
        endpointing={
            "mode": settings.endpointing_mode,
            "min_delay": settings.min_endpointing_delay,
            "max_delay": settings.max_endpointing_delay,
        },
        interruption={
            "enabled": True,
            "mode": "vad",
            "min_duration": settings.min_interruption_duration,
            "discard_audio_if_uninterruptible": True,
            "resume_false_interruption": True,
            "false_interruption_timeout": 1.5,
        },
        preemptive_generation={
            "enabled": True,
            "preemptive_tts": False,
        },
    )


def build_agent(settings: AppSettings) -> Agent:
    return Agent(instructions=build_instructions(settings.maya), tools=[])


def attach_hermes_handlers(
    session: AgentSession,
    hermes: HermesLLM,
    broker: ApprovalBroker,
) -> None:
    progress_speech = None
    progress_task: asyncio.Task[None] | None = None

    async def speak_progress() -> None:
        nonlocal progress_speech
        try:
            await asyncio.sleep(PROGRESS_DELAY_SECONDS)
        except asyncio.CancelledError:
            return
        if getattr(session, "agent_state", "thinking") == "speaking":
            return
        if progress_speech is not None and not progress_speech.done():
            return
        try:
            progress_speech = session.say(
                PROGRESS_PHRASE,
                add_to_chat_ctx=False,
                allow_interruptions=True,
            )
        except Exception:
            logger.debug("progress speech failed", exc_info=True)

    def on_progress(payload: dict) -> None:
        nonlocal progress_task
        if payload.get("status") != "running":
            return
        if getattr(session, "agent_state", "thinking") == "speaking":
            return
        if progress_task is not None and not progress_task.done():
            return
        if progress_speech is not None and not progress_speech.done():
            return
        progress_task = asyncio.create_task(speak_progress(), name="maya-progress-speech")

    def stop_progress() -> None:
        nonlocal progress_speech, progress_task
        if progress_task is not None and not progress_task.done():
            progress_task.cancel()
        progress_task = None
        if progress_speech is not None and not progress_speech.done():
            try:
                progress_speech.interrupt()
            except RuntimeError:
                logger.debug("progress speech cannot be interrupted", exc_info=True)
        progress_speech = None

    def on_content_started(payload: dict) -> None:
        stop_progress()

    def on_cancelled(payload: dict) -> None:
        stop_progress()

    def on_progress_done(payload: dict) -> None:
        stop_progress()

    def on_approval(payload: dict) -> None:
        if not payload.get("silent"):
            session.say(APPROVAL_PHRASE, add_to_chat_ctx=False, allow_interruptions=False)
        broker.publish(payload)

    def on_error(event: object) -> None:
        if getattr(event, "recoverable", False):
            return
        session.say(ERROR_PHRASE, add_to_chat_ctx=False, allow_interruptions=False)

    def on_close(event: object) -> None:
        stop_progress()
        broker.close_later()

    hermes.on("progress", on_progress)
    hermes.on("progress_done", on_progress_done)
    hermes.on("content_started", on_content_started)
    hermes.on("cancelled", on_cancelled)
    hermes.on("approval", on_approval)
    hermes.on("error", on_error)
    session.on("close", on_close)


def build_session(
    settings: AppSettings,
    vad: vad_base.VAD,
    *,
    session_id: str | None = None,
    stream: StreamTransport | None = None,
    approval_broker: ApprovalBroker | None = None,
) -> AgentSession:
    voice_instruction = build_instructions(settings.maya)
    hermes = build_hermes_llm(
        settings.hermes,
        session_id=session_id or uuid4().hex,
        voice_instruction=voice_instruction,
        stream=stream,
    )
    session = AgentSession(
        vad=vad,
        stt=build_whisper_stt(settings.whisper, settings.maya.language_code),
        llm=hermes,
        tts=build_elevenlabs_tts(settings.elevenlabs, settings.maya.language_code),
        turn_handling=build_turn_handling(settings.turn),
    )
    broker = approval_broker or ApprovalBroker(
        base_url=settings.hermes.base_url,
        api_key=settings.hermes.api_key,
        port=settings.hermes.approval_port,
        enabled=settings.hermes.approval_enabled,
    )
    attach_hermes_handlers(session, hermes, broker)
    return session
