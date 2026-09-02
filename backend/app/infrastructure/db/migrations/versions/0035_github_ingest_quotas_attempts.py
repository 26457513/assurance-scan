"""Add GitHub owner quota identity and safe ingest-attempt evidence.

Revision ID: 0035_github_ingest_quotas_attempts
Revises: 0034_github_ingest_claims
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0035_github_ingest_quotas_attempts"
down_revision: Union[str, None] = "0034_github_ingest_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("github_ingest_requests") as batch:
        batch.add_column(sa.Column("github_owner_id", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE github_ingest_requests SET github_owner_id = ("
        "SELECT github_owner_id FROM github_installation_repositories "
        "WHERE github_installation_repositories.github_repository_id = "
        "github_ingest_requests.github_repository_id)"
    )
    # The push route remains disabled before this migration. Orphaned candidate
    # claims cannot be authenticated against an active installation, so discard
    # them instead of guessing a mutable or transferred owner identity.
    op.execute("DELETE FROM github_ingest_requests WHERE github_owner_id IS NULL")
    with op.batch_alter_table("github_ingest_requests") as batch:
        batch.alter_column("github_owner_id", existing_type=sa.BigInteger(), nullable=False)
        batch.drop_constraint("ck_github_ingest_requests_identity", type_="check")
        batch.create_check_constraint(
            "ck_github_ingest_requests_identity",
            "github_repository_id > 0 AND github_owner_id > 0 AND github_run_id > 0 AND run_attempt > 0",
        )
        batch.create_index(
            "ix_github_ingest_requests_owner_created",
            ["github_owner_id", "created_at"],
        )

    op.create_table(
        "ingest_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("correlation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("principal_kind", sa.String(32), nullable=False),
        sa.Column("principal_reference_hash", sa.String(64), nullable=False),
        sa.Column("canonical_request_key_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("wire_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("origin IN ('github', 'local')", name="ck_ingest_attempts_origin"),
        sa.CheckConstraint(
            "principal_kind IN ('github_oidc', 'local_token')",
            name="ck_ingest_attempts_principal_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'replayed', 'rejected', 'failed_internal')",
            name="ck_ingest_attempts_outcome",
        ),
        sa.CheckConstraint("wire_bytes >= 0", name="ck_ingest_attempts_wire_bytes"),
        sa.CheckConstraint("expires_at > received_at", name="ck_ingest_attempts_expiry"),
        sa.CheckConstraint("completed_at >= received_at", name="ck_ingest_attempts_completion"),
        sa.CheckConstraint("length(id) = 36", name="ck_ingest_attempts_id"),
        sa.CheckConstraint("length(correlation_id) = 36", name="ck_ingest_attempts_correlation"),
        sa.CheckConstraint(
            "length(principal_reference_hash) = 64 AND length(canonical_request_key_hash) = 64",
            name="ck_ingest_attempts_hashes",
        ),
        sa.CheckConstraint(
            "(origin = 'github' AND principal_kind = 'github_oidc' "
            "AND submitted_by_user_id IS NULL) OR "
            "(origin = 'local' AND principal_kind = 'local_token' "
            "AND submitted_by_user_id IS NOT NULL)",
            name="ck_ingest_attempts_identity",
        ),
    )
    op.create_index("ix_ingest_attempts_project_received", "ingest_attempts", ["project_id", "received_at"])
    op.create_index("ix_ingest_attempts_expires", "ingest_attempts", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("0035 is forward-only; restore the verified pre-migration backup to roll back")
