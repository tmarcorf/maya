/**
 * Estado do ciclo de vida do backend Python, gerenciado pelo main.
 *
 * Default "skipped" (nada a exibir) até o primeiro `backend:status` chegar:
 * no navegador (dev web) não há backend gerenciado e nada deve renderizar.
 */

import { create } from "zustand";

import type { BackendStatus } from "@/shared/backend";

interface BackendState extends BackendStatus {
  setStatus: (status: BackendStatus) => void;
}

export const useBackendStore = create<BackendState>()((set) => ({
  phase: "skipped",
  setStatus: (status) => set(status),
}));
