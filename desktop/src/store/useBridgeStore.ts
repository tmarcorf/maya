/**
 * Estado espelhado do backend: conexão, voz e wake word.
 *
 * Tudo aqui reflete o que o backend PUBLICOU (nunca estado otimista) —
 * o toggle só muda de valor quando chega `wake_state`/`ack` do servidor.
 */

import { create } from "zustand";

import type {
  GetStateData,
  HelloEvent,
  SessionInfo,
  StateEvent,
  VoiceState,
  WakeInfo,
  WakeStateEvent,
} from "@/shared/protocol";
import type { ConnectionStatus } from "@/lib/transport";

const DEFAULT_WAKE: WakeInfo = { enabled: false, state: "disabled", phrase: null };

interface BridgeState {
  connection: ConnectionStatus;
  voice: VoiceState;
  wake: WakeInfo;
  session: SessionInfo | null;
  bridgeVersion: number | null;
  setConnection: (connection: ConnectionStatus) => void;
  applyHello: (event: HelloEvent) => void;
  applyState: (event: StateEvent) => void;
  applyWakeState: (event: WakeStateEvent) => void;
  applySnapshot: (data: GetStateData) => void;
}

export const useBridgeStore = create<BridgeState>()((set) => ({
  connection: "disconnected",
  voice: "idle",
  wake: DEFAULT_WAKE,
  session: null,
  bridgeVersion: null,

  setConnection: (connection) => set({ connection }),

  applyHello: (event) =>
    set({ session: event.session, bridgeVersion: event.bridgeVersion }),

  applyState: (event) => set({ voice: event.voice, wake: event.wake }),

  applyWakeState: (event) =>
    set({ wake: { enabled: event.enabled, state: event.state, phrase: event.phrase } }),

  applySnapshot: (data) => set({ voice: data.voice, wake: data.wake, session: data.session }),
}));
