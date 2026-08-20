import { beforeEach, describe, expect, it } from "vitest";

import { handleEvent, initBridge } from "@/lib/dispatcher";
import type { ConnectionHandler, ConnectionStatus, EventHandler, Transport } from "@/lib/transport";
import type { AckEvent, BridgeEvent, Command } from "@/shared/protocol";
import { useBridgeStore } from "@/store/useBridgeStore";
import { useChatStore } from "@/store/useChatStore";
import { useLevelStore } from "@/store/useLevelStore";

class FakeTransport implements Transport {
  readonly eventHandlers = new Set<EventHandler>();
  readonly connectionHandlers = new Set<ConnectionHandler>();
  connected = false;

  connect(): void {
    this.connected = true;
    this.emitConnection("connected");
  }

  disconnect(): void {
    this.connected = false;
    this.emitConnection("disconnected");
  }

  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    return () => this.connectionHandlers.delete(handler);
  }

  async sendCommand(_command: Omit<Command, "id">): Promise<AckEvent> {
    return { type: "ack", id: 1, ok: true };
  }

  emit(event: BridgeEvent): void {
    for (const handler of this.eventHandlers) handler(event);
  }

  emitConnection(status: ConnectionStatus): void {
    for (const handler of this.connectionHandlers) handler(status);
  }
}

function resetStores(): void {
  useBridgeStore.setState({
    connection: "disconnected",
    voice: "idle",
    wake: { enabled: false, state: "disabled", phrase: null },
    session: null,
    bridgeVersion: null,
  });
  useChatStore.setState({ messages: [], toolActivities: [] });
  useLevelStore.setState({ input: 0, output: 0 });
}

beforeEach(resetStores);

describe("handleEvent", () => {
  it("hello preenche sessão e versão", () => {
    handleEvent({
      type: "hello",
      ts: 1,
      bridgeVersion: 1,
      session: { appSessionId: "voice-session-test", hermesSessionId: null },
    });
    expect(useBridgeStore.getState().session?.appSessionId).toBe("voice-session-test");
    expect(useBridgeStore.getState().bridgeVersion).toBe(1);
  });

  it("state atualiza voz e wake — espelho do backend", () => {
    handleEvent({
      type: "state",
      ts: 1,
      voice: "thinking",
      wake: { enabled: true, state: "awake", phrase: "e aí polaris" },
    });
    const bridge = useBridgeStore.getState();
    expect(bridge.voice).toBe("thinking");
    expect(bridge.wake.state).toBe("awake");
  });

  it("wake_state atualiza só o wake", () => {
    handleEvent({ type: "wake_state", ts: 1, enabled: false, state: "disabled", phrase: null });
    const bridge = useBridgeStore.getState();
    expect(bridge.wake.enabled).toBe(false);
    expect(bridge.wake.state).toBe("disabled");
    expect(bridge.voice).toBe("idle"); // intocado
  });

  it("user_transcript vira mensagem de usuário final", () => {
    handleEvent({ type: "user_transcript", ts: 10, text: "Que horas são?" });
    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ role: "user", text: "Que horas são?", final: true, ts: 10 });
  });

  it("agent_text acumula e agent_text_end fecha o turno", () => {
    handleEvent({ type: "agent_text", ts: 1, turnId: "turn-1", delta: "São " });
    handleEvent({ type: "agent_text", ts: 2, turnId: "turn-1", delta: "14h32." });
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0]).toMatchObject({ id: "turn-1", final: false });

    handleEvent({ type: "agent_text_end", ts: 3, turnId: "turn-1", text: "São 14h32." });
    expect(useChatStore.getState().messages[0]).toMatchObject({ id: "turn-1", text: "São 14h32.", final: true });
  });

  it("tool_activity atualiza o mesmo card por toolCallId", () => {
    handleEvent({ type: "tool_activity", ts: 1, tool: "terminal", label: "date", emoji: "▸", toolCallId: "call-1", status: "running" });
    handleEvent({ type: "tool_activity", ts: 2, tool: "terminal", label: "date", emoji: "▸", toolCallId: "call-1", status: "completed" });
    const activities = useChatStore.getState().toolActivities;
    expect(activities).toHaveLength(1);
    expect(activities[0].status).toBe("completed");
  });

  it("audio_level atualiza a store de níveis", () => {
    handleEvent({ type: "audio_level", ts: 1, input: 0.4, output: 0.1 });
    expect(useLevelStore.getState()).toMatchObject({ input: 0.4, output: 0.1 });
  });
});

describe("initBridge", () => {
  it("liga transport e repassa status de conexão", () => {
    const fake = new FakeTransport();
    const teardown = initBridge(fake);
    expect(fake.connected).toBe(true);
    expect(useBridgeStore.getState().connection).toBe("connected");

    fake.emitConnection("disconnected");
    expect(useBridgeStore.getState().connection).toBe("disconnected");

    teardown();
    expect(fake.connected).toBe(false);
  });

  it("eventos do transport passam pelo dispatcher", () => {
    const fake = new FakeTransport();
    const teardown = initBridge(fake);
    fake.emit({ type: "user_transcript", ts: 1, text: "oi" });
    expect(useChatStore.getState().messages).toHaveLength(1);
    teardown();
  });
});
