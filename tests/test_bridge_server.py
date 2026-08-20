"""BridgeServer over a real websockets connection (loopback, random port)."""

from __future__ import annotations

import json

import pytest
import websockets

from pipeline.bridge import BridgeServer
from pipeline.wake_controller import WakeWordController


class _SessionManager:
    app_session_id = "voice-session-test"

    def current_hermes_session_id(self):
        return "hermes-session-1"


@pytest.fixture
async def server():
    """A running BridgeServer on an OS-assigned port."""
    controller = WakeWordController(enabled=True)
    bridge_server = BridgeServer(
        port=0,
        wake_controller=controller,
        session_manager=_SessionManager(),
        snapshot=lambda: {
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
        },
    )
    await bridge_server.start()
    yield bridge_server, controller
    await bridge_server.stop()


async def _connect(server) -> websockets.ClientConnection:
    bridge_server, _controller = server
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
