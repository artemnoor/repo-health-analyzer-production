import * as React from "react";
import type { HealthRankingEntry } from "@repowise-dev/types/health-ranking";
import type { HealthRankingTrendResponse } from "@repowise-dev/types/health-ranking";
import { TrendChart } from "@repowise-dev/ui/health/trend-chart";

export function RankingTrendChart({
  entries,
  trend,
}: {
  entries: HealthRankingEntry[];
  trend?: HealthRankingTrendResponse;
}) {
  if (trend && trend.items.length > 0) {
    return (
      <div className="space-y-8">
        {trend.items.slice(0, 3).map((series) => {
          const digests = new Set(series.points.map((point) => point.score_config_digest));
          return (
            <section key={series.repository_id} className="border-t border-[var(--color-border-default)] pt-4 first:border-t-0 first:pt-0">
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-[var(--color-text-primary)]">{series.name}</h3>
                {digests.size > 1 && (
                  <span className="text-xs text-[var(--color-warning)]">score policy changed in this history</span>
                )}
              </div>
              <TrendChart
                history={series.points.filter((point) => point.overall_score != null).map((point) => ({
                  taken_at: point.analyzed_at,
                  average_health: point.overall_score as number,
                  hotspot_health: null,
                  worst_performer_score: null,
                }))}
                scoreScale={100}
              />
            </section>
          );
        })}
        {trend.items.length > 3 && (
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Showing trend history for the first three visible repositories; use compare for a focused view.
          </p>
        )}
      </div>
    );
  }

  const movers = entries
    .filter((entry) => entry.score_delta != null)
    .sort((a, b) => Math.abs(b.score_delta ?? 0) - Math.abs(a.score_delta ?? 0))
    .slice(0, 8);
  const max = Math.max(1, ...movers.map((entry) => Math.abs(entry.score_delta ?? 0)));

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">Recent score movement</h3>
        <span className="text-xs text-[var(--color-text-tertiary)]">vs previous published snapshot</span>
      </div>
      {movers.length === 0 ? (
        <p className="text-sm text-[var(--color-text-secondary)]">No comparable previous snapshot is available yet.</p>
      ) : (
        <div className="space-y-2.5">
          {movers.map((entry) => {
            const delta = entry.score_delta ?? 0;
            const width = (Math.abs(delta) / max) * 100;
            const positive = delta > 0;
            return (
              <div key={entry.repository_id} className="grid grid-cols-[minmax(0,150px)_minmax(0,1fr)_55px] items-center gap-3 text-xs">
                <span className="truncate text-[var(--color-text-secondary)]">{entry.name}</span>
                <div className="flex h-2 items-center bg-[var(--color-bg-inset)]">
                  <div
                    className={`h-2 rounded-full ${positive ? "bg-[var(--color-success)]" : "bg-[var(--color-error)]"}`}
                    style={{ width: `${width}%` }}
                  />
                </div>
                <span className={`text-right tabular-nums ${positive ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}>
                  {positive ? "+" : ""}{delta.toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
