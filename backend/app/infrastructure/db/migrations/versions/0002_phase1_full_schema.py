"""Phase 1 full schema: catalogue, FRs, evidence, state, waivers, audit.

Adds: catalogue_snapshots, frs, scan_jobs, evidence, fr_state, waivers,
agent_actions. Also adds new columns to `runs` (catalogue_snapshot_id,
evidence_bundle_json).

Revision ID: 0002_phase1_full_schema
Revises: 0001_initial
Create Date: 2026-08-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002_phase1_full_schema"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Catalogue group
    op.create_table(
        "catalogue_snapshots",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("catalogue_version", sa.String(length=64), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "frs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("catalogue_snapshot_id", sa.String(length=64), nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("fr_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("implemented_by_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("required_evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("satisfies_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("depends_on_json", sa.Text(), nullable=False, server_default="[]"),
        sa.ForeignKeyConstraint(
            ["catalogue_snapshot_id"],
            ["catalogue_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("catalogue_snapshot_id", "fr_id", name="uq_frs_snapshot_fr"),
    )
    op.create_index("ix_frs_project", "frs", ["project_path"])
    op.create_index("ix_frs_snapshot", "frs", ["catalogue_snapshot_id"])

    # Extend runs with catalogue + evidence bundle references
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column("catalogue_snapshot_id", sa.String(length=64), nullable=True)
        )
        batch.add_column(sa.Column("evidence_bundle_json", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_runs_catalogue_snapshot",
            "catalogue_snapshots",
            ["catalogue_snapshot_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Run state machine
    op.create_table(
        "scan_jobs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )

    # Evidence
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("fr_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("source_json", sa.Text(), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("artifact_ref", sa.String(length=80), nullable=True),
        sa.Column("artifact_hash", sa.String(length=80), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_run_fr", "evidence", ["run_id", "fr_id"])
    op.create_index("ix_evidence_project_fr", "evidence", ["project_path", "fr_id"])

    # Cached state
    op.create_table(
        "fr_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("fr_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fr_state_project", "fr_state", ["project_path"])
    op.create_index("ix_fr_state_run", "fr_state", ["run_id"])

    # Waivers
    op.create_table(
        "waivers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=False),
        sa.Column("fr_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("waived_by", sa.String(length=128), nullable=False),
        sa.Column("waived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_waivers_project_fr", "waivers", ["project_path", "fr_id"])

    # Audit log
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_path", sa.String(length=1024), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("action_kind", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_actions_run", "agent_actions", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_actions_run", table_name="agent_actions")
    op.drop_table("agent_actions")

    op.drop_index("ix_waivers_project_fr", table_name="waivers")
    op.drop_table("waivers")

    op.drop_index("ix_fr_state_run", table_name="fr_state")
    op.drop_index("ix_fr_state_project", table_name="fr_state")
    op.drop_table("fr_state")

    op.drop_index("ix_evidence_project_fr", table_name="evidence")
    op.drop_index("ix_evidence_run_fr", table_name="evidence")
    op.drop_table("evidence")

    op.drop_table("scan_jobs")

    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("fk_runs_catalogue_snapshot", type_="foreignkey")
        batch.drop_column("evidence_bundle_json")
        batch.drop_column("catalogue_snapshot_id")

    op.drop_index("ix_frs_snapshot", table_name="frs")
    op.drop_index("ix_frs_project", table_name="frs")
    op.drop_table("frs")

    op.drop_table("catalogue_snapshots")
