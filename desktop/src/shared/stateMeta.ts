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
