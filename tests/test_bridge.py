"""Desktop bridge: voice state machine, levels and event payloads."""

from __future__ import annotations

import numpy as np
import pytest
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
    TTSStoppedFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.bridge import (
    SPECTRUM_BINS_WIRE,
    VoiceBridge,
    _analyse_pcm,
    _ChannelBuffer,
    _rms,
    _to_mono,
)
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
        # Ordem real: o texto completa antes do playback da última sentença
        # terminar — o BotStopped do transport é o último frame do turno.
        LLMFullResponseEndFrame(),
        BotStoppedSpeakingFrame(),
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


async def test_tts_stream_drives_the_state_machine():
    """Frame order as observed in production (observer between the TTS
    service and the output transport): the TTS service re-emits the LLM
    response boundary frames and emits the TTS stream."""

    bridge, sink = _make_bridge()

    await _feed(
        bridge,
        LLMFullResponseStartFrame(),
        TTSStartedFrame(),
        TTSTextFrame(text="Olá", aggregated_by="test"),
        TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1),
        TTSStoppedFrame(),
        LLMFullResponseEndFrame(),
    )

    voices = [event["voice"] for event in _events(sink, "state")]
    assert voices == ["thinking", "speaking", "idle"]
    assert bridge.voice == "idle"

    deltas = _events(sink, "agent_text")
    assert len(deltas) == 1 and deltas[0]["delta"] == "Olá"
    ends = _events(sink, "agent_text_end")
    assert len(ends) == 1 and ends[0]["text"] == "Olá"
    assert ends[0]["turnId"] == deltas[0]["turnId"]

    # While speaking, the audio_level event carries the OUTPUT side.
    levels = _events(sink, "audio_level")
    assert len(levels) == 1
    assert levels[0]["output"] > 0
    assert levels[0]["level"] == pytest.approx(levels[0]["output"])


async def test_multi_sentence_tts_keeps_speaking_through_sentence_gaps():
    """Respostas com várias sentenças emitem um TTSStarted/Stopped por
    sentença (TextAggregationMode.SENTENCE), e o transport ecoa
    BotStoppedSpeakingFrame a cada fim de playback. O estado não pode piscar
    para idle no vácuo entre sentenças, e o LLMFullResponseEnd (texto
    completo) também não derruba: o áudio da última sentença ainda está em
    voo. O idle só chega com o BotStoppedSpeakingFrame final — o fim do
    playback real."""

    bridge, sink = _make_bridge()

    await _feed(
        bridge,
        UserStartedSpeakingFrame(),
        LLMFullResponseStartFrame(),
        TTSStartedFrame(),
        TTSTextFrame(text="Primeira", aggregated_by="test"),
        TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1),
        TTSStoppedFrame(),
        BotStoppedSpeakingFrame(),  # transport: fim do playback da 1ª sentença
        TTSStartedFrame(),
        TTSTextFrame(text="segunda", aggregated_by="test"),
        TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1),
        TTSStoppedFrame(),
        LLMFullResponseEndFrame(),  # texto completo — NÃO pode derrubar o estado
        BotStoppedSpeakingFrame(),  # transport: fim do playback — só aqui cai
    )

    voices = [event["voice"] for event in _events(sink, "state")]
    # Sem idle entre as sentenças nem no fim do texto:
    # user_speaking → thinking → speaking → (idle só no último BotStopped).
    assert voices == ["user_speaking", "thinking", "speaking", "idle"]
    assert bridge.voice == "idle"

    ends = _events(sink, "agent_text_end")
    # Os deltas ("Primeira" + "segunda") ganham o espaço de volta no
    # `_restore_delta_space` — o texto final é "Primeira segunda".
    assert len(ends) == 1 and ends[0]["text"] == "Primeira segunda"


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


