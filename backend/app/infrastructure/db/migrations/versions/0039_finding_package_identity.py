"""Preserve structured package identity on normalized findings.

Revision ID: 0039_finding_package_identity
Revises: 0038_github_signin_return_paths
Create Date: 2026-09-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0039_finding_package_identity"
down_revision: Union[str, None] = "0038_github_signin_return_paths"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("findings") as batch:
        batch.add_column(sa.Column("package_name", sa.String(512), nullable=True))
        batch.add_column(sa.Column("package_version", sa.String(256), nullable=True))
        batch.add_column(sa.Column("package_ecosystem", sa.String(64), nullable=True))
        batch.add_column(sa.Column("package_purl", sa.String(1024), nullable=True))
        batch.create_index("ix_findings_run_package", ["run_id", "package_purl"])


def downgrade() -> None:
    raise RuntimeError("0039 is forward-only; restore a verified pre-migration backup to roll back")
