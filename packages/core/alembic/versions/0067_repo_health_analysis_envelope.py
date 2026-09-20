"""Persist serialized Repo Health analysis envelopes for replay and idempotency."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_health_analysis_envelopes",
        sa.Column("analysis_id", sa.String(128), primary_key=True),
        sa.Column("repository_id", sa.String(32), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="repo-health.v1"),
        sa.Column("facts_digest", sa.String(128), nullable=True),
        sa.Column("policy_digest", sa.String(128), nullable=True),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("facts_json", sa.Text(), nullable=True),
        sa.Column("category_results_json", sa.Text(), nullable=False, server_default='{"items":[]}'),
        sa.Column("score_json", sa.Text(), nullable=True),
        sa.Column("status_json", sa.Text(), nullable=False),
        sa.Column("tool_versions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("envelope_json", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("repository_id", "idempotency_key", name="uq_repo_health_envelope_idempotency"),
    )
    op.create_index("ix_repo_health_envelopes_repository", "repo_health_analysis_envelopes", ["repository_id", "created_at"])
    op.create_index("ix_repo_health_envelopes_snapshot", "repo_health_analysis_envelopes", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_repo_health_envelopes_snapshot", table_name="repo_health_analysis_envelopes")
    op.drop_index("ix_repo_health_envelopes_repository", table_name="repo_health_analysis_envelopes")
    op.drop_table("repo_health_analysis_envelopes")
