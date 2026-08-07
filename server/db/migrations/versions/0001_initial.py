"""Phase 0 baseline schema: runs, scanner_runs, scanner_artifacts, findings.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-06

Scope: just enough to run scans and store findings. The full 13-table
schema (catalogue snapshots, FRs, evidence, waivers, etc.) lands in a
later migration when Phase 1 begins.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("findings_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )

    op.create_table(
        "scanner_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("scanner_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scanner_runs_run_kind",
        "scanner_runs",
        ["run_id", "scanner_kind"],
    )

    op.create_table(
        "scanner_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scanner_run_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content_blob", sa.LargeBinary(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scanner_run_id"],
            ["scanner_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("scanner_kind", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=256), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("theme", sa.String(length=64), nullable=True),
        sa.Column("fix_strategy", sa.String(length=32), nullable=True),
        sa.Column("compliance_tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("raw_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_run", "findings", ["run_id"])
    op.create_index("ix_findings_run_severity", "findings", ["run_id", "severity"])
    op.create_index("ix_findings_run_file", "findings", ["run_id", "file_path"])


def downgrade() -> None:
    op.drop_index("ix_findings_run_file", table_name="findings")
    op.drop_index("ix_findings_run_severity", table_name="findings")
    op.drop_index("ix_findings_run", table_name="findings")
    op.drop_table("findings")

    op.drop_table("scanner_artifacts")

    op.drop_index("ix_scanner_runs_run_kind", table_name="scanner_runs")
    op.drop_table("scanner_runs")

    op.drop_table("runs")
