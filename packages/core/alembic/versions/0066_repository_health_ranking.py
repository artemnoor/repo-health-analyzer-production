"""Add public visibility and materialized repository-health ranking."""

import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="private"),
    )
    op.create_index("ix_repositories_visibility", "repositories", ["visibility"])
    op.create_table(
        "repository_health_ranking",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("repository_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", sa.String(length=32), nullable=False),
        sa.Column("score_config_digest", sa.String(length=64), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("grade", sa.String(length=2), nullable=False, server_default="—"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="inconclusive"),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="full"),
        sa.Column("dimensions_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("languages_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score_delta", sa.Float(), nullable=True),
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eligibility_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["repository_health_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("repository_id", name="uq_repository_health_ranking_repo"),
    )
    op.create_index(
        "ix_repository_health_ranking_public",
        "repository_health_ranking",
        ["eligible", "overall_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_repository_health_ranking_public", table_name="repository_health_ranking")
    op.drop_table("repository_health_ranking")
    op.drop_index("ix_repositories_visibility", table_name="repositories")
    op.drop_column("repositories", "visibility")
