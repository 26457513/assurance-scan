"""Permit immutable-only GitHub links and expiring GitHub App memberships.

Revision ID: 0027_github_account_linking
Revises: 0026_github_identity_sessions
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0027_github_account_linking"
down_revision: Union[str, None] = "0026_github_identity_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("github_accounts") as batch:
        batch.alter_column("email", existing_type=sa.String(256), nullable=True)
        batch.alter_column("token_encrypted", existing_type=sa.Text(), nullable=True)

    with op.batch_alter_table("project_memberships") as batch:
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.drop_constraint("ck_project_memberships_source", type_="check")
        batch.create_check_constraint(
            "ck_project_memberships_source",
            "source IN ('github', 'github_app', 'manual')",
        )
        batch.create_check_constraint(
            "ck_project_memberships_github_app_expiry",
            "source != 'github_app' OR expires_at IS NOT NULL",
        )


def downgrade() -> None:
    raise RuntimeError("0027 is forward-only; restore the verified pre-migration backup to roll back")
