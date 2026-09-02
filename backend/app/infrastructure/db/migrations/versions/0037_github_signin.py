"""Add clean-launch GitHub sign-in identity and pre-authentication state.

Revision ID: 0037_github_signin
Revises: 0036_ingest_usage_ledger
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0037_github_signin"
down_revision: Union[str, None] = "0036_ingest_usage_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This is an explicit clean launch. Discard credentials, transient states,
    # and authorization projections from the retired auth/pull architecture.
    op.execute("DELETE FROM github_installation_states")
    op.execute("DELETE FROM github_oauth_states")
    op.execute("DELETE FROM browser_sessions")
    op.execute("DELETE FROM project_memberships")
    op.drop_table("github_oauth_states")
    op.drop_table("identity_migration_journal")
    op.drop_table("organisations")
    op.drop_table("github_accounts")

    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.String(256), nullable=True)
        batch.add_column(sa.Column("github_login", sa.String(128), nullable=True))
        batch.drop_column("github_access_synced_at")

    with op.batch_alter_table("project_memberships") as batch:
        batch.drop_constraint("ck_project_memberships_source", type_="check")
        batch.drop_constraint("ck_project_memberships_github_app_expiry", type_="check")
        batch.create_check_constraint("ck_project_memberships_source", "source = 'github_app'")
        batch.create_check_constraint("ck_project_memberships_github_app_expiry", "expires_at IS NOT NULL")

    op.create_table(
        "github_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("login_at_last_verify", sa.String(128), nullable=True),
        sa.Column("encrypted_user_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("credential_key_id", sa.String(64), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("github_user_id > 0", name="ck_github_accounts_github_user_id"),
    )
    op.create_index("uq_github_accounts_user_id", "github_accounts", ["user_id"], unique=True)
    op.create_index(
        "uq_github_accounts_github_user_id",
        "github_accounts",
        ["github_user_id"],
        unique=True,
    )
    op.create_table(
        "github_signin_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_digest", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("transaction_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("return_path", sa.String(64), nullable=False),
        sa.Column("pkce_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("credential_key_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(id) = 36", name="ck_github_signin_states_id"),
        sa.CheckConstraint("length(state_digest) = 32", name="ck_github_signin_states_state_digest"),
        sa.CheckConstraint("length(transaction_digest) = 32", name="ck_github_signin_states_transaction_digest"),
        sa.CheckConstraint(
            "return_path IN ('/', '/projects', '/setup')",
            name="ck_github_signin_states_return_path",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_github_signin_states_expiry"),
    )
    op.create_index(
        "ix_github_signin_states_transaction_expiry",
        "github_signin_states",
        ["transaction_digest", "expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("0037 is forward-only; restore the verified pre-migration backup to roll back")
