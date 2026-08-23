/**
 * Adaptador entre a bridge da Polaris e o motor do orb.
 *
 * O protótipo em `orb/` lia um `AnalyserNode` do Web Audio. Aqui a análise
 * acontece no backend, sobre o mesmo PCM que a pipeline já processa: o
 * microfone do usuário e o áudio do TTS. Isso evita disputar o microfone com
 * o Python, funciona em qualquer plataforma e — o principal — faz o orb
 * reagir tanto à voz do usuário quanto à voz da Polaris.
 *
 * A suavização, normalização por pico e detecção de batida continuam aqui,
 * do lado do cliente, exatamente como no protótipo.
 */

import type { AudioLevels } from "@/store/useLevelStore";

import { BeatDetector, Envelope, upsampleSpectrum } from "./audioMath";
import { SPECTRUM_BINS } from "./types";
import type { AudioFrame } from "./types";

/**
 * `pulse` — Polaris falando: o pulso do orb é o áudio real do TTS, com
 * ganho acima do modo ambiente para ler como reação à fala dela.
 * `live` — alguém está falando, use o áudio real.
 * `ambient` — Polaris pensando: não há áudio, mas o orb não pode morrer.
 * `rest` — ocioso: decai para o repouso.
 */
export type AudioMood = "pulse" | "live" | "ambient" | "rest";

/** Sem evento novo por este tempo, o áudio é considerado morto. */
const STALE_MS = 400;

export class BridgeAudioSource {
  sensitivity = 1;

  private levels: AudioLevels = { input: 0, output: 0, ts: 0 };
  private mood: AudioMood = "rest";
  private clock = 0;
  private peak = 0.25;

  private readonly spectrum = new Uint8Array(SPECTRUM_BINS);
  private readonly envLevel = new Envelope(0.3, 0.05);
  private readonly envBass = new Envelope(0.45, 0.07);
  private readonly envMid = new Envelope(0.35, 0.06);
  private readonly envTreble = new Envelope(0.5, 0.09);
  private readonly beatDetector = new BeatDetector();

  /** Recebe o último `audio_level`. Chamado pelo `useOrbEngine`. */
  ingest(levels: AudioLevels): void {
    this.levels = levels;
  }

  setMood(mood: AudioMood): void {
    this.mood = mood;
  }

  /** Um frame por quadro renderizado. Sempre devolve algo utilizável. */
  read(dt: number): AudioFrame {
    this.clock += dt;

    // Polaris falando: o gate é o estado de voz, não a frescura do áudio —
    // entre sentenças a bridge segura o último nível publicado (o zero
    // arrancaria o pulso no meio da fala), então o staleness não vale aqui.
    if (this.mood === "pulse") return this.pulse(dt);
    if (this.mood === "ambient") return this.synthesize(dt, 0.45);
    if (this.mood === "rest" || this.isStale()) return this.rest(dt);
    return this.live(dt);
  }

  private isStale(): boolean {
    return this.levels.ts === 0 || Date.now() - this.levels.ts > STALE_MS;
  }

  /**
   * Polaris falando: o mesmo drive do `live`, com ganho acima do modo
   * ambiente — o orb lê como reação à fala dela, não como a respiração
   * sintética do "pensando…". O nível segue a sílaba (ataque rápido do
   * envelope) e, quando ela para, o estado de voz volta a `rest` e o pulso
   * decai com a soltura lenta.
   */
  private pulse(dt: number): AudioFrame {
    return this.live(dt, 0.90);
  }

  private live(dt: number, drive = 0.55): AudioFrame {
    const { levels } = this;
    // `level` já é o RMS do lado ativo (quem fala). Sem ele, o maior dos dois
    // lados é a melhor aproximação.
    const rms = levels.level ?? Math.max(levels.input, levels.output);

    // Pico com queda lenta: mantém material baixo expressivo sem estourar o
    // material alto.
    this.peak = Math.max(rms, this.peak - dt * 0.08);
    const norm = this.sensitivity / Math.max(this.peak, 0.045);
    const level = Math.min(1.6, rms * norm * drive);

    const hasBands = levels.bass !== undefined;
    const rawBass = hasBands ? levels.bass! : rms * 0.9;
    const rawMid = hasBands ? levels.mid! : rms * 0.7;
    const rawTreble = hasBands ? levels.treble! : rms * 0.45;

    const bass = Math.min(1.5, rawBass * this.sensitivity * 1.15);
    const mid = Math.min(1.5, rawMid * this.sensitivity * 1.35);
    const treble = Math.min(1.5, rawTreble * this.sensitivity * 1.7);

    if (levels.spectrum && levels.spectrum.length > 0) {
      upsampleSpectrum(levels.spectrum, this.spectrum, this.sensitivity);
    } else {
      // Bridge sem FFT: um espectro inclinado, escalado pelo volume, mantém a
      // silhueta viva mesmo sem timbre real.
      this.fillTiltedSpectrum(rms * this.sensitivity);
    }

    return {
      level: this.envLevel.push(level),
      bass: this.envBass.push(bass),
      mid: this.envMid.push(mid),
      treble: this.envTreble.push(treble),
      beat: this.beatDetector.push(bass, dt),
      spectrum: this.spectrum,
      silent: rms < 0.002,
    };
  }

  /** Repouso: tudo decai para um estado calmo, sem espectro. */
  private rest(dt: number): AudioFrame {
    this.spectrum.fill(0);
    return {
      level: this.envLevel.push(0.06),
      bass: this.envBass.push(0.05),
      mid: this.envMid.push(0.04),
      treble: this.envTreble.push(0.03),
      beat: this.beatDetector.push(0, dt),
      spectrum: this.spectrum,
      silent: true,
    };
  }

  /**
   * Pulsação sintética para quando não há áudio nenhum mas o orb precisa
   * mostrar que algo acontece — a Polaris pensando entre a fala e a resposta.
   */
  private synthesize(dt: number, amplitude: number): AudioFrame {
    const t = this.clock;
    const pulse = Math.pow(Math.max(0, Math.sin(t * 2.2)), 6);

    for (let i = 0; i < SPECTRUM_BINS; i++) {
      const u = i / SPECTRUM_BINS;
      const wave =
        Math.sin(u * 9 + t * 1.3) * 0.5 +
        Math.sin(u * 23 - t * 2.1) * 0.28 +
        Math.sin(u * 47 + t * 3.7) * 0.15;
      const tilt = Math.pow(1 - u, 1.6);
      const value = (wave * 0.5 + 0.5) * tilt * (0.55 + pulse * 0.6) * amplitude;
      this.spectrum[i] = Math.max(0, Math.min(1, value)) * 255;
    }

    const bass = (0.22 + pulse * 0.55) * amplitude;
    const mid = (0.18 + Math.abs(Math.sin(t * 0.7)) * 0.3) * amplitude;
    const treble = (0.12 + Math.abs(Math.sin(t * 1.9)) * 0.25) * amplitude;

    return {
      level: this.envLevel.push((bass + mid + treble) / 2.4),
      bass: this.envBass.push(bass),
      mid: this.envMid.push(mid),
      treble: this.envTreble.push(treble),
      beat: this.beatDetector.push(bass, dt),
      spectrum: this.spectrum,
      silent: false,
    };
  }

  private fillTiltedSpectrum(level: number): void {
    for (let i = 0; i < SPECTRUM_BINS; i++) {
      const u = i / SPECTRUM_BINS;
      const tilt = Math.pow(1 - u, 1.8);
      this.spectrum[i] = Math.max(0, Math.min(255, Math.round(tilt * level * 255)));
    }
  }
}
