/**
 * Preload — expõe ao renderer SÓ o que ele precisa (contextBridge), com
 * contextIsolation + sandbox ativos. Nunca expõe `ipcRenderer` cru.
 */

import { contextBridge, ipcRenderer } from "electron";

import type { BackendStatus } from "../src/shared/backend";
import type {
  AckEvent,
  BridgeEvent,
  Command,
  ConnectionStatus,
  SessionInfo,
  VoiceState,
  WakeInfo,
} from "../src/shared/protocol";

export interface BridgeSnapshot {
  status: ConnectionStatus;
  session: SessionInfo | null;
  voice: VoiceState;
  wake: WakeInfo;
}

export interface MayaBridgeApi {
  onBridgeEvent(callback: (event: BridgeEvent) => void): () => void;
  onConnectionChange(callback: (status: ConnectionStatus) => void): () => void;
  sendCommand(command: Omit<Command, "id">): Promise<AckEvent>;
  /** Snapshot atual do main — resolve a corrida de inicialização. */
  getBridgeState(): Promise<BridgeSnapshot>;
  /** Ciclo de vida do backend Python (spawn/monitoramento pelo main). */
  onBackendStatus(callback: (status: BackendStatus) => void): () => void;
  getBackendStatus(): Promise<BackendStatus | null>;
  history: {
    load(): Promise<unknown[]>;
    save(messages: unknown[]): Promise<void>;
    clear(): Promise<void>;
  };
}

const api: MayaBridgeApi = {
  onBridgeEvent(callback) {
    const listener = (_event: unknown, payload: BridgeEvent) => callback(payload);
    ipcRenderer.on("bridge:event", listener);
    return () => {
      ipcRenderer.removeListener("bridge:event", listener);
    };
  },
  onConnectionChange(callback) {
    const listener = (_event: unknown, status: ConnectionStatus) => callback(status);
    ipcRenderer.on("bridge:status", listener);
    return () => {
      ipcRenderer.removeListener("bridge:status", listener);
    };
  },
  sendCommand(command) {
    return ipcRenderer.invoke("bridge:command", command) as Promise<AckEvent>;
  },
  getBridgeState() {
    return ipcRenderer.invoke("bridge:get-state") as Promise<BridgeSnapshot>;
  },
  onBackendStatus(callback) {
    const listener = (_event: unknown, status: BackendStatus) => callback(status);
    ipcRenderer.on("backend:status", listener);
    return () => {
      ipcRenderer.removeListener("backend:status", listener);
    };
  },
  getBackendStatus() {
    return ipcRenderer.invoke("backend:get-status") as Promise<BackendStatus | null>;
  },
  history: {
    load: () => ipcRenderer.invoke("history:load") as Promise<unknown[]>,
    save: (messages) => ipcRenderer.invoke("history:save", messages) as Promise<void>,
    clear: () => ipcRenderer.invoke("history:clear") as Promise<void>,
  },
};

contextBridge.exposeInMainWorld("maya", api);
