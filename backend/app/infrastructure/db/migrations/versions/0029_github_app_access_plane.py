"""Add dormant GitHub App installation access-plane storage.

Revision ID: 0029_github_app_access_plane
Revises: 0028_identity_cutover_journal
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0029_github_app_access_plane"
down_revision: Union[str, None] = "0028_identity_cutover_journal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "github_app_installations",
        sa.Column("github_installation_id", sa.BigInteger(), primary_key=True),
        sa.Column("github_owner_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_login_at_last_verify", sa.String(128), nullable=False),
        sa.Column("account_type", sa.String(16), nullable=False),
        sa.Column("repository_selection", sa.String(16), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("repositories_etag", sa.String(256), nullable=True),
        sa.Column("reconciliation_cursor", sa.String(512), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("github_installation_id > 0", name="ck_github_app_installations_id"),
        sa.CheckConstraint("github_owner_id > 0", name="ck_github_app_installations_owner_id"),
        sa.CheckConstraint(
            "account_type IN ('user', 'organization', 'enterprise')",
            name="ck_github_app_installations_account_type",
        ),
        sa.CheckConstraint(
            "repository_selection IN ('all', 'selected')",
            name="ck_github_app_installations_selection",
        ),
    )
    op.create_index(
        "ix_github_app_installations_owner_active",
        "github_app_installations",
        ["github_owner_id", "deleted_at", "suspended_at"],
    )
    op.create_table(
        "github_installation_repositories",
        sa.Column("github_installation_id", sa.BigInteger(), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("repository_full_name", sa.String(256), nullable=False),
        sa.Column("github_owner_id", sa.BigInteger(), nullable=False),
        sa.Column("default_branch", sa.String(256), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("repository_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["github_installation_id"],
            ["github_app_installations.github_installation_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint(
            "github_installation_id",
            "github_repository_id",
            name="pk_github_installation_repositories",
        ),
        sa.UniqueConstraint(
            "github_repository_id",
            name="uq_github_installation_repositories_repository",
        ),
        sa.CheckConstraint("github_repository_id > 0", name="ck_github_installation_repositories_id"),
        sa.CheckConstraint("github_owner_id > 0", name="ck_github_installation_repositories_owner_id"),
        sa.CheckConstraint(
            "visibility IN ('public', 'private', 'internal')",
            name="ck_github_installation_repositories_visibility",
        ),
    )
    op.create_index(
        "ix_github_installation_repositories_project",
        "github_installation_repositories",
        ["project_id"],
    )
    op.create_index(
        "ix_github_installation_repositories_active",
        "github_installation_repositories",
        ["github_installation_id", "removed_at", "disabled", "archived"],
    )
    op.create_table(
        "github_installation_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("browser_session_id", sa.String(36), nullable=False),
        sa.Column("return_path", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["browser_session_id"], ["browser_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("state_digest", name="uq_github_installation_states_digest"),
        sa.CheckConstraint("length(id) = 36", name="ck_github_installation_states_id"),
        sa.CheckConstraint("length(state_digest) = 32", name="ck_github_installation_states_digest"),
        sa.CheckConstraint(
            "return_path IN ('/', '/projects', '/setup')",
            name="ck_github_installation_states_return_path",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_github_installation_states_expiry"),
    )
    op.create_index(
        "ix_github_installation_states_expiry",
        "github_installation_states",
        ["expires_at", "consumed_at"],
    )
    op.create_table(
        "github_webhook_deliveries",
        sa.Column("delivery_id", sa.String(36), primary_key=True),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(delivery_id) = 36", name="ck_github_webhook_deliveries_id"),
        sa.CheckConstraint("length(body_hash) = 64", name="ck_github_webhook_deliveries_hash"),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'acknowledged', 'failed')",
            name="ck_github_webhook_deliveries_status",
        ),
        sa.CheckConstraint("expires_at > received_at", name="ck_github_webhook_deliveries_expiry"),
    )
    op.create_index(
        "ix_github_webhook_deliveries_expiry",
        "github_webhook_deliveries",
        ["expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("0029 is forward-only; restore the verified pre-migration backup to roll back")
