"""Add project-scoped user authorization.

Revision ID: 0024_project_memberships
Revises: 0023_local_run_display_identity
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024_project_memberships"
down_revision: Union[str, None] = "0023_local_run_display_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("github_access_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("permission", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "project_id", "source", name="uq_project_memberships_source"
        ),
        sa.CheckConstraint(
            "permission IN ('view', 'upload', 'manage')",
            name="ck_project_memberships_permission",
        ),
        sa.CheckConstraint(
            "source IN ('github', 'manual')",
            name="ck_project_memberships_source",
        ),
    )
    op.create_index(
        "ix_project_memberships_user_project",
        "project_memberships",
        ["user_id", "project_id"],
    )
    op.create_index(
        "ix_project_memberships_project", "project_memberships", ["project_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "0024 is forward-only; restore the verified pre-migration backup to roll back"
    )
