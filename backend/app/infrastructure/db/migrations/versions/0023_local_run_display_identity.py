"""Add stable local-run sequence numbers and machine labels.

Revision ID: 0023_local_run_display_identity
Revises: 0022_local_ingest_claims
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0023_local_run_display_identity"
down_revision: Union[str, None] = "0022_local_ingest_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("local_run_counter", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("runs", sa.Column("local_run_number", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("local_machine_label", sa.String(64), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT run_id, project_id FROM runs WHERE origin = 'local' "
            "ORDER BY project_id, started_at, run_id"
        )
    ).mappings()
    counters: dict[int, int] = {}
    for row in rows:
        project_id = int(row["project_id"])
        number = counters.get(project_id, 0) + 1
        counters[project_id] = number
        connection.execute(
            sa.text(
                "UPDATE runs SET local_run_number = :number, "
                "local_machine_label = ("
                "SELECT label FROM api_tokens WHERE api_tokens.id = runs.submitting_token_id"
                ") WHERE run_id = :run_id"
            ),
            {"number": number, "run_id": row["run_id"]},
        )
    for project_id, counter in counters.items():
        connection.execute(
            sa.text(
                "UPDATE projects SET local_run_counter = :counter WHERE id = :project_id"
            ),
            {"counter": counter, "project_id": project_id},
        )

    op.create_index(
        "uq_runs_project_local_number",
        "runs",
        ["project_id", "local_run_number"],
        unique=True,
    )


def downgrade() -> None:
    raise RuntimeError(
        "0023 is forward-only; restore the verified pre-migration backup to roll back"
    )
