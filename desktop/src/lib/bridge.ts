/**
 * Transport singleton — o canal de eventos do app.
 *
 * Fase 1 (web): `WsTransport` direto. Fase 2 (Electron): `IpcTransport`
 * via preload — a troca acontece aqui, sem tocar nas stores.
 * O App inicia a conexão com `initBridge()` (lib/dispatcher) uma única vez.
 */

import { IpcTransport, WsTransport, type Transport } from "@/lib/transport";

function createTransport(): Transport {
  // No Electron (preload presente), a conexão vive no processo main —
  // tray e atalho global continuam com a janela fechada. No navegador
  // (dev web), o renderer conecta direto na bridge.
  if (typeof window !== "undefined" && window.polaris) {
    return new IpcTransport(window.polaris);
  }
  return new WsTransport();
}

export const transport: Transport = createTransport();
