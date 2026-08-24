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
  /**
   * Segmento de texto fechado por uma chamada de ferramenta: o turno do
   * agente continua, mas este trecho já tem posição fixa na linha do tempo
   * (o texto que chega depois — a resposta final — vai para um segmento
   * novo, abaixo do card da ferramenta).
   */
  sealed?: boolean;
}

export interface ToolActivity {
  toolCallId: string;
  tool: string;
  label: string;
  emoji: string;
  status: string;
  ts: number;
}

const STORAGE_KEY = "maya.chat.v1";
// Chave antiga (Polaris): só para a migração única de nomes.
const LEGACY_STORAGE_KEY = "polaris.chat.v1";
const MAX_MESSAGES = 200;
// Atividades de ferramenta: eventos raros (uma por chamada), cap mais folgado
// que as mensagens — nunca chegam perto, mas o DOM fica limitado de qualquer
// jeito em sessão longa.
const MAX_TOOLS = 100;

// Bookkeeping do streaming por turno (não-reativo de propósito): o turno do
// agente é identificado pelo `turnId` do protocolo; o texto que chega é
// acumulado no segmento ativo. Quando uma ferramenta roda no meio do turno,
// o segmento é selado e os deltas seguintes abrem um novo.
const activeSegments = new Map<string, string>(); // turnId → messageId
const nextSegment = new Map<string, number>(); // turnId → próximo sufixo

interface ChatState {
  messages: ChatMessage[];
  toolActivities: ToolActivity[];
  addUserTranscript: (text: string, ts: number) => void;
  appendAgentDelta: (turnId: string, delta: string, ts: number) => void;
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

/** Migração única de nomes: copia o que houver na chave antiga (Polaris). */
function migrateStorageKey(): void {
  try {
    if (localStorage.getItem(STORAGE_KEY) !== null) return;
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacy !== null) {
      localStorage.setItem(STORAGE_KEY, legacy);
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    }
  } catch {
    // Storage bloqueado/quota: sem migração, segue sem dados.
  }
}

