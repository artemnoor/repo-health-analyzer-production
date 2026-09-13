"""Code-health wire models: findings, trends, churn, badge and the work queue.

These mirror the dicts ``routers/code_health/serializers.py`` builds. Where a
serializer emits ``None`` it means "no signal", never zero, so those fields are
nullable; where it coerces to a number they are not.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HealthAnalyzerStatus = Literal[
    "pass",
    "warn",
    "fail",
    "skipped",
    "inconclusive",
    "error",
]


class HealthEvidenceRefResponse(BaseModel):
    """Traceability pointer shared by REST, MCP and the dashboard drawer."""

    source: str
    source_commit: str | None = None
    tool_version: str | None = None
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    json_pointer: str | None = None
    snippet_hash: str | None = None
    collected_at: str | None = None
    confidence: float = 1.0
    redaction: str = "partial"
    raw_ref: str | None = None


class HealthEvidenceCoverageResponse(BaseModel):
    """Counts and coverage ratios; no ratio is inferred from missing evidence."""

    metric_count: int = 0
    metric_evidence_count: int = 0
    finding_count: int = 0
    finding_evidence_count: int = 0
    total_evidence_count: int = 0
    covered_metrics: int = 0
    evidence_coverage: float = 0.0
    by_source: dict[str, int] = Field(default_factory=dict)


class HealthLimitationResponse(BaseModel):
    code: str
    message: str
    affected: int | float | str | None = None


class HealthCriticalityContextResponse(BaseModel):
    """Criticality ranks remediation priority; it never changes health score."""

    score: float = 0.0
    applied_to_score: bool = False
    used_for_recommendation_priority: bool = True


class HealthAnalyzerResultResponse(BaseModel):
    """Canonical persisted analyzer/source result summary."""

    analyzer_id: str
    source: str
    source_commit: str | None = None
    tool_version: str | None = None
    status: HealthAnalyzerStatus | str
    duration_ms: int = 0
    raw_fact_count: int = 0
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class CanonicalHealthScoreBreakdownResponse(BaseModel):
    """Explainable contribution row; unknown future fields remain forward-compatible."""

    model_config = ConfigDict(extra="allow")

    dimension: str
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    analyzer_id: str | None = None
    source: str | None = None
    weight: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    metric_name: str | None = None
    denominator: int | None = Field(default=None, ge=0)
    status: HealthAnalyzerStatus | str = "pass"
    configured_dimension_weight: float = Field(default=0.0, ge=0.0)


class CanonicalHealthScoreLimitationResponse(BaseModel):
    """Why a projection is partial without changing missing data into zero."""

    model_config = ConfigDict(extra="allow")

    reason: str
    kind: str = "other"
    affected_scope: str | None = None
    evidence_refs: list[HealthEvidenceRefResponse] = Field(default_factory=list)


class CanonicalHealthScoreProjectionResponse(BaseModel):
    """Typed repository-level score projection on the canonical 0..100 scale."""

    id: str
    score_config_digest: str
    overall_score: float | None = Field(default=None, ge=0.0, le=100.0)
    dimensions: dict[str, float | None] = Field(default_factory=dict)
    breakdown: list[CanonicalHealthScoreBreakdownResponse] = Field(default_factory=list)
    configured_weight: float = Field(default=0.0, ge=0.0)
    available_weight: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    status: HealthAnalyzerStatus | str = "inconclusive"
    limitations: list[CanonicalHealthScoreLimitationResponse] = Field(default_factory=list)
    score_recomputed: bool = False


class CanonicalHealthReport(BaseModel):
    """One read-only health projection consumed by every product surface."""

    schema_version: int = 1
    repository_id: str
    snapshot: dict[str, Any]
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    score_projection: CanonicalHealthScoreProjectionResponse | None = None
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    analyzers: list[HealthAnalyzerResultResponse] = Field(default_factory=list)
    coverage: HealthEvidenceCoverageResponse
    limitations: list[HealthLimitationResponse] = Field(default_factory=list)
    criticality: HealthCriticalityContextResponse
    meta: dict[str, Any] = Field(default_factory=dict)


class HealthFindingResponse(BaseModel):
    """One biomarker finding, as the table and drawer read it."""

    id: str
    file_path: str
    biomarker_type: str
    severity: str
    function_name: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    health_impact: float
    reason: str | None = None
    #: Open by design: the payload differs per biomarker.
    details: dict[str, Any] = {}
    status: str
    #: defect | maintainability | performance. Rows predating the split read
    #: as ``defect``.
    dimension: str = "defect"


class HealthFindingWithSymbolResponse(HealthFindingResponse):
    """A listed finding, resolved to the symbol a tool can look up.

    ``None`` when the finding is file-level, or no symbol matched its span,
    so the UI degrades to the file page.
    """

    symbol_id: str | None = None


class ChurnComplexityPoint(BaseModel):
    """One file on the churn-vs-complexity scatter.

    Every figure is coerced by the producer, so none is nullable here: a zero
    means zero, not "no signal".
    """

    file_path: str
    commit_count_90d: int
    max_ccn: int
    nloc: int
    score: float
    churn_percentile: float


class ChurnComplexityResponse(BaseModel):
    points: list[ChurnComplexityPoint] = []
    #: Points before the request's limit, so a slice is not read as the whole.
    total: int = 0


class FileTrendPointResponse(BaseModel):
    taken_at: str | None = None
    score: float
    #: ``score`` with the floor undone; equal to it unless the file was on it.
    unclamped_score: float


class FileHealthTrendResponse(BaseModel):
    """One file's score over time. ``points`` is empty on thin history."""

    file_path: str
    points: list[FileTrendPointResponse] = []
    current: float | None = None
    previous: float | None = None
    delta: float | None = None
    unclamped_delta: float | None = None
    declining: bool = False
    snapshot_count: int = 0


