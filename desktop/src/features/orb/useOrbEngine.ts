/**
 * Ponte stores → controller do orb, sem re-render por frame.
 *
 * O controller guarda estado de voz e níveis em refs internos; este hook
 * só traduz mudanças das stores (Zustand v5: `subscribe` sem seletor —
 * guarda manual evita trabalho desnecessário) em chamadas imperativas.
 */

import { useEffect } from "react";

import { useBridgeStore } from "@/store/useBridgeStore";
import { useLevelStore } from "@/store/useLevelStore";

import type { OrbController } from "./OrbController";

export function useOrbEngine(controller: OrbController | null): void {
  useEffect(() => {
    if (!controller) return;

    const offVoice = useBridgeStore.subscribe((state, prev) => {
      if (state.voice !== prev.voice) controller.setState(state.voice);
    });
    const offLevels = useLevelStore.subscribe((state, prev) => {
      if (state.input !== prev.input || state.output !== prev.output) {
        controller.setLevels(state.input, state.output);
      }
    });

    // Coerência com o estado corrente na montagem.
    controller.setState(useBridgeStore.getState().voice);
    controller.setLevels(useLevelStore.getState().input, useLevelStore.getState().output);

    return () => {
      offVoice();
      offLevels();
    };
  }, [controller]);
}