function loadPersisted(): ChatMessage[] {
  // No Electron (preload presente) o histórico vive no userData e chega
  // assíncrono (App faz o load); no navegador, localStorage é o fallback.
  migrateStorageKey();
  if (typeof window !== "undefined" && window.maya) return [];
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
  if (typeof window !== "undefined" && window.maya) {
    void window.maya.history.save(capped).catch(() => {
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
  if (typeof window === "undefined" || !window.maya) return;
  void window.maya.history
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

export type TimelineItem =
  | { kind: "message"; id: string; ts: number; message: ChatMessage }
  | { kind: "tool"; id: string; ts: number; activity: ToolActivity };

/**
 * Mensagens e atividades de ferramenta numa única linha do tempo.
 *
 * As duas listas já chegam ordenadas por `ts` (append-only), então basta um
 * merge linear. Empate vai para a mensagem: a ferramenta é consequência do
 * turno do agente, e lê melhor logo abaixo dele.
 */
export function selectTimeline(
  state: Pick<ChatState, "messages" | "toolActivities">,
): TimelineItem[] {
  const { messages, toolActivities } = state;
  const items: TimelineItem[] = [];
  let i = 0;
  let j = 0;
  while (i < messages.length || j < toolActivities.length) {
    const message = messages[i];
    const activity = toolActivities[j];
    if (message && (!activity || message.ts <= activity.ts)) {
      items.push({ kind: "message", id: message.id, ts: message.ts, message });
      i++;
    } else if (activity) {
      items.push({
        kind: "tool",
        id: activity.toolCallId || `${activity.tool}-${activity.ts}`,
        ts: activity.ts,
        activity,
      });
      j++;
    }
  }
  return items;
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
    set((state) => {
      const message: ChatMessage = { id: newMessageId(), role: "user", text, ts, final: true };
      return { messages: [...state.messages, message].slice(-MAX_MESSAGES) };
    });
    persist(get().messages);
  },

  appendAgentDelta: (turnId, delta, ts) => {
    set((state) => {
      const activeId = activeSegments.get(turnId);
      if (activeId && state.messages.some((m) => m.id === activeId)) {
        return {
          messages: state.messages
            .map((m) => (m.id === activeId ? { ...m, text: m.text + delta } : m))
            .slice(-MAX_MESSAGES),
        };
      }
      // Novo segmento: o primeiro herda o turnId; os seguintes ganham
      // sufixo para não colidir com o segmento selado.
      const id = state.messages.some((m) => m.id === turnId)
        ? `${turnId}:${nextSegment.get(turnId) ?? 1}`
        : turnId;
      if (id !== turnId) {
        nextSegment.set(turnId, (nextSegment.get(turnId) ?? 1) + 1);
      }
      activeSegments.set(turnId, id);
      const message: ChatMessage = { id, role: "agent", text: delta, ts, final: false };
      return { messages: [...state.messages, message].slice(-MAX_MESSAGES) };
    });
  },

  endAgentTurn: (turnId, text) => {
    const activeId = activeSegments.get(turnId);
    if (activeId) {
      set((state) => {
        // `agent_text_end` traz o texto completo do turno (autoritativo),
        // mas com segmentos selados o trecho anterior já está exibido:
        // o texto final do segmento ativo é o texto completo menos o
        // prefixo dos segmentos selados do mesmo turno.
        const sealedPrefix = state.messages
          .filter(
            (m) =>
              m.role === "agent" &&
              m.sealed &&
              (m.id === turnId || m.id.startsWith(`${turnId}:`)),
          )
          .map((m) => m.text)
          .join("");
        const finalText =
          sealedPrefix && text.startsWith(sealedPrefix)
            ? text.slice(sealedPrefix.length)
            : text;
        return {
          messages: state.messages
            .map((m) => (m.id === activeId ? { ...m, text: finalText, final: true } : m))
            .slice(-MAX_MESSAGES),
        };
      });
      activeSegments.delete(turnId);
      persist(get().messages);
    }
  },

  upsertToolActivity: (event) => {
    set((state) => {
      // Cronologia: a ferramenta roda no meio do turno — sela o segmento de
      // texto em andamento para que o texto seguinte (a resposta final)
      // abra um segmento novo, abaixo do card da ferramenta.
      let messages = state.messages;
      const open = messages.filter((m) => m.role === "agent" && !m.final && !m.sealed);
      if (open.length > 0) {
        const sealedIds = new Set(open.map((m) => m.id));
        messages = messages.map((m) =>
          sealedIds.has(m.id) ? { ...m, sealed: true } : m,
        );
        for (const [turnId, messageId] of activeSegments) {
          if (sealedIds.has(messageId)) activeSegments.delete(turnId);
        }
      }

      const index = state.toolActivities.findIndex(
        (a) => a.toolCallId && a.toolCallId === event.toolCallId,
      );
      if (index === -1) {
        return {
          messages,
          toolActivities: [
            ...state.toolActivities,
            {
              toolCallId: event.toolCallId,
              tool: event.tool,
              label: event.label,
              emoji: event.emoji,
              status: event.status,
              ts: event.ts,
            },
          ].slice(-MAX_TOOLS),
        };
      }
      // `ts` é o instante em que a ferramenta apareceu, não o da última
      // atualização: preservá-lo mantém o card ancorado no seu lugar da
      // timeline quando o status vira `completed`.
      const next = [...state.toolActivities];
      next[index] = {
        ...next[index],
        tool: event.tool,
        // O comando vem no evento `running`; o `completed` chega com label
        // vazio e não pode apagá-lo — o primeiro label não-vazio vence.
        label: event.label || next[index].label,
        emoji: event.emoji || next[index].emoji,
        status: event.status,
      };
      return { messages, toolActivities: next.slice(-MAX_TOOLS) };
    });
  },

  clear: () => {
    activeSegments.clear();
    nextSegment.clear();
    set({ messages: [], toolActivities: [] });
    if (typeof window !== "undefined" && window.maya) {
      void window.maya.history.clear().catch(() => {
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
