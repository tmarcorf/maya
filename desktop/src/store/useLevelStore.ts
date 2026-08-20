/**
 * Níveis de áudio (input/output) a ~30 Hz.
 *
 * Nenhum componente React assina esta store com `useStore` — o orb lê os
 * valores via `subscribe` dentro de um `useEffect` e os grava em refs do
 * controller Three.js. Zero re-render por frame de áudio.
 */

import { create } from "zustand";

export interface AudioLevels {
  input: number;
  output: number;
}

interface LevelState extends AudioLevels {
  setLevels: (input: number, output: number) => void;
}

export const useLevelStore = create<LevelState>()((set) => ({
  input: 0,
  output: 0,
  setLevels: (input, output) => set({ input, output }),
}));
