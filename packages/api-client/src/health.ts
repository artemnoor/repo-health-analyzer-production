import { apiGet } from "./client";
import type { HealthResponse } from "./types";

export type {
  CanonicalHealthQuery,
  CanonicalHealthReport,
  CanonicalHealthScoreProjection,
} from "@repowise-dev/types/health";
export type { HealthRankingBand } from "@repowise-dev/types/health-ranking";
export { getCanonicalHealth } from "./code-health";

export async function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/health");
}

export interface CoordinatorHealth {
  sql_pages: number | null;
  sql_decisions: number | null;
  vector_count: number | null;
  vector_page_count: number | null;
  vector_decision_count: number | null;
  graph_nodes: number | null;
  drift_pct: number | null;
  page_drift_pct: number | null;
  decision_drift_pct: number | null;
  status: "ok" | "warning" | "critical";
  detail: string | null;
}

export async function getCoordinatorHealth(repoId: string): Promise<CoordinatorHealth> {
  return apiGet<CoordinatorHealth>(`/api/repos/${repoId}/health/coordinator`);
}
