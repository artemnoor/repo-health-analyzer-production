import * as React from "react";
import type { HealthRankingEntry } from "@repowise-dev/types/health-ranking";
import {
  rankingHealthBandColor,
  rankingHealthBandForEntry,
  rankingHealthBandLabel,
} from "@repowise-dev/ui/health/ranking-tokens";

const DIMENSION_LABELS: Record<string, string> = {
  code: "Code quality",
  history: "Git history",
  tests: "Tests",
  dependencies: "Dependencies",
  security: "Security",
  delivery: "Delivery",
  community: "Community",
  docs: "Documentation",
};

export function ScoreBreakdown({ entries }: { entries: HealthRankingEntry[] }) {
  const dimensions = Array.from(
    new Set(entries.flatMap((entry) => Object.keys(entry.dimensions))),
  ).sort();
  const distribution = (["excellent", "good", "fair", "weak", "critical", "unknown"] as const).map((band) => ({
    label: rankingHealthBandLabel(band),
    key: band,
    count: entries.filter((entry) => rankingHealthBandForEntry(entry.band, entry.overall_score) === band).length,
    color: rankingHealthBandColor(band),
  }));
  const maxCount = Math.max(1, ...distribution.map((item) => item.count));

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
      <div>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">Score distribution</h3>
          <span className="text-xs text-[var(--color-text-tertiary)]">{entries.length} visible</span>
        </div>
        <div className="space-y-2.5">
          {distribution.map((item) => (
            <div key={item.key} className="grid grid-cols-[110px_minmax(0,1fr)_32px] items-center gap-2 text-xs">
              <span className="text-[var(--color-text-secondary)]">{item.label}</span>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--color-bg-inset)]">
                <div className="h-full rounded-full" style={{ width: `${(item.count / maxCount) * 100}%`, background: item.color }} />
              </div>
              <span className="text-right tabular-nums text-[var(--color-text-tertiary)]">{item.count}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">Dimension coverage</h3>
          <span className="text-xs text-[var(--color-text-tertiary)]">health only · criticality excluded</span>
        </div>
        {dimensions.length === 0 ? (
          <p className="text-sm text-[var(--color-text-secondary)]">No dimension measurements are available for these rows.</p>
        ) : (
          <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {dimensions.map((dimension) => {
              const measured = entries.filter((entry) => entry.dimensions[dimension] != null).length;
              const ratio = entries.length === 0 ? 0 : measured / entries.length;
              const averageValues = entries
                .map((entry) => entry.dimensions[dimension])
                .filter((value): value is number => value != null);
              const average = averageValues.length > 0
                ? averageValues.reduce((sum, value) => sum + value, 0) / averageValues.length
                : null;
              return (
                <div key={dimension} className="border-t border-[var(--color-border-default)] pt-2">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="font-medium text-[var(--color-text-primary)]">{DIMENSION_LABELS[dimension] ?? dimension}</span>
                    <span className="tabular-nums text-[var(--color-text-tertiary)]">{average == null ? "—" : `${average.toFixed(1)}/100`}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--color-bg-inset)]" title={`${measured} of ${entries.length} rows measured`}>
                    <div className="h-full bg-[var(--color-accent-secondary)]" style={{ width: `${ratio * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export function EntryDimensionBars({ entry }: { entry: HealthRankingEntry }) {
  const dimensions = Object.entries(entry.dimensions).sort(([a], [b]) => a.localeCompare(b));
  if (dimensions.length === 0) {
    return <span className="text-xs text-[var(--color-text-tertiary)]">No dimension data</span>;
  }
  return (
    <div className="space-y-2">
      {dimensions.map(([dimension, value]) => (
        <div key={dimension} className="grid grid-cols-[120px_minmax(0,1fr)_45px] items-center gap-2 text-xs">
          <span className="truncate text-[var(--color-text-secondary)]">{DIMENSION_LABELS[dimension] ?? dimension}</span>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--color-bg-inset)]">
            <div
              className="h-full"
              style={{
                width: `${Math.max(0, Math.min(100, value ?? 0))}%`,
                background: rankingHealthBandColor(rankingHealthBandForEntry(undefined, value)),
              }}
            />
          </div>
          <span className="text-right tabular-nums text-[var(--color-text-tertiary)]">{value == null ? "—" : value.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}

export { DIMENSION_LABELS };
