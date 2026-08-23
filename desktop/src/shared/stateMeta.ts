/**
 * Metadados de estado de voz — single source das cores e rótulos pt-BR,
 * usado pelo orb (uniform hex) e pelo readout de estado no painel.
 *
 * Paleta da referência (print do usuário): família rosa → lavanda → azul.
 */

import type { VoiceState } from "@/shared/protocol";

export interface StateMeta {
  label: string;
  color: string;
}

export const STATE_META: Record<VoiceState, StateMeta> = {
  idle: { label: "Em espera", color: "#a89ac0" },
  listening: { label: "Ouvindo", color: "#8fc2d4" },
  user_speaking: { label: "Você fala", color: "#d19a9a" },
  thinking: { label: "Pensando", color: "#b09ce0" },
  speaking: { label: "Falando", color: "#e89a9e" },
};

/**
 * Estados VISUAIS do orb (4) — metadados do HUD (label/detail/dot) no
 * estilo orb-voice. `user_speaking` não tem visual próprio: renderiza
 * como `listening` (o usuário fala enquanto o orb "ouve").
 */
export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** Mapeia os 5 estados da bridge para os 4 estados visuais do orb. */
export function toOrbState(voice: VoiceState): OrbState {
  return voice === "user_speaking" ? "listening" : voice;
}

export interface OrbMeta {
  label: string; // texto do HUD, já em maiúsculas (fidelidade orb-voice)
  detail: string; // linha de detalhe do status-wrap
  dotColor: string; // cor do state-dot (single source do HUD)
}

export const ORB_META: Record<OrbState, OrbMeta> = {
  idle: { label: "AGUARDANDO", detail: "pronto para ouvir", dotColor: "#a9b6c8" },
  listening: { label: "OUVINDO", detail: "escutando sua voz", dotColor: "#ffb35c" },
  thinking: { label: "PENSANDO", detail: "processando sua voz", dotColor: "#b09ce0" },
  speaking: { label: "FALANDO", detail: "respondendo à sua voz", dotColor: "#ff6f61" },
};

export function wakeStatusLabel(state: string): string {
  switch (state) {
    case "asleep":
      return "Dormindo";
    case "awake":
      return "Acordada";
    case "disabled":
      return "Desligado";
    default:
      return state;
  }
}
