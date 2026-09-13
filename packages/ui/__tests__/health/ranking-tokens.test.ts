import { describe, expect, it } from "vitest";
import {
  rankingHealthBandColor,
  rankingHealthBandForEntry,
  rankingHealthBandLabel,
  rankingHealthBandRangeLabel,
} from "../../src/health/ranking-tokens";

describe("canonical ranking health tokens", () => {
  it.each([
    ["excellent", "var(--color-success)"],
    ["good", "var(--color-success)"],
    ["fair", "var(--color-caution)"],
    ["weak", "var(--color-warning)"],
    ["critical", "var(--color-error)"],
    ["unknown", "var(--color-text-tertiary)"],
  ] as const)("maps %s to its dedicated ranking color", (band, color) => {
    expect(rankingHealthBandColor(band)).toBe(color);
    expect(rankingHealthBandLabel(band)).not.toBe("");
    expect(rankingHealthBandRangeLabel(band)).not.toBe("");
  });

  it("uses the API band when present and derives only for old responses", () => {
    expect(rankingHealthBandForEntry("fair", 95)).toBe("fair");
    expect(rankingHealthBandForEntry(undefined, 79.99)).toBe("fair");
    expect(rankingHealthBandForEntry(undefined, 80)).toBe("good");
    expect(rankingHealthBandForEntry("not-a-band", null)).toBe("unknown");
    expect(rankingHealthBandForEntry(undefined, Number.NaN)).toBe("unknown");
  });
});
