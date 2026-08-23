import { describe, expect, it } from "vitest";

import { ORB_META, toOrbState } from "@/shared/stateMeta";

describe("toOrbState", () => {
  it("mapeia os 5 estados da bridge para os 4 estados visuais", () => {
    expect(toOrbState("idle")).toBe("idle");
    expect(toOrbState("listening")).toBe("listening");
    expect(toOrbState("user_speaking")).toBe("listening");
    expect(toOrbState("thinking")).toBe("thinking");
    expect(toOrbState("speaking")).toBe("speaking");
  });
});

describe("ORB_META", () => {
  it("cobre os 4 estados visuais com label, detail e dotColor", () => {
    for (const state of ["idle", "listening", "thinking", "speaking"] as const) {
      const meta = ORB_META[state];
      expect(meta.label.length).toBeGreaterThan(0);
      expect(meta.detail.length).toBeGreaterThan(0);
      expect(meta.dotColor).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});
