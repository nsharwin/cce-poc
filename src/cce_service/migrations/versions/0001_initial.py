"""Initial CCE service schema: jobs, audit_events, users.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("tenant", sa.String(255), nullable=False),
        sa.Column("repo_url", sa.Text, nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False),
        sa.Column("spec_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("record_hash", sa.String(256), nullable=True),
        sa.Column("score", sa.String(32), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("sidecars", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_tenant", "jobs", ["tenant"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])

    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("tenant", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_index("ix_audit_events_ts", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_tenant", table_name="jobs")
    op.drop_table("jobs")
