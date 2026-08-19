"""compliance_mapping_snapshots — immutable mapping history with pinned targets.

Revision ID: 0009_mapping_snapshots
Revises: 0008_snapshot_source_commit
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009_mapping_snapshots"
down_revision: Union[str, None] = "0008_snapshot_source_commit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_mapping_snapshots",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("catalogue_content_hash", sa.String(length=80), nullable=True),
        sa.Column("packs_json", sa.Text(), nullable=False),
        sa.Column("mapping_doc_json", sa.Text(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_compliance_mapping_snapshots_project",
        "compliance_mapping_snapshots",
        ["project_path"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compliance_mapping_snapshots_project",
        table_name="compliance_mapping_snapshots",
    )
    op.drop_table("compliance_mapping_snapshots")
