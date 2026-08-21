"""catalogue_snapshots.source_branch — branch the catalogue was authored against.

Revision ID: 0020_snapshot_source_branch
Revises: 0019_project_checkouts
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020_snapshot_source_branch"
down_revision: Union[str, None] = "0019_project_checkouts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("catalogue_snapshots", sa.Column("source_branch", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("catalogue_snapshots", "source_branch")
