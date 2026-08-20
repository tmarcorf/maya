/**
 * Dispatcher único de eventos → stores.
 *
 * Cada evento da bridge atualiza exatamente a fatia de estado que lhe diz
 * respeito. Os componentes assinam as stores com seletores (Zustand), então
 * um evento de áudio a ~30 Hz só acorda o orb — nunca o resto da árvore.
 */

import { transport } from "@/lib/bridge";
import type { Transport } from "@/lib/transport";
import type { BridgeEvent } from "@/shared/protocol";
import { useBridgeStore } from "@/store/useBridgeStore";
import { useChatStore } from "@/store/useChatStore";
import { useLevelStore } from "@/store/useLevelStore";

/** Liga o transport (singleton por padrão; injetável em testes). */
export function initBridge(transportOverride?: Transport): () => void {
  const active = transportOverride ?? transport;
  const offEvent = active.onEvent(handleEvent);
  const offConnection = active.onConnectionChange((status) => {
    useBridgeStore.getState().setConnection(status);
  });
  active.connect();
  return () => {
    offEvent();
    offConnection();
    active.disconnect();
  };
}

export function handleEvent(event: BridgeEvent): void {
  switch (event.type) {
    case "hello":
      useBridgeStore.getState().applyHello(event);
      break;
    case "state":
      useBridgeStore.getState().applyState(event);
      break;
    case "wake_state":
      useBridgeStore.getState().applyWakeState(event);
      break;
    case "user_transcript":
      useChatStore.getState().addUserTranscript(event.text, event.ts);
      break;
    case "agent_text":
      useChatStore.getState().appendAgentDelta(event.turnId, event.delta);
      break;
    case "agent_text_end":
      useChatStore.getState().endAgentTurn(event.turnId, event.text);
      break;
    case "tool_activity":
      useChatStore.getState().upsertToolActivity(event);
      break;
    case "audio_level":
      useLevelStore.getState().setLevels(event.input, event.output);
      break;
    case "interruption":
    case "error":
    case "ack":
      // Interrupção vira estado de voz via `state`; erro/ack são tratados
      // nos comandos (promise) — nada a espelhar nas stores.
      break;
  }
}
