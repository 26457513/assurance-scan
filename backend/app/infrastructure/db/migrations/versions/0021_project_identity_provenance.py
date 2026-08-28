"""Mandatory project identity and explicit scan provenance clean cutover.

Revision ID: 0021_project_identity_provenance
Revises: 0020_snapshot_source_branch
Create Date: 2026-08-28

This is intentionally forward-only. Rollback restores the verified pre-cutover
database backup with the matching application release.
"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.infrastructure.db.migrations.identity_preflight import (
    IdentityPlan,
    build_identity_plan,
    canonical_repository,
)


revision: str = "0021_project_identity_provenance"
down_revision: Union[str, None] = "0020_snapshot_source_branch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _project_id_columns() -> tuple[tuple[str, bool, str], ...]:
    return (
        ("catalogue_snapshots", False, "RESTRICT"),
        ("runs", False, "RESTRICT"),
        ("project_checkouts", False, "CASCADE"),
        ("waivers", False, "CASCADE"),
        ("finding_acceptances", False, "CASCADE"),
        ("agent_actions", True, "SET NULL"),
        ("compliance_mappings", False, "CASCADE"),
        ("compliance_mapping_snapshots", False, "CASCADE"),
    )


def _add_projection_columns() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.alter_column("local_path", existing_type=sa.String(1024), nullable=True)
        batch.add_column(sa.Column("github_repo_key", sa.String(256), nullable=True))
        batch.add_column(sa.Column("github_repository_id", sa.BigInteger(), nullable=True))
        batch.create_check_constraint(
            "ck_projects_has_locator",
            "local_path IS NOT NULL OR github_repo_key IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_projects_repository_id_has_key",
            "github_repository_id IS NULL OR github_repo_key IS NOT NULL",
        )

    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("label_key", sa.String(64), nullable=False),
        sa.Column("selector", sa.String(16), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("selector", name="uq_api_tokens_selector"),
        sa.CheckConstraint("length(id) = 36", name="ck_api_tokens_id"),
        sa.CheckConstraint("length(secret_digest) = 32", name="ck_api_tokens_secret_digest"),
        sa.CheckConstraint("token_version > 0", name="ck_api_tokens_version"),
    )
    op.create_index("ix_api_tokens_user_label", "api_tokens", ["user_id", "label_key"])
    op.create_index("ix_api_tokens_user_revoked", "api_tokens", ["user_id", "revoked_at"])

    for table, nullable, _ondelete in _project_id_columns():
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("project_checkouts") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("origin", sa.String(24), nullable=True))
        batch.add_column(sa.Column("repository_full_name_at_scan", sa.String(256), nullable=True))
        batch.add_column(sa.Column("working_tree_dirty", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("source_content_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source_manifest_version", sa.String(64), nullable=True))
        batch.add_column(sa.Column("submitted_by_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("submitting_token_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("payload_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("client_provenance_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("client_provenance_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("git_object_format", sa.String(8), nullable=True))
        batch.add_column(sa.Column("github_run_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("github_run_number", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("github_run_attempt", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("github_run_url", sa.String(2048), nullable=True))
        batch.add_column(sa.Column("github_event", sa.String(64), nullable=True))
        batch.add_column(sa.Column("github_actor", sa.String(256), nullable=True))
        batch.add_column(sa.Column("github_head_sha", sa.String(64), nullable=True))

    with op.batch_alter_table("scanner_runs") as batch:
        batch.add_column(sa.Column("image_reference", sa.String(512), nullable=True))
        batch.add_column(sa.Column("image_digest", sa.String(80), nullable=True))
        batch.add_column(sa.Column("tool_version", sa.String(128), nullable=True))
        batch.add_column(sa.Column("database_version_json", sa.Text(), nullable=True))


def _insert_and_resolve_projects(plan: IdentityPlan) -> dict[str, int]:
    connection = op.get_bind()
    for row in connection.execute(sa.text("SELECT id, github_repo, local_path FROM projects")):
        project_id, github_repo, local_path = row
        repository_value = github_repo
        if not repository_value and isinstance(local_path, str) and local_path.startswith("github:"):
            repository_value = local_path
        key = canonical_repository(str(repository_value))[1] if repository_value else None
        connection.execute(
            sa.text("UPDATE projects SET github_repo_key = :key WHERE id = :project_id"),
            {"key": key, "project_id": int(project_id)},
        )

    for creation in plan.projects_to_create:
        connection.execute(sa.text(
            "INSERT INTO projects "
            "(tag, local_path, github_repo, github_repo_key, github_repository_id, hidden, created_at) "
            "VALUES (:tag, NULL, :repository, :key, NULL, 0, CURRENT_TIMESTAMP)"
        ), {
            "tag": creation.tag,
            "repository": creation.repository,
            "key": creation.repository_key,
        })

    repository_ids = {
        str(key): int(project_id)
        for project_id, key in connection.execute(sa.text(
            "SELECT id, github_repo_key FROM projects WHERE github_repo_key IS NOT NULL"
        ))
    }
    targets: dict[str, int] = {}
    for path, target in plan.path_targets.items():
        kind, value = target.split(":", 1)
        targets[path] = int(value) if kind == "project" else repository_ids[value]
    return targets


def _project_repository(project_id: int) -> str | None:
    row = op.get_bind().execute(
        sa.text("SELECT github_repo FROM projects WHERE id = :project_id"),
        {"project_id": project_id},
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _project_legacy_rows(plan: IdentityPlan, targets: dict[str, int]) -> None:
    connection = op.get_bind()
    for table, _nullable, _ondelete in _project_id_columns():
        for path, project_id in targets.items():
            connection.execute(
                sa.text(f'UPDATE "{table}" SET project_id = :project_id WHERE project_path = :path'),
                {"project_id": project_id, "path": path},
            )

    for checkout_id, user_id in plan.checkout_users.items():
        connection.execute(
            sa.text("UPDATE project_checkouts SET user_id = :user_id WHERE id = :checkout_id"),
            {"user_id": user_id, "checkout_id": int(checkout_id)},
        )

    rows = connection.execute(sa.text(
        "SELECT run_id, project_path, commit_sha, options_json FROM runs ORDER BY run_id"
    )).fetchall()
    for run_id, project_path, commit_sha, options_json in rows:
        run_key = str(run_id)
        origin = plan.run_origins[run_key]
        options = json.loads(str(options_json or "{}"))
        project_id = targets[str(project_path)]
        repository = None
        if str(project_path).startswith("github:"):
            repository = canonical_repository(str(project_path))[0]
        elif origin == "github-actions":
            repository = _project_repository(project_id)
        object_format = None
        if commit_sha is not None:
            object_format = "sha1" if len(str(commit_sha)) == 40 else "sha256"
        github_run_id = None
        if origin == "github-actions":
            raw_id = options.get("github_run_id")
            if raw_id is None and run_key.startswith("gh-") and run_key[3:].isdigit():
                raw_id = run_key[3:]
            github_run_id = int(raw_id) if raw_id is not None and str(raw_id).isdigit() else None
        connection.execute(sa.text(
            "UPDATE runs SET origin = :origin, repository_full_name_at_scan = :repository, "
            "working_tree_dirty = :dirty, git_object_format = :object_format, "
            "github_run_id = :github_run_id, github_run_number = :github_run_number, "
            "github_run_attempt = :github_run_attempt, github_run_url = :github_run_url, "
            "github_event = :github_event, github_actor = :github_actor, "
            "github_head_sha = :github_head_sha WHERE run_id = :run_id"
        ), {
            "origin": origin,
            "repository": repository,
            "dirty": False if origin == "github-actions" else None,
            "object_format": object_format,
            "github_run_id": github_run_id,
            "github_run_number": options.get("run_number"),
            "github_run_attempt": options.get("run_attempt"),
            "github_run_url": options.get("run_url"),
            "github_event": options.get("event"),
            "github_actor": options.get("actor"),
            "github_head_sha": str(commit_sha) if origin == "github-actions" and commit_sha else None,
            "run_id": run_key,
        })


def _finalize_projects() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.create_unique_constraint("uq_projects_github_repo_key", ["github_repo_key"])
        batch.create_unique_constraint("uq_projects_github_repository_id", ["github_repository_id"])


def _finalize_run_tables() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("project_path")
        batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("origin", existing_type=sa.String(24), nullable=False)
        batch.alter_column("git_branch", existing_type=sa.String(64), type_=sa.String(512), nullable=True)
        batch.create_foreign_key("fk_runs_project", "projects", ["project_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key(
            "fk_runs_submitted_user", "users", ["submitted_by_user_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_foreign_key(
            "fk_runs_submitting_token", "api_tokens", ["submitting_token_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_check_constraint("ck_runs_origin", "origin IN ('github-actions', 'local', 'server')")
        batch.create_check_constraint(
            "ck_runs_commit_object_format",
            "(commit_sha IS NULL AND git_object_format IS NULL) OR "
            "(git_object_format = 'sha1' AND length(commit_sha) = 40 "
            "AND commit_sha NOT GLOB '*[^0-9a-f]*') OR "
            "(git_object_format = 'sha256' AND length(commit_sha) = 64 "
            "AND commit_sha NOT GLOB '*[^0-9a-f]*')",
        )
        batch.create_check_constraint(
            "ck_runs_source_content_hash",
            "source_content_hash IS NULL OR (length(source_content_hash) = 64 "
            "AND source_content_hash NOT GLOB '*[^0-9a-f]*')",
        )
        batch.create_check_constraint(
            "ck_runs_payload_hash",
            "payload_hash IS NULL OR (length(payload_hash) = 64 "
            "AND payload_hash NOT GLOB '*[^0-9a-f]*')",
        )
        batch.create_check_constraint(
            "ck_runs_github_provenance",
            "origin != 'github-actions' OR (working_tree_dirty = 0 "
            "AND commit_sha IS NOT NULL AND github_run_id IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_runs_local_provenance",
            "origin != 'local' OR (working_tree_dirty IS NOT NULL "
            "AND source_content_hash IS NOT NULL AND source_manifest_version IS NOT NULL "
            "AND submitted_by_user_id IS NOT NULL AND submitting_token_id IS NOT NULL "
            "AND commit_sha IS NOT NULL)",
        )
        batch.create_index("ix_runs_project_started", ["project_id", "started_at", "run_id"])
        batch.create_index(
            "ix_runs_project_origin_started", ["project_id", "origin", "started_at", "run_id"]
        )
        batch.create_index("ix_runs_project_commit", ["project_id", "commit_sha"])
        batch.create_index("uq_runs_github_run_id", ["github_run_id"], unique=True)

    with op.batch_alter_table("scanner_runs") as batch:
        batch.create_unique_constraint("uq_scanner_runs_run_kind", ["run_id", "scanner_kind"])
        batch.create_check_constraint(
            "ck_scanner_runs_image_digest",
            "image_digest IS NULL OR (length(image_digest) = 71 "
            "AND substr(image_digest, 1, 7) = 'sha256:' "
            "AND substr(image_digest, 8) NOT GLOB '*[^0-9a-f]*')",
        )


def _finalize_project_tables() -> None:
    with op.batch_alter_table("catalogue_snapshots") as batch:
        batch.drop_column("project_path")
        batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("source_branch", existing_type=sa.String(64), type_=sa.String(512), nullable=True)
        batch.create_foreign_key(
            "fk_catalogue_snapshots_project", "projects", ["project_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_catalogue_snapshots_project_created", ["project_id", "created_at"])

    with op.batch_alter_table("frs") as batch:
        batch.drop_index("ix_frs_project")
        batch.drop_column("project_path")

    with op.batch_alter_table("project_checkouts") as batch:
        batch.drop_index("ix_project_checkouts_project")
        batch.drop_constraint("uq_project_checkouts_user_project", type_="unique")
        batch.drop_column("user_email")
        batch.drop_column("project_path")
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_project_checkouts_user", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_project_checkouts_project", "projects", ["project_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_unique_constraint("uq_project_checkouts_user_project", ["user_id", "project_id"])
        batch.create_index("ix_project_checkouts_project", ["project_id"])

    for table, index_name in (
        ("test_results", "ix_test_results_project_fr"),
        ("evidence", "ix_evidence_project_fr"),
        ("fr_state", "ix_fr_state_project"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(index_name)
            batch.drop_column("project_path")

    for table, index_name, columns, ondelete in (
        ("waivers", "ix_waivers_project_fr", ["project_id", "fr_id"], "CASCADE"),
        (
            "finding_acceptances",
            "ix_finding_acceptances_lookup",
            ["project_id", "scanner_kind", "rule_id"],
            "CASCADE",
        ),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(index_name)
            batch.drop_column("project_path")
            batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(
                f"fk_{table}_project", "projects", ["project_id"], ["id"], ondelete=ondelete
            )
            batch.create_index(index_name, columns)

    with op.batch_alter_table("agent_actions") as batch:
        batch.drop_column("project_path")
        batch.create_foreign_key(
            "fk_agent_actions_project", "projects", ["project_id"], ["id"], ondelete="SET NULL"
        )

    for table, index_name, columns in (
        ("compliance_mappings", "ix_compliance_mappings_project", ["project_id"]),
        (
            "compliance_mapping_snapshots",
            "ix_compliance_mapping_snapshots_project",
            ["project_id", "loaded_at"],
        ),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(index_name)
            batch.drop_column("project_path")
            batch.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(
                f"fk_{table}_project", "projects", ["project_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_index(index_name, columns)


def _create_ingest_requests() -> None:
    op.create_table(
        "ingest_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "submitted_by_user_id", "client_request_id", name="uq_ingest_requests_user_request"
        ),
        sa.UniqueConstraint("run_id", name="uq_ingest_requests_run"),
        sa.CheckConstraint(
            "state IN ('processing', 'completed', 'failed')", name="ck_ingest_requests_state"
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64 AND payload_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_ingest_requests_payload_hash",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR run_id IS NOT NULL", name="ck_ingest_requests_completed_run"
        ),
    )
    op.create_index(
        "ix_ingest_requests_project_created", "ingest_requests", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_ingest_requests_state_lease", "ingest_requests", ["state", "lease_expires_at"]
    )


def upgrade() -> None:
    connection = op.get_bind()
    plan = build_identity_plan(connection)
    _add_projection_columns()
    targets = _insert_and_resolve_projects(plan)
    _project_legacy_rows(plan, targets)
    _finalize_projects()
    _finalize_project_tables()
    _finalize_run_tables()
    _create_ingest_requests()


def downgrade() -> None:
    raise RuntimeError(
        "0021 is a clean cutover; restore the verified pre-migration backup "
        "and deploy the matching previous application release"
    )
