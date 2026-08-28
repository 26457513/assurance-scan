"""projects.default_scan_ref — branch preference for Scan now.

Revision ID: 0016_project_scan_ref
Revises: 0015_users_roles
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016_project_scan_ref"
down_revision: Union[str, None] = "0015_users_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("default_scan_ref", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "default_scan_ref")
