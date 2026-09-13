// @vitest-environment jsdom

import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type {
  HealthRankingBand,
  HealthRankingEntry,
  HealthRankingTrendResponse,
} from "@repowise-dev/types/health-ranking";
import { RankingTrendChart } from "./trend-chart";
import { EntryDimensionBars, ScoreBreakdown } from "./score-breakdown";
import { RankingTable } from "./ranking-table";

afterEach(cleanup);

const rows: HealthRankingEntry[] = [
  {
    repository_id: "a",
    name: "alpha",
    url: "",
    snapshot_id: "s-a",
    score_config_digest: "same",
    overall_score: 91,
    grade: "A",
    status: "ready",
    dimensions: { code: 95, tests: 88 },
    languages: ["Rust"],
    confidence: 0.9,
    coverage: 0.9,
    evidence_coverage: 0.9,
    analyzed_at: null,
    stale: false,
    eligible: true,
    eligibility_reason: null,
    score_delta: 3.5,
  },
  {
    repository_id: "b",
    name: "beta",
    url: "",
    snapshot_id: "s-b",
    score_config_digest: "same",
    overall_score: 54,
    grade: "D",
    status: "partial",
    dimensions: { code: null, tests: 42 },
    languages: ["Python"],
    confidence: 0.4,
    coverage: 0.4,
    evidence_coverage: 0.35,
    analyzed_at: null,
    stale: true,
    eligible: true,
    eligibility_reason: null,
    score_delta: -2.25,
  },
];

describe("extended ranking summaries", () => {
  it("shows distribution and separates missing dimensions from zero", () => {
    render(
      <>
        <ScoreBreakdown entries={rows} />
        <EntryDimensionBars entry={rows[1]!} />
      </>,
    );
    expect(screen.getByText("Score distribution")).toBeTruthy();
    expect(screen.getByText("Dimension coverage")).toBeTruthy();
    expect(screen.getAllByText("Code quality").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders score movement with direction and previous-snapshot context", () => {
    render(<RankingTrendChart entries={rows} />);
    expect(screen.getByText("Recent score movement")).toBeTruthy();
    expect(screen.getByText("vs previous published snapshot")).toBeTruthy();
    expect(screen.getByText("+3.50")).toBeTruthy();
    expect(screen.getByText("-2.25")).toBeTruthy();
  });

  it("uses canonical ranking bands at every boundary and keeps null neutral", () => {
    const boundaries: Array<[number | null, HealthRankingBand]> = [
      [0, "critical"],
      [59.99, "critical"],
      [60, "weak"],
      [79.99, "fair"],
      [80, "good"],
      [89.99, "good"],
      [90, "excellent"],
      [100, "excellent"],
      [null, "unknown"],
    ];
    const boundaryRows: HealthRankingEntry[] = boundaries.map(([overall_score, band], index) => ({
      ...rows[0]!,
      repository_id: `boundary-${index}`,
      name: `boundary-${index}`,
      overall_score,
      band,
    }));

    render(<RankingTable entries={boundaryRows} page={1} />);

    expect(screen.getByLabelText("Repository score 0.0/100")).toBeTruthy();
    expect(screen.getAllByLabelText("Repository score 60.0/100").length).toBe(2);
    expect(screen.getAllByLabelText("Repository score 80.0/100").length).toBe(2);
    expect(screen.getAllByLabelText("Repository score 90.0/100").length).toBe(2);
    expect(screen.getByLabelText("Repository score 100.0/100")).toBeTruthy();
    expect(screen.getByLabelText("Repository score unknown")).toBeTruthy();
    expect(screen.getAllByText("Excellent").length).toBe(2);
    expect(screen.getAllByText("Good").length).toBe(2);
    expect(screen.getAllByText("Fair").length).toBe(1);
    expect(screen.getAllByText("Weak").length).toBe(1);
    expect(screen.getAllByText("Critical").length).toBe(2);
    expect(screen.getAllByText("Unknown").length).toBe(1);
  });

  it("passes ranking scores to the shared trend chart on a 0–100 scale", () => {
    const trend: HealthRankingTrendResponse = {
      items: [
        {
          repository_id: "a",
          name: "alpha",
          points: [
            {
              snapshot_id: "s-0",
              score_config_digest: "same",
              overall_score: 0,
              band: "critical",
              grade: "F",
              status: "ready",
              analyzed_at: null,
            },
            {
              snapshot_id: "s-1",
              score_config_digest: "same",
              overall_score: 82.5,
              band: "good",
              grade: "B",
              status: "ready",
              analyzed_at: null,
            },
            {
              snapshot_id: "s-2",
              score_config_digest: "same",
              overall_score: null,
              band: "unknown",
              grade: "?",
              status: "inconclusive",
              analyzed_at: null,
            },
          ],
        },
      ],
      limit: 12,
      generated_at: "2026-09-10T12:00:00Z",
    };

    render(<RankingTrendChart entries={rows} trend={trend} />);

    expect(screen.getByRole("img", { name: "Health KPI trend (0–100)" })).toBeTruthy();
    expect(screen.getAllByText("100").length).toBeGreaterThan(0);
    expect(screen.queryByRole("img", { name: "Health KPI trend (0–10)" })).toBeNull();
  });
});
