"""catalogue_snapshots.source_commit_sha — git HEAD the catalogue was generated against.

Revision ID: 0008_snapshot_source_commit
Revises: 0007_run_mapping_hash
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_snapshot_source_commit"
down_revision: Union[str, None] = "0007_run_mapping_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalogue_snapshots",
        sa.Column("source_commit_sha", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catalogue_snapshots", "source_commit_sha")
