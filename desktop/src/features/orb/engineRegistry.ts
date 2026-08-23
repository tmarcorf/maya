/**
 * Registro do motor vivo do orb.
 *
 * O painel de ajustes precisa escrever em `visualizer.settings` a cada
 * movimento de slider. Passar o visualizer por props obrigaria a árvore
 * inteira a re-renderizar (ou a virar contexto) por causa de um objeto que só
 * o loop de render lê. Um registro de módulo mantém o painel desacoplado e o
 * React fora do caminho.
 */

import type { OrbVisualSettings } from "./orbSettings";
import type { Visualizer } from "./visualizer";

let current: Visualizer | null = null;

export function setOrbVisualizer(visualizer: Visualizer | null): void {
  current = visualizer;
}

export function getOrbVisualizer(): Visualizer | null {
  return current;
}

/** Empurra os ajustes para o motor. Ignorado se o orb não estiver montado. */
export function applyOrbSettings(settings: OrbVisualSettings): void {
  const visualizer = current;
  if (!visualizer) return;
  visualizer.settings.turbulence = settings.turbulence;
  visualizer.settings.detail = settings.detail;
  visualizer.settings.speed = settings.speed;
  visualizer.settings.glow = settings.glow;
  visualizer.settings.bloom = settings.bloom;
  visualizer.settings.sensitivity = settings.sensitivity;
  if (visualizer.settings.palette !== settings.palette) {
    visualizer.applyPalette(settings.palette);
  }
}
