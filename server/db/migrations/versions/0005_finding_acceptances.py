"""finding_acceptances table.

Revision ID: 0005_finding_acceptances
Revises: 0004_compliance_mappings
Create Date: 2026-08-09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0005_finding_acceptances"
down_revision: Union[str, None] = "0004_compliance_mappings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finding_acceptances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("scanner_kind", sa.String(length=64), nullable=False),
        sa.Column("rule_id", sa.String(length=256), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("accepted_by", sa.String(length=128), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_finding_acceptances_lookup",
        "finding_acceptances",
        ["project_path", "scanner_kind", "rule_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_finding_acceptances_lookup", table_name="finding_acceptances")
    op.drop_table("finding_acceptances")
