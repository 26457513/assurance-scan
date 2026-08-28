"""runs.mapping_hash — pin the compliance mapping a run evaluated against.

Revision ID: 0007_run_mapping_hash
Revises: 0006_finding_acceptance_advisory
Create Date: 2026-08-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_run_mapping_hash"
down_revision: Union[str, None] = "0006_finding_acceptance_advisory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("mapping_hash", sa.String(length=80), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "mapping_hash")
