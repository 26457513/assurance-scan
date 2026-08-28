"""Fence local-ingest claims and preserve deletion tombstones.

Revision ID: 0022_local_ingest_claims
Revises: 0021_project_identity_provenance
Create Date: 2026-08-28

The local-ingest feature remained disabled through 0021, so a non-empty claim
table indicates unsupported pre-release data whose token and byte attribution
cannot be reconstructed safely. The migration aborts before changing schema in
that case.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022_local_ingest_claims"
down_revision: Union[str, None] = "0021_project_identity_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    claim_count = connection.execute(sa.text("SELECT count(*) FROM ingest_requests")).scalar_one()
    if claim_count:
        raise RuntimeError(
            "0022 cannot attribute pre-release ingest claims to a token or byte quota; "
            "LOCAL_INGEST_ENABLED was required to remain false through 0021. Restore the "
            "verified backup and remove unsupported ingest_requests before retrying."
        )

    # SQLite cannot reliably address the unnamed 0021 run foreign key. Since
    # the table is guaranteed empty above, replacing it is deterministic and
    # avoids relying on dialect-generated constraint names.
    op.drop_table("ingest_requests")
    op.create_table(
        "ingest_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("submitting_token_id", sa.String(36), nullable=False),
        sa.Column("client_request_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("accepted_bytes", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("lease_id", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstone_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["submitting_token_id"], ["api_tokens.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "submitted_by_user_id",
            "client_request_id",
            name="uq_ingest_requests_user_request",
        ),
        sa.UniqueConstraint("run_id", name="uq_ingest_requests_run"),
        sa.CheckConstraint(
            "state IN ('processing', 'completed', 'failed', 'tombstoned')",
            name="ck_ingest_requests_state",
        ),
        sa.CheckConstraint(
            "accepted_bytes >= 0", name="ck_ingest_requests_accepted_bytes"
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64 AND payload_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_ingest_requests_payload_hash",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR run_id IS NOT NULL",
            name="ck_ingest_requests_completed_run",
        ),
        sa.CheckConstraint(
            "state != 'processing' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_ingest_requests_processing_lease",
        ),
        sa.CheckConstraint(
            "state != 'tombstoned' OR (run_id IS NULL AND tombstoned_at IS NOT NULL "
            "AND tombstone_expires_at IS NOT NULL)",
            name="ck_ingest_requests_tombstone",
        ),
    )
    op.create_index(
        "ix_ingest_requests_project_created", "ingest_requests", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_ingest_requests_state_lease", "ingest_requests", ["state", "lease_expires_at"]
    )
    op.create_index(
        "ix_ingest_requests_token_created",
        "ingest_requests",
        ["submitting_token_id", "created_at"],
    )
    op.create_index(
        "ix_ingest_requests_user_created",
        "ingest_requests",
        ["submitted_by_user_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "0022 is forward-only; restore the verified pre-migration backup to roll back"
    )
