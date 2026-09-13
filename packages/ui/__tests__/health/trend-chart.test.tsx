// @vitest-environment jsdom

import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TrendChart, type TrendSeriesPoint } from "../../src/health/trend-chart";

const history: TrendSeriesPoint[] = [
  { taken_at: null, average_health: 0, hotspot_health: null, worst_performer_score: null },
  { taken_at: null, average_health: 5, hotspot_health: null, worst_performer_score: null },
  { taken_at: null, average_health: 10, hotspot_health: null, worst_performer_score: null },
];

function svgText(): string[] {
  return Array.from(document.querySelectorAll("svg text"), (node) => node.textContent ?? "");
}

describe("TrendChart score scales", () => {
  it("keeps the legacy 0–10 scale by default", () => {
    render(<TrendChart history={history} />);

    expect(screen.getByRole("img", { name: "Health KPI trend (0–10)" })).toBeTruthy();
    expect(svgText()).toEqual(expect.arrayContaining(["0", "2", "4", "6", "8", "10"]));
    expect(svgText()).not.toContain("100");
  });

  it("renders canonical 0–100 ticks and preserves the bottom/top endpoints", () => {
    render(
      <TrendChart
        scoreScale={100}
        history={[
          { ...history[0]!, average_health: 0 },
          { ...history[1]!, average_health: 82.5 },
          { ...history[2]!, average_health: 100 },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Health KPI trend (0–100)" })).toBeTruthy();
    expect(svgText()).toEqual(expect.arrayContaining(["0", "20", "40", "60", "80", "100"]));
    expect(document.querySelectorAll("circle")).toHaveLength(3);
  });
});
