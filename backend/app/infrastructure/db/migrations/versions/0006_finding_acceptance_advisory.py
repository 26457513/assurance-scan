"""Add fix_assessment + invalidation_conditions to finding_acceptances.

Revision ID: 0006_finding_acceptance_advisory
Revises: 0005_finding_acceptances
Create Date: 2026-08-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_finding_acceptance_advisory"
down_revision: Union[str, None] = "0005_finding_acceptances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("finding_acceptances", sa.Column("fix_assessment", sa.Text(), nullable=True))
    op.add_column("finding_acceptances", sa.Column("invalidation_conditions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("finding_acceptances", "invalidation_conditions")
    op.drop_column("finding_acceptances", "fix_assessment")
