"""Add deterministic finding keys and bounded source contexts.

Revision ID: 0025_finding_source_contexts
Revises: 0024_project_memberships
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0025_finding_source_contexts"
down_revision: Union[str, None] = "0024_project_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("finding_key", sa.String(36), nullable=True))
    op.create_index(
        "uq_findings_run_key",
        "findings",
        ["run_id", "finding_key"],
        unique=True,
    )
    op.create_table(
        "source_contexts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("context_key", sa.String(36), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("window_start", sa.Integer(), nullable=True),
        sa.Column("window_end", sa.Integer(), nullable=True),
        sa.Column("highlight_start", sa.Integer(), nullable=True),
        sa.Column("highlight_end", sa.Integer(), nullable=True),
        sa.Column("highlight_truncated", sa.Boolean(), nullable=False),
        sa.Column("lines_json", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("redaction_version", sa.Integer(), nullable=False),
        sa.Column("redaction_changed", sa.Boolean(), nullable=False),
        sa.Column("unavailable_reason", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "context_key", name="uq_source_contexts_run_key"),
    )
    op.create_index("ix_source_contexts_run", "source_contexts", ["run_id"])
    op.create_table(
        "source_context_findings",
        sa.Column("context_id", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["context_id"], ["source_contexts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("context_id", "finding_id"),
    )
    op.create_index(
        "ix_source_context_findings_finding",
        "source_context_findings",
        ["finding_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "0025 is forward-only; restore the verified pre-migration backup to roll back"
    )
