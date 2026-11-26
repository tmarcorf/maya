from __future__ import annotations

from livekit.agents import Agent, AgentSession, TurnHandlingOptions, inference
from livekit.agents import vad as vad_base

from .config import AppSettings, TurnSettings
from .instructions import build_instructions
from .llm_deepseek import build_deepseek_llm
from .stt_whisper import build_whisper_stt
from .tools import build_tools
from .tts_elevenlabs import build_elevenlabs_tts


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
    return Agent(
        instructions=build_instructions(settings.maya),
        tools=build_tools(settings),
    )


def build_session(settings: AppSettings, vad: vad_base.VAD) -> AgentSession:
    return AgentSession(
        vad=vad,
        stt=build_whisper_stt(settings.whisper, settings.maya.language_code),
        llm=build_deepseek_llm(settings.deepseek),
        tts=build_elevenlabs_tts(settings.elevenlabs, settings.maya.language_code),
        turn_handling=build_turn_handling(settings.turn),
    )
