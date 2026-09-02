"""Add restart-safe identity cutover disposition and journal fields.

Revision ID: 0028_identity_cutover_journal
Revises: 0027_github_account_linking
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0028_identity_cutover_journal"
down_revision: Union[str, None] = "0027_github_account_linking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column(
                "lifecycle_state",
                sa.String(32),
                nullable=False,
                server_default="active",
            )
        )
        batch.create_check_constraint(
            "ck_projects_lifecycle_state",
            "lifecycle_state IN ('active', 'legacy_unbound')",
        )
    op.add_column(
        "runs",
        sa.Column("legacy_retained", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "identity_migration_journal",
        sa.Column("phase", sa.String(32), primary_key=True),
        sa.Column("preflight_checksum", sa.String(64), nullable=False),
        sa.Column("state_checksum", sa.String(64), nullable=False),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('preflight_verified', 'dispositions_applied', "
            "'run_ids_migrated', 'validated', 'switch_complete')",
            name="ck_identity_migration_journal_phase",
        ),
        sa.CheckConstraint(
            "length(preflight_checksum) = 64",
            name="ck_identity_migration_journal_preflight_checksum",
        ),
        sa.CheckConstraint(
            "length(state_checksum) = 64",
            name="ck_identity_migration_journal_state_checksum",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("0028 is forward-only; restore the verified pre-migration backup to roll back")
