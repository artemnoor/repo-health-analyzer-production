"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { ArrowLeft, ChevronLeft, ChevronRight, Trophy } from "lucide-react";
import { PageShell } from "@repowise-dev/ui/shared/page-shell";
import { PageLede, LedeLink } from "@repowise-dev/ui/shared/page-lede";
import { OverviewSection, SectionLink } from "@repowise-dev/ui/overview";
import { StatRibbon, type RibbonStat } from "@repowise-dev/ui/stats/stat-ribbon";
import { Button } from "@repowise-dev/ui/ui/button";
import { formatNumber } from "@repowise-dev/ui/lib/format";
import type {
  HealthRankingResponse,
  HealthRankingTrendResponse,
} from "@repowise-dev/types/health-ranking";
import { getHealthRanking, getHealthRankingTrend } from "@/lib/api/health-ranking";
import {
  RankingFilters,
  RankingStatus,
  RankingTable,
  RankingTrendChart,
  ScoreBreakdown,
  CompareDrawer,
  rankingFiltersFromSearch,
  rankingQueryForFilters,
  type RankingFilterState,
} from ".";

const DIMENSIONS = [
  "code",
  "history",
  "tests",
  "dependencies",
  "security",
  "delivery",
  "community",
  "docs",
];

export function rankingFacetValues(
  data: Pick<HealthRankingResponse, "items" | "facets"> | undefined,
): { dimensions: string[]; languages: string[]; statuses: string[] } {
  if (data?.facets) return data.facets;
  const items = data?.items ?? [];
  return {
    dimensions: DIMENSIONS,
    languages: Array.from(new Set(items.flatMap((entry) => entry.languages))).sort(),
    statuses: Array.from(new Set(items.map((entry) => entry.status))).sort(),
  };
}

