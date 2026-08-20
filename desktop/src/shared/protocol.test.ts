import { describe, expect, it } from "vitest";

import { isBridgeEvent } from "@/shared/protocol";

describe("isBridgeEvent", () => {
  it("aceita eventos conhecidos", () => {
    expect(isBridgeEvent({ type: "hello", ts: 1, bridgeVersion: 1, session: null })).toBe(true);
    expect(isBridgeEvent({ type: "state", ts: 1, voice: "idle", wake: {} })).toBe(true);
    expect(isBridgeEvent({ type: "audio_level", ts: 1, input: 0.1, output: 0 })).toBe(true);
    expect(isBridgeEvent({ type: "ack", id: 3, ok: true })).toBe(true);
  });

  it("descarta payloads desconhecidos ou malformados", () => {
    expect(isBridgeEvent(null)).toBe(false);
    expect(isBridgeEvent("texto")).toBe(false);
    expect(isBridgeEvent({})).toBe(false);
    expect(isBridgeEvent({ type: "nao_existe" })).toBe(false);
    expect(isBridgeEvent({ type: 42 })).toBe(false);
  });
});