async def test_user_transcript_observer_publishes_and_passes_through():
    """Sem wake word, o turno começa com o VAD (broadcast do aggregator chega
    antes da transcrição): a fala publica na hora. O observer publica só o que
    o Hermes processa — o broadcast de UserStartedSpeakingFrame é o gate."""

    from pipeline.bridge import UserTranscriptObserver

    observer = UserTranscriptObserver()
    sink = _Sink()
    observer.set_publisher(sink)

    # push_frame is a no-op outside a running pipeline; spy on it via an
    # instance attribute (non-data descriptor) to verify the passthrough.
    pushed: list[tuple] = []

    async def fake_push(frame, direction):
        pushed.append((frame, direction))

    observer.push_frame = fake_push  # type: ignore[method-assign]

    vad_start = VADUserStartedSpeakingFrame()
    frame = TranscriptionFrame(
        text="que horas são?", user_id="user", timestamp="2026-08-19T12:00:00Z"
    )
    turn_start = UserStartedSpeakingFrame()
    await observer.process_frame(vad_start, FrameDirection.UPSTREAM)
    await observer.process_frame(frame, FrameDirection.DOWNSTREAM)
    await observer.process_frame(turn_start, FrameDirection.UPSTREAM)

    transcripts = _events(sink, "user_transcript")
    assert len(transcripts) == 1
    assert transcripts[0]["text"] == "que horas são?"
    assert "ts" in transcripts[0]
    # Every frame keeps flowing to the aggregator.
    assert pushed == [
        (vad_start, FrameDirection.UPSTREAM),
        (frame, FrameDirection.DOWNSTREAM),
        (turn_start, FrameDirection.UPSTREAM),
    ]


async def test_user_transcript_observer_drops_utterance_while_wake_asleep():
    """Dormindo, o STT transcreve, mas o gate da palavra de ativação não abre
    o turno: nenhum UserStartedSpeakingFrame é transmitido e a fala (ex.
    "abobrinha 1, 2, 3") não pode aparecer no chat. O segmento encerra com o
    VAD stop — os pendentes são descartados."""

    from pipeline.bridge import UserTranscriptObserver

    observer = UserTranscriptObserver()
    sink = _Sink()
    observer.set_publisher(sink)
    pushed: list[tuple] = []

    async def fake_push(frame, direction):
        pushed.append((frame, direction))

    observer.push_frame = fake_push  # type: ignore[method-assign]

    await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await observer.process_frame(
        TranscriptionFrame(text="abobrinha 1, 2, 3", user_id="user", timestamp="t1"),
        FrameDirection.DOWNSTREAM,
    )
    # Uma segunda transcrição do mesmo segmento (VAD agrupando pausas).
    await observer.process_frame(
        TranscriptionFrame(text="que horas são?", user_id="user", timestamp="t2"),
        FrameDirection.DOWNSTREAM,
    )
    await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

    assert _events(sink, "user_transcript") == []
    assert len(pushed) == 4  # passthrough integral, nada foi engolido


async def test_user_transcript_observer_wake_phrase_publishes_buffered():
    """Com wake word, a estratégia avalia a transcrição antes de abrir o
    turno: o broadcast de UserStartedSpeakingFrame chega DEPOIS da
    transcrição. A fala que casou com a palavra de ativação sai do buffer e
    publica — as anteriores, de um segmento que não abriu turno, ficam para
    trás."""

    from pipeline.bridge import UserTranscriptObserver

    observer = UserTranscriptObserver()
    sink = _Sink()
    observer.set_publisher(sink)
    pushed: list[tuple] = []

    async def fake_push(frame, direction):
        pushed.append((frame, direction))

    observer.push_frame = fake_push  # type: ignore[method-assign]

    await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await observer.process_frame(
        TranscriptionFrame(text="abobrinha 1, 2, 3", user_id="user", timestamp="t1"),
        FrameDirection.DOWNSTREAM,
    )
    await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
    # Novamente: agora a fala casa com "maya".
    await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await observer.process_frame(
        TranscriptionFrame(text="maya, que horas são?", user_id="user", timestamp="t2"),
        FrameDirection.DOWNSTREAM,
    )
    await observer.process_frame(UserStartedSpeakingFrame(), FrameDirection.UPSTREAM)

    transcripts = _events(sink, "user_transcript")
    assert [t["text"] for t in transcripts] == ["maya, que horas são?"]
    assert len(pushed) == 6


