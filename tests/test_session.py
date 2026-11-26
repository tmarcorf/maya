from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from maya_agent.config import TurnSettings, load_settings
from maya_agent.session import attach_hermes_handlers, build_agent, build_turn_handling


def test_build_turn_handling_wires_settings() -> None:
    settings = TurnSettings(
        detector_version="v1-mini",
        endpointing_mode="dynamic",
        min_endpointing_delay=0.2,
        max_endpointing_delay=1.8,
        min_interruption_duration=0.3,
    )

    options = build_turn_handling(settings)

    assert options["endpointing"]["mode"] == "dynamic"
    assert options["endpointing"]["min_delay"] == 0.2
    assert options["endpointing"]["max_delay"] == 1.8
    assert options["interruption"]["enabled"] is True
    assert options["interruption"]["mode"] == "vad"
    assert options["interruption"]["min_duration"] == 0.3


def _settings(tmp_path):
    prompt_path = tmp_path / "maya.md"
    prompt_path.write_text("Formato de voz de teste.", encoding="utf-8")
    return load_settings(
        {
            "HERMES_API_KEY": "hermes-key",
            "ELEVENLABS_API_KEY": "elevenlabs-key",
            "ELEVENLABS_VOICE_ID": "voice-id",
            "MAYA_PROMPT_PATH": str(prompt_path),
        }
    )


def test_build_agent_has_no_local_tools(tmp_path) -> None:
    agent = build_agent(_settings(tmp_path))

    assert agent.tools == []


class FakeEmitter:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, callback: Any = None) -> Any:
        self.handlers[event] = callback
        return callback

    def emit(self, event: str, payload: Any) -> None:
        self.handlers[event](payload)


class FakeHandle:
    def __init__(self) -> None:
        self.interrupted = False

    def done(self) -> bool:
        return False

    def interrupt(self) -> None:
        self.interrupted = True


class FakeSession(FakeEmitter):
    agent_state = "thinking"

    def __init__(self) -> None:
        super().__init__()
        self.spoken: list[tuple[str, dict[str, Any]]] = []
        self.last_handle: FakeHandle | None = None

    def say(self, text: str, **kwargs: Any) -> FakeHandle:
        self.spoken.append((text, kwargs))
        self.last_handle = FakeHandle()
        return self.last_handle


class FakeBroker:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    def publish(self, payload: dict[str, Any]) -> None:
        self.published.append(payload)


async def test_attach_hermes_handlers_speaks_progress_and_publishes_approval(
    monkeypatch,
) -> None:
    monkeypatch.setattr("maya_agent.session.PROGRESS_DELAY_SECONDS", 0.0)
    hermes = FakeEmitter()
    session = FakeSession()
    broker = FakeBroker()
    attach_hermes_handlers(session, hermes, broker)  # type: ignore[arg-type]

    hermes.emit("progress", {"status": "running", "timestamp": 1.0})
    await asyncio.sleep(0.01)
    hermes.emit("approval", {"run_id": "run-1", "request_id": "req-1"})

    assert session.spoken[0] == (
        "Um instante.",
        {"add_to_chat_ctx": False, "allow_interruptions": True},
    )
    assert session.spoken[1][0].startswith("Preciso de uma aprovação")
    assert broker.published == [{"run_id": "run-1", "request_id": "req-1"}]


def test_attach_hermes_handlers_speaks_only_terminal_errors() -> None:
    hermes = FakeEmitter()
    session = FakeSession()
    broker = FakeBroker()
    attach_hermes_handlers(session, hermes, broker)  # type: ignore[arg-type]

    hermes.emit("error", SimpleNamespace(recoverable=True))
    hermes.emit("error", SimpleNamespace(recoverable=False))

    assert len(session.spoken) == 1
    assert session.spoken[0][0].startswith("Tive um problema")


async def test_content_started_interrupts_progress_speech(monkeypatch) -> None:
    monkeypatch.setattr("maya_agent.session.PROGRESS_DELAY_SECONDS", 0.0)
    hermes = FakeEmitter()
    session = FakeSession()
    broker = FakeBroker()
    attach_hermes_handlers(session, hermes, broker)  # type: ignore[arg-type]

    hermes.emit("progress", {"status": "running", "timestamp": 1.0})
    await asyncio.sleep(0.01)
    handle = session.last_handle
    assert handle is not None

    hermes.emit("content_started", {})

    assert handle.interrupted is True


def test_progress_is_silent_while_agent_speaks() -> None:
    hermes = FakeEmitter()
    session = FakeSession()
    broker = FakeBroker()
    session.agent_state = "speaking"
    attach_hermes_handlers(session, hermes, broker)  # type: ignore[arg-type]

    hermes.emit("progress", {"status": "running", "timestamp": 1.0})

    assert session.spoken == []


async def test_cancelled_interrupts_progress_speech(monkeypatch) -> None:
    monkeypatch.setattr("maya_agent.session.PROGRESS_DELAY_SECONDS", 0.0)
    hermes = FakeEmitter()
    session = FakeSession()
    broker = FakeBroker()
    attach_hermes_handlers(session, hermes, broker)  # type: ignore[arg-type]

    hermes.emit("progress", {"status": "running", "timestamp": 1.0})
    await asyncio.sleep(0.01)
    handle = session.last_handle
    assert handle is not None

    hermes.emit("cancelled", {})

    assert handle.interrupted is True


async def test_progress_done_interrupts_progress_speech(monkeypatch) -> None:
    monkeypatch.setattr("maya_agent.session.PROGRESS_DELAY_SECONDS", 0.0)
    hermes = FakeEmitter()
    session = FakeSession()
    broker = FakeBroker()
    attach_hermes_handlers(session, hermes, broker)  # type: ignore[arg-type]

    hermes.emit("progress", {"status": "running", "timestamp": 1.0})
    await asyncio.sleep(0.01)
    handle = session.last_handle
    assert handle is not None

    hermes.emit("progress_done", {})

    assert handle.interrupted is True
