"""Polaris — local voice assistant (Pipecat + Hermes Agent).

Entry point:

    uv run python app.py

Polaris is the voice bridge: audio capture, VAD/turn detection, STT, TTS and
streaming live in Pipecat; all reasoning, tools and memory live in the Hermes
Agent API server (a separate process).
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from dotenv import load_dotenv
from loguru import logger

from config.settings import Settings, load_settings
from pipeline.voice_pipeline import run_voice_agent
from utils.logging import setup_logging


async def check_hermes_health(base_url: str, timeout_secs: float = 3.0) -> bool:
    """Return True when the Hermes API server answers on /v1/health."""
    try:
        async with httpx.AsyncClient(timeout=timeout_secs) as client:
            response = await client.get(f"{base_url}/health")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def _start_hint(base_url: str) -> str:
    return (
        f"Hermes API server is offline at {base_url}/health. Start it with:\n"
        "  hermes gateway\n"
        "and make sure ~/.hermes/.env contains:\n"
        "  API_SERVER_ENABLED=true\n"
        "  API_SERVER_KEY=<your-api-key>\n"
        "Then set the same key as HERMES_API_KEY in this project's .env."
    )


def main() -> int:
    load_dotenv(override=True)

    try:
        settings: Settings = load_settings()
    except ValueError as error:
        print(f"Polaris: configuration error: {error}", file=sys.stderr)
        return 1

    setup_logging(settings.log_level)
    logger.info("Polaris voice agent starting...")

    if not asyncio.run(check_hermes_health(settings.hermes_base_url)):
        logger.error(_start_hint(settings.hermes_base_url))
        return 1

    try:
        asyncio.run(run_voice_agent(settings))
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Polaris shutting down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
