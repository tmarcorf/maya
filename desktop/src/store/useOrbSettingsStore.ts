/**
 * Ajustes visuais do orb.
 *
 * A store existe para os controles do painel re-renderizarem; o motor não a
 * lê. Cada mudança é empurrada imperativamente para o `Visualizer` (via
 * `applyOrbSettings`), então arrastar um slider não re-renderiza nada além do
 * próprio slider — e nunca toca no loop de render.
 */

import { create } from "zustand";

import { applyOrbSettings } from "@/features/orb/engineRegistry";
import {
  ORB_SETTINGS_DEFAULTS,
  loadOrbSettings,
  persistOrbSettings,
} from "@/features/orb/orbSettings";
import type { OrbVisualSettings } from "@/features/orb/orbSettings";
import type { PaletteKey } from "@/features/orb/visualizer";
import type { OrbSettings } from "@/features/orb/types";

const PERSIST_DELAY_MS = 250;

let persistTimer: ReturnType<typeof setTimeout> | undefined;

/** Grava no fim do arrasto, não a cada frame do slider. */
function schedulePersist(settings: OrbVisualSettings): void {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => persistOrbSettings(settings), PERSIST_DELAY_MS);
}

interface OrbSettingsState extends OrbVisualSettings {
  setValue: (key: keyof OrbSettings, value: number) => void;
  setPalette: (palette: PaletteKey) => void;
  reset: () => void;
}

export const useOrbSettingsStore = create<OrbSettingsState>()((set, get) => ({
  ...loadOrbSettings(),

  setValue: (key, value) => {
    set({ [key]: value } as Partial<OrbSettingsState>);
    const settings = snapshot(get());
    applyOrbSettings(settings);
    schedulePersist(settings);
  },

  setPalette: (palette) => {
    set({ palette });
    const settings = snapshot(get());
    applyOrbSettings(settings);
    schedulePersist(settings);
  },

  reset: () => {
    set({ ...ORB_SETTINGS_DEFAULTS });
    applyOrbSettings(ORB_SETTINGS_DEFAULTS);
    schedulePersist(ORB_SETTINGS_DEFAULTS);
  },
}));

function snapshot(state: OrbSettingsState): OrbVisualSettings {
  return {
    turbulence: state.turbulence,
    detail: state.detail,
    speed: state.speed,
    glow: state.glow,
    bloom: state.bloom,
    sensitivity: state.sensitivity,
    resolution: state.resolution,
    palette: state.palette,
  };
}
