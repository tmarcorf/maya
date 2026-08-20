/**
 * Mensagens da conversa (espelho da sessão) + atividades de ferramenta.
 *
 * O contexto real vive na sessão do Hermes; este histórico é um espelho de
 * UI. O turno do agente é acumulado por `turnId` (streaming de deltas) e
 * fechado por `agent_text_end` — que traz o texto completo, autoritativo.
 * Persistência v1: localStorage (Fase 2 troca por JSON no userData via IPC).
 */

import { create } from "zustand";

import type { ToolActivityEvent } from "@/shared/protocol";

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  text: string;
  ts: number;
  final: boolean;
}

export interface ToolActivity {
  toolCallId: string;
  tool: string;
  label: string;
  emoji: string;
  status: string;
  ts: number;
}

const STORAGE_KEY = "polaris.chat.v1";
const MAX_MESSAGES = 200;

interface ChatState {
  messages: ChatMessage[];
  toolActivities: ToolActivity[];
  addUserTranscript: (text: string, ts: number) => void;
  appendAgentDelta: (turnId: string, delta: string) => void;
  endAgentTurn: (turnId: string, text: string) => void;
  upsertToolActivity: (event: ToolActivityEvent) => void;
  clear: () => void;
}

function isChatMessage(value: unknown): value is ChatMessage {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ChatMessage).id === "string" &&
    ((value as ChatMessage).role === "user" || (value as ChatMessage).role === "agent") &&
    typeof (value as ChatMessage).text === "string"
  );
}

function loadPersisted(): ChatMessage[] {
  // No Electron (preload presente) o histórico vive no userData e chega
  // assíncrono (App faz o load); no navegador, localStorage é o fallback.
  if (typeof window !== "undefined" && window.polaris) return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isChatMessage);
  } catch {
    return [];
  }
}

function persist(messages: ChatMessage[]): void {
  const capped = messages.slice(-MAX_MESSAGES);
  if (typeof window !== "undefined" && window.polaris) {
    void window.polaris.history.save(capped).catch(() => {
      // Best-effort: o espelho persistido não pode quebrar a sessão.
    });
    return;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
  } catch {
    // Quota/privacidade: o espelho persistido é best-effort.
  }
}

/** Carrega o histórico persistido no userData (Electron) e mescla. */
export function hydrateChatHistory(): void {
  if (typeof window === "undefined" || !window.polaris) return;
  void window.polaris.history
    .load()
    .then((loaded) => {
      const valid = loaded.filter(isChatMessage);
      if (valid.length === 0) return;
      const store = useChatStore.getState();
      // Só hidrata se nada chegou ainda — eventos ao vivo têm precedência.
      if (store.messages.length === 0) {
        useChatStore.setState({ messages: valid });
      }
    })
    .catch(() => {
      // Best-effort: sem histórico persistido, segue vazio.
    });
}

function newMessageId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `m-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export const useChatStore = create<ChatState>()((set, get) => ({
  messages: loadPersisted(),
  toolActivities: [],

  addUserTranscript: (text, ts) => {
    if (!text.trim()) return;
    set((state) => ({
      messages: [...state.messages, { id: newMessageId(), role: "user", text, ts, final: true }],
    }));
    persist(get().messages);
  },

  appendAgentDelta: (turnId, delta) => {
    set((state) => {
      const existing = state.messages.find((m) => m.id === turnId);
      if (!existing) {
        return {
          messages: [
            ...state.messages,
            { id: turnId, role: "agent", text: delta, ts: Date.now(), final: false },
          ],
        };
      }
      return {
        messages: state.messages.map((m) =>
          m.id === turnId ? { ...m, text: m.text + delta } : m,
        ),
      };
    });
  },

  endAgentTurn: (turnId, text) => {
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === turnId ? { ...m, text, final: true } : m,
      ),
    }));
    persist(get().messages);
  },

  upsertToolActivity: (event) => {
    const activity: ToolActivity = {
      toolCallId: event.toolCallId,
      tool: event.tool,
      label: event.label,
      emoji: event.emoji,
      status: event.status,
      ts: event.ts,
    };
    set((state) => {
      const index = state.toolActivities.findIndex(
        (a) => a.toolCallId && a.toolCallId === event.toolCallId,
      );
      if (index === -1) {
        return { toolActivities: [...state.toolActivities, activity] };
      }
      const next = [...state.toolActivities];
      next[index] = activity;
      return { toolActivities: next };
    });
  },

  clear: () => {
    set({ messages: [], toolActivities: [] });
    if (typeof window !== "undefined" && window.polaris) {
      void window.polaris.history.clear().catch(() => {
        // best-effort
      });
      return;
    }
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // best-effort
    }
  },
}));
