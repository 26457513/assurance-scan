"""compliance_mappings table.

Revision ID: 0004_compliance_mappings
Revises: 0003_v3_test_results
Create Date: 2026-08-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_compliance_mappings"
down_revision: Union[str, None] = "0003_v3_test_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("mapping_doc_json", sa.Text(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compliance_mappings_project", "compliance_mappings", ["project_path"])


def downgrade() -> None:
    op.drop_index("ix_compliance_mappings_project", table_name="compliance_mappings")
    op.drop_table("compliance_mappings")
