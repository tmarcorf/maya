/**
 * Liga o renderer ao ciclo de vida do backend (processo main).
 *
 * Assina o canal `backend:status` e faz um pull inicial — o main pode já ter
 * emitido fases antes do renderer montar (mesma corrida da bridge).
 * No navegador (sem preload) não há backend gerenciado: no-op.
 */

import { useBackendStore } from "@/store/useBackendStore";

export function initBackendStatus(): () => void {
  if (typeof window === "undefined" || !window.maya) return () => {};
  const unsubscribe = window.maya.onBackendStatus((status) => {
    useBackendStore.getState().setStatus(status);
  });
  void window.maya.getBackendStatus().then((status) => {
    if (status) useBackendStore.getState().setStatus(status);
  });
  return unsubscribe;
}
