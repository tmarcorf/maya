/**
 * Declaração do bridge exposto pelo preload do Electron (Fase 2).
 *
 * Na Fase 1 (web puro) `window.polaris` não existe e o renderer usa o
 * `WsTransport`; quando o preload estiver presente, o `IpcTransport` o
 * substitui sem tocar nas stores.
 */
import type {
  AckEvent,
  BridgeEvent,
  Command,
  ConnectionStatus,
  VoiceState,
  WakeInfo,
} from "@/shared/protocol";
import type { ChatMessage } from "@/store/useChatStore";

declare global {
  interface Window {
    polaris?: {
      onBridgeEvent(callback: (event: BridgeEvent) => void): () => void;
      onConnectionChange(callback: (status: ConnectionStatus) => void): () => void;
      sendCommand(command: Omit<Command, "id">): Promise<AckEvent>;
      getBridgeState(): Promise<{
        status: ConnectionStatus;
        session: { appSessionId: string | null; hermesSessionId: string | null } | null;
        voice: VoiceState;
        wake: WakeInfo;
      }>;
      history: {
        load(): Promise<ChatMessage[]>;
        save(messages: ChatMessage[]): Promise<void>;
        clear(): Promise<void>;
      };
    };
  }
}

export {};
