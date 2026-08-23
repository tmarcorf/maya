/**
 * Tipos compartilhados do motor do orb.
 *
 * `AudioFrame` é o contrato que o `Orb` consome uma vez por frame — o mesmo
 * que o protótipo em `orb/` produzia com Web Audio. Aqui ele é produzido pelo
 * `BridgeAudioSource`, a partir dos eventos da bridge da Polaris.
 */

export const SPECTRUM_BINS = 256;

export interface AudioFrame {
  /** Volume percebido, 0..~1.6 (passa de 1 nos picos, de propósito). */
  level: number;
  bass: number;
  mid: number;
  treble: number;
  /** 1 no ataque da batida, decaindo até 0. */
  beat: number;
  /** `SPECTRUM_BINS` magnitudes 0..255, alimentando a textura do shader. */
  spectrum: Uint8Array;
  silent: boolean;
}

export interface OrbPalette {
  label: string;
  top: number;
  upper: number;
  mid: number;
  lower: number;
  bottom: number;
  flareTop: number;
  flareBottom: number;
  /** Gradiente de fundo do palco: [interno, externo]. */
  background: readonly [string, string];
}

/** Controles ao vivo do painel de ajustes. */
export interface OrbSettings {
  turbulence: number;
  detail: number;
  speed: number;
  glow: number;
  bloom: number;
  sensitivity: number;
}
