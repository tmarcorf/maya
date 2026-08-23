import { describe, expect, it } from "vitest";

import { BeatDetector, Envelope, upsampleSpectrum } from "@/features/orb/audioMath";
import { BridgeAudioSource } from "@/features/orb/bridgeAudio";
import { SPECTRUM_BINS } from "@/features/orb/types";
import type { AudioLevels } from "@/store/useLevelStore";

const FRAME = 1 / 60;

function levels(partial: Partial<AudioLevels> = {}): AudioLevels {
  return { input: 0, output: 0, ts: Date.now(), ...partial };
}

/** Roda `n` frames e devolve o último. */
function run(source: BridgeAudioSource, n: number) {
  let frame = source.read(FRAME);
  for (let i = 1; i < n; i++) frame = source.read(FRAME);
  return frame;
}

describe("Envelope", () => {
  it("sobe rápido e desce devagar", () => {
    const env = new Envelope(0.5, 0.05);
    env.push(1);
    const afterAttack = env.value;
    expect(afterAttack).toBeCloseTo(0.5, 5);

    env.push(0);
    // A queda usa o release (0.05), muito menor que o ataque.
    expect(env.value).toBeCloseTo(afterAttack * 0.95, 5);
  });
});

describe("BeatDetector", () => {
  it("dispara no ataque de graves e respeita o cooldown", () => {
    const detector = new BeatDetector();
    expect(detector.push(0.9, FRAME)).toBeGreaterThan(0.9);

    // Dentro dos 140 ms de cooldown o valor só decai, nunca volta a 1.
    const immediately = detector.push(0.9, FRAME);
    expect(immediately).toBeLessThan(1);
  });

  it("não dispara com graves fracos", () => {
    const detector = new BeatDetector();
    expect(detector.push(0.05, FRAME)).toBe(0);
  });

  it("decai até zero sem novos ataques", () => {
    const detector = new BeatDetector();
    detector.push(0.9, FRAME);
    let beat = 1;
    for (let i = 0; i < 60; i++) beat = detector.push(0, FRAME);
    expect(beat).toBe(0);
  });
});

describe("upsampleSpectrum", () => {
  it("reamostra preservando as extremidades", () => {
    const out = new Uint8Array(256);
    upsampleSpectrum([0, 255], out);
    expect(out[0]).toBe(0);
    expect(out[255]).toBe(255);
    expect(out[128]).toBeGreaterThan(100);
    expect(out[128]).toBeLessThan(155);
  });

  it("é monotônica para uma rampa", () => {
    const out = new Uint8Array(256);
    upsampleSpectrum([0, 64, 128, 192, 255], out);
    for (let i = 1; i < out.length; i++) {
      expect(out[i]).toBeGreaterThanOrEqual(out[i - 1]);
    }
  });

  it("zera para entrada vazia e satura no clamp", () => {
    const out = new Uint8Array(8).fill(9);
    upsampleSpectrum([], out);
    expect([...out]).toEqual(new Array(8).fill(0));

    upsampleSpectrum([200, 200], out, 4);
    expect([...out]).toEqual(new Array(8).fill(255));
  });
});

describe("BridgeAudioSource", () => {
  it("usa as bandas da bridge quando elas chegam", () => {
    const source = new BridgeAudioSource();
    source.setMood("live");
    source.ingest(
      levels({ input: 0.5, level: 0.5, bass: 0.8, mid: 0.2, treble: 0.1, spectrum: [255, 0] }),
    );

    const frame = run(source, 30);
    expect(frame.bass).toBeGreaterThan(frame.mid);
    expect(frame.mid).toBeGreaterThan(frame.treble);
    expect(frame.spectrum).toHaveLength(SPECTRUM_BINS);
    expect(frame.spectrum[0]).toBeGreaterThan(frame.spectrum[255]);
    expect(frame.silent).toBe(false);
  });

  it("sintetiza o espectro quando a bridge não manda FFT", () => {
    const source = new BridgeAudioSource();
    source.setMood("live");
    source.ingest(levels({ input: 0.4, output: 0 }));

    const frame = run(source, 30);
    expect(frame.level).toBeGreaterThan(0);
    // Sem bandas reais, ainda assim há um espectro inclinado para o orb usar.
    expect(frame.spectrum[0]).toBeGreaterThan(0);
    expect(frame.spectrum[0]).toBeGreaterThan(frame.spectrum[200]);
  });

  it("segue o lado ativo: a voz da Polaris move o orb igual à do usuário", () => {
    const speaking = new BridgeAudioSource();
    speaking.setMood("live");
    speaking.ingest(levels({ input: 0, output: 0.6, level: 0.6, bass: 0.5, mid: 0.4, treble: 0.2 }));
    const bot = run(speaking, 30);

    const listening = new BridgeAudioSource();
    listening.setMood("live");
    listening.ingest(levels({ input: 0.6, output: 0, level: 0.6, bass: 0.5, mid: 0.4, treble: 0.2 }));
    const user = run(listening, 30);

    expect(bot.level).toBeCloseTo(user.level, 6);
    expect(bot.bass).toBeCloseTo(user.bass, 6);
  });

  it("repousa quando ocioso", () => {
    const source = new BridgeAudioSource();
    source.setMood("rest");
    const frame = run(source, 60);

    expect(frame.silent).toBe(true);
    expect(frame.level).toBeLessThan(0.1);
    expect(frame.beat).toBe(0);
    expect([...frame.spectrum].every((v) => v === 0)).toBe(true);
  });

  it("pulsa enquanto a Polaris pensa, mesmo sem áudio nenhum", () => {
    const source = new BridgeAudioSource();
    source.setMood("ambient");

    // Sem áudio, o modo ambiente precisa render movimento — senão o orb
    // morreria justo enquanto o Hermes processa.
    const samples = Array.from({ length: 90 }, () => source.read(FRAME).level);
    expect(Math.max(...samples)).toBeGreaterThan(0.05);
    expect(source.read(FRAME).silent).toBe(false);
  });

  it("cai para repouso quando a bridge para de mandar níveis", () => {
    const source = new BridgeAudioSource();
    source.setMood("live");
    source.ingest(levels({ input: 0.7, level: 0.7, ts: Date.now() - 5000 }));

    const frame = run(source, 30);
    expect(frame.silent).toBe(true);
    expect(frame.level).toBeLessThan(0.1);
  });
});
