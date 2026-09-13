import * as React from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Minus, ShieldAlert } from "lucide-react";
import type { HealthRankingEntry } from "@repowise-dev/types/health-ranking";
import { formatDateTime } from "@repowise-dev/ui/lib/format";
import {
  rankingHealthBandColor,
  rankingHealthBandForEntry,
  rankingHealthBandLabel,
} from "@repowise-dev/ui/health/ranking-tokens";

function scoreColor(score: number | null, band: string | undefined): string {
  return rankingHealthBandColor(rankingHealthBandForEntry(band, score));
}

function percentage(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function rankingDelta(delta: number | null) {
  if (delta == null || Math.abs(delta) < 0.005) {
    return <Minus className="h-3.5 w-3.5 text-[var(--color-text-tertiary)]" aria-label="No score change" />;
  }
  const positive = delta > 0;
  const Icon = positive ? ArrowUp : ArrowDown;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-xs tabular-nums ${positive ? "text-[var(--color-success)]" : "text-[var(--color-error)]"}`}
      title={`${positive ? "Improved" : "Declined"} by ${Math.abs(delta).toFixed(2)} points`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {Math.abs(delta).toFixed(2)}
    </span>
  );
}

export function RankingTable({
  entries,
  page,
  pageSize = 50,
  onToggleCompare,
  selectedIds,
}: {
  entries: HealthRankingEntry[];
  page: number;
  pageSize?: number;
  selectedIds?: string[];
  onToggleCompare?: (repositoryId: string) => void;
}) {
  const selectable = Boolean(onToggleCompare);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-left">
        <caption className="sr-only">Public repository health ranking</caption>
        <thead>
          <tr className="border-y border-[var(--color-border-default)] text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">
            {selectable && <th scope="col" className="w-10 px-2 py-3"><span className="sr-only">Compare</span></th>}
            <th scope="col" className="w-14 px-2 py-3 text-right">Rank</th>
            <th scope="col" className="px-3 py-3">Repository</th>
            <th scope="col" className="w-28 px-3 py-3 text-right">Score</th>
            <th scope="col" className="w-20 px-3 py-3">Grade</th>
            <th scope="col" className="w-32 px-3 py-3">Status</th>
            <th scope="col" className="w-28 px-3 py-3">Coverage</th>
            <th scope="col" className="w-28 px-3 py-3">Evidence</th>
            <th scope="col" className="w-28 px-3 py-3">Confidence</th>
            <th scope="col" className="w-32 px-3 py-3">Last analysis</th>
            <th scope="col" className="w-24 px-3 py-3 text-right">Change</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border-default)]">
          {entries.map((entry, index) => {
            const score = entry.overall_score;
            const band = rankingHealthBandForEntry(entry.band, score);
            const stale = entry.stale;
            const selected = selectedIds?.includes(entry.repository_id) ?? false;
            return (
              <tr key={entry.repository_id} className="group hover:bg-[var(--color-bg-wash-hover)]">
                {selectable && (
                  <td className="px-2 py-3.5 align-top">
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => onToggleCompare?.(entry.repository_id)}
                      aria-label={`Compare ${entry.name}`}
                      className="mt-1 h-4 w-4 accent-[var(--color-accent-primary)]"
                    />
                  </td>
                )}
                <td className="px-2 py-3.5 text-right align-top font-mono text-xs tabular-nums text-[var(--color-text-tertiary)]">
                  {(page - 1) * pageSize + index + 1}
                </td>
                <td className="px-3 py-3.5 align-top">
                  <Link
                    href={`/repos/${encodeURIComponent(entry.repository_id)}/code-health`}
                    className="font-medium text-[var(--color-text-primary)] no-underline transition-colors hover:text-[var(--color-accent-primary)]"
                  >
                    {entry.name}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--color-text-tertiary)]">
                    <span>{entry.languages.length > 0 ? entry.languages.slice(0, 3).join(" · ") : "Language unknown"}</span>
                    {entry.languages.length > 3 && <span>+{entry.languages.length - 3}</span>}
                    {stale && (
                      <span className="inline-flex items-center gap-1 text-[var(--color-warning)]">
                        <ShieldAlert className="h-3 w-3" aria-hidden /> stale
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-3.5 text-right align-top">
                  <span
                    className="text-xl font-semibold tabular-nums"
                    style={{ color: scoreColor(score, entry.band) }}
                    aria-label={`Repository score ${score == null ? "unknown" : `${score.toFixed(1)}/100`}`}
                  >
                    {score == null ? "—" : score.toFixed(1)}
                  </span>
                  <span className="ml-1 text-xs text-[var(--color-text-tertiary)]">/100</span>
                  <span className="mt-1 block text-[10px] text-[var(--color-text-tertiary)]">
                    {rankingHealthBandLabel(band)}
                  </span>
                </td>
                <td className="px-3 py-3.5 align-top">
                  <span className="font-semibold text-[var(--color-text-primary)]">{entry.grade}</span>
                </td>
                <td className="px-3 py-3.5 align-top">
                  <span className="text-xs text-[var(--color-text-secondary)]">{entry.status}</span>
                  {!entry.eligible && entry.eligibility_reason && (
                    <span className="mt-1 block text-[11px] text-[var(--color-warning)]">
                      {entry.eligibility_reason}
                    </span>
                  )}
                </td>
                <td className="px-3 py-3.5 align-top">
                  <MetricBar value={entry.coverage} label="Analyzer coverage" />
                </td>
                <td className="px-3 py-3.5 align-top">
                  <MetricBar value={entry.evidence_coverage} label="Evidence coverage" />
                </td>
                <td className="px-3 py-3.5 align-top">
                  <MetricBar value={entry.confidence} label="Confidence" />
                </td>
                <td className="px-3 py-3.5 align-top text-xs text-[var(--color-text-secondary)]">
                  {entry.analyzed_at ? (
                    <time dateTime={entry.analyzed_at} title={formatDateTime(entry.analyzed_at)}>
                      {formatDateTime(entry.analyzed_at)}
                    </time>
                  ) : "—"}
                </td>
                <td className="px-3 py-3.5 text-right align-top">{rankingDelta(entry.score_delta)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MetricBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="min-w-[90px]" title={`${label}: ${percentage(value)}`}>
      <div className="mb-1 text-xs tabular-nums text-[var(--color-text-secondary)]">{percentage(value)}</div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-bg-inset)]">
        <div
          className="h-full bg-[var(--color-accent-secondary)]"
          style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        />
      </div>
    </div>
  );
}
