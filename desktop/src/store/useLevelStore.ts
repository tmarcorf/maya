/**
 * Níveis de áudio (RMS + análise espectral) a ~30 Hz.
 *
 * Nenhum componente React assina esta store com `useStore` — o orb lê os
 * valores via `subscribe` dentro de um `useEffect` e os entrega ao adaptador
 * de áudio. Zero re-render por frame de áudio.
 *
 * `bass`/`mid`/`treble`/`spectrum` são opcionais: descrevem o lado ativo
 * (quem está falando) e só chegam de uma bridge que faz a FFT. Sem eles o
 * adaptador sintetiza o espectro a partir do RMS.
 */

import { create } from "zustand";

import type { AudioLevelEvent } from "@/shared/protocol";

export interface AudioLevels {
  input: number;
  output: number;
  level?: number;
  bass?: number;
  mid?: number;
  treble?: number;
  spectrum?: number[];
  /** `ts` do evento — o adaptador usa para detectar dados velhos. */
  ts: number;
}

interface LevelState extends AudioLevels {
  setLevels: (event: AudioLevelEvent) => void;
}

export const useLevelStore = create<LevelState>()((set) => ({
  input: 0,
  output: 0,
  ts: 0,
  setLevels: (event) =>
    set({
      input: event.input,
      output: event.output,
      level: event.level,
      bass: event.bass,
      mid: event.mid,
      treble: event.treble,
      spectrum: event.spectrum,
      ts: event.ts,
    }),
}));
