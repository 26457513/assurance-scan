"""catalogue_snapshots.tag — friendly label for the dropdowns.

Revision ID: 0012_catalogue_tag
Revises: 0011_projects_registry
Create Date: 2026-08-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012_catalogue_tag"
down_revision: Union[str, None] = "0011_projects_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("catalogue_snapshots", sa.Column("tag", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("catalogue_snapshots", "tag")
