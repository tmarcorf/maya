from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

logger = logging.getLogger("maya.latency")


class SessionEmitter(Protocol):
    def on(self, event: str, callback: Callable[..., Any] | None = None) -> Callable[..., Any]: ...


def attach_turn_latency_logger(
    session: SessionEmitter,
    *,
    llm: SessionEmitter | None = None,
    room: str | None = None,
    session_id: str | None = None,
    log: logging.Logger = logger,
) -> None:
    last_speech_at: float | None = None
    logged = False
    first_token_ms: int | None = None
    tool_ack_ms: int | None = None

    def on_user_state(ev: UserStateChangedEvent) -> None:
        nonlocal last_speech_at, logged, first_token_ms, tool_ack_ms
        if ev.new_state == "listening" and ev.old_state == "speaking":
            last_speech_at = ev.speech_timestamp or ev.created_at
            logged = False
            first_token_ms = None
            tool_ack_ms = None
        elif ev.new_state == "speaking":
            last_speech_at = None

    def on_agent_state(ev: AgentStateChangedEvent) -> None:
        nonlocal logged
        if ev.new_state != "speaking" or logged or last_speech_at is None:
            return

        first_audio_ms = round(max(0.0, ev.created_at - last_speech_at) * 1000)
        record = {
            "room": room,
            "session_id": session_id,
            "first_audio_ms": first_audio_ms,
            "first_token_ms": first_token_ms,
            "tool_ack_ms": tool_ack_ms,
        }
        log.info(
            "turn latency: end of speech -> first agent audio: %d ms %s",
            first_audio_ms,
            json.dumps(record, ensure_ascii=False),
        )
        logged = True

    def on_metrics(ev: Any) -> None:
        nonlocal first_token_ms
        if last_speech_at is None or first_token_ms is not None:
            return
        ttft = getattr(ev, "ttft", None)
        if isinstance(ttft, (int, float)):
            first_token_ms = round(max(0.0, float(ttft)) * 1000)

    def on_progress(payload: Any) -> None:
        nonlocal tool_ack_ms
        if last_speech_at is None or tool_ack_ms is not None or not isinstance(payload, dict):
            return
        timestamp = payload.get("timestamp")
        if isinstance(timestamp, (int, float)):
            tool_ack_ms = round(max(0.0, float(timestamp) - last_speech_at) * 1000)

    session.on("user_state_changed", on_user_state)
    session.on("agent_state_changed", on_agent_state)
    if llm is not None:
        llm.on("metrics_collected", on_metrics)
        llm.on("progress", on_progress)
