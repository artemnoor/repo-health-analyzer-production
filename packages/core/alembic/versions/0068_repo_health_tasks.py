"""Add explicit Repo Health queue claim/lease state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repo_health_tasks",
        sa.Column("task_id", sa.String(128), primary_key=True),
        sa.Column("analysis_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("analyzer_id", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("analysis_id", "idempotency_key", name="uq_repo_health_task_idempotency"),
    )
    op.create_index("ix_repo_health_tasks_claim", "repo_health_tasks", ["status", "available_at", "lease_until"])
    op.create_index("ix_repo_health_tasks_analysis", "repo_health_tasks", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_repo_health_tasks_analysis", table_name="repo_health_tasks")
    op.drop_index("ix_repo_health_tasks_claim", table_name="repo_health_tasks")
    op.drop_table("repo_health_tasks")
