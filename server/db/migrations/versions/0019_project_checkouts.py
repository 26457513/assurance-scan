"""project_checkouts — per-user local checkout paths for github projects.

Revision ID: 0019_project_checkouts
Revises: 0018_users_mcp_token
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019_project_checkouts"
down_revision: Union[str, None] = "0018_users_mcp_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_checkouts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_email", sa.String(256), nullable=False, default=""),
        sa.Column("project_path", sa.String(1024), nullable=False),
        sa.Column("checkout_path", sa.String(1024), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_email", "project_path", name="uq_project_checkouts_user_project"),
    )
    op.create_index("ix_project_checkouts_project", "project_checkouts", ["project_path"])


def downgrade() -> None:
    op.drop_index("ix_project_checkouts_project", table_name="project_checkouts")
    op.drop_table("project_checkouts")
