"""BridgeServer over a real websockets connection (loopback, random port)."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest
import websockets
from pipecat.frames.frames import LLMMessagesAppendFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection

from pipeline.bridge import SPECTRUM_BINS_WIRE, BridgeServer, VoiceBridge
from pipeline.wake_controller import WakeWordController


class _SessionManager:
    app_session_id = "voice-session-test"

    def current_hermes_session_id(self):
        return "hermes-session-1"


def _snapshot(controller: WakeWordController) -> dict:
    return {
        "voice": "idle",
        "wake": {
            "enabled": controller.enabled,
            "state": controller.state,
            "phrase": controller.phrase,
        },
        "session": {
            "appSessionId": "voice-session-test",
            "hermesSessionId": "hermes-session-1",
        },
    }


class _QueueRecorder:
    """Registra as chamadas de queue_frames para inspecionar o injetado."""

    def __init__(self):
        self.calls: list[list] = []
        self._lock = asyncio.Lock()

    async def queue_frames(self, frames: list) -> None:
        async with self._lock:
            self.calls.append(list(frames))


@pytest.fixture
async def server():
    """A running BridgeServer on an OS-assigned port."""
    controller = WakeWordController(enabled=True)
    bridge_server = BridgeServer(
        port=0,
        wake_controller=controller,
        session_manager=_SessionManager(),
        snapshot=lambda: _snapshot(controller),
    )
    await bridge_server.start()
    yield bridge_server, controller
    await bridge_server.stop()


@pytest.fixture
async def server_with_queue():
    """BridgeServer wired to a queue_frames recorder (chat injection)."""
    controller = WakeWordController(enabled=True)
    recorder = _QueueRecorder()
    bridge_server = BridgeServer(
        port=0,
        wake_controller=controller,
        session_manager=_SessionManager(),
        snapshot=lambda: _snapshot(controller),
        queue_frames=recorder.queue_frames,
    )
    await bridge_server.start()
    yield bridge_server, controller, recorder
    await bridge_server.stop()


async def _connect(server) -> websockets.ClientConnection:
    bridge_server = server[0]
    return await websockets.connect(f"ws://127.0.0.1:{bridge_server.port}")


async def _handshake(ws: websockets.ClientConnection) -> tuple[dict, dict]:
    """Consume the hello + state snapshot sent on connect."""
    hello = json.loads(await ws.recv())
    state = json.loads(await ws.recv())
    assert hello["type"] == "hello"
    assert state["type"] == "state"
    return hello, state


async def test_hello_and_get_state(server):
    async with await _connect(server) as ws:
        hello, state = await _handshake(ws)

        assert hello["bridgeVersion"] == 1
        assert hello["session"] == {
            "appSessionId": "voice-session-test",
            "hermesSessionId": "hermes-session-1",
        }
        assert state["voice"] == "idle"
        assert state["wake"]["enabled"] is True

        await ws.send(json.dumps({"id": 7, "cmd": "get_state"}))
        ack = json.loads(await ws.recv())
        assert ack["type"] == "ack"
        assert ack["id"] == 7
        assert ack["ok"] is True
        assert ack["data"]["voice"] == "idle"
        assert ack["data"]["session"]["appSessionId"] == "voice-session-test"


async def test_set_wake_word_enabled_acks_and_broadcasts(server):
    _bridge_server, controller = server
    async with await _connect(server) as ws:
        await _handshake(ws)

        await ws.send(
            json.dumps({"id": 2, "cmd": "set_wake_word_enabled", "enabled": False})
        )

        # ack and wake_state may arrive in either order — collect both.
        messages = {m["type"]: m for m in [json.loads(await ws.recv()) for _ in range(2)]}
        assert messages["ack"]["ok"] is True
        assert messages["ack"]["data"] == {"enabled": False}
        assert messages["wake_state"]["enabled"] is False
        assert messages["wake_state"]["state"] == "disabled"
        assert controller.enabled is False


async def test_second_client_is_refused(server):
    async with await _connect(server) as first:
        await _handshake(first)

        async with websockets.connect(
            f"ws://127.0.0.1:{server[0].port}"
        ) as second:
            message = json.loads(await second.recv())
            assert message["type"] == "error"
            assert message["code"] == "occupied"


async def test_publish_reaches_connected_client(server):
    bridge_server, _controller = server
    async with await _connect(server) as ws:
        await _handshake(ws)

        await bridge_server.publish({"type": "custom_test", "value": 1})

        event = json.loads(await ws.recv())
        assert event["type"] == "custom_test"
        assert event["value"] == 1
        assert "ts" in event


async def test_bad_json_and_unknown_command(server):
    async with await _connect(server) as ws:
        await _handshake(ws)

        await ws.send("isto não é json")
        ack = json.loads(await ws.recv())
        assert ack["ok"] is False
        assert ack["error"]["code"] == "bad_json"

        await ws.send(json.dumps({"id": 9, "cmd": "nope"}))
        ack = json.loads(await ws.recv())
        assert ack["ok"] is False
        assert ack["id"] == 9
        assert ack["error"]["code"] == "unknown_command"


async def test_ping_pongs(server):
    async with await _connect(server) as ws:
        await _handshake(ws)

        await ws.send(json.dumps({"id": 3, "cmd": "ping"}))
        ack = json.loads(await ws.recv())
        assert ack["ok"] is True
        assert ack["data"] == "pong"


async def test_send_user_message_injects_and_publishes(server_with_queue):
    """Chat text queues an LLMMessagesAppendFrame and echoes user_transcript."""
    _bridge_server, _controller, recorder = server_with_queue
    async with await _connect(server_with_queue) as ws:
        await _handshake(ws)

        await ws.send(
            json.dumps({"id": 11, "cmd": "send_user_message", "text": "que horas são?"})
        )

        # ack and user_transcript may arrive in either order — collect both.
        messages = {m["type"]: m for m in [json.loads(await ws.recv()) for _ in range(2)]}
        assert messages["ack"]["ok"] is True
        assert messages["ack"]["id"] == 11
        assert messages["user_transcript"]["text"] == "que horas são?"

        assert len(recorder.calls) == 1
        (frame,) = recorder.calls[0]
        assert isinstance(frame, LLMMessagesAppendFrame)
        assert frame.messages == [{"role": "user", "content": "que horas são?"}]
        assert frame.run_llm is True


async def test_send_user_message_rejects_empty_text(server_with_queue):
    _bridge_server, _controller, recorder = server_with_queue
    async with await _connect(server_with_queue) as ws:
        await _handshake(ws)

        await ws.send(json.dumps({"id": 12, "cmd": "send_user_message", "text": "   "}))
        ack = json.loads(await ws.recv())
        assert ack["ok"] is False
        assert ack["id"] == 12
        assert ack["error"]["code"] == "empty_text"
        # Nada enfileirado nem publicado além do ack.
        assert recorder.calls == []


async def test_send_user_message_unavailable_without_pipeline(server):
    """Sem queue_frames (bridge solta) o comando responde not_available."""
    async with await _connect(server) as ws:
        await _handshake(ws)

        await ws.send(json.dumps({"id": 13, "cmd": "send_user_message", "text": "oi"}))
        ack = json.loads(await ws.recv())
        assert ack["ok"] is False
        assert ack["id"] == 13
        assert ack["error"]["code"] == "not_available"


async def test_audio_level_reaches_the_client_with_spectrum(server):
    """The full path: a PCM frame in the pipeline → spectrum on the wire."""
    bridge_server, controller = server

    async with await _connect(server) as ws:
        await _handshake(ws)

        bridge = VoiceBridge(wake_controller=controller)
        bridge.set_publisher(bridge_server.publish)
        # 440 Hz at 24 kHz, the TTS rate — as if Polaris were speaking.
        samples = np.sin(2 * np.pi * 440 * np.arange(2400) / 24000) * 0.8
        pcm = (samples * 32767).astype(np.int16).tobytes()
        await bridge.process_frame(
            TTSAudioRawFrame(audio=pcm, sample_rate=24000, num_channels=1),
            FrameDirection.DOWNSTREAM,
        )

        event = json.loads(await ws.recv())
        assert event["type"] == "audio_level"
        assert 0.4 < event["output"] < 0.7
        assert len(event["spectrum"]) == SPECTRUM_BINS_WIRE
        assert event["mid"] > event["bass"]
        assert max(event["spectrum"]) > 0
