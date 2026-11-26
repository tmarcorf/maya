from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from livekit.agents import AgentStateChangedEvent, UserStateChangedEvent

from maya_agent.latency import attach_turn_latency_logger


class FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, callback: Any = None) -> Any:
        if callback is not None:
            self.handlers[event] = callback
            return callback

        def register(fn: Any) -> Any:
            self.handlers[event] = fn
            return fn

        return register

    def emit(self, event: str, payload: Any) -> None:
        self.handlers[event](payload)


def _user_stopped_speaking(created_at: float) -> UserStateChangedEvent:
    return UserStateChangedEvent(
        type="user_state_changed",
        old_state="speaking",
        new_state="listening",
        speech_timestamp=created_at,
        created_at=created_at,
    )


def _agent_started_speaking(created_at: float) -> AgentStateChangedEvent:
    return AgentStateChangedEvent(
        type="agent_state_changed",
        old_state="thinking",
        new_state="speaking",
        created_at=created_at,
    )


def test_logs_time_from_end_of_speech_to_first_audio(caplog) -> None:
    caplog.set_level(logging.INFO, logger="maya.latency")
    session = FakeSession()
    attach_turn_latency_logger(session)

    now = 1_000.0
    session.emit("user_state_changed", _user_stopped_speaking(now))
    session.emit("agent_state_changed", _agent_started_speaking(now + 0.8))

    assert "800 ms" in caplog.text


def test_does_not_log_greeting(caplog) -> None:
    caplog.set_level(logging.INFO, logger="maya.latency")
    session = FakeSession()
    attach_turn_latency_logger(session)

    session.emit("agent_state_changed", _agent_started_speaking(1_000.0))

    assert "turn latency" not in caplog.text


def test_logs_once_per_turn(caplog) -> None:
    caplog.set_level(logging.INFO, logger="maya.latency")
    session = FakeSession()
    attach_turn_latency_logger(session)

    now = 1_000.0
    session.emit("user_state_changed", _user_stopped_speaking(now))
    session.emit("agent_state_changed", _agent_started_speaking(now + 0.5))
    session.emit("agent_state_changed", _agent_started_speaking(now + 0.7))

    assert caplog.text.count("turn latency") == 1


class FakeLLM(FakeSession):
    pass


def test_logs_structured_turn_record(caplog) -> None:
    caplog.set_level(logging.INFO, logger="maya.latency")
    session = FakeSession()
    llm = FakeLLM()
    attach_turn_latency_logger(session, llm=llm, room="room-1", session_id="session-1")

    now = 1_000.0
    session.emit("user_state_changed", _user_stopped_speaking(now))
    llm.emit("metrics_collected", SimpleNamespace(ttft=0.5))
    llm.emit("progress", {"status": "running", "timestamp": now + 1.2})
    session.emit("agent_state_changed", _agent_started_speaking(now + 2.0))

    assert '"first_audio_ms": 2000' in caplog.text
    assert '"first_token_ms": 500' in caplog.text
    assert '"tool_ack_ms": 1200' in caplog.text
    assert '"room": "room-1"' in caplog.text
    assert '"session_id": "session-1"' in caplog.text
