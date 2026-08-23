import { beforeEach, describe, expect, it } from "vitest";

import { selectTimeline, useChatStore } from "@/store/useChatStore";

function toolEvent(ts: number, toolCallId: string, status: string) {
  return {
    type: "tool_activity" as const,
    ts,
    tool: "terminal",
    label: "ls",
    emoji: "",
    toolCallId,
    status,
  };
}

beforeEach(() => {
  useChatStore.setState({ messages: [], toolActivities: [] });
});

describe("useChatStore", () => {
  it("addUserTranscript ignora vazio", () => {
    useChatStore.getState().addUserTranscript("   ", 1);
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it("appendAgentDelta cria o turno na primeira chamada", () => {
    useChatStore.getState().appendAgentDelta("turn-1", "Olá");
    const messages = useChatStore.getState().messages;
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ id: "turn-1", role: "agent", text: "Olá", final: false });
  });

  it("endAgentTurn usa o texto completo autoritativo", () => {
    const store = useChatStore.getState();
    store.appendAgentDelta("turn-1", "parcial ");
    store.appendAgentDelta("turn-1", "que ");
    // O backend reenvia o texto inteiro no fim — ele vence os deltas.
    store.endAgentTurn("turn-1", "texto definitivo");
    expect(useChatStore.getState().messages[0]).toMatchObject({
      text: "texto definitivo",
      final: true,
    });
  });

  it("upsertToolActivity substitui pelo mesmo toolCallId", () => {
    const store = useChatStore.getState();
    store.upsertToolActivity({ type: "tool_activity", ts: 1, tool: "terminal", label: "a", emoji: "", toolCallId: "c1", status: "running" });
    store.upsertToolActivity({ type: "tool_activity", ts: 2, tool: "terminal", label: "a", emoji: "", toolCallId: "c1", status: "completed" });
    store.upsertToolActivity({ type: "tool_activity", ts: 3, tool: "browser", label: "b", emoji: "", toolCallId: "c2", status: "running" });

    const activities = useChatStore.getState().toolActivities;
    expect(activities).toHaveLength(2);
    expect(activities[0]).toMatchObject({ toolCallId: "c1", status: "completed" });
    expect(activities[1]).toMatchObject({ toolCallId: "c2", status: "running" });
  });

  it("o comando (label do running) sobrevive ao completed com label vazio", () => {
    const store = useChatStore.getState();
    store.upsertToolActivity({ type: "tool_activity", ts: 1, tool: "terminal", label: "date", emoji: "", toolCallId: "c1", status: "running" });
    store.upsertToolActivity({ type: "tool_activity", ts: 2, tool: "terminal", label: "", emoji: "", toolCallId: "c1", status: "completed" });

    const activities = useChatStore.getState().toolActivities;
    expect(activities[0]).toMatchObject({ label: "date", status: "completed" });
  });

  it("upsertToolActivity preserva o ts da primeira aparição", () => {
    const store = useChatStore.getState();
    store.upsertToolActivity(toolEvent(10, "c1", "running"));
    store.upsertToolActivity(toolEvent(99, "c1", "completed"));

    // O ts é a âncora do card na timeline: se ele andasse junto com o
    // status, a ferramenta pularia de lugar ao concluir.
    expect(useChatStore.getState().toolActivities[0]).toMatchObject({
      ts: 10,
      status: "completed",
    });
  });

  it("clear esvazia mensagens e atividades", () => {
    useChatStore.getState().appendAgentDelta("turn-1", "x");
    useChatStore.getState().clear();
    expect(useChatStore.getState().messages).toHaveLength(0);
    expect(useChatStore.getState().toolActivities).toHaveLength(0);
  });
});

describe("selectTimeline", () => {
  it("intercala mensagens e ferramentas por ts", () => {
    const store = useChatStore.getState();
    store.addUserTranscript("liste os arquivos", 100);
    store.upsertToolActivity(toolEvent(200, "c1", "running"));
    store.addUserTranscript("obrigado", 300);

    const timeline = selectTimeline(useChatStore.getState());
    expect(timeline.map((i) => [i.kind, i.ts])).toEqual([
      ["message", 100],
      ["tool", 200],
      ["message", 300],
    ]);
  });

  it("a ferramenta não muda de posição quando conclui", () => {
    const store = useChatStore.getState();
    store.addUserTranscript("primeira", 100);
    store.upsertToolActivity(toolEvent(200, "c1", "running"));
    store.addUserTranscript("segunda", 300);
    store.upsertToolActivity(toolEvent(400, "c1", "completed"));

    const timeline = selectTimeline(useChatStore.getState());
    expect(timeline.map((i) => i.kind)).toEqual(["message", "tool", "message"]);
  });

  it("empate de ts coloca a mensagem antes da ferramenta", () => {
    const store = useChatStore.getState();
    store.addUserTranscript("oi", 50);
    store.upsertToolActivity(toolEvent(50, "c1", "running"));

    expect(selectTimeline(useChatStore.getState()).map((i) => i.kind)).toEqual([
      "message",
      "tool",
    ]);
  });

  it("lista vazia devolve timeline vazia", () => {
    expect(selectTimeline({ messages: [], toolActivities: [] })).toEqual([]);
  });
});
