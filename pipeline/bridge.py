"""Local WebSocket bridge that mirrors the voice pipeline to the desktop app.

A single observer processor at the end of the pipeline derives the voice
state machine from Pipecat frames and publishes structured events; a small
websockets server on 127.0.0.1 forwards them to the desktop app and handles
control commands (currently: the runtime wake-word toggle). The bridge is
purely observational — nothing it does changes how audio/LLM frames flow.

Protocol (JSON lines, one object per WebSocket frame; ``ts`` = epoch ms):

    server → client events:
      hello {bridgeVersion, session}
      state {voice, wake:{enabled, state, phrase}}
      user_transcript {text}
      agent_text {turnId, delta} / agent_text_end {turnId, text}
      tool_activity {tool, label, emoji, toolCallId, status}
      interruption {}
      audio_level {input, output}      (throttled to ~30 Hz)
      wake_state {enabled, state, phrase}
      error {code, message}
    client → server commands (ack is the only response — never optimistic):
      {id, cmd:"get_state"} → ack {voice, wake, session}
      {id, cmd:"set_wake_word_enabled", enabled} → ack {enabled}
      {id, cmd:"ping"} → ack "pong"
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable

import numpy as np
import websockets
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.frames import ToolActivityFrame
from pipeline.hermes import HermesSessionManager
from pipeline.wake_controller import WakeWordController

BRIDGE_VERSION = 1
HOST = "127.0.0.1"
# Broadcast audio levels at most every LEVEL_INTERVAL_SECS seconds (~30 Hz).
LEVEL_INTERVAL_SECS = 0.033
# Tool activity can arrive in bursts; keep the newest status per tool call
# but never emit more than one event per tool per TOOL_THROTTLE_SECS.
TOOL_THROTTLE_SECS = 0.2
MAX_TRACKED_TOOLS = 64

VoiceState = str  # "idle" | "user_speaking" | "listening" | "thinking" | "speaking"
Publisher = Callable[[dict], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _rms(audio: bytes, num_channels: int) -> float:
    """RMS of an int16 PCM chunk, 0..1, averaged over channels."""
    if not audio:
        return 0.0
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
    if num_channels > 1:
        samples = samples.reshape(-1, num_channels).mean(axis=1)
    return float(min(np.sqrt(np.mean(samples**2)), 1.0))


class VoiceBridge(FrameProcessor):
    """Observer at the end of the pipeline: derives voice state + levels.

    Frames flow through unchanged; each is inspected exactly once and
    converted into bridge events. Transitions are idempotent — a repeated
    event never re-broadcasts the same state.
    """

    def __init__(
        self,
        *,
        wake_controller: WakeWordController,
        session_manager: HermesSessionManager | None = None,
    ) -> None:
        super().__init__()
        self._wake_controller = wake_controller
        self._session_manager = session_manager
        self._publisher: Publisher | None = None
        self._voice: VoiceState = "idle"
        self._turn_id: str | None = None
        self._turn_text = ""
        self._levels = {"input": 0.0, "output": 0.0}
        self._last_level_ts = 0.0
        self._last_tool_ts: dict[str, float] = {}

    def set_publisher(self, publisher: Publisher | None) -> None:
        """Attach the event sink (the ``BridgeServer.publish`` coroutine)."""
        self._publisher = publisher

    @property
    def voice(self) -> VoiceState:
        return self._voice

    def snapshot(self) -> dict:
        """Current state, sent on connect and as the ``get_state`` reply."""
        return {
            "voice": self._voice,
            "wake": self._wake_payload(),
            "session": self._session_payload(),
        }

    def _wake_payload(self) -> dict:
        return {
            "enabled": self._wake_controller.enabled,
            "state": self._wake_controller.state,
            "phrase": self._wake_controller.phrase,
        }

    def _session_payload(self) -> dict:
        return {
            "appSessionId": (
                self._session_manager.app_session_id if self._session_manager else None
            ),
            "hermesSessionId": (
                self._session_manager.current_hermes_session_id()
                if self._session_manager
                else None
            ),
        }

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            await self._set_voice("user_speaking")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._voice == "user_speaking":
                await self._set_voice("listening")
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._turn_id = str(uuid.uuid4())
            self._turn_text = ""
            await self._set_voice("thinking")
        elif isinstance(frame, LLMTextFrame):
            if self._turn_id is None:
                self._turn_id = str(uuid.uuid4())
            self._turn_text += frame.text
            await self._publish(
                {"type": "agent_text", "turnId": self._turn_id, "delta": frame.text}
            )
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._turn_id is not None:
                await self._publish(
                    {
                        "type": "agent_text_end",
                        "turnId": self._turn_id,
                        "text": self._turn_text,
                    }
                )
                self._turn_id = None
                self._turn_text = ""
            if self._voice in ("thinking", "listening"):
                await self._set_voice("idle")
        elif isinstance(frame, (TTSStartedFrame, BotStartedSpeakingFrame)):
            # Stale bot-start frames during a barge-in must not override
            # user_speaking — only a turn that was thinking moves to speaking.
            if self._voice == "thinking":
                await self._set_voice("speaking")
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._voice == "speaking":
                await self._set_voice("idle")
        elif isinstance(frame, InterruptionFrame):
            await self._publish({"type": "interruption"})
            if self._voice in ("speaking", "thinking"):
                await self._set_voice("user_speaking")
        elif isinstance(frame, TranscriptionFrame):
            await self._publish({"type": "user_transcript", "text": frame.text})
        elif isinstance(frame, TTSAudioRawFrame):
            self._levels["output"] = _rms(frame.audio, frame.num_channels)
            await self._maybe_publish_levels()
        elif isinstance(frame, InputAudioRawFrame):
            self._levels["input"] = _rms(frame.audio, frame.num_channels)
            await self._maybe_publish_levels()
        elif isinstance(frame, ToolActivityFrame):
            await self._publish_tool(frame)

        await self.push_frame(frame, direction)

    async def _set_voice(self, voice: VoiceState) -> None:
        if voice == self._voice:
            return
        self._voice = voice
        await self._publish({"type": "state", "voice": voice, "wake": self._wake_payload()})

    async def _publish(self, event: dict) -> None:
        if self._publisher is None:
            return
        await self._publisher({"ts": _now_ms(), **event})

    async def _maybe_publish_levels(self) -> None:
        now = time.monotonic()
        if now - self._last_level_ts < LEVEL_INTERVAL_SECS:
            return
        self._last_level_ts = now
        await self._publish({"type": "audio_level", **self._levels})

    async def _publish_tool(self, frame: ToolActivityFrame) -> None:
        now = time.monotonic()
        key = frame.tool_call_id or frame.tool
        last = self._last_tool_ts.get(key)
        # Drop intermediate statuses within the window but never the final one.
        if (
            last is not None
            and now - last < TOOL_THROTTLE_SECS
            and frame.status != "completed"
        ):
            return
        self._last_tool_ts[key] = now
        if len(self._last_tool_ts) > MAX_TRACKED_TOOLS:
            # Bounded memory on long sessions; throttling only needs recency.
            self._last_tool_ts.pop(next(iter(self._last_tool_ts)))
        await self._publish(
            {
                "type": "tool_activity",
                "tool": frame.tool,
                "label": frame.label,
                "emoji": frame.emoji,
                "toolCallId": frame.tool_call_id,
                "status": frame.status,
            }
        )


class BridgeServer:
    """websockets server exposing VoiceBridge events + commands to the app.

    Listens on 127.0.0.1 only; at most one client (the desktop app) — a
    second connection is refused with an ``occupied`` error. Events published
    while nobody is connected are dropped: the ``hello`` + ``state`` snapshot
    sent on connect is the catch-up mechanism.
    """

    def __init__(
        self,
        *,
        port: int,
        wake_controller: WakeWordController,
        session_manager: HermesSessionManager | None,
        snapshot: Callable[[], dict],
    ) -> None:
        self._port = port
        self._wake_controller = wake_controller
        self._session_manager = session_manager
        self._snapshot = snapshot
        self._server: websockets.Server | None = None
        self._connection: websockets.ServerConnection | None = None

    @property
    def port(self) -> int:
        """Actual bound port (useful when started with port=0 in tests)."""
        if self._server is None:
            return self._port
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        # Wake controller events (toggle/detection/timeout) become
        # ``wake_state`` broadcasts — wired here so tests and production
        # share the exact same behavior.
        self._wake_controller.set_listener(self._on_wake_controller_event)
        self._server = await websockets.serve(self._handle_connection, HOST, self._port)
        logger.info(f"Desktop bridge listening on ws://{HOST}:{self.port}")

    def _on_wake_controller_event(self, _event: str, _data: dict) -> None:
        self.schedule(
            {
                "type": "wake_state",
                "enabled": self._wake_controller.enabled,
                "state": self._wake_controller.state,
                "phrase": self._wake_controller.phrase,
            }
        )

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.info("Desktop bridge stopped")

    async def publish(self, event: dict) -> None:
        """Send one event to the connected client (no-op if none)."""
        connection = self._connection
        if connection is None:
            return
        event.setdefault("ts", _now_ms())
        try:
            await connection.send(json.dumps(event, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001 — a dead client must not break the pipeline
            logger.debug(f"Bridge publish to a dead client failed: {e}")

    def schedule(self, event: dict) -> None:
        """Fire-and-forget publish for sync callers (controller events)."""
        if self._connection is None:
            return
        asyncio.get_running_loop().create_task(self.publish(event))

    def _session_payload(self) -> dict:
        return {
            "appSessionId": (
                self._session_manager.app_session_id if self._session_manager else None
            ),
            "hermesSessionId": (
                self._session_manager.current_hermes_session_id()
                if self._session_manager
                else None
            ),
        }

    async def _handle_connection(self, connection: websockets.ServerConnection) -> None:
        if self._connection is not None:
            try:
                await connection.send(
                    json.dumps(
                        {
                            "type": "error",
                            "ts": _now_ms(),
                            "code": "occupied",
                            "message": "Bridge já conectada ao app desktop.",
                        },
                        ensure_ascii=False,
                    )
                )
            finally:
                await connection.close()
            return
        self._connection = connection
        try:
            await self._send_hello(connection)
            async for raw in connection:
                try:
                    await self._dispatch(connection, raw)
                except websockets.exceptions.ConnectionClosed:
                    break
        finally:
            self._connection = None

    async def _send_hello(self, connection: websockets.ServerConnection) -> None:
        await connection.send(
            json.dumps(
                {
                    "type": "hello",
                    "ts": _now_ms(),
                    "bridgeVersion": BRIDGE_VERSION,
                    "session": self._session_payload(),
                },
                ensure_ascii=False,
            )
        )
        await connection.send(
            json.dumps(
                {"type": "state", "ts": _now_ms(), **self._snapshot()},
                ensure_ascii=False,
            )
        )

    async def _dispatch(self, connection: websockets.ServerConnection, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_ack(
                connection,
                None,
                ok=False,
                error={"code": "bad_json", "message": "Comando não é JSON válido."},
            )
            return
        cmd = message.get("cmd")
        if cmd == "get_state":
            await self._send_ack(connection, message.get("id"), ok=True, data=self._snapshot())
        elif cmd == "set_wake_word_enabled":
            enabled = bool(message.get("enabled"))
            self._wake_controller.set_enabled(enabled)
            await self._send_ack(
                connection, message.get("id"), ok=True, data={"enabled": enabled}
            )
        elif cmd == "ping":
            await self._send_ack(connection, message.get("id"), ok=True, data="pong")
        else:
            await self._send_ack(
                connection,
                message.get("id"),
                ok=False,
                error={
                    "code": "unknown_command",
                    "message": f"Comando desconhecido: {cmd!r}.",
                },
            )

    @staticmethod
    async def _send_ack(
        connection: websockets.ServerConnection,
        msg_id: int | None,
        *,
        ok: bool,
        data=None,
        error: dict | None = None,
    ) -> None:
        payload: dict = {"type": "ack", "id": msg_id, "ok": ok}
        if data is not None:
            payload["data"] = data
        if error is not None:
            payload["error"] = error
        await connection.send(json.dumps(payload, ensure_ascii=False))
