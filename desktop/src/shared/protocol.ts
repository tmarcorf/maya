/**
 * Contrato da bridge desktop — espelho de `pipeline/bridge.py`.
 *
 * Single source of truth dos tipos trocados entre o backend (Python) e o
 * app (renderer e processo main). Qualquer mudança no protocolo atualiza
 * este arquivo, `pipeline/bridge.py` e `scripts/mock-bridge.mjs` juntos.
 *
 * Eventos server → client (JSON lines, `ts` = epoch ms):
 *   hello, state, user_transcript, agent_text, agent_text_end,
 *   tool_activity, interruption, audio_level, wake_state, error
 *
 * `audio_level` carrega, além do RMS de cada lado, a análise espectral do
 * lado ativo (campos opcionais: level/bass/mid/treble/spectrum).
 * Comandos client → server (ack é a única resposta — nunca otimista):
 *   get_state, set_wake_word_enabled, ping
 */

export const BRIDGE_VERSION = 1;
export const DEFAULT_BRIDGE_URL = "ws://127.0.0.1:8686";

export type VoiceState =
  | "idle"
  | "user_speaking"
  | "listening"
  | "thinking"
  | "speaking";

export type WakeState = "asleep" | "awake" | "disabled";

/** Estado da conexão com a bridge (renderer e processo main compartilham). */
export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export interface SessionInfo {
  appSessionId: string | null;
  hermesSessionId: string | null;
}

export interface WakeInfo {
  enabled: boolean;
  state: WakeState;
  phrase: string | null;
}

export interface HelloEvent {
  type: "hello";
  ts: number;
  bridgeVersion: number;
  session: SessionInfo;
}

export interface StateEvent {
  type: "state";
  ts: number;
  voice: VoiceState;
  wake: WakeInfo;
}

export interface UserTranscriptEvent {
  type: "user_transcript";
  ts: number;
  text: string;
}

export interface AgentTextEvent {
  type: "agent_text";
  ts: number;
  turnId: string;
  delta: string;
}

export interface AgentTextEndEvent {
  type: "agent_text_end";
  ts: number;
  turnId: string;
  text: string;
}

export interface ToolActivityEvent {
  type: "tool_activity";
  ts: number;
  tool: string;
  label: string;
  emoji: string;
  toolCallId: string;
  status: string;
}

export interface InterruptionEvent {
  type: "interruption";
  ts: number;
}

/** Número de bins do espectro no fio (o renderer reamostra para 256). */
export const SPECTRUM_BINS_WIRE = 32;

export interface AudioLevelEvent {
  type: "audio_level";
  ts: number;
  input: number;
  output: number;
  /**
   * Análise espectral do lado ativo (quem está falando: microfone durante
   * `user_speaking`/`listening`, TTS durante `speaking`). Opcionais — uma
   * bridge antiga não os envia e o orb cai no caminho degradado, sintetizando
   * o espectro a partir do RMS.
   */
  level?: number;
  bass?: number;
  mid?: number;
  treble?: number;
  /** `SPECTRUM_BINS_WIRE` bins log-espaçados (~28 Hz–16 kHz), 0..255. */
  spectrum?: number[];
}

export interface WakeStateEvent {
  type: "wake_state";
  ts: number;
  enabled: boolean;
  state: WakeState;
  phrase: string | null;
}

export interface ErrorEvent {
  type: "error";
  ts: number;
  code: string;
  message: string;
}

export interface AckEvent {
  type: "ack";
  id: number | null;
  ok: boolean;
  data?: unknown;
  error?: { code: string; message: string };
}

export type BridgeEvent =
  | HelloEvent
  | StateEvent
  | UserTranscriptEvent
  | AgentTextEvent
  | AgentTextEndEvent
  | ToolActivityEvent
  | InterruptionEvent
  | AudioLevelEvent
  | WakeStateEvent
  | ErrorEvent
  | AckEvent;

export type CommandName = "get_state" | "set_wake_word_enabled" | "ping";

export interface Command {
  id: number;
  cmd: CommandName;
  enabled?: boolean;
}

/** Payload de `get_state` (e do `state` enviado junto do `hello`). */
export interface GetStateData {
  voice: VoiceState;
  wake: WakeInfo;
  session: SessionInfo;
}

const BRIDGE_EVENT_TYPES = new Set<string>([
  "hello",
  "state",
  "user_transcript",
  "agent_text",
  "agent_text_end",
  "tool_activity",
  "interruption",
  "audio_level",
  "wake_state",
  "error",
  "ack",
]);

/** Type guard tolerante: payloads desconhecidos são descartados sem erro. */
export function isBridgeEvent(raw: unknown): raw is BridgeEvent {
  if (typeof raw !== "object" || raw === null) return false;
  const type = (raw as { type?: unknown }).type;
  return typeof type === "string" && BRIDGE_EVENT_TYPES.has(type);
}
