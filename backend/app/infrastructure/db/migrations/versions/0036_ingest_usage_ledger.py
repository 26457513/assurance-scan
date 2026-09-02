"""Add cross-origin quota lock and immutable usage charges.

Revision ID: 0036_ingest_usage_ledger
Revises: 0035_github_ingest_quotas_attempts
Create Date: 2026-09-02
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0036_ingest_usage_ledger"
down_revision: Union[str, None] = "0035_github_ingest_quotas_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingest_quota_locks",
        sa.Column("lock_name", sa.String(32), primary_key=True),
        sa.CheckConstraint("lock_name = 'global'", name="ck_ingest_quota_locks_global"),
    )
    op.execute("INSERT INTO ingest_quota_locks (lock_name) VALUES ('global')")
    op.create_table(
        "ingest_usage_charges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("correlation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("accepted_bytes", sa.BigInteger(), nullable=False),
        sa.Column("local_user_id", sa.Integer(), nullable=True),
        sa.Column("local_token_id", sa.String(36), nullable=True),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=True),
        sa.Column("github_owner_id", sa.BigInteger(), nullable=True),
        sa.Column("charged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("origin IN ('github', 'local')", name="ck_ingest_usage_charges_origin"),
        sa.CheckConstraint("accepted_bytes >= 0", name="ck_ingest_usage_charges_bytes"),
        sa.CheckConstraint("expires_at > charged_at", name="ck_ingest_usage_charges_expiry"),
        sa.CheckConstraint(
            "(origin = 'local' AND local_user_id IS NOT NULL AND local_user_id > 0 "
            "AND local_token_id IS NOT NULL AND github_repository_id IS NULL "
            "AND github_owner_id IS NULL) OR "
            "(origin = 'github' AND local_user_id IS NULL AND local_token_id IS NULL "
            "AND github_repository_id IS NOT NULL AND github_repository_id > 0 "
            "AND github_owner_id IS NOT NULL AND github_owner_id > 0)",
            name="ck_ingest_usage_charges_identity",
        ),
    )
    for name, columns in (
        ("ix_ingest_usage_charges_token_time", ["local_token_id", "charged_at"]),
        ("ix_ingest_usage_charges_user_time", ["local_user_id", "charged_at"]),
        ("ix_ingest_usage_charges_repository_time", ["github_repository_id", "charged_at"]),
        ("ix_ingest_usage_charges_owner_time", ["github_owner_id", "charged_at"]),
        ("ix_ingest_usage_charges_expires", ["expires_at"]),
    ):
        op.create_index(name, "ingest_usage_charges", columns)
    _backfill_charges()


def _backfill_charges() -> None:
    connection = op.get_bind()
    charges = sa.table(
        "ingest_usage_charges",
        sa.column("id", sa.String),
        sa.column("correlation_id", sa.String),
        sa.column("origin", sa.String),
        sa.column("accepted_bytes", sa.BigInteger),
        sa.column("local_user_id", sa.Integer),
        sa.column("local_token_id", sa.String),
        sa.column("github_repository_id", sa.BigInteger),
        sa.column("github_owner_id", sa.BigInteger),
        sa.column("charged_at", sa.DateTime(timezone=True)),
        sa.column("expires_at", sa.DateTime(timezone=True)),
    )
    rows: list[dict[str, object]] = []
    for row in connection.execute(
        sa.text("SELECT submitted_by_user_id, submitting_token_id, accepted_bytes, created_at FROM ingest_requests")
    ).mappings():
        charged_at = _aware(row["created_at"])
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "origin": "local",
                "accepted_bytes": row["accepted_bytes"],
                "local_user_id": row["submitted_by_user_id"],
                "local_token_id": row["submitting_token_id"],
                "github_repository_id": None,
                "github_owner_id": None,
                "charged_at": charged_at,
                "expires_at": charged_at + dt.timedelta(days=2),
            }
        )
    for row in connection.execute(
        sa.text("SELECT github_repository_id, github_owner_id, accepted_bytes, created_at FROM github_ingest_requests")
    ).mappings():
        charged_at = _aware(row["created_at"])
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "correlation_id": str(uuid.uuid4()),
                "origin": "github",
                "accepted_bytes": row["accepted_bytes"],
                "local_user_id": None,
                "local_token_id": None,
                "github_repository_id": row["github_repository_id"],
                "github_owner_id": row["github_owner_id"],
                "charged_at": charged_at,
                "expires_at": charged_at + dt.timedelta(days=2),
            }
        )
    if rows:
        connection.execute(charges.insert(), rows)


def _aware(value: object) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        value = dt.datetime.fromisoformat(str(value))
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value


def downgrade() -> None:
    raise RuntimeError("0036 is forward-only; restore the verified pre-migration backup to roll back")
