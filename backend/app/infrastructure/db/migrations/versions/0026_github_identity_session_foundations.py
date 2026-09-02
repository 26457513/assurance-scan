"""Add dormant GitHub identity, OAuth-state and browser-session foundations.

Revision ID: 0026_github_identity_sessions
Revises: 0025_finding_source_contexts
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0026_github_identity_sessions"
down_revision: Union[str, None] = "0025_finding_source_contexts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("github_accounts") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("github_user_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("login_at_last_verify", sa.String(128), nullable=True))
        batch.add_column(sa.Column("encrypted_user_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("encrypted_refresh_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("credential_key_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_github_accounts_user_id", "users", ["user_id"], ["id"], ondelete="RESTRICT")
        batch.create_check_constraint(
            "ck_github_accounts_identity_pair",
            "(user_id IS NULL AND github_user_id IS NULL) OR (user_id IS NOT NULL AND github_user_id IS NOT NULL)",
        )
    op.create_index("uq_github_accounts_user_id", "github_accounts", ["user_id"], unique=True)
    op.create_index("uq_github_accounts_github_user_id", "github_accounts", ["github_user_id"], unique=True)

    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rotated_from_id"], ["browser_sessions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("session_digest", name="uq_browser_sessions_digest"),
        sa.CheckConstraint("length(id) = 36", name="ck_browser_sessions_id"),
        sa.CheckConstraint("length(session_digest) = 32", name="ck_browser_sessions_digest"),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_browser_sessions_expiry_order",
        ),
    )
    op.create_index("ix_browser_sessions_user_active", "browser_sessions", ["user_id", "revoked_at"])
    op.create_index("ix_browser_sessions_absolute_expiry", "browser_sessions", ["absolute_expires_at"])

    op.create_table(
        "github_oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("browser_session_id", sa.String(36), nullable=False),
        sa.Column("flow_kind", sa.String(16), nullable=False),
        sa.Column("return_path", sa.String(64), nullable=False),
        sa.Column("pkce_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("credential_key_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("state_digest", name="uq_github_oauth_states_digest"),
        sa.CheckConstraint("length(id) = 36", name="ck_github_oauth_states_id"),
        sa.CheckConstraint("length(state_digest) = 32", name="ck_github_oauth_states_digest"),
        sa.CheckConstraint("flow_kind IN ('signin', 'link')", name="ck_github_oauth_states_flow"),
        sa.CheckConstraint(
            "return_path IN ('/', '/projects', '/setup')",
            name="ck_github_oauth_states_return_path",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_github_oauth_states_expiry"),
    )
    op.create_index(
        "ix_github_oauth_states_session_expiry",
        "github_oauth_states",
        ["browser_session_id", "expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("0026 is forward-only; restore the verified pre-migration backup to roll back")
