"""projects registry — explicit project definitions (tag, local path, repo).

Revision ID: 0011_projects_registry
Revises: 0010_run_git_branch
Create Date: 2026-08-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011_projects_registry"
down_revision: Union[str, None] = "0010_run_git_branch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tag", sa.String(128), nullable=False, unique=True),
        sa.Column("local_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("github_repo", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("projects")