export function RankingPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const filters = React.useMemo(() => rankingFiltersFromSearch(search), [search]);
  const query = React.useMemo(() => rankingQueryForFilters(filters), [filters]);
  const { data, error, isLoading, mutate } = useSWR<HealthRankingResponse>(
    ["public-health-ranking", JSON.stringify(query)],
    () => getHealthRanking(query),
    { keepPreviousData: true, revalidateOnFocus: false },
  );
  const trendIds = React.useMemo(
    () => (data?.items ?? []).slice(0, 8).map((entry) => entry.repository_id),
    [data?.items],
  );
  const { data: trend } = useSWR<HealthRankingTrendResponse>(
    trendIds.length > 0 ? ["public-health-ranking-trend", trendIds.join(",")] : null,
    () => getHealthRankingTrend(trendIds, 12),
    { revalidateOnFocus: false, keepPreviousData: true },
  );
  const [selectedIds, setSelectedIds] = React.useState<string[]>([]);
  const [compareOpen, setCompareOpen] = React.useState(false);

  const updateFilters = React.useCallback(
    (next: Partial<RankingFilterState>) => {
      const merged = { ...filters, ...next };
      const params = new URLSearchParams(search);
      const setOrDelete = (name: string, value: string, defaultValue = "") => {
        if (value && value !== defaultValue) params.set(name, value);
        else params.delete(name);
      };
      setOrDelete("band", merged.band);
      setOrDelete("dimension", merged.dimension);
      setOrDelete("language", merged.language);
      setOrDelete("status", merged.status);
      if (merged.freshness === "all") params.delete("stale");
      else params.set("stale", merged.freshness === "stale" ? "true" : "false");
      if (merged.eligibility === "all") params.set("include_ineligible", "true");
      else params.delete("include_ineligible");
      if (merged.page > 1) params.set("page", String(merged.page));
      else params.delete("page");
      const nextSearch = params.toString();
      router.replace(nextSearch ? `${pathname}?${nextSearch}` : pathname, { scroll: false });
    },
    [filters, pathname, router, search],
  );

  const resetFilters = React.useCallback(() => {
    router.replace(pathname, { scroll: false });
    setSelectedIds([]);
    setCompareOpen(false);
  }, [pathname, router]);

  const toggleCompare = React.useCallback((repositoryId: string) => {
    setSelectedIds((current) => {
      if (current.includes(repositoryId)) return current.filter((id) => id !== repositoryId);
      if (current.length >= 4) return current;
      return [...current, repositoryId];
    });
  }, []);

  const items = data?.items ?? [];
  const average = averageScore(items);
  const staleCount = items.filter((entry) => entry.stale).length;
  const measuredCount = items.filter((entry) => entry.overall_score != null).length;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.limit)) : 1;
  const showLoading = isLoading && !data;
  const facets = rankingFacetValues(data);

  const ribbon: RibbonStat[] = [
    { label: "Public rows", value: data ? formatNumber(data.total) : "—", sub: "eligible by default" },
    { label: "Visible", value: data ? formatNumber(items.length) : "—", sub: "after current filters" },
    { label: "Average score", value: average == null ? "—" : average.toFixed(1), sub: "out of 100" },
    { label: "Measured", value: data ? `${measuredCount}/${items.length}` : "—", sub: "visible rows with a score" },
    { label: "Stale", value: data ? formatNumber(staleCount) : "—", sub: "shown, never hidden as healthy" },
  ];

  return (
    <PageShell
      title="Repository ranking"
      icon={<Trophy className="h-5 w-5 text-[var(--color-accent-primary)]" />}
      description="A public, explainable view of repository health. Scores are comparable only when their score policy and evidence quality are visible."
      actions={
        <Link href="/" className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-accent-primary)] hover:underline">
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Dashboard
        </Link>
      }
      maxWidth="wide"
    >
      <PageLede
        label="Average health score"
        value={average == null ? "—" : average.toFixed(1)}
        unit="out of 100"
        layout="beside"
        action={<LedeLink href="#ranking-table">Read the ranking</LedeLink>}
      >
        <p>
          The default list includes public repositories with a completed, fresh enough analysis
          and sufficient evidence. An em dash means the score is not measured; it is never a
          zero disguised as a successful analysis.
        </p>
        <p>
          Health dimensions are separate from repository criticality. A widely depended-on
          repository is not automatically healthier, and a small project is not penalized for
          having less community activity.
        </p>
      </PageLede>

      <StatRibbon stats={ribbon} />

      <OverviewSection
        title="Find a repository"
        description="Filters are encoded in the URL, so a view can be shared without losing its ranking policy."
      >
        <RankingFilters
          value={filters}
          dimensions={facets.dimensions}
          languages={facets.languages}
          statuses={facets.statuses}
          onChange={(next) => updateFilters({ ...next, page: 1 })}
          onReset={resetFilters}
        />
      </OverviewSection>

      <OverviewSection
        id="ranking-table"
        title="Public repository health"
        description="Ranked by score, then evidence coverage, freshness and stable repository identity. Select up to four rows to compare their dimension breakdowns."
        action={
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={selectedIds.length === 0}
            onClick={() => setCompareOpen(true)}
          >
            Compare{selectedIds.length > 0 ? ` (${selectedIds.length})` : ""}
          </Button>
        }
      >
        {showLoading ? (
          <RankingStatus state="loading" />
        ) : error && !data ? (
          <RankingStatus state="error" onRetry={() => void mutate()} />
        ) : items.length === 0 ? (
          <RankingStatus state="empty" total={data?.total ?? 0} />
        ) : (
          <>
            {error && (
              <p className="mb-3 text-xs text-[var(--color-warning)]" role="status">
                Showing the last available ranking while the latest refresh is unavailable.
              </p>
            )}
            <RankingTable
              entries={items}
              page={filters.page}
              pageSize={data?.limit ?? 50}
              selectedIds={selectedIds}
              onToggleCompare={toggleCompare}
            />
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-[var(--color-text-tertiary)]">
              <span>Page {filters.page} of {totalPages} · {formatNumber(data?.total ?? items.length)} repositories</span>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label="Previous ranking page"
                  disabled={filters.page <= 1}
                  onClick={() => updateFilters({ page: Math.max(1, filters.page - 1) })}
                >
                  <ChevronLeft aria-hidden />
                </Button>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label="Next ranking page"
                  disabled={filters.page >= totalPages}
                  onClick={() => updateFilters({ page: Math.min(totalPages, filters.page + 1) })}
                >
                  <ChevronRight aria-hidden />
                </Button>
              </div>
            </div>
          </>
        )}
      </OverviewSection>

      <OverviewSection
        title="What shapes the score"
        description="The composite score is the weighted result of available health dimensions. Missing data is visible and does not get confused with a measured failure."
        action={<SectionLink href="#ranking-table">Back to rows</SectionLink>}
      >
        <ScoreBreakdown entries={items} />
      </OverviewSection>

      <OverviewSection
        title="Recent movement"
        description="A score delta is calculated against the previous published snapshot for the same repository. It is a change signal, not a historical score series."
      >
        <RankingTrendChart entries={items} trend={trend} />
      </OverviewSection>

      {compareOpen && selectedIds.length > 0 && (
        <CompareDrawer repositoryIds={selectedIds} onClose={() => setCompareOpen(false)} />
      )}
    </PageShell>
  );
}

function averageScore(entries: HealthRankingResponse["items"]): number | null {
  const scores = entries
    .map((entry) => entry.overall_score)
    .filter((score): score is number => score != null);
  if (scores.length === 0) return null;
  return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}
