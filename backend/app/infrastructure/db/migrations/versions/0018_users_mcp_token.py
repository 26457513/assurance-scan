"""users.mcp_token_hash — per-user MCP bearer tokens.

Revision ID: 0018_users_mcp_token
Revises: 0017_projects_hidden
Create Date: 2026-08-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018_users_mcp_token"
down_revision: Union[str, None] = "0017_projects_hidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mcp_token_hash", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("mcp_token_generated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "mcp_token_generated_at")
    op.drop_column("users", "mcp_token_hash")
