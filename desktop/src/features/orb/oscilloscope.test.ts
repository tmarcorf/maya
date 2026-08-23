import { describe, expect, it } from "vitest";

import { traceFromSpectrum } from "@/features/orb/oscilloscope";

const POINTS = 192;

function flatPhases(bins: number): Float32Array {
  return new Float32Array(bins);
}

describe("traceFromSpectrum", () => {
  it("devolve a linha plana com espectro zerado", () => {
    const trace = traceFromSpectrum(new Uint8Array(48), flatPhases(48), 0.5, POINTS);
    expect([...trace].every((v) => v === 0)).toBe(true);
  });

  it("devolve a linha plana com nível zero", () => {
    const spectrum = new Uint8Array(48).fill(100);
    const trace = traceFromSpectrum(spectrum, flatPhases(48), 0, POINTS);
    expect([...trace].every((v) => v === 0)).toBe(true);
  });

  it("é determinística com fases fixas", () => {
    const spectrum = new Uint8Array(48).fill(120);
    const phases = flatPhases(48);
    const a = traceFromSpectrum(spectrum, phases, 0.5, POINTS);
    const b = traceFromSpectrum(spectrum, phases, 0.5, POINTS);
    expect([...a]).toEqual([...b]);
  });

  it("escala a amplitude com o nível", () => {
    const spectrum = new Uint8Array(48).fill(120);
    const quiet = traceFromSpectrum(spectrum, flatPhases(48), 0.2, POINTS);
    const loud = traceFromSpectrum(spectrum, flatPhases(48), 0.8, POINTS);

    const span = (trace: Float32Array) => Math.max(...trace) - Math.min(...trace);
    expect(span(loud)).toBeGreaterThan(span(quiet));
  });

  it("um pico num único bin vira a senóide daquele harmônico", () => {
    // Bin 0 (fase 0) → senóide de um ciclo pelo traço: começa em 0, volta a 0.
    const spectrum = new Uint8Array(48);
    spectrum[0] = 255;
    const trace = traceFromSpectrum(spectrum, flatPhases(48), 0.5, POINTS);

    expect(trace[0]).toBeCloseTo(0, 5);
    expect(trace[POINTS - 1]).toBeCloseTo(0, 5);
    // Pico positivo perto de u = 0.25 (um quarto do ciclo).
    const quarter = trace[Math.round(POINTS * 0.25)];
    expect(quarter).toBeGreaterThan(0);
    // Vale negativo perto de u = 0.75.
    expect(trace[Math.round(POINTS * 0.75)]).toBeLessThan(0);
  });

  it("as fases mudam a forma, não a amplitude", () => {
    const spectrum = new Uint8Array(48).fill(120);
    const phases = new Float32Array(48).map((_, b) => b * 1.7);
    const shifted = traceFromSpectrum(spectrum, phases, 0.5, POINTS);

    const span = (trace: Float32Array) => Math.max(...trace) - Math.min(...trace);
    const plain = traceFromSpectrum(spectrum, flatPhases(48), 0.5, POINTS);
    expect(span(shifted)).toBeGreaterThan(0);
    // O traço não é idêntico ao de fases zeradas — a fase deriva a silhueta.
    expect([...shifted]).not.toEqual([...plain]);
  });
});
