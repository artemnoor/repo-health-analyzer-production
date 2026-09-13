/** Public-safe repository health ranking contract. */

export type HealthRankingBand =
  | "excellent"
  | "good"
  | "fair"
  | "weak"
  | "critical"
  | "unknown";

/** Minimum canonical score for each measured ranking band. */
export const HEALTH_RANKING_BAND_THRESHOLDS = {
  excellent: 90,
  good: 80,
  fair: 70,
  weak: 60,
  critical: 0,
} as const satisfies Record<Exclude<HealthRankingBand, "unknown">, number>;

export const HEALTH_RANKING_BAND_LABELS: Record<HealthRankingBand, string> = {
  excellent: "Excellent (90–100)",
  good: "Good (80–<90)",
  fair: "Fair (70–<80)",
  weak: "Weak (60–<70)",
  critical: "Critical (0–<60)",
  unknown: "Unknown (unavailable)",
};

export function healthRankingBandForScore(score: number | null): HealthRankingBand {
  if (score == null || !Number.isFinite(score)) return "unknown";
  if (score >= HEALTH_RANKING_BAND_THRESHOLDS.excellent) return "excellent";
  if (score >= HEALTH_RANKING_BAND_THRESHOLDS.good) return "good";
  if (score >= HEALTH_RANKING_BAND_THRESHOLDS.fair) return "fair";
  if (score >= HEALTH_RANKING_BAND_THRESHOLDS.weak) return "weak";
  return "critical";
}

export interface HealthRankingFacets {
  dimensions: string[];
  languages: string[];
  statuses: string[];
}

export interface HealthRankingEntry {
  repository_id: string;
  name: string;
  url: string;
  snapshot_id: string;
  score_config_digest: string;
  overall_score: number | null;
  /** Optional for clients reading a response from a pre-band server. */
  band?: HealthRankingBand;
  grade: string;
  status: string;
  dimensions: Record<string, number | null>;
  languages: string[];
  confidence: number;
  coverage: number;
  evidence_coverage: number;
  analyzed_at: string | null;
  stale: boolean;
  eligible: boolean;
  eligibility_reason: string | null;
  score_delta: number | null;
}

export interface HealthRankingQuery extends Record<string, string | number | boolean | undefined> {
  page?: number;
  limit?: number;
  band?: HealthRankingBand;
  dimension?: string;
  language?: string;
  status?: string;
  stale?: boolean;
  eligible?: boolean;
  include_ineligible?: boolean;
}

export interface HealthRankingResponse {
  items: HealthRankingEntry[];
  page: number;
  limit: number;
  total: number;
  generated_at: string;
  facets?: HealthRankingFacets | null;
}

export interface HealthRankingCompareResponse {
  items: HealthRankingEntry[];
  dimensions: Record<string, Record<string, number | null>>;
  score_config_digests: string[];
  truncated: boolean;
  generated_at: string;
}

export interface HealthRankingTrendPoint {
  snapshot_id: string;
  score_config_digest: string;
  overall_score: number | null;
  band: HealthRankingBand;
  grade: string;
  status: string;
  analyzed_at: string | null;
}

export interface HealthRankingTrendSeries {
  repository_id: string;
  name: string;
  points: HealthRankingTrendPoint[];
}

export interface HealthRankingTrendResponse {
  items: HealthRankingTrendSeries[];
  limit: number;
  generated_at: string;
}
