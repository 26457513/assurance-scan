"""v3: introduce test_results table.

The v2 evidence model is replaced by per-test evaluations. Each test on
an FR gets one row per run with pass/fail/pending + a detail dict.

Revision ID: 0003_v3_test_results
Revises: 0002_phase1_full_schema
Create Date: 2026-08-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_v3_test_results"
down_revision: Union[str, None] = "0002_phase1_full_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "test_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("fr_id", sa.String(length=64), nullable=False),
        sa.Column("test_id", sa.String(length=128), nullable=False),
        sa.Column("test_type", sa.String(length=32), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "fr_id", "test_id", name="uq_test_results_run_fr_test"),
    )
    op.create_index("ix_test_results_run", "test_results", ["run_id"])
    op.create_index("ix_test_results_run_fr", "test_results", ["run_id", "fr_id"])
    op.create_index("ix_test_results_project_fr", "test_results", ["project_path", "fr_id"])

    # v3 also adds category + lifecycle_status columns to frs.
    with op.batch_alter_table("frs") as batch:
        batch.add_column(sa.Column("category", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("lifecycle_status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("frs") as batch:
        batch.drop_column("lifecycle_status")
        batch.drop_column("category")

    op.drop_index("ix_test_results_project_fr", table_name="test_results")
    op.drop_index("ix_test_results_run_fr", table_name="test_results")
    op.drop_index("ix_test_results_run", table_name="test_results")
    op.drop_table("test_results")
