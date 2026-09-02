"""Use repository-scoped GitHub run-attempt identity.

Revision ID: 0033_github_run_attempt_identity
Revises: 0032_github_oidc_replays
Create Date: 2026-09-02
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0033_github_run_attempt_identity"
down_revision: Union[str, None] = "0032_github_oidc_replays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("uq_runs_github_run_id", table_name="runs")
    op.create_index(
        "uq_runs_project_github_run_attempt",
        "runs",
        ["project_id", "github_run_id", "github_run_attempt"],
        unique=True,
    )


def downgrade() -> None:
    raise RuntimeError("0033 is forward-only; restore the verified pre-migration backup to roll back")
