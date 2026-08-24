"""Local WebSocket bridge that mirrors the voice pipeline to the desktop app.

Two observer processors publish structured events: the main one sits between
the TTS service and the output transport (voice state machine and audio
levels), and a lighter one between the STT service and the user aggregator
forwards each transcription as a ``user_transcript`` event — the aggregator
consumes ``TranscriptionFrame`` without re-pushing it, so an observer placed
downstream would never see it. A small websockets server on 127.0.0.1
forwards events to the desktop app and handles control commands (currently:
the runtime wake-word toggle). The bridge is purely observational — nothing
it does changes how audio/LLM frames flow.

The observer must sit upstream of the assistant aggregator (which consumes
the LLM response boundary frames without re-pushing them) but downstream of
the TTS service (which re-emits them along with the TTS stream). In this
position ``agent_text`` deltas come from ``TTSTextFrame`` — note that the
ElevenLabs provider sets ``push_text_frames=False`` and never emits it, so
the agent text events are unavailable there; kokoro (default) and Qwen3
work. The ``BotStartedSpeakingFrame``/``BotStoppedSpeakingFrame`` copies
emitted by the output transport still arrive (upstream direction).

Protocol (JSON lines, one object per WebSocket frame; ``ts`` = epoch ms):

    server → client events:
      hello {bridgeVersion, session}
      state {voice, wake:{enabled, state, phrase}}
      user_transcript {text}
      agent_text {turnId, delta} / agent_text_end {turnId, text}
      tool_activity {tool, label, emoji, toolCallId, status}
      interruption {}
      audio_level {input, output, level?, bass?, mid?, treble?, spectrum?}
                                       (throttled to ~30 Hz; the optional
                                        fields analyse the active side)
      wake_state {enabled, state, phrase}
      error {code, message}
    client → server commands (ack is the only response — never optimistic):
      {id, cmd:"get_state"} → ack {voice, wake, session}
      {id, cmd:"set_wake_word_enabled", enabled} → ack {enabled}
      {id, cmd:"ping"} → ack "pong"
      {id, cmd:"send_user_message", text} → ack; injects the text into the
          pipeline as a user message (LLMMessagesAppendFrame run_llm) — the
          reply flows through TTS as usual. Bypasses the wake gate: chat
          input is always processed.
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
    LLMMessagesAppendFrame,
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

# Spectral analysis feeding the desktop orb. The window is accumulated across
# chunks (see _ChannelBuffer) so the bass band is actually resolvable.
FFT_SIZE = 2048
MIN_FFT_SAMPLES = 256
SPECTRUM_BINS_WIRE = 32
SPECTRUM_MIN_HZ = 28.0
SPECTRUM_MAX_HZ = 16000.0
BAND_RANGES_HZ = (("bass", 20.0, 160.0), ("mid", 160.0, 1800.0), ("treble", 1800.0, 11000.0))
# Same decibel window as the Web Audio API's getByteFrequencyData, which the
# orb shader was tuned against.
MIN_DB = -95.0
MAX_DB = -12.0

VoiceState = str  # "idle" | "user_speaking" | "listening" | "thinking" | "speaking"
Publisher = Callable[[dict], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_mono(audio: bytes, num_channels: int) -> np.ndarray:
    """int16 PCM bytes → mono float32 samples in -1..1."""
    if not audio:
        return np.empty(0, dtype=np.float32)
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
    if num_channels > 1:
        usable = (samples.size // num_channels) * num_channels
        if usable == 0:
            return np.empty(0, dtype=np.float32)
        samples = samples[:usable].reshape(-1, num_channels).mean(axis=1)
    return samples


def _rms(audio: bytes, num_channels: int) -> float:
    """RMS of an int16 PCM chunk, 0..1, averaged over channels."""
    samples = _to_mono(audio, num_channels)
    if samples.size == 0:
        return 0.0
    return float(min(np.sqrt(np.mean(samples**2)), 1.0))


class _ChannelBuffer:
    """Ring buffer of the most recent mono samples of one side.

    A pipecat chunk is ~10-20 ms; an FFT over one of those resolves ~50-100 Hz
    per bin, far too coarse to separate the 20-160 Hz bass band. Accumulating
    ``FFT_SIZE`` samples gives a ~85 ms window (~8 Hz bins at 24 kHz) while
    still costing one small rfft per published event.
    """

    def __init__(self, size: int = FFT_SIZE) -> None:
        self._data = np.zeros(size, dtype=np.float32)
        self._filled = 0
        self.sample_rate = 0

    def push(self, samples: np.ndarray, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            # Never mix rates in one window: the bin→Hz mapping would lie.
            self.reset()
            self.sample_rate = sample_rate
        if samples.size == 0:
            return
        if samples.size >= self._data.size:
            self._data[:] = samples[-self._data.size :]
            self._filled = self._data.size
            return
        self._data[:-samples.size] = self._data[samples.size :]
        self._data[-samples.size :] = samples
        self._filled = min(self._data.size, self._filled + samples.size)

    def reset(self) -> None:
        self._data.fill(0.0)
        self._filled = 0

    def snapshot(self) -> np.ndarray:
        """The filled tail of the window, oldest first."""
        return self._data[-self._filled :] if self._filled else self._data[:0]


def _analyse_pcm(samples: np.ndarray, sample_rate: int) -> tuple[dict[str, float], list[int]]:
    """Band energies + log-spaced spectrum of mono float32 PCM.

    Magnitudes are mapped to the same decibel window the Web Audio API uses
    for ``getByteFrequencyData`` (-95..-12 dB → 0..1), because the orb shader
    was tuned against that scale. Linear magnitudes would leave speech, which
    sits around -50 dB, indistinguishable from silence.
    """
    zero_bands = {name: 0.0 for name, _, _ in BAND_RANGES_HZ}
    n = min(samples.size, FFT_SIZE)
    if n < MIN_FFT_SAMPLES or sample_rate <= 0:
        return zero_bands, [0] * SPECTRUM_BINS_WIRE

    window = samples[-n:] * np.hanning(n)
    # Hann has 0.5 coherent gain; the ×2 puts a full-scale sine back at 1.0.
    magnitude = np.abs(np.fft.rfft(window)) / (n / 2) * 2.0
    decibels = 20.0 * np.log10(np.maximum(magnitude, 1e-10))
    normalized = np.clip((decibels - MIN_DB) / (MAX_DB - MIN_DB), 0.0, 1.0)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)

    bands: dict[str, float] = {}
    for name, low, high in BAND_RANGES_HZ:
        selected = normalized[(freqs >= low) & (freqs < high)]
        bands[name] = float(selected.mean()) if selected.size else 0.0

    ratio = SPECTRUM_MAX_HZ / SPECTRUM_MIN_HZ
    spectrum: list[int] = []
    for i in range(SPECTRUM_BINS_WIRE):
        low = SPECTRUM_MIN_HZ * ratio ** (i / SPECTRUM_BINS_WIRE)
        high = SPECTRUM_MIN_HZ * ratio ** ((i + 1) / SPECTRUM_BINS_WIRE)
        selected = normalized[(freqs >= low) & (freqs < high)]
        value = float(selected.mean()) if selected.size else 0.0
        spectrum.append(int(min(255, round(value * 255))))
    return bands, spectrum


class VoiceBridge(FrameProcessor):
    """Observer at the end of the pipeline: derives voice state + levels.

    Frames flow through unchanged; each is inspected exactly once and
    converted into bridge events. Transitions are idempotent — a repeated
    event never re-broadcasts the same state.

    Raw VAD frames (VADUserStarted/StoppedSpeakingFrame) drive
    ``user_speaking`` even while the wake word is asleep, so the desktop
    orb reacts to any speech; when no turn actually started, the VAD stop
    returns the state to idle.
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
        # Rolling PCM windows per side, for the spectrum the orb consumes.
        self._buffers = {"input": _ChannelBuffer(), "output": _ChannelBuffer()}
        self._last_audio_side: str | None = None
        # True between the turn-start broadcast (UserStartedSpeakingFrame)
        # and the LLM turn end — lets the VAD-stop fallback distinguish a
        # real turn (listening follows) from speech ignored while the wake
        # word is asleep (back to idle).
        self._user_turn_active = False

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

    @staticmethod
    def _restore_delta_space(accumulated: str, delta: str) -> str:
        """Restore the space pipecat strips between text deltas.

        The TTS aggregator emits each sentence with ``strip(" ")`` on both
        edges, so "De nada." + "Estou por aqui" arrive as two deltas with
        the space between them missing; when the gateway streams
        space-less words, the same gluing happens word by word. In a clean
        stream two non-whitespace characters never collide at a delta
        boundary, so re-inserting the space only ever fires where the
        space was actually lost.
        """
        if not accumulated or not delta:
            return delta
        prev, nxt = accumulated[-1], delta[0]
        if prev.isspace() or nxt.isspace():
            return delta
        return " " + delta

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_turn_active = True
            await self._set_voice("user_speaking")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            if self._voice == "user_speaking":
                await self._set_voice("listening")
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            # Raw VAD frames flow even while the wake word is asleep — the
            # wake strategy swallows the turn start, so no
            # UserStartedSpeakingFrame is ever broadcast. The orb still
            # reacts to the user's voice: show user_speaking.
            await self._set_voice("user_speaking")
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # No turn actually started (asleep / gated): return to idle. If
            # a turn is active the UserStoppedSpeakingFrame broadcast that
            # follows drives the listening transition instead.
            if self._voice == "user_speaking" and not self._user_turn_active:
                await self._set_voice("idle")
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._turn_id = str(uuid.uuid4())
            self._turn_text = ""
            await self._set_voice("thinking")
        elif isinstance(frame, LLMTextFrame):
            # Never observed in production: the TTS service consumes
            # LLMTextFrame for synthesis. Kept as a fallback for direct
            # observers/tests.
            if self._turn_id is None:
                self._turn_id = str(uuid.uuid4())
            delta = self._restore_delta_space(self._turn_text, frame.text)
            self._turn_text += delta
            await self._publish(
                {"type": "agent_text", "turnId": self._turn_id, "delta": delta}
            )
        elif isinstance(frame, TTSTextFrame):
            # The TTS service re-emits each spoken sentence as a
            # TTSTextFrame; this is the production source of agent_text.
            # (Not emitted by the ElevenLabs provider: push_text_frames=False.)
            if self._turn_id is None:
                self._turn_id = str(uuid.uuid4())
            delta = self._restore_delta_space(self._turn_text, frame.text)
            self._turn_text += delta
            await self._publish(
                {"type": "agent_text", "turnId": self._turn_id, "delta": delta}
            )
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._user_turn_active = False
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
            # Só "thinking"/"listening" caem aqui. Se o estado é "speaking",
            # o texto acabou mas o áudio da última sentença ainda está em
            # voo (síntese e playback terminam depois do LLMFullResponseEnd)
            # — quem derruba é o BotStoppedSpeakingFrame do transport, no fim
            # do playback real. Derrupar aqui arrancaria o traço junto com o
            # texto, antes da fala terminar.
            if self._voice in ("thinking", "listening"):
                await self._set_voice("idle")
        elif isinstance(frame, (TTSStartedFrame, BotStartedSpeakingFrame)):
            # Stale bot-start frames during a barge-in must not override
            # user_speaking. A turn that was thinking moves to speaking;
            # "listening" is also accepted to cover the race where the
            # TTSStartedFrame beats the LLMFullResponseStartFrame that the
            # TTS service re-emits through its serialization queue. "idle"
            # dentro de um turno ativo cobre o vácuo entre sentenças — a
            # resposta ainda não acabou.
            if self._voice in ("thinking", "listening") or (
                self._voice == "idle" and self._user_turn_active
            ):
                await self._set_voice("speaking")
        elif isinstance(frame, (TTSStoppedFrame, BotStoppedSpeakingFrame)):
            # Drop the tail of the TTS window, or the orb would keep shaking
            # to audio that already finished playing. TTSStoppedFrame arrives
            # when the last sentence is generated (~1 chunk before playback
            # ends) and BotStoppedSpeakingFrame (upstream copy from the
            # output transport) at the end of the real playback — both
            # idempotent. Com TextAggregationMode.SENTENCE cada sentença
            # emite um par Started/Stopped: com o turno ainda ativo (resposta
            # com várias sentenças), o estado permanece "speaking" através do
            # vácuo, e o traço não pisca entre sentenças.
            self._buffers["output"].reset()
            self._levels["output"] = 0.0
            if self._voice == "speaking" and not self._user_turn_active:
                await self._set_voice("idle")
        elif isinstance(frame, InterruptionFrame):
            await self._publish({"type": "interruption"})
            if self._voice in ("speaking", "thinking"):
                await self._set_voice("user_speaking")
        elif isinstance(frame, TranscriptionFrame):
            await self._publish({"type": "user_transcript", "text": frame.text})
        elif isinstance(frame, TTSAudioRawFrame):
            self._ingest_audio("output", frame)
            await self._maybe_publish_levels()
        elif isinstance(frame, InputAudioRawFrame):
            self._ingest_audio("input", frame)
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

    def _ingest_audio(self, side: str, frame: Frame) -> None:
        """Update one side's RMS and rolling spectral window."""
        samples = _to_mono(frame.audio, frame.num_channels)
        self._levels[side] = (
            float(min(np.sqrt(np.mean(samples**2)), 1.0)) if samples.size else 0.0
        )
        self._buffers[side].push(samples, frame.sample_rate)
        self._last_audio_side = side

    def _active_side(self) -> str | None:
        """Which side the orb should visualize: whoever is speaking.

        Outside a turn (idle/thinking) there is no obvious owner, so the side
        of the chunk that triggered this publish wins — that keeps residual
        audio, like the TTS drain right after a turn, driving the orb.
        """
        if self._voice in ("user_speaking", "listening"):
            return "input"
        if self._voice == "speaking":
            return "output"
        return self._last_audio_side

    async def _maybe_publish_levels(self) -> None:
        now = time.monotonic()
        if now - self._last_level_ts < LEVEL_INTERVAL_SECS:
            return
        self._last_level_ts = now

        side = self._active_side()
        # Enquanto a Polaris fala, os chunks do microfone continuam chegando
        # e pedem publicação a cada LEVEL_INTERVAL_SECS. O TTSStopped (fim da
        # síntese da sentença) zera o nível e a janela do output — mas o
        # playback ainda está em voo por segundos. Publicar o zero arrancaria
        # o traço no meio da fala: o lado do output só publica com áudio
        # fresco; sem ele, o frontend segura a última forma e decai no fim do
        # turno (setActive(false) no idle).
        if side == "output" and self._levels["output"] <= 0.0:
            return

        event = {"type": "audio_level", **self._levels}
        if side is not None:
            buffer = self._buffers[side]
            bands, spectrum = _analyse_pcm(buffer.snapshot(), buffer.sample_rate)
            event.update(bands)
            event["level"] = self._levels[side]
            event["spectrum"] = spectrum
        await self._publish(event)

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


