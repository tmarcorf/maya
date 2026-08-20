/**
 * Abstração do canal de eventos com o backend.
 *
 * Fase 1 (web): `WsTransport` conecta direto em ws://127.0.0.1:8686.
 * Fase 2 (Electron): `IpcTransport` repassa pelo preload — o renderer
 * continua consumindo a mesma interface, sem tocar nas stores.
 */

import {
  BRIDGE_VERSION,
  DEFAULT_BRIDGE_URL,
  isBridgeEvent,
  type AckEvent,
  type BridgeEvent,
  type Command,
  type ConnectionStatus,
} from "@/shared/protocol";

export type { ConnectionStatus };

export type EventHandler = (event: BridgeEvent) => void;
export type ConnectionHandler = (status: ConnectionStatus) => void;

export interface Transport {
  connect(): void;
  disconnect(): void;
  onEvent(handler: EventHandler): () => void;
  onConnectionChange(handler: ConnectionHandler): () => void;
  /** O `id` do comando é gerado pelo transport; o ack chega pela promise. */
  sendCommand(command: Omit<Command, "id">): Promise<AckEvent>;
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const COMMAND_TIMEOUT_MS = 5_000;

/**
 * Transport sobre o preload do Electron (Fase 2): a conexão real vive no
 * processo main — aqui só se repassam eventos e comandos pelo IPC.
 */
export class IpcTransport implements Transport {
  private offEvent: (() => void) | null = null;
  private offConnection: (() => void) | null = null;

  constructor(private readonly api: NonNullable<typeof window.polaris>) {}

  connect(): void {
    // Idempotente: StrictMode remonta efeitos no dev — reconectar não
    // pode acumular listeners duplicados (mensagens em dobro).
    this.disconnect();
    this.offEvent = this.api.onBridgeEvent((event) => {
      this.eventHandlers.forEach((handler) => handler(event));
    });
    this.offConnection = this.api.onConnectionChange((status) => {
      this.connectionHandlers.forEach((handler) => handler(status));
    });
    // Pull do estado corrente: o main pode ter conectado antes desta
    // assinatura existir — sem o snapshot, o status inicial se perde.
    void this.api
      .getBridgeState()
      .then((snapshot) => {
        this.connectionHandlers.forEach((handler) => handler(snapshot.status));
        if (snapshot.session) {
          this.emitEvent({
            type: "hello",
            ts: Date.now(),
            bridgeVersion: BRIDGE_VERSION,
            session: snapshot.session,
          });
        }
        this.emitEvent({
          type: "state",
          ts: Date.now(),
          voice: snapshot.voice,
          wake: snapshot.wake,
        });
      })
      .catch(() => {
        // Sem snapshot (main indisponível): o stream de eventos segue
        // sozinho quando a conexão existir.
      });
  }

  private emitEvent(event: BridgeEvent): void {
    this.eventHandlers.forEach((handler) => handler(event));
  }

  disconnect(): void {
    // A conexão pertence ao processo main — o renderer só se desliga dos
    // listeners do IPC (o reload recria tudo do zero).
    this.offEvent?.();
    this.offConnection?.();
    this.offEvent = null;
    this.offConnection = null;
  }

  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    return () => this.connectionHandlers.delete(handler);
  }

  sendCommand(command: Omit<Command, "id">): Promise<AckEvent> {
    return this.api.sendCommand(command);
  }

  private readonly eventHandlers = new Set<EventHandler>();
  private readonly connectionHandlers = new Set<ConnectionHandler>();
}

interface PendingCommand {
  resolve: (ack: AckEvent) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class WsTransport implements Transport {
  private readonly url: string;
  private ws: WebSocket | null = null;
  private status: ConnectionStatus = "disconnected";
  private reconnectDelayMs = RECONNECT_BASE_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = false;
  private nextCommandId = 1;
  private readonly pending = new Map<number, PendingCommand>();
  private readonly eventHandlers = new Set<EventHandler>();
  private readonly connectionHandlers = new Set<ConnectionHandler>();

  constructor(url: string = DEFAULT_BRIDGE_URL) {
    this.url = url;
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
    this.rejectAllPending(new Error("Transporte desconectado."));
    this.detachSocket();
    this.setStatus("disconnected");
  }

  /** Desacopla os handlers e fecha o socket corrente, se houver. */
  private detachSocket(): void {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    // Sem handlers, o onclose do socket antigo não pode agendar
    // reconexão nem competir com um socket novo (StrictMode remonta
    // efeitos no dev — o primeiro socket não pode "reviver" o loop).
    if (ws.readyState === WebSocket.CONNECTING) {
      // Fecha assim que o handshake terminar: fechar durante CONNECTING
      // dispara um warning "closed before the connection is established".
      ws.onopen = () => ws.close();
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      return;
    }
    ws.onopen = null;
    ws.onmessage = null;
    ws.onclose = null;
    ws.onerror = null;
    if (ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
  }

  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    return () => this.connectionHandlers.delete(handler);
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

    ws.onopen = () => {
      this.reconnectDelayMs = RECONNECT_BASE_MS;
      this.setStatus("connected");
    };

    ws.onmessage = (message) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(message.data));
      } catch {
        return; // payload inválido: ignora, não derruba o espelho
      }
      if (!isBridgeEvent(parsed)) return;

      if (parsed.type === "ack") {
        this.resolvePending(parsed);
      }
      this.eventHandlers.forEach((handler) => handler(parsed));
    };

    ws.onclose = () => {
      this.ws = null;
      this.setStatus("disconnected");
      this.rejectAllPending(new Error("Conexão fechada."));
      if (!this.closedByUser) this.scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose sempre segue; nada a fazer aqui.
    };
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

  private setStatus(status: ConnectionStatus): void {
    if (status === this.status) return;
    this.status = status;
    this.connectionHandlers.forEach((handler) => handler(status));
  }
}
