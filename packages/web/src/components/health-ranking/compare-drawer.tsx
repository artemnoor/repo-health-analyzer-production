"use client";

import * as React from "react";
import Link from "next/link";
import { X } from "lucide-react";
import useSWR from "swr";
import type { HealthRankingCompareResponse } from "@repowise-dev/types/health-ranking";
import { compareHealthRanking } from "@/lib/api/health-ranking";
import { Button } from "@repowise-dev/ui/ui/button";
import { EntryDimensionBars } from "./score-breakdown";

export function CompareDrawer({
  repositoryIds,
  onClose,
}: {
  repositoryIds: string[];
  onClose: () => void;
}) {
  const { data, error, isLoading } = useSWR<HealthRankingCompareResponse>(
    repositoryIds.length > 0 ? ["health-ranking-compare", repositoryIds.join(",")] : null,
    () => compareHealthRanking(repositoryIds),
    { revalidateOnFocus: false },
  );

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[520px] flex-col border-l border-[var(--color-border-default)] bg-[var(--color-bg-surface)] shadow-2xl"
      aria-label="Repository comparison"
    >
      <div className="flex items-center justify-between gap-4 border-b border-[var(--color-border-default)] px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Compare repositories</h2>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">Same score policy · up to four public rows</p>
        </div>
        <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Close comparison">
          <X aria-hidden />
        </Button>
      </div>
      <div className="flex-1 overflow-auto px-5 py-5">
        {isLoading ? <p className="text-sm text-[var(--color-text-secondary)]">Loading comparison…</p> : null}
        {error ? <p className="text-sm text-[var(--color-error)]">Comparison is unavailable right now.</p> : null}
        {data && data.score_config_digests.length > 1 ? (
          <p className="mb-4 text-xs text-[var(--color-warning)]">These rows use different score configurations; compare dimensions carefully.</p>
        ) : null}
        {data?.truncated ? <p className="mb-4 text-xs text-[var(--color-warning)]">Only the first four selected repositories are shown.</p> : null}
        <div className="space-y-7">
          {data?.items.map((entry) => (
            <section key={entry.repository_id} className="border-t border-[var(--color-border-default)] pt-4 first:border-t-0 first:pt-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link href={`/repos/${encodeURIComponent(entry.repository_id)}/code-health`} className="font-medium text-[var(--color-text-primary)] hover:text-[var(--color-accent-primary)]">
                    {entry.name}
                  </Link>
                  <p className="mt-1 text-xs text-[var(--color-text-tertiary)]">{entry.status} · {entry.grade}</p>
                </div>
                <span className="text-2xl font-semibold tabular-nums text-[var(--color-text-primary)]">
                  {entry.overall_score == null ? "—" : entry.overall_score.toFixed(1)}
                </span>
              </div>
              <div className="mt-4"><EntryDimensionBars entry={entry} /></div>
            </section>
          ))}
        </div>
      </div>
    </aside>
  );
}
