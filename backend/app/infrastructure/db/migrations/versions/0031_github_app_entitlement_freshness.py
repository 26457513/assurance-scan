"""Separate GitHub App entitlement freshness from the legacy poller grant.

Revision ID: 0031_github_app_entitlement_freshness
Revises: 0030_github_webhook_work_queue
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0031_github_app_entitlement_freshness"
down_revision: Union[str, None] = "0030_github_webhook_work_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "github_app_access_synced_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    raise RuntimeError("0031 is forward-only; restore the verified pre-migration backup to roll back")
