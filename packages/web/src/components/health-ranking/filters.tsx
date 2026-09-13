"use client";

import * as React from "react";
import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { Button } from "@repowise-dev/ui/ui/button";
import {
  HEALTH_RANKING_BAND_LABELS,
  type HealthRankingBand,
} from "@repowise-dev/types/health-ranking";

export interface RankingFilterState {
  page: number;
  band: string;
  dimension: string;
  language: string;
  status: string;
  freshness: "all" | "fresh" | "stale";
  eligibility: "eligible" | "all";
}

export const DEFAULT_RANKING_FILTERS: RankingFilterState = {
  page: 1,
  band: "",
  dimension: "",
  language: "",
  status: "",
  freshness: "all",
  eligibility: "eligible",
};

const RANKING_BANDS: readonly HealthRankingBand[] = [
  "excellent",
  "good",
  "fair",
  "weak",
  "critical",
  "unknown",
];

function rankingBand(value: string): HealthRankingBand | undefined {
  return (RANKING_BANDS as readonly string[]).includes(value)
    ? (value as HealthRankingBand)
    : undefined;
}

export function rankingFiltersFromSearch(search: string): RankingFilterState {
  const params = new URLSearchParams(search);
  const freshness = params.get("stale");
  return {
    page: Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1),
    band: params.get("band") ?? "",
    dimension: params.get("dimension") ?? "",
    language: params.get("language") ?? "",
    status: params.get("status") ?? "",
    freshness: freshness === "true" ? "stale" : freshness === "false" ? "fresh" : "all",
    eligibility: params.get("include_ineligible") === "true" ? "all" : "eligible",
  };
}

export function rankingQueryForFilters(filters: RankingFilterState) {
  const band = rankingBand(filters.band);
  return {
    page: filters.page,
    limit: 50,
    ...(band ? { band } : {}),
    ...(filters.dimension ? { dimension: filters.dimension } : {}),
    ...(filters.language ? { language: filters.language } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.freshness === "stale" ? { stale: true } : {}),
    ...(filters.freshness === "fresh" ? { stale: false } : {}),
    ...(filters.eligibility === "all" ? { include_ineligible: true } : {}),
  } as const;
}

export function RankingFilters({
  value,
  dimensions,
  languages,
  statuses,
  onChange,
  onReset,
}: {
  value: RankingFilterState;
  dimensions: string[];
  languages: string[];
  statuses: string[];
  onChange: (next: Partial<RankingFilterState>) => void;
  onReset: () => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3" aria-label="Ranking filters">
      <div className="mr-1 flex items-center gap-1.5 pb-1 text-xs font-medium text-[var(--color-text-secondary)]">
        <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
        Filters
      </div>
      <SelectFilter label="Band" value={value.band} onChange={(band) => onChange({ band })}>
        <option value="">All bands</option>
        <option value="excellent">{HEALTH_RANKING_BAND_LABELS.excellent}</option>
        <option value="good">{HEALTH_RANKING_BAND_LABELS.good}</option>
        <option value="fair">{HEALTH_RANKING_BAND_LABELS.fair}</option>
        <option value="weak">{HEALTH_RANKING_BAND_LABELS.weak}</option>
        <option value="critical">{HEALTH_RANKING_BAND_LABELS.critical}</option>
      </SelectFilter>
      <SelectFilter
        label="Dimension"
        value={value.dimension}
        onChange={(dimension) => onChange({ dimension })}
      >
        <option value="">All dimensions</option>
        {dimensions.map((dimension) => <option key={dimension} value={dimension}>{dimension}</option>)}
      </SelectFilter>
      <SelectFilter
        label="Language"
        value={value.language}
        onChange={(language) => onChange({ language })}
      >
        <option value="">All languages</option>
        {languages.map((language) => <option key={language} value={language}>{language}</option>)}
      </SelectFilter>
      <SelectFilter label="Status" value={value.status} onChange={(status) => onChange({ status })}>
        <option value="">Any status</option>
        {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
      </SelectFilter>
      <SelectFilter
        label="Freshness"
        value={value.freshness}
        onChange={(freshness) => onChange({ freshness: freshness as RankingFilterState["freshness"] })}
      >
        <option value="all">Freshness: all</option>
        <option value="fresh">Fresh only</option>
        <option value="stale">Stale only</option>
      </SelectFilter>
      <SelectFilter
        label="Eligibility"
        value={value.eligibility}
        onChange={(eligibility) => onChange({ eligibility: eligibility as RankingFilterState["eligibility"] })}
      >
        <option value="eligible">Eligible only</option>
        <option value="all">Include not ranked</option>
      </SelectFilter>
      <Button type="button" size="sm" variant="ghost" onClick={onReset}>
        <RotateCcw className="h-3.5 w-3.5" aria-hidden />
        Reset
      </Button>
    </div>
  );
}

function SelectFilter({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="flex min-w-[132px] flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-tertiary)]">
        {label}
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] px-2 text-xs text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent-primary)] focus:ring-1 focus:ring-[var(--color-accent-primary)]"
      >
        {children}
      </select>
    </label>
  );
}
