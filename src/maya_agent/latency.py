from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

logger = logging.getLogger("maya.latency")


class SessionEmitter(Protocol):
    def on(self, event: str, callback: Callable[..., Any] | None = None) -> Callable[..., Any]: ...


def attach_turn_latency_logger(session: SessionEmitter, log: logging.Logger = logger) -> None:
    last_speech_at: float | None = None
    logged = False

    def on_user_state(ev: UserStateChangedEvent) -> None:
        nonlocal last_speech_at, logged
        if ev.new_state == "listening" and ev.old_state == "speaking":
            last_speech_at = ev.speech_timestamp or ev.created_at
            logged = False
        elif ev.new_state == "speaking":
            last_speech_at = None

    def on_agent_state(ev: AgentStateChangedEvent) -> None:
        nonlocal logged
        if ev.new_state != "speaking" or logged or last_speech_at is None:
            return

        log.info(
            "turn latency: end of speech -> first agent audio: %.0f ms",
            max(0.0, ev.created_at - last_speech_at) * 1000,
        )
        logged = True

    session.on("user_state_changed", on_user_state)
    session.on("agent_state_changed", on_agent_state)
