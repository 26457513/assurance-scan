"""Add durable GitHub Actions OIDC replay evidence.

Revision ID: 0032_github_oidc_replays
Revises: 0031_github_app_entitlement_freshness
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0032_github_oidc_replays"
down_revision: Union[str, None] = "0031_github_app_entitlement_freshness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_oidc_replays",
        sa.Column("jti_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(jti_digest) = 32",
            name="ck_github_oidc_replays_digest",
        ),
        sa.CheckConstraint(
            "github_repository_id > 0",
            name="ck_github_oidc_replays_repository_id",
        ),
        sa.CheckConstraint(
            "expires_at > consumed_at",
            name="ck_github_oidc_replays_expiry",
        ),
        sa.PrimaryKeyConstraint("jti_digest"),
    )
    op.create_index(
        "ix_github_oidc_replays_expires",
        "github_oidc_replays",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError("0032 is forward-only; restore the verified pre-migration backup to roll back")