class UserTranscriptObserver(FrameProcessor):
    """Observer between the STT service and the user aggregator.

    The LLM user aggregator consumes ``TranscriptionFrame`` without
    re-pushing it, so the VoiceBridge at the end of the pipeline never sees
    transcriptions in production. This observer publishes each final
    transcription that will actually be processed by Hermes as a
    ``user_transcript`` event and passes every frame through unchanged — the
    aggregator keeps consuming it as usual.

    The wake gate lives in the aggregator's turn-start strategies: while the
    wake word is asleep the STT keeps transcribing but no user turn ever
    starts, so Hermes never sees the utterance. The aggregator broadcasts
    ``UserStartedSpeakingFrame`` upstream only when a turn really starts —
    that broadcast opens the turn and ``UserStoppedSpeakingFrame`` closes it
    (the default stop strategy waits for the final transcription before
    broadcasting, so no speech of the turn is missed). Transcriptions heard
    before the turn opens are held in a buffer: in wake mode the strategy
    evaluates the transcription before opening the turn, so the broadcast
    arrives after the wake phrase segment's transcription. Segments that end
    without a turn were never processed and are dropped. Once the turn is
    open the VAD segment boundaries no longer matter — the user may keep
    speaking ("Polaris" alone, then the request in a new segment), so later
    segments publish live instead of re-buffering. With the wake word off the
    broadcast arrives at VAD start, so the transcriptions publish live, as
    before.
    """

    def __init__(self) -> None:
        super().__init__()
        self._publisher: Publisher | None = None
        self._pending: list[str] = []
        self._turn_started = False

    def set_publisher(self, publisher: Publisher | None) -> None:
        """Attach the event sink (the ``BridgeServer.publish`` coroutine)."""
        self._publisher = publisher

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            # O gate abriu: o que foi transcrito desde o início do segmento
            # será processado pelo Hermes.
            self._turn_started = True
            for text in self._pending:
                await self._publish({"type": "user_transcript", "text": text})
            self._pending = []
        elif isinstance(frame, UserStoppedSpeakingFrame):
            # Turno fechado (a stop strategy espera a transcrição final
            # antes deste broadcast). O estado volta ao gate.
            self._turn_started = False
            self._pending = []
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            # Novo segmento de fala. Com o turno já aberto (palavra de
            # ativação no segmento anterior, usuário continuando a falar) o
            # estado persiste; sem turno, limpa o buffer de um segmento que
            # acabou sem publicar.
            if not self._turn_started:
                self._pending = []
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # Segmento encerrou sem turno: dormindo, a palavra de ativação
            # nunca casou — o Hermes não viu esta fala; descarta.
            if not self._turn_started:
                self._pending = []
        elif isinstance(frame, TranscriptionFrame) and frame.text.strip():
            # Whisper only ever emits final transcriptions; interim frames
            # are a distinct class and never match this check.
            if self._turn_started:
                await self._publish({"type": "user_transcript", "text": frame.text})
            else:
                self._pending.append(frame.text)

        await self.push_frame(frame, direction)

    async def _publish(self, event: dict) -> None:
        if self._publisher is None:
            return
        await self._publisher({"ts": _now_ms(), **event})


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
        queue_frames: Callable[[list[Frame]], Awaitable[None]] | None = None,
    ) -> None:
        self._port = port
        self._wake_controller = wake_controller
        self._session_manager = session_manager
        self._snapshot = snapshot
        self._queue_frames = queue_frames
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
        elif cmd == "send_user_message":
            text = str(message.get("text") or "").strip()
            if not text:
                await self._send_ack(
                    connection,
                    message.get("id"),
                    ok=False,
                    error={"code": "empty_text", "message": "Mensagem vazia."},
                )
            elif self._queue_frames is None:
                await self._send_ack(
                    connection,
                    message.get("id"),
                    ok=False,
                    error={
                        "code": "not_available",
                        "message": "Bridge sem pipeline conectado.",
                    },
                )
            else:
                # Injeta a mensagem como um turno de usuário normal: o
                # aggregator adiciona ao contexto e roda o LLM; a resposta
                # flui pelo TTS (fala + agent_text) como qualquer outra.
                # O gate da palavra de ativação não se aplica a chat.
                await self._queue_frames(
                    [
                        LLMMessagesAppendFrame(
                            messages=[{"role": "user", "content": text}],
                            run_llm=True,
                        )
                    ]
                )
                # O espelho do chat só adiciona bolha do usuário via
                # user_transcript; publica o texto digitado no mesmo fluxo.
                await self.publish({"type": "user_transcript", "text": text})
                await self._send_ack(connection, message.get("id"), ok=True)
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