async def test_user_transcript_observer_keeps_publishing_after_wake_segment():
    """A palavra de ativação costuma ser seu próprio segmento de VAD: o turno
    abre com "Maya" e o pedido vem num segmento seguinte ("que horas
    são?"). Os segmentos pós-abertura não podem resetar o turno nem ser
    descartados no VAD stop — publicam ao vivo, e o turno só fecha com o
    broadcast de UserStoppedSpeakingFrame."""

    from pipeline.bridge import UserTranscriptObserver

    observer = UserTranscriptObserver()
    sink = _Sink()
    observer.set_publisher(sink)
    pushed: list[tuple] = []

    async def fake_push(frame, direction):
        pushed.append((frame, direction))

    observer.push_frame = fake_push  # type: ignore[method-assign]

    # Segmento 1: só a palavra de ativação.
    await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await observer.process_frame(
        TranscriptionFrame(text="Maya", user_id="user", timestamp="t1"),
        FrameDirection.DOWNSTREAM,
    )
    await observer.process_frame(UserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    # Segmento 2: o pedido — chega com o turno já aberto.
    await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await observer.process_frame(
        TranscriptionFrame(text="que horas são?", user_id="user", timestamp="t2"),
        FrameDirection.DOWNSTREAM,
    )
    await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
    # Fim do turno.
    await observer.process_frame(UserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

    transcripts = _events(sink, "user_transcript")
    assert [t["text"] for t in transcripts] == ["Maya", "que horas são?"]

    # Turno fechado: fala seguinte sem ativação é descartada de novo.
    await observer.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await observer.process_frame(
        TranscriptionFrame(text="abobrinha 1, 2, 3", user_id="user", timestamp="t3"),
        FrameDirection.DOWNSTREAM,
    )
    await observer.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
    assert [t["text"] for t in transcripts] == ["Maya", "que horas são?"]
    assert len(pushed) == 10  # passthrough integral


async def test_user_transcript_observer_ignores_non_transcription_frames():
    from pipeline.bridge import UserTranscriptObserver

    observer = UserTranscriptObserver()
    sink = _Sink()
    observer.set_publisher(sink)
    pushed: list = []

    async def fake_push(frame, direction):
        pushed.append(frame)

    observer.push_frame = fake_push  # type: ignore[method-assign]

    await observer.process_frame(
        TTSTextFrame(text="olá", aggregated_by="test"), FrameDirection.DOWNSTREAM
    )
    await observer.process_frame(
        TranscriptionFrame(text="   ", user_id="user", timestamp="x"),
        FrameDirection.DOWNSTREAM,
    )

    assert _events(sink, "user_transcript") == []
    assert len(pushed) == 2  # passthrough for every frame, without exception


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


async def test_vad_frames_reveal_speech_while_wake_asleep():
    """Raw VAD frames must move the orb even with no user turn started.

    While the wake word is asleep the wake strategy swallows the turn
    start, so no UserStartedSpeakingFrame is broadcast — the bridge would
    otherwise stay ``idle`` the whole time the user talks.
    """
    bridge, sink = _make_bridge(enabled=True)  # wake controller asleep

    await _feed(bridge, VADUserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame())

    voices = [event["voice"] for event in _events(sink, "state")]
    assert voices == ["user_speaking", "idle"]
    assert bridge.voice == "idle"


async def test_vad_stop_keeps_turn_flow_when_turn_active():
    """With a real turn in flight, VAD stop must NOT reset to idle.

    The listening transition belongs to the UserStoppedSpeakingFrame
    broadcast that follows the turn-start machinery.
    """
    bridge, sink = _make_bridge()

    await _feed(
        bridge,
        VADUserStartedSpeakingFrame(),
        UserStartedSpeakingFrame(),
        VADUserStoppedSpeakingFrame(),
        UserStoppedSpeakingFrame(),
    )

    voices = [event["voice"] for event in _events(sink, "state")]
    assert voices == ["user_speaking", "listening"]
    assert bridge.voice == "listening"


async def test_vad_stop_alone_does_not_emit_state():
    """A VAD stop without a preceding start is a no-op (idempotent)."""
    bridge, sink = _make_bridge()

    await _feed(bridge, VADUserStoppedSpeakingFrame())

    assert _events(sink, "state") == []
    assert bridge.voice == "idle"


async def test_state_carries_wake_payload():
    controller = WakeWordController(enabled=True)
    controller.notify_detected("e aí maya")
    bridge = VoiceBridge(wake_controller=controller)
    sink = _Sink()
    bridge.set_publisher(sink)

    await _feed(bridge, UserStartedSpeakingFrame())

    state = _events(sink, "state")[0]
    assert state["wake"] == {"enabled": True, "state": "awake", "phrase": "e aí maya"}


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


async def test_audio_level_carries_spectrum_of_the_active_side():
    bridge, sink = _make_bridge()

    await _feed(bridge, TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1))
    event = _events(sink, "audio_level")[0]

    assert len(event["spectrum"]) == SPECTRUM_BINS_WIRE
    assert all(isinstance(v, int) and 0 <= v <= 255 for v in event["spectrum"])
    # _pcm() is a 440 Hz tone: energy belongs to mid, not bass or treble.
    assert event["mid"] > event["bass"]
    assert event["mid"] > event["treble"]
    assert event["level"] == event["output"]


async def test_input_chunks_do_not_zero_the_output_during_playback_drain():
    """Kokoro entrega a sentença num burst de síntese e o TTSStopped zera o
    lado do output; os chunks do microfone (sempre fluindo) não podem
    publicar o zero no meio do playback — o traço segura a última forma até o
    próximo burst de síntese ou o fim do turno."""

    bridge, sink = _make_bridge()

    # Turno real: o UserStartedSpeakingFrame abre o turno (sem ele o
    # TTSStopped derruba para idle e o side vira o microfone, outro caminho).
    await _feed(
        bridge,
        UserStartedSpeakingFrame(),
        LLMFullResponseStartFrame(),
        TTSStartedFrame(),
        TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1),
        TTSStoppedFrame(),
    )
    live = _events(sink, "audio_level")
    assert len(live) == 1 and live[-1]["level"] > 0
    assert any(v > 0 for v in live[-1]["spectrum"])
    # O TTSStopped zerou o output mas o turno segue ativo (speaking).
    assert bridge._voice == "speaking"

    # Playback em voo: o microfone segue mandando chunks, mas o lado ativo é
    # o output (zero desde o TTSStopped) — nenhum evento pode ser publicado.
    bridge._last_level_ts = 0.0  # sem o throttle, para exercitar o guard
    for _ in range(6):
        await _feed(
            bridge, InputAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1)
        )
    assert len(_events(sink, "audio_level")) == 1

    # O burst da sentença seguinte volta a publicar.
    bridge._last_level_ts = 0.0
    await _feed(
        bridge,
        TTSStartedFrame(),
        TTSAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1),
    )
    levels = _events(sink, "audio_level")
    assert len(levels) == 2 and levels[-1]["level"] > 0


