"use client";

import { useState } from "react";
import * as React from "react";
import { AlertTriangle, CheckCircle2, CircleHelp, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@repowise-dev/ui/ui/card";
import type { CanonicalHealthReport } from "@repowise-dev/types/health";
import { SIGILS_HEALTH_PANELS } from "@/lib/health-panels/sigils";

function pct(value: number): string {
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : "—";
}

function score(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "—";
}

function priority(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "—";
}

function shortDigest(value: string | undefined): string {
  return value ? value.slice(0, 12) : "—";
}

function safeLocation(location: Record<string, unknown>): string | null {
  const path = typeof location.path === "string" ? location.path : null;
  const line = typeof location.line_start === "number" && Number.isFinite(location.line_start)
    ? location.line_start
    : null;
  if (path) return line == null ? path : `${path}:${line}`;
  return line == null ? null : `line ${line}`;
}

function projectionState(
  report: CanonicalHealthReport,
): "ready" | "stale" | "partial" | "unavailable" | "error" {
  const projection = report.score_projection;
  if (!projection) return "unavailable";
  if (projection.status === "error" || projection.status === "fail") return "error";
  if (report.snapshot.is_stale) return "stale";
  if (
    projection.overall_score == null ||
    projection.status === "warn" ||
    projection.status === "inconclusive" ||
    projection.status === "skipped"
  ) {
    return "partial";
  }
  return "ready";
}

function projectionStateLabel(state: ReturnType<typeof projectionState>): string {
  if (state === "stale") return "Stale canonical projection";
  if (state === "partial") return "Partial canonical projection";
  if (state === "error") return "Canonical projection error";
  if (state === "unavailable") return "Canonical score unavailable";
  return "Canonical projection ready";
}

function statusIcon(status: string) {
  if (status === "pass") return <CheckCircle2 className="h-4 w-4 text-[var(--color-success)]" aria-hidden />;
  if (status === "error" || status === "fail") return <AlertTriangle className="h-4 w-4 text-[var(--color-danger)]" aria-hidden />;
  return <CircleHelp className="h-4 w-4 text-[var(--color-warning)]" aria-hidden />;
}

export function CanonicalHealthSummary({
  data,
  loadEvidence,
}: {
  data?: CanonicalHealthReport;
  loadEvidence: () => Promise<CanonicalHealthReport>;
}) {
  const [detailed, setDetailed] = useState<CanonicalHealthReport>();
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const report = detailed ?? data;

  if (!report) return null;

  const snapshot = report.snapshot;
  const projection = report.score_projection;
  const canonicalScore = projection?.overall_score ?? null;
  const state = projectionState(report);
  const findings = report.recommendations.slice(0, 5);
  const loadFullEvidence = async () => {
    if (detailed || loadingEvidence) return;
    setLoadingEvidence(true);
    try {
      setDetailed(await loadEvidence());
    } finally {
      setLoadingEvidence(false);
    }
  };

  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-[var(--color-accent-primary)]" aria-hidden />
            <CardTitle className="text-sm">Persisted health evidence</CardTitle>
          </div>
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
            {statusIcon(snapshot.status)}
            <span className="capitalize">{snapshot.status}</span>
            <span>·</span>
            <span aria-label="Canonical repository score">
              {canonicalScore == null ? "Canonical score unavailable" : `${score(canonicalScore)}/100`}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--color-text-tertiary)]">
          <span aria-label="Canonical projection state">{projectionStateLabel(state)}</span>
          {projection ? <span>projection status {projection.status}</span> : null}
          <span>Read model: {snapshot.id.slice(0, 8)}</span>
        </div>
        <p className="text-xs text-[var(--color-text-tertiary)]">
          confidence {pct(snapshot.confidence)} · scope {snapshot.scope}
          {snapshot.is_stale ? " · stale snapshot" : ""}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-4">
          <Stat label="Evidence" value={pct(snapshot.evidence_coverage)} />
          <Stat label="Metrics" value={String(report.coverage.metric_count)} />
          <Stat label="Risks" value={String(report.recommendations.length)} />
          <Stat label="Priority context" value={pct(report.criticality.score)} />
        </div>

        {projection ? (
          <div className="grid gap-2 sm:grid-cols-3">
            <Stat
              label="Projection weight"
              value={`${score(projection.available_weight)} / ${score(projection.configured_weight)}`}
            />
            <Stat label="Score coverage" value={pct(projection.coverage)} />
            <Stat label="Evidence coverage" value={pct(projection.evidence_coverage)} />
            <Stat label="Projection confidence" value={pct(projection.confidence)} />
            <Stat label="Score config" value={shortDigest(projection.score_config_digest)} />
            <Stat label="Recomputed" value={projection.score_recomputed ? "yes" : "no"} />
          </div>
        ) : (
          <div
            role="status"
            aria-label="Canonical score unavailable"
            className="rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-3 py-2 text-xs text-[var(--color-text-secondary)]"
          >
            Canonical score unavailable. This read model does not contain a persisted 0–100 projection.
          </div>
        )}

        {projection?.breakdown?.length ? (
          <div>
            <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">
              Canonical score breakdown
            </p>
            <div className="grid gap-2 sm:grid-cols-3">
              {projection.breakdown.map((item, index) => (
                <div
                  key={`${item.dimension}:${item.analyzer_id ?? index}`}
                  className="rounded-md border border-[var(--color-border-default)] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-[var(--color-text-secondary)]">{item.dimension}</span>
                    <span className="font-mono tabular-nums text-[var(--color-text-primary)]">
                      {score(item.score)}
                    </span>
                  </div>
                  <div className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
                    weight {item.weight == null ? "—" : score(item.weight)} · evidence {item.evidence_coverage == null ? "—" : pct(item.evidence_coverage)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {report.dimensions.length > 0 ? (
          <div>
            <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">
              Dimensions
            </p>
            <div className="grid gap-2 sm:grid-cols-3">
              {report.dimensions.map((dimension) => (
                <div key={`${dimension.dimension}:${dimension.name}`} className="rounded-md border border-[var(--color-border-default)] px-3 py-2">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-[var(--color-text-secondary)]">{dimension.dimension}</span>
                    <span className="font-mono tabular-nums text-[var(--color-text-primary)]">
                      {dimension.score == null ? "?" : dimension.score.toFixed(1)}
                    </span>
                  </div>
                  <div className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
                    evidence {pct(dimension.evidence_coverage)} · unknown {dimension.unknown_count} · errors {dimension.error_count}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {findings.length > 0 ? (
          <div>
            <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">
              Top risks and recommendations
            </p>
            <div className="space-y-1.5">
              {findings.map((finding) => (
                <details key={finding.recommendation_id} className="rounded-md border border-[var(--color-border-default)] px-3 py-2">
                  <summary className="cursor-pointer list-none text-xs text-[var(--color-text-primary)]">
                    <span className="mr-2 uppercase text-[10px] text-[var(--color-text-tertiary)]">{finding.severity}</span>
                    {finding.subject} <span className="text-[var(--color-text-tertiary)]">· priority {finding.priority.toFixed(2)}</span>
                  </summary>
                  <p className="mt-2 text-xs text-[var(--color-text-secondary)]">{finding.reason}</p>
                  <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
                    <span className="font-medium text-[var(--color-text-primary)]">Remediation:</span>{" "}
                    {finding.remediation ?? "Remediation unavailable"}
                  </p>
                  {safeLocation(finding.location) ? (
                    <p className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
                      Location: {safeLocation(finding.location)}
                    </p>
                  ) : null}
                  <p className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
                    evidence {finding.evidence.count} · {finding.evidence.locations.length} location(s) · {finding.evidence.raw_refs.length} raw ref(s)
                  </p>
                  {detailed ? (
                    <div className="mt-2 space-y-1 border-t border-[var(--color-border-default)] pt-2 text-[10px] text-[var(--color-text-tertiary)]">
                      {(finding.evidence.refs ?? []).map((ref, index) => (
                        <div key={`${ref.raw_ref ?? ref.source}:${index}`}>
                          {ref.source} · {ref.path ?? "no path"}
                          {ref.line_start != null ? `:${ref.line_start}` : ""}
                          {ref.raw_ref ? ` · ${ref.raw_ref}` : ""}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </details>
              ))}
            </div>
            <button
              type="button"
              onClick={loadFullEvidence}
              disabled={loadingEvidence || Boolean(detailed)}
              className="mt-2 text-[10px] uppercase tracking-[0.12em] text-[var(--color-accent-primary)] disabled:opacity-50"
            >
              {detailed ? "Evidence details loaded" : loadingEvidence ? "Loading evidence…" : "Load evidence details"}
            </button>
          </div>
        ) : null}

        {report.limitations.length > 0 ? (
          <div className="rounded-md bg-[var(--color-bg-elevated)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
            {report.limitations.map((limitation) => (
              <div key={limitation.code}>• {limitation.message}</div>
            ))}
            {projection?.limitations.map((limitation, index) => (
              <div key={`${limitation.kind}:${index}`}>• {limitation.kind}: {limitation.reason}</div>
            ))}
          </div>
        ) : projection?.limitations.length ? (
          <div className="rounded-md bg-[var(--color-bg-elevated)] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
            {projection.limitations.map((limitation, index) => (
              <div key={`${limitation.kind}:${index}`}>• {limitation.kind}: {limitation.reason}</div>
            ))}
          </div>
        ) : null}

        <details className="border-t border-[var(--color-border-default)] pt-3">
          <summary className="cursor-pointer text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">
            Reused community signal recipes ({SIGILS_HEALTH_PANELS.length})
          </summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {SIGILS_HEALTH_PANELS.slice(0, 6).map((panel) => (
              <div key={panel.id} className="rounded-md border border-[var(--color-border-default)] px-3 py-2">
                <div className="text-xs text-[var(--color-text-primary)]">{panel.title}</div>
                <div className="mt-1 text-[10px] text-[var(--color-text-tertiary)]">
                  {panel.source} · {panel.measures.join(" · ")}
                </div>
              </div>
            ))}
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-[var(--color-bg-elevated)] px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">{label}</div>
      <div className="mt-1 font-mono text-sm tabular-nums text-[var(--color-text-primary)]">{value}</div>
    </div>
  );
}
