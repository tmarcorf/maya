/**
 * Utilidades de análise de áudio do orb.
 *
 * Portadas do protótipo (`orb/src/audio-engine.js`): são elas que dão o
 * "feel" do visual — ataque rápido, queda lenta, batida com cooldown. Ficam
 * separadas do adaptador por serem puras e testáveis sem DOM nem WebGL.
 */

/** Suavização assimétrica: sobe rápido, desce devagar. */
export class Envelope {
  value = 0;

  constructor(
    private readonly attack = 0.35,
    private readonly release = 0.06,
  ) {}

  push(target: number): number {
    const k = target > this.value ? this.attack : this.release;
    this.value += (target - this.value) * k;
    return this.value;
  }

  reset(): void {
    this.value = 0;
  }
}

/**
 * Batida por energia de graves acima da média recente.
 *
 * Dispara em 1 e decai; o cooldown evita que uma sílaba longa vire uma
 * sequência de batidas.
 */
export class BeatDetector {
  private readonly history = new Float32Array(48);
  private cursor = 0;
  private beat = 0;
  private clock = 0;
  private lastBeatAt = Number.NEGATIVE_INFINITY;

  push(bass: number, dt: number): number {
    this.clock += dt;
    this.history[this.cursor] = bass;
    this.cursor = (this.cursor + 1) % this.history.length;

    let mean = 0;
    for (let i = 0; i < this.history.length; i++) mean += this.history[i];
    mean /= this.history.length;

    if (this.clock - this.lastBeatAt > 0.14 && bass > 0.16 && bass > mean * 1.32) {
      this.lastBeatAt = this.clock;
      this.beat = 1;
    }

    this.beat = Math.max(0, this.beat - dt * 3.4);
    return this.beat;
  }
}

/**
 * Reamostra os bins que vêm pela bridge para o tamanho que o shader espera.
 *
 * Os dois lados já são log-espaçados na mesma faixa, então a interpolação
 * linear entre bins vizinhos preserva o formato do espectro.
 */
export function upsampleSpectrum(
  bins: ArrayLike<number>,
  out: Uint8Array,
  gain = 1,
): void {
  const n = bins.length;
  if (n === 0) {
    out.fill(0);
    return;
  }
  if (n === 1) {
    out.fill(Math.max(0, Math.min(255, Math.round(bins[0] * gain))));
    return;
  }

  const last = out.length - 1;
  const scale = (n - 1) / last;
  for (let i = 0; i <= last; i++) {
    const x = i * scale;
    const low = Math.floor(x);
    const high = Math.min(n - 1, low + 1);
    const frac = x - low;
    const value = bins[low] * (1 - frac) + bins[high] * frac;
    out[i] = Math.max(0, Math.min(255, Math.round(value * gain)));
  }
}
