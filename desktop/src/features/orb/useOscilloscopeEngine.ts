/**
 * Ponte stores → osciloscópio, sem re-render por frame.
 *
 * Espelho de `useOrbEngine`: `subscribe` sem seletor com guarda manual —
 * áudio a 30 Hz vai direto para o adaptador, e a visibilidade/cor só mudam
 * quando o estado correspondente muda.
 */

import { useEffect } from "react";

import { useBridgeStore } from "@/store/useBridgeStore";
import { useLevelStore } from "@/store/useLevelStore";
import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";

import { Oscilloscope } from "./oscilloscope";
import { PALETTES } from "./visualizer";

export function useOscilloscopeEngine(oscilloscope: Oscilloscope | null): void {
  useEffect(() => {
    if (!oscilloscope) return;

    const offLevels = useLevelStore.subscribe((state, prev) => {
      if (state.ts !== prev.ts) oscilloscope.ingest(state);
    });
    const offVoice = useBridgeStore.subscribe((state, prev) => {
      if (state.voice !== prev.voice) oscilloscope.setActive(state.voice === "speaking");
    });
    const offPalette = useOrbSettingsStore.subscribe((state, prev) => {
      if (state.palette !== prev.palette) {
        // A cor do sul do orb: o polo sul do gradiente de latitude do shader.
        oscilloscope.setColor(PALETTES[state.palette].bottom);
      }
    });

    // Coerência com o estado corrente na montagem.
    oscilloscope.ingest(useLevelStore.getState());
    oscilloscope.setActive(useBridgeStore.getState().voice === "speaking");
    oscilloscope.setColor(PALETTES[useOrbSettingsStore.getState().palette].bottom);

    return () => {
      offLevels();
      offVoice();
      offPalette();
    };
  }, [oscilloscope]);
}
