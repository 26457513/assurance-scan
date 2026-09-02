"""Make authenticated GitHub webhook deliveries actionable and lease-safe.

Revision ID: 0030_github_webhook_work_queue
Revises: 0029_github_app_access_plane
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0030_github_webhook_work_queue"
down_revision: Union[str, None] = "0029_github_app_access_plane"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("github_webhook_deliveries") as batch:
        batch.add_column(sa.Column("github_installation_id", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.String(36), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error_code", sa.String(64), nullable=True))
        batch.create_check_constraint(
            "ck_github_webhook_deliveries_installation_id",
            "github_installation_id IS NULL OR github_installation_id > 0",
        )
        batch.create_check_constraint(
            "ck_github_webhook_deliveries_attempt_count",
            "attempt_count >= 0",
        )
        batch.create_index(
            "ix_github_webhook_deliveries_work",
            ["status", "available_at", "received_at"],
        )


def downgrade() -> None:
    raise RuntimeError("0030 is forward-only; restore the verified pre-migration backup to roll back")
