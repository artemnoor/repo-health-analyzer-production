// @vitest-environment jsdom

import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CanonicalHealthReport } from "@repowise-dev/types/health";
import { CanonicalHealthSummary } from "./canonical-summary";

afterEach(cleanup);

const projection = {
  id: "projection-1",
  score_config_digest: "config-digest-123456",
  overall_score: 82.5,
  dimensions: { reliability: 82.5 },
  breakdown: [
    {
      dimension: "reliability",
      score: 82.5,
      analyzer_id: "analyzer-1",
      weight: 1,
      evidence_coverage: 0.9,
    },
  ],
  configured_weight: 1,
  available_weight: 0.9,
  confidence: 0.88,
  coverage: 0.9,
  evidence_coverage: 0.9,
  status: "warn",
  limitations: [{ reason: "One analyzer is partial", kind: "partial" }],
  score_recomputed: false,
};

function makeReport(options: {
  score?: number | null;
  scoreProjection?: CanonicalHealthReport["score_projection"];
  stale?: boolean;
  remediation?: string | null;
  status?: string;
} = {}): CanonicalHealthReport {
  return {
    schema_version: 1,
    repository_id: "repo-1",
    snapshot: {
      id: "snapshot-1",
      repository_id: "repo-1",
      head_sha: "abc123",
      analyzed_at: "2026-09-10T12:00:00Z",
      as_of_ts: "2026-09-10T12:00:00Z",
      config_digest: "config-1",
      analyzer_versions_digest: "analyzers-1",
      score_config_digest: "config-digest-123456",
      scope: "all",
      mode: "full",
      status: options.status ?? "warn",
      score: 9.1,
      confidence: 0.75,
      unknown_count: 1,
      error_count: 0,
      skipped_weight: 0.1,
      evidence_coverage: 0.8,
      criticality: 0.7,
      stale_after_ts: null,
      is_stale: options.stale ?? false,
      diagnostics: {},
    },
    score_projection:
      options.scoreProjection === undefined
        ? { ...projection, overall_score: options.score === undefined ? projection.overall_score : options.score }
        : options.scoreProjection,
    dimensions: [
      {
        dimension: "reliability",
        name: "Reliability",
        scope: "all",
        value: 0.82,
        score: 82.5,
        unknown_count: 1,
        error_count: 0,
        skipped_weight: 0.1,
        evidence_coverage: 0.9,
        criticality: 0.7,
        provenance: { count: 2 },
      },
    ],
    metrics: [],
    findings: [],
    recommendations: [
      {
        id: "finding-1",
        recommendation_id: "recommendation-1",
        finding_id: "finding-1",
        subject: "Reliability check",
        dimension: "reliability",
        status: "open",
        severity: "high",
        reason: "A reliability signal is incomplete.",
        remediation: options.remediation === undefined ? "Run the missing reliability analyzer." : options.remediation,
        location: { path: "src/health.py", line_start: 42 },
        priority: 0.8,
        lifecycle: "open",
        benefit: 0.8,
        confidence: 0.7,
        criticality: 0.7,
        effort: 0.2,
        risk: 0.1,
        blast_radius: 0.1,
        raw_impact: null,
        applied_impact: null,
        first_seen_at: null,
        last_seen_at: null,
        evidence: {
          count: 3,
          locations: [{ path: "src/health.py", line_start: 42, line_end: 45, json_pointer: null }],
          raw_refs: ["ref-1"],
        },
      },
    ],
    analyzers: [],
    coverage: {
      metric_count: 3,
      metric_evidence_count: 2,
      finding_count: 1,
      finding_evidence_count: 1,
      total_evidence_count: 3,
      covered_metrics: 2,
      evidence_coverage: 0.8,
      by_source: {},
    },
    limitations: [{ code: "partial", message: "One source is unavailable", affected: 1 }],
    criticality: {
      score: 0.7,
      applied_to_score: false,
      used_for_recommendation_priority: true,
    },
    meta: {
      read_model: "canonical_health",
      score_recomputed: false,
      include_evidence: false,
      filters: {},
      evidence_detail: "summary_only",
    },
  };
}

describe("CanonicalHealthSummary", () => {
  it("renders the canonical 0-100 score and actionable evidence", () => {
    const { container } = render(
      <CanonicalHealthSummary data={makeReport()} loadEvidence={vi.fn()} />,
    );

    expect(screen.getByText("82.5/100")).toBeTruthy();
    expect(screen.getByText("Run the missing reliability analyzer.")).toBeTruthy();
    expect(screen.getByText("Location: src/health.py:42")).toBeTruthy();
    expect(screen.getByText("Projection weight")).toBeTruthy();
    expect(screen.getByText("Priority context")).toBeTruthy();
    expect(screen.queryByText("82.5/10", { exact: true })).toBeNull();
  });

  it("keeps measured zero distinct from unavailable scores and never falls back to snapshot.score", () => {
    const { container, rerender } = render(
      <CanonicalHealthSummary data={makeReport({ score: 0 })} loadEvidence={vi.fn()} />,
    );
    expect(screen.getByText("0.0/100")).toBeTruthy();
    expect(screen.queryByText("Canonical score unavailable")).toBeNull();

    rerender(
      <CanonicalHealthSummary data={makeReport({ score: null })} loadEvidence={vi.fn()} />,
    );
    expect(screen.getByLabelText("Canonical repository score").textContent).toBe(
      "Canonical score unavailable",
    );
    expect(container.textContent).not.toContain("9.1/10");

    rerender(
      <CanonicalHealthSummary data={makeReport({ scoreProjection: null })} loadEvidence={vi.fn()} />,
    );
    expect(screen.getByRole("status", { name: "Canonical score unavailable" })).toBeTruthy();
    expect(container.textContent).not.toContain("9.1/10");
  });

  it("exposes stale, partial, error and remediation-unavailable states separately", () => {
    const { rerender } = render(
      <CanonicalHealthSummary data={makeReport({ stale: true })} loadEvidence={vi.fn()} />,
    );
    expect(screen.getByLabelText("Canonical projection state").textContent).toContain(
      "Stale canonical projection",
    );

    rerender(
      <CanonicalHealthSummary data={makeReport({ score: null })} loadEvidence={vi.fn()} />,
    );
    expect(screen.getByLabelText("Canonical projection state").textContent).toContain(
      "Partial canonical projection",
    );
    expect(screen.getByText(/One analyzer is partial/)).toBeTruthy();

    rerender(
      <CanonicalHealthSummary
        data={makeReport({ status: "error", scoreProjection: { ...projection, status: "error" } })}
        loadEvidence={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Canonical projection state").textContent).toContain(
      "Canonical projection error",
    );

    rerender(
      <CanonicalHealthSummary data={makeReport({ remediation: null })} loadEvidence={vi.fn()} />,
    );
    expect(screen.getByText("Remediation unavailable")).toBeTruthy();
    expect(screen.getByText(/evidence 3 · 1 location\(s\) · 1 raw ref\(s\)/)).toBeTruthy();
  });
});
