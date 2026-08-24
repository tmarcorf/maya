/**
 * Ajustes visuais do orb — preferências de UI, por máquina.
 *
 * Persistidas em `localStorage` e não no `userData` via IPC: não são dados da
 * sessão (como o histórico), e perder um slider não quebra nada. Segue o
 * mesmo padrão best-effort de `useChatStore`.
 */

import { isPaletteKey } from "./visualizer";
import type { PaletteKey } from "./visualizer";
import type { OrbSettings } from "./types";

export interface OrbVisualSettings extends OrbSettings {
  palette: PaletteKey;
}

const STORAGE_KEY = "maya.orb-settings.v1";
// Chave antiga (Polaris): só para a migração única de nomes.
const LEGACY_STORAGE_KEY = "polaris.orb-settings.v1";

export const ORB_SETTINGS_DEFAULTS: OrbVisualSettings = {
  turbulence: 1,
  detail: 0.5,
  speed: 1,
  glow: 1,
  bloom: 0.9,
  sensitivity: 1,
  resolution: 1.5,
  palette: "ember",
};

export interface SliderSpec {
  key: keyof OrbSettings;
  label: string;
  min: number;
  max: number;
  step: number;
  hint: string;
}

/** Mesmas faixas do protótipo, onde o visual foi calibrado. */
export const ORB_SLIDERS: SliderSpec[] = [
  { key: "sensitivity", label: "Sensibilidade", min: 0.2, max: 3, step: 0.05, hint: "resposta ao volume da voz" },
  { key: "turbulence", label: "Turbulência", min: 0, max: 2.5, step: 0.05, hint: "amplitude da deformação" },
  { key: "detail", label: "Detalhe", min: 0, max: 1.5, step: 0.05, hint: "frequência do ruído" },
  { key: "speed", label: "Velocidade", min: 0, max: 3, step: 0.05, hint: "rotação e evolução" },
  { key: "glow", label: "Brilho", min: 0, max: 2, step: 0.05, hint: "intensidade das flares" },
  { key: "bloom", label: "Bloom", min: 0, max: 2.5, step: 0.05, hint: "halo luminoso" },
  { key: "resolution", label: "Resolução", min: 1, max: 2, step: 0.25, hint: "nítidez vs desempenho" },
];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Migração única de nomes: copia o que houver na chave antiga (Polaris). */
function migrateStorageKey(): void {
  try {
    if (localStorage.getItem(STORAGE_KEY) !== null) return;
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacy !== null) {
      localStorage.setItem(STORAGE_KEY, legacy);
      localStorage.removeItem(LEGACY_STORAGE_KEY);
    }
  } catch {
    // Storage bloqueado/quota: sem migração, segue com os padrões.
  }
}

export function loadOrbSettings(): OrbVisualSettings {
  const settings = { ...ORB_SETTINGS_DEFAULTS };
  if (typeof localStorage === "undefined") return settings;
  migrateStorageKey();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return settings;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return settings;
    const record = parsed as Record<string, unknown>;

    for (const slider of ORB_SLIDERS) {
      const value = record[slider.key];
      if (typeof value === "number" && Number.isFinite(value)) {
        settings[slider.key] = clamp(value, slider.min, slider.max);
      }
    }
    if (isPaletteKey(record.palette)) settings.palette = record.palette;
  } catch {
    // Valor corrompido ou storage bloqueado: os padrões servem.
  }
  return settings;
}

export function persistOrbSettings(settings: OrbVisualSettings): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Quota/privacidade: preferências são best-effort.
  }
}
