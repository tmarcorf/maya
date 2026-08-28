/**
 * Declaração do bridge exposto pelo preload do Electron (Fase 2).
 *
 * Na Fase 1 (web puro) `window.maya` não existe e o renderer usa o
 * `WsTransport`; quando o preload estiver presente, o `IpcTransport` o
 * substitui sem tocar nas stores.
 */
import type { BackendStatus } from "@/shared/backend";
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
    maya?: {
      onBridgeEvent(callback: (event: BridgeEvent) => void): () => void;
      onConnectionChange(callback: (status: ConnectionStatus) => void): () => void;
      sendCommand(command: Omit<Command, "id">): Promise<AckEvent>;
      getBridgeState(): Promise<{
        status: ConnectionStatus;
        session: { appSessionId: string | null; hermesSessionId: string | null } | null;
        voice: VoiceState;
        wake: WakeInfo;
      }>;
      onBackendStatus(callback: (status: BackendStatus) => void): () => void;
      getBackendStatus(): Promise<BackendStatus | null>;
      history: {
        load(): Promise<ChatMessage[]>;
        save(messages: ChatMessage[]): Promise<void>;
        clear(): Promise<void>;
      };
    };
  }
}

export {};
