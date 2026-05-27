"""Add tenant column to audit_events (REQ-D-5, PREQ-S-2).

Forward-only: ADD COLUMN with DEFAULT so existing rows get 'default'.
Downgrade path drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column(
            "tenant",
            sa.String(255),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "tenant")
