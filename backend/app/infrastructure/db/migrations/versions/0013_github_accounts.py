"""github_accounts — per-user GitHub tokens, encrypted at rest.

Revision ID: 0013_github_accounts
Revises: 0012_catalogue_tag
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0013_github_accounts"
down_revision: Union[str, None] = "0012_catalogue_tag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(256), nullable=False, unique=True),
        sa.Column("login", sa.String(128), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("github_accounts")
