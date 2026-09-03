"""Permit validated internal routes as GitHub sign-in return paths.

Revision ID: 0038_github_signin_return_paths
Revises: 0037_github_signin
Create Date: 2026-09-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0038_github_signin_return_paths"
down_revision: Union[str, None] = "0037_github_signin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("github_signin_states") as batch:
        batch.drop_constraint("ck_github_signin_states_return_path", type_="check")
        batch.alter_column(
            "return_path",
            existing_type=sa.String(64),
            type_=sa.String(512),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            "ck_github_signin_states_return_path",
            "length(return_path) BETWEEN 1 AND 512 "
            "AND substr(return_path, 1, 1) = '/' "
            "AND substr(return_path, 1, 2) != '//'",
        )


def downgrade() -> None:
    raise RuntimeError("0038 is forward-only; restore a verified pre-migration backup to roll back")
