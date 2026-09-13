"""Add the append-only repository health envelope and provenance tables."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repository_health_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("repository_id", sa.String(32), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("analyzer_versions_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("score_config_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("scope", sa.String(32), nullable=False, server_default="all"),
        sa.Column("mode", sa.String(32), nullable=False, server_default="full"),
        sa.Column("status", sa.String(24), nullable=False, server_default="inconclusive"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("criticality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stale_after_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repository_id", "head_sha", "as_of_ts", "config_digest", "analyzer_versions_digest", "scope", name="uq_repository_health_snapshot_replay"),
    )
    op.create_index("ix_repository_health_snapshots_repo_asof", "repository_health_snapshots", ["repository_id", "as_of_ts"])
    op.create_index("ix_repository_health_snapshots_repo_status", "repository_health_snapshots", ["repository_id", "status"])

    op.create_table(
        "health_source_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analyzer_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("source_commit", sa.String(64), nullable=True),
        sa.Column("tool_version", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_fact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("diagnostic_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_health_source_runs_snapshot", "health_source_runs", ["snapshot_id"])
    op.create_index("ix_health_source_runs_analyzer", "health_source_runs", ["analyzer_id", "source"])

    op.create_table(
        "health_raw_facts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_run_id", sa.String(32), sa.ForeignKey("health_source_runs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("source_commit", sa.String(64), nullable=True),
        sa.Column("tool_version", sa.String(128), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("stable_event_id", sa.String(255), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("payload_ref", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("redaction", sa.String(16), nullable=False, server_default="partial"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("snapshot_id", "source", "stable_event_id", "source_commit", name="uq_health_raw_fact_event"),
    )
    op.create_index("ix_health_raw_facts_snapshot_type", "health_raw_facts", ["snapshot_id", "event_type"])
    op.create_index("ix_health_raw_facts_source_event", "health_raw_facts", ["source", "stable_event_id"])
    op.create_index("ix_health_raw_facts_payload_hash", "health_raw_facts", ["payload_hash"])

    op.create_table(
        "health_normalized_facts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("raw_fact_id", sa.String(32), sa.ForeignKey("health_raw_facts.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("fact_type", sa.String(64), nullable=False),
        sa.Column("stable_event_id", sa.String(255), nullable=False),
        sa.Column("canonical_contributor_id", sa.String(255), nullable=True),
        sa.Column("normalized_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("original_offset_minutes", sa.Integer(), nullable=True),
        sa.Column("timestamp_corrected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("identity_confidence", sa.Float(), nullable=True),
        sa.Column("normalization_policy", sa.String(64), nullable=False, server_default=""),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_event_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "stable_event_id", "normalization_policy", name="uq_health_normalized_fact"),
    )
    op.create_index("ix_health_normalized_facts_snapshot_contributor", "health_normalized_facts", ["snapshot_id", "canonical_contributor_id"])
    op.create_index("ix_health_normalized_facts_snapshot_ts", "health_normalized_facts", ["snapshot_id", "normalized_ts"])

    op.create_table(
        "health_metric_values",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analyzer_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("numeric_value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("population", sa.Integer(), nullable=True),
        sa.Column("denominator", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("available_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("snapshot_id", "analyzer_id", "name", name="uq_health_metric_value"),
    )
    op.create_index("ix_health_metric_values_snapshot_analyzer", "health_metric_values", ["snapshot_id", "analyzer_id"])
    op.create_index("ix_health_metric_values_name", "health_metric_values", ["name"])

    op.create_table(
        "health_finding_evidence",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("finding_id", sa.String(255), nullable=False),
        sa.Column("analyzer_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("source_commit", sa.String(64), nullable=True),
        sa.Column("tool_version", sa.String(128), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("json_pointer", sa.Text(), nullable=True),
        sa.Column("snippet_hash", sa.String(64), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("redaction", sa.String(16), nullable=False, server_default="partial"),
        sa.Column("raw_ref", sa.Text(), nullable=True),
    )
    op.create_index("ix_health_finding_evidence_snapshot_finding", "health_finding_evidence", ["snapshot_id", "finding_id"])
    op.create_index("ix_health_finding_evidence_location", "health_finding_evidence", ["path", "line_start"])

    op.create_table(
        "health_aggregates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("score_config_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("scope", sa.String(32), nullable=False, server_default="repository"),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("criticality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "score_config_digest", "scope", "dimension", "name", name="uq_health_aggregate_config"),
    )
    op.create_index("ix_health_aggregates_snapshot_dimension", "health_aggregates", ["snapshot_id", "dimension"])

    op.create_table(
        "health_recommendations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recommendation_id", sa.String(128), nullable=False),
        sa.Column("finding_id", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("finding_status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("location_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("lifecycle", sa.String(16), nullable=False, server_default="new"),
        sa.Column("benefit", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("criticality", sa.Float(), nullable=False, server_default="0"),
        sa.Column("effort", sa.Float(), nullable=False, server_default="1"),
        sa.Column("risk", sa.Float(), nullable=False, server_default="1"),
        sa.Column("blast_radius", sa.Float(), nullable=False, server_default="1"),
        sa.Column("raw_impact", sa.Float(), nullable=True),
        sa.Column("applied_impact", sa.Float(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "recommendation_id", name="uq_health_recommendation_snapshot"),
        sa.CheckConstraint("lifecycle IN ('new', 'open', 'accepted', 'dismissed', 'resolved', 'stale')", name="ck_health_recommendation_lifecycle"),
    )
    op.create_index("ix_health_recommendations_snapshot_priority", "health_recommendations", ["snapshot_id", "priority"])
    op.create_index("ix_health_recommendations_subject", "health_recommendations", ["subject"])
    op.create_index("ix_health_recommendations_finding", "health_recommendations", ["finding_id"])


def downgrade() -> None:
    op.drop_index("ix_health_recommendations_finding", table_name="health_recommendations")
    op.drop_index("ix_health_recommendations_subject", table_name="health_recommendations")
    op.drop_index("ix_health_recommendations_snapshot_priority", table_name="health_recommendations")
    op.drop_table("health_recommendations")
    op.drop_index("ix_health_aggregates_snapshot_dimension", table_name="health_aggregates")
    op.drop_table("health_aggregates")
    op.drop_index("ix_health_finding_evidence_location", table_name="health_finding_evidence")
    op.drop_index("ix_health_finding_evidence_snapshot_finding", table_name="health_finding_evidence")
    op.drop_table("health_finding_evidence")
    op.drop_index("ix_health_metric_values_name", table_name="health_metric_values")
    op.drop_index("ix_health_metric_values_snapshot_analyzer", table_name="health_metric_values")
    op.drop_table("health_metric_values")
    op.drop_index("ix_health_normalized_facts_snapshot_ts", table_name="health_normalized_facts")
    op.drop_index("ix_health_normalized_facts_snapshot_contributor", table_name="health_normalized_facts")
    op.drop_table("health_normalized_facts")
    op.drop_index("ix_health_raw_facts_payload_hash", table_name="health_raw_facts")
    op.drop_index("ix_health_raw_facts_source_event", table_name="health_raw_facts")
    op.drop_index("ix_health_raw_facts_snapshot_type", table_name="health_raw_facts")
    op.drop_table("health_raw_facts")
    op.drop_index("ix_health_source_runs_analyzer", table_name="health_source_runs")
    op.drop_index("ix_health_source_runs_snapshot", table_name="health_source_runs")
    op.drop_table("health_source_runs")
    op.drop_index("ix_repository_health_snapshots_repo_status", table_name="repository_health_snapshots")
    op.drop_index("ix_repository_health_snapshots_repo_asof", table_name="repository_health_snapshots")
    op.drop_table("repository_health_snapshots")
