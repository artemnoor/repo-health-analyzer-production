"""Materialize one versioned composite score per health snapshot."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("health_metric_values", sa.Column("dimension", sa.String(64), nullable=True))
    op.create_index("ix_health_metric_values_snapshot_dimension", "health_metric_values", ["snapshot_id", "dimension"])
    op.create_table(
        "health_score_projections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("snapshot_id", sa.String(32), sa.ForeignKey("repository_health_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score_config_digest", sa.String(64), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("dimensions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("breakdown_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("configured_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("available_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="inconclusive"),
        sa.Column("limitations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("score_recomputed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("snapshot_id", "score_config_digest", name="uq_health_score_projection_config"),
    )
    op.create_index("ix_health_score_projections_snapshot", "health_score_projections", ["snapshot_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_health_score_projections_snapshot", table_name="health_score_projections")
    op.drop_table("health_score_projections")
    op.drop_index("ix_health_metric_values_snapshot_dimension", table_name="health_metric_values")
    op.drop_column("health_metric_values", "dimension")

