/**
 * Client WebSocket da bridge no processo MAIN.
 *
 * Vive aqui (e não no renderer) porque o tray e o atalho global precisam
 * do estado com a janela fechada, e reloads do renderer não podem derrubar
 * a conexão. Reconexão com backoff exponencial + jitter; comandos são
 * resolvidos pelo ack (id) — nunca otimista. Emite `event` (BridgeEvent)
 * e `status` (ConnectionStatus); `voice`/`wake` guardam o último estado
 * conhecido para o tray.
 */

import { EventEmitter } from "node:events";

import WebSocket from "ws";

import {
  isBridgeEvent,
  type AckEvent,
  type BridgeEvent,
  type Command,
  type ConnectionStatus,
  type SessionInfo,
  type VoiceState,
  type WakeInfo,
} from "../src/shared/protocol";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const COMMAND_TIMEOUT_MS = 5_000;

interface PendingCommand {
  resolve: (ack: AckEvent) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

export class BridgeClient extends EventEmitter {
  readonly url: string;
  private ws: WebSocket | null = null;
  private status: ConnectionStatus = "disconnected";
  private reconnectDelayMs = RECONNECT_BASE_MS;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private closedByUser = false;
  private nextCommandId = 1;
  private readonly pending = new Map<number, PendingCommand>();

  /** Último estado conhecido — fonte do tray e do atalho global. */
  voice: VoiceState = "idle";
  wake: WakeInfo = { enabled: false, state: "disabled", phrase: null };
  session: SessionInfo | null = null;

  constructor(url: string) {
    super();
    this.url = url;
  }

  get connectionStatus(): ConnectionStatus {
    return this.status;
  }

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.rejectAllPending(new Error("Bridge desconectada."));
    this.detachSocket();
    this.setStatus("disconnected");
  }

  sendCommand(command: Omit<Command, "id">): Promise<AckEvent> {
    if (this.ws === null || this.ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("Bridge desconectada."));
    }
    const id = this.nextCommandId++;
    return new Promise<AckEvent>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Comando ${command.cmd} sem resposta (timeout).`));
      }, COMMAND_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      this.ws!.send(JSON.stringify({ ...command, id }));
    });
  }

  private open(): void {
    this.setStatus("connecting");
    this.detachSocket();
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.on("open", () => {
      this.reconnectDelayMs = RECONNECT_BASE_MS;
      this.setStatus("connected");
    });

    ws.on("message", (data) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(data));
      } catch {
        return; // payload inválido: ignora, não derruba o espelho
      }
      if (!isBridgeEvent(parsed)) return;
      if (parsed.type === "ack") this.resolvePending(parsed);
      this.trackState(parsed);
      this.emit("event", parsed);
    });

    ws.on("close", () => {
      this.ws = null;
      this.setStatus("disconnected");
      this.rejectAllPending(new Error("Conexão fechada."));
      if (!this.closedByUser) this.scheduleReconnect();
    });

    ws.on("error", () => {
      // `close` sempre segue; nada a fazer aqui.
    });
  }

  private trackState(event: BridgeEvent): void {
    if (event.type === "hello") {
      this.session = event.session;
    } else if (event.type === "state") {
      this.voice = event.voice;
      this.wake = event.wake;
    } else if (event.type === "wake_state") {
      this.wake = { enabled: event.enabled, state: event.state, phrase: event.phrase };
    }
  }

  private scheduleReconnect(): void {
    // Backoff exponencial com jitter para evitar rajadas em loop de erro.
    const jitter = this.reconnectDelayMs * (0.5 + Math.random() * 0.5);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open();
    }, jitter);
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, RECONNECT_MAX_MS);
  }

  private resolvePending(ack: AckEvent): void {
    const id = ack.id;
    if (id === null) return;
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    clearTimeout(pending.timer);
    pending.resolve(ack);
  }

  private rejectAllPending(error: Error): void {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  private detachSocket(): void {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    ws.removeAllListeners();
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
  }

  private setStatus(status: ConnectionStatus): void {
    if (status === this.status) return;
    this.status = status;
    this.emit("status", status);
  }
}