async def test_active_side_follows_the_voice_state():
    bridge, sink = _make_bridge()

    # While the user speaks, the orb must visualize the microphone even if a
    # stale TTS chunk arrives in the same window.
    await _feed(bridge, UserStartedSpeakingFrame())
    await _feed(bridge, InputAudioRawFrame(audio=_pcm(), sample_rate=24000, num_channels=1))
    assert _events(sink, "audio_level")[-1]["level"] == pytest.approx(
        _events(sink, "audio_level")[-1]["input"]
    )


def test_analyse_pcm_separates_bands():
    def tone(hz: float, rate: int = 24000, n: int = 2048) -> np.ndarray:
        return np.sin(2 * np.pi * hz * np.arange(n) / rate).astype(np.float32) * 0.8

    low, _ = _analyse_pcm(tone(80), 24000)
    mid, _ = _analyse_pcm(tone(600), 24000)
    high, _ = _analyse_pcm(tone(6000), 24000)

    assert low["bass"] > low["mid"]
    assert mid["mid"] > mid["bass"] and mid["mid"] > mid["treble"]
    assert high["treble"] > high["mid"]


def test_analyse_pcm_handles_empty_and_short_input():
    for samples in (np.empty(0, dtype=np.float32), np.zeros(32, dtype=np.float32)):
        bands, spectrum = _analyse_pcm(samples, 24000)
        assert bands == {"bass": 0.0, "mid": 0.0, "treble": 0.0}
        assert spectrum == [0] * SPECTRUM_BINS_WIRE


def test_to_mono_downmixes_stereo():
    interleaved = np.array([100, 300, 200, 400], dtype=np.int16)
    mono = _to_mono(interleaved.tobytes(), 2)
    assert mono.size == 2
    assert mono == pytest.approx(np.array([200, 300]) / 32768.0, abs=1e-6)


def test_channel_buffer_keeps_the_newest_samples():
    buffer = _ChannelBuffer(size=4)
    buffer.push(np.array([1, 2, 3], dtype=np.float32), 24000)
    assert buffer.snapshot() == pytest.approx([1, 2, 3])

    buffer.push(np.array([4, 5], dtype=np.float32), 24000)
    assert buffer.snapshot() == pytest.approx([2, 3, 4, 5])

    # A rate change invalidates the window: bins would map to the wrong Hz.
    buffer.push(np.array([9], dtype=np.float32), 16000)
    assert buffer.snapshot() == pytest.approx([9])
    assert buffer.sample_rate == 16000


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