class HealthTrendKpiRow(BaseModel):
    """One snapshot in the repo-level history, newest first."""

    taken_at: str | None = None
    #: ``None`` under a narrowed scope, which recorded only the average.
    hotspot_health: float | None = None
    average_health: float
    worst_performer_path: str | None = None
    worst_performer_score: float | None = None
    #: The headline's two halves in deduction points, and the maintainability
    #: pillar, at this snapshot. ``None`` before each was recorded and under a
    #: narrowed scope, so a series starts partway along the axis rather than
    #: reading an unrecorded point as a zero.
    structure_average: float | None = None
    history_average: float | None = None
    maintainability_average: float | None = None


class HealthTrendSummary(BaseModel):
    #: ``None`` under a narrowed scope: only the average was recorded for both
    #: populations, and a repo-wide hotspot figure under a production label
    #: would describe files the rest of the response has dropped.
    current_hotspot_health: float | None = None
    current_average_health: float
    previous_hotspot_health: float | None = None
    previous_average_health: float | None = None
    hotspot_delta: float | None = None
    average_delta: float | None = None
    #: The newest reading's two halves, in deduction points.
    current_structure_deduction: float | None = None
    current_history_deduction: float | None = None


class HealthTrendAlert(BaseModel):
    #: ``declining`` and ``predicted_decline`` are regressions; ``history_drag``
    #: is a fall the code shape did not cause and there is nothing to act on.
    kind: str
    metric: str
    current: float
    baseline: float | None = None
    delta: float
    message: str
    #: Which half of the headline moved, and each half's share of ``delta``.
    driver: str | None = None
    structure_delta: float | None = None
    history_delta: float | None = None


class HealthFileDelta(BaseModel):
    """One file's movement between the last two snapshots."""

    file_path: str
    before: float
    after: float
    delta: float


class HealthTrendResponse(BaseModel):
    history: list[HealthTrendKpiRow] = []
    summary: HealthTrendSummary
    alerts: list[HealthTrendAlert] = []
    #: Largest movement first, in either direction.
    file_deltas: list[HealthFileDelta] = []
    #: The count behind the slice, so the UI can say "N of M".
    file_deltas_total: int = 0
    snapshot_count: int = 0
    #: Which half of the repository these figures describe.
    scope: str = "all"


class HealthBadgeResponse(BaseModel):
    """Shields-compatible badge fields for the JSON endpoint.

    ``schemaVersion`` is camelCase because the Shields endpoint protocol
    requires that exact key; without it every embedded badge renders as
    "invalid response" instead of the score.
    """

    schemaVersion: int = 1  # noqa: N815
    label: str
    message: str
    color: str
    band: str


class HealthWorkItem(BaseModel):
    """One file in the triage queue, ranked by impact over effort."""

    file_path: str
    score: float
    nloc: int
    module: str | None = None
    primary_biomarker: str
    primary_severity: str
    primary_reason: str | None = None
    primary_function: str | None = None
    primary_line_start: int | None = None
    primary_line_end: int | None = None
    primary_suggestion: str | None = None
    primary_finding_id: str
    #: Pre-clamp deduction magnitude over the findings that passed the filters.
    total_impact: float
    finding_count: int
    biomarkers: list[str] = []
    #: S | M | L | XL
    effort_bucket: str
    impact_per_effort: float


class HealthWorkQueueResponse(BaseModel):
    targets: list[HealthWorkItem] = []
    total: int = 0
