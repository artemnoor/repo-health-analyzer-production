/**
 * Tokens for the repository ranking's canonical 0–100 score.
 *
 * These intentionally live beside, but do not reuse, the legacy 0–10
 * HealthBand tokens. A ranking band is a public contract with different names
 * and thresholds, so changing one vocabulary must never silently repaint the
 * other surfaces.
 */

import {
  HEALTH_RANKING_BAND_LABELS,
  healthRankingBandForScore,
  type HealthRankingBand,
} from "@repowise-dev/types/health-ranking";

const RANKING_BAND_COLOR: Record<HealthRankingBand, string> = {
  excellent: "var(--color-success)",
  good: "var(--color-success)",
  fair: "var(--color-caution)",
  weak: "var(--color-warning)",
  critical: "var(--color-error)",
  unknown: "var(--color-text-tertiary)",
};

const RANKING_BAND_LABEL: Record<HealthRankingBand, string> = {
  excellent: "Excellent",
  good: "Good",
  fair: "Fair",
  weak: "Weak",
  critical: "Critical",
  unknown: "Unknown",
};

export function rankingHealthBandColor(band: HealthRankingBand): string {
  return RANKING_BAND_COLOR[band];
}

export function rankingHealthBandLabel(band: HealthRankingBand): string {
  return RANKING_BAND_LABEL[band];
}

export function rankingHealthBandRangeLabel(band: HealthRankingBand): string {
  return HEALTH_RANKING_BAND_LABELS[band];
}

export function rankingHealthBandForEntry(
  band: HealthRankingBand | string | null | undefined,
  score: number | null,
): HealthRankingBand {
  if (
    band === "excellent" ||
    band === "good" ||
    band === "fair" ||
    band === "weak" ||
    band === "critical" ||
    band === "unknown"
  ) {
    return band;
  }
  return healthRankingBandForScore(score);
}
