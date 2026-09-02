"""Add leased GitHub run-attempt ingestion claims.

Revision ID: 0034_github_ingest_claims
Revises: 0033_github_run_attempt_identity
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0034_github_ingest_claims"
down_revision: Union[str, None] = "0033_github_run_attempt_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_ingest_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("github_run_id", sa.BigInteger(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted_bytes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("lease_id", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstone_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "github_repository_id > 0 AND github_run_id > 0 AND run_attempt > 0",
            name="ck_github_ingest_requests_identity",
        ),
        sa.CheckConstraint(
            "state IN ('processing', 'completed', 'failed', 'tombstoned')",
            name="ck_github_ingest_requests_state",
        ),
        sa.CheckConstraint(
            "accepted_bytes >= 0", name="ck_github_ingest_requests_accepted_bytes"
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64 AND payload_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_github_ingest_requests_payload_hash",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR run_id IS NOT NULL",
            name="ck_github_ingest_requests_completed_run",
        ),
        sa.CheckConstraint(
            "state != 'processing' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_github_ingest_requests_processing_lease",
        ),
        sa.CheckConstraint(
            "state != 'tombstoned' OR (run_id IS NULL AND tombstoned_at IS NOT NULL "
            "AND tombstone_expires_at IS NOT NULL)",
            name="ck_github_ingest_requests_tombstone",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "github_repository_id",
            "github_run_id",
            "run_attempt",
            name="uq_github_ingest_requests_run_attempt",
        ),
        sa.UniqueConstraint("run_id", name="uq_github_ingest_requests_run"),
    )
    op.create_index(
        "ix_github_ingest_requests_repository_created",
        "github_ingest_requests",
        ["github_repository_id", "created_at"],
    )
    op.create_index(
        "ix_github_ingest_requests_state_lease",
        "github_ingest_requests",
        ["state", "lease_expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("0034 is forward-only; restore the verified pre-migration backup to roll back")
