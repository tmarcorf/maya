"""Desktop bridge: voice state machine, levels and event payloads."""

from __future__ import annotations

import numpy as np
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
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
from pipecat.processors.frame_processor import FrameDirection

from pipeline.bridge import VoiceBridge, _rms
from pipeline.frames import ToolActivityFrame
from pipeline.wake_controller import WakeWordController


class _Sink:
    """Async event sink replacing the BridgeServer in unit tests."""

    def __init__(self):
        self.events: list[dict] = []

    async def __call__(self, event: dict):
        self.events.append(event)


def _events(sink: _Sink, event_type: str) -> list[dict]:
    return [event for event in sink.events if event["type"] == event_type]


async def _feed(bridge: VoiceBridge, *frames) -> None:
    for frame in frames:
        await bridge.process_frame(frame, FrameDirection.DOWNSTREAM)


def _pcm(amp: float = 0.8, frames: int = 2400) -> bytes:
    """One 0.1 s sine chunk at 24 kHz as int16 PCM."""
    t = np.arange(frames) / 24000
    return (np.sin(2 * np.pi * 440 * t) * amp * 32767).astype(np.int16).tobytes()


def _make_bridge(enabled: bool = False) -> tuple[VoiceBridge, _Sink]:
    bridge = VoiceBridge(wake_controller=WakeWordController(enabled=enabled))
    sink = _Sink()
    bridge.set_publisher(sink)
    return bridge, sink


async def test_state_machine_happy_path():
    bridge, sink = _make_bridge()

    await _feed(
        bridge,
        UserStartedSpeakingFrame(),
        UserStoppedSpeakingFrame(),
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Olá"),
        TTSStartedFrame(),
        BotStoppedSpeakingFrame(),
        LLMFullResponseEndFrame(),
    )

    voices = [event["voice"] for event in _events(sink, "state")]
    assert voices == ["user_speaking", "listening", "thinking", "speaking", "idle"]
    assert bridge.voice == "idle"

    deltas = _events(sink, "agent_text")
    assert len(deltas) == 1 and deltas[0]["delta"] == "Olá"
    ends = _events(sink, "agent_text_end")
    assert len(ends) == 1
    assert ends[0]["text"] == "Olá"
    # Streaming and final events share the turn id.
    assert ends[0]["turnId"] == deltas[0]["turnId"]


async def test_user_transcript_published():
    bridge, sink = _make_bridge()

    await _feed(
        bridge,
        TranscriptionFrame(text="que horas são?", user_id="user", timestamp="2026-08-19T12:00:00Z"),
    )

    transcripts = _events(sink, "user_transcript")
    assert len(transcripts) == 1
    assert transcripts[0]["text"] == "que horas são?"
    assert "ts" in transcripts[0]


async def test_interruption_moves_speaking_to_user_speaking():
    bridge, sink = _make_bridge()

    await _feed(bridge, LLMFullResponseStartFrame(), TTSStartedFrame(), InterruptionFrame())

    voices = [event["voice"] for event in _events(sink, "state")]
    assert voices == ["thinking", "speaking", "user_speaking"]
    assert len(_events(sink, "interruption")) == 1


async def test_response_end_without_audio_falls_back_to_idle():
    """An empty/error response never starts TTS — close the turn anyway."""
    bridge, sink = _make_bridge()

    await _feed(bridge, LLMFullResponseStartFrame(), LLMFullResponseEndFrame())

    voices = [event["voice"] for event in _events(sink, "state")]
    assert voices == ["thinking", "idle"]


async def test_stale_bot_start_during_barge_in_does_not_override_user():
    """Bot-start frames arriving after an interruption are stale."""
    bridge, sink = _make_bridge()

    await _feed(
        bridge,
        LLMFullResponseStartFrame(),
        InterruptionFrame(),
        BotStartedSpeakingFrame(),
    )

    assert bridge.voice == "user_speaking"
    assert [event["voice"] for event in _events(sink, "state")][-1] == "user_speaking"


async def test_state_transitions_are_idempotent():
    bridge, sink = _make_bridge()

    await _feed(bridge, UserStartedSpeakingFrame(), UserStartedSpeakingFrame())

    assert [event["voice"] for event in _events(sink, "state")] == ["user_speaking"]


async def test_state_carries_wake_payload():
    controller = WakeWordController(enabled=True)
    controller.notify_detected("e aí polaris")
    bridge = VoiceBridge(wake_controller=controller)
    sink = _Sink()
    bridge.set_publisher(sink)

    await _feed(bridge, UserStartedSpeakingFrame())

    state = _events(sink, "state")[0]
    assert state["wake"] == {"enabled": True, "state": "awake", "phrase": "e aí polaris"}


async def test_audio_levels_rms_and_throttle():
    bridge, sink = _make_bridge()

    await _feed(bridge, TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1))
    levels = _events(sink, "audio_level")
    assert len(levels) == 1
    # 0.8 amplitude sine → RMS ≈ 0.8 * 0.707 ≈ 0.57.
    assert 0.4 < levels[0]["output"] < 0.7
    assert levels[0]["input"] == 0.0

    # A second chunk immediately after is throttled (no new event).
    await _feed(bridge, InputAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1))
    assert len(_events(sink, "audio_level")) == 1


async def test_tool_activity_throttle_never_drops_completed():
    bridge, sink = _make_bridge()

    running = ToolActivityFrame(tool="terminal", label="ls", tool_call_id="call_1", status="running")
    await _feed(
        bridge,
        running,
        ToolActivityFrame(tool="terminal", label="ls", tool_call_id="call_1", status="running"),
    )
    assert len(_events(sink, "tool_activity")) == 1

    # The final status is never dropped, even within the throttle window.
    completed = ToolActivityFrame(
        tool="terminal", label="ls", tool_call_id="call_1", status="completed"
    )
    await _feed(bridge, completed)
    events = _events(sink, "tool_activity")
    assert len(events) == 2
    assert events[-1]["status"] == "completed"
    assert events[-1]["toolCallId"] == "call_1"


def test_rms_empty_and_sine():
    assert _rms(b"", 1) == 0.0
    samples = (np.sin(np.linspace(0, 20 * np.pi, 2400)) * 32767).astype(np.int16)
    assert abs(_rms(samples.tobytes(), 1) - 0.707) < 0.01


def test_snapshot_has_voice_wake_and_session():
    class _SessionManager:
        app_session_id = "voice-session-test"

        def current_hermes_session_id(self):
            return "hermes-session-1"

    bridge = VoiceBridge(
        wake_controller=WakeWordController(enabled=True),
        session_manager=_SessionManager(),
    )

    snapshot = bridge.snapshot()

    assert snapshot["voice"] == "idle"
    assert snapshot["session"] == {
        "appSessionId": "voice-session-test",
        "hermesSessionId": "hermes-session-1",
    }
    assert snapshot["wake"]["enabled"] is True
