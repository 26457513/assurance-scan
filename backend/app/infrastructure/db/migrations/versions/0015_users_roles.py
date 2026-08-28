"""users — roles for UI access control (admin is seeded and API-immutable).

Revision ID: 0015_users_roles
Revises: 0014_organisations
Create Date: 2026-08-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015_users_roles"
down_revision: Union[str, None] = "0014_organisations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    users = sa.sql.table(
        "users",
        sa.sql.column("email", sa.String),
        sa.sql.column("role", sa.String),
        sa.sql.column("created_at", sa.DateTime),
        sa.sql.column("last_login_at", sa.DateTime),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(256), nullable=False, unique=True),
        # admin (protected) | superuser (delegated, revocable) | user (default)
        sa.Column("role", sa.String(32), nullable=False, default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    import datetime

    op.execute(
        users.insert().values(
            email="jon@barkleygen.com",
            role="admin",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
    )


def downgrade() -> None:
    op.drop_table("users")
