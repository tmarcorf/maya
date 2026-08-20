import { beforeEach, describe, expect, it } from "vitest";

import { useChatStore } from "@/store/useChatStore";

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

  it("clear esvazia mensagens e atividades", () => {
    useChatStore.getState().appendAgentDelta("turn-1", "x");
    useChatStore.getState().clear();
    expect(useChatStore.getState().messages).toHaveLength(0);
    expect(useChatStore.getState().toolActivities).toHaveLength(0);
  });
});
