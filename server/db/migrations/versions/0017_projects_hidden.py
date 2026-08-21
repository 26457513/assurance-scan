"""projects.hidden — tombstone so deleted projects stay deleted.

Revision ID: 0017_projects_hidden
Revises: 0016_project_scan_ref
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017_projects_hidden"
down_revision: Union[str, None] = "0016_project_scan_ref"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("projects", "hidden")
