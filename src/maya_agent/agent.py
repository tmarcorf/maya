from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentServer, JobContext, JobProcess
from livekit.plugins import silero

from .config import PROJECT_ROOT, load_settings
from .instructions import greeting_instructions
from .latency import attach_turn_latency_logger
from .session import build_agent, build_session

logger = logging.getLogger("maya")


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext) -> None:
    settings = load_settings(os.environ)
    logger.info(
        "starting Maya: language=%s whisper=%s/%s deepseek=%s elevenlabs=%s "
        "turn_detector=%s web_search=%s",
        settings.maya.language,
        settings.whisper.model,
        settings.whisper.device,
        settings.deepseek.model,
        settings.elevenlabs.model_id,
        settings.turn.detector_version,
        "enabled" if settings.web_search.enabled else "disabled",
    )

    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()
    session = build_session(settings, vad)
    attach_turn_latency_logger(session)

    await session.start(agent=build_agent(settings), room=ctx.room)
    await session.generate_reply(instructions=greeting_instructions(settings.maya))


def build_server() -> AgentServer:
    server = AgentServer(setup_fnc=prewarm)
    server.rtc_session()(entrypoint)
    return server


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    agents.cli.run_app(build_server())


if __name__ == "__main__":
    main()
