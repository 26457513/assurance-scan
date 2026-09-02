"""SQLAlchemy ORM models for the Alembic-managed Assurance Scan schema."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Common declarative base."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Catalogue group
# ---------------------------------------------------------------------------


class CatalogueSnapshot(Base):
    """Immutable per-load copy of an FR catalogue. FK'd from every run that
    used it, so historical runs stay interpretable when the catalogue changes."""

    __tablename__ = "catalogue_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    catalogue_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    source_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_branch: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_catalogue_snapshots_project_created", "project_id", "created_at"),)


class Fr(Base):
    """One FR at a point in time. The same FR ID can appear in many snapshots."""

    __tablename__ = "frs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalogue_snapshot_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalogue_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    implemented_by_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    satisfies_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    __table_args__ = (
        UniqueConstraint("catalogue_snapshot_id", "fr_id", name="uq_frs_snapshot_fr"),
        Index("ix_frs_snapshot", "catalogue_snapshot_id"),
    )


# ---------------------------------------------------------------------------
# Run group
# ---------------------------------------------------------------------------


class Project(Base):
    """Durable project identity with optional local and GitHub locators."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    local_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    github_repo: Mapped[str | None] = mapped_column(String(256), nullable=True)
    github_repo_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    github_repository_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_scan_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    local_run_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "local_path IS NOT NULL OR github_repo_key IS NOT NULL",
            name="ck_projects_has_locator",
        ),
        CheckConstraint(
            "github_repository_id IS NULL OR github_repo_key IS NOT NULL",
            name="ck_projects_repository_id_has_key",
        ),
        CheckConstraint(
            "lifecycle_state IN ('active', 'legacy_unbound')",
            name="ck_projects_lifecycle_state",
        ),
        Index("uq_projects_local_path", "local_path", unique=True),
        Index("uq_projects_github_repo_key", "github_repo_key", unique=True),
        Index(
            "uq_projects_github_repository_id",
            "github_repository_id",
            unique=True,
        ),
    )


class Run(Base):
    """One scan execution against a project."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    catalogue_snapshot_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("catalogue_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    options_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(512), nullable=True)
    git_object_format: Mapped[str | None] = mapped_column(String(8), nullable=True)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    repository_full_name_at_scan: Mapped[str | None] = mapped_column(String(256), nullable=True)
    working_tree_dirty: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_manifest_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    submitting_token_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_tokens.id", ondelete="RESTRICT"), nullable=True
    )
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_provenance_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    github_run_number: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    github_run_attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_run_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    github_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    github_actor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    github_head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_run_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_machine_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapping_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_bundle_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    legacy_retained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    scanner_runs: Mapped[list["ScannerRun"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ScannerRun.scanner_kind",
    )

    __table_args__ = (
        CheckConstraint(
            "origin IN ('github-actions', 'local', 'server')",
            name="ck_runs_origin",
        ),
        CheckConstraint(
            "(commit_sha IS NULL AND git_object_format IS NULL) OR "
            "(git_object_format = 'sha1' AND length(commit_sha) = 40 "
            "AND commit_sha NOT GLOB '*[^0-9a-f]*') OR "
            "(git_object_format = 'sha256' AND length(commit_sha) = 64 "
            "AND commit_sha NOT GLOB '*[^0-9a-f]*')",
            name="ck_runs_commit_object_format",
        ),
        CheckConstraint(
            "source_content_hash IS NULL OR "
            "(length(source_content_hash) = 64 "
            "AND source_content_hash NOT GLOB '*[^0-9a-f]*')",
            name="ck_runs_source_content_hash",
        ),
        CheckConstraint(
            "payload_hash IS NULL OR (length(payload_hash) = 64 AND payload_hash NOT GLOB '*[^0-9a-f]*')",
            name="ck_runs_payload_hash",
        ),
        CheckConstraint(
            "origin != 'github-actions' OR (working_tree_dirty = 0 "
            "AND commit_sha IS NOT NULL AND github_run_id IS NOT NULL)",
            name="ck_runs_github_provenance",
        ),
        CheckConstraint(
            "origin != 'local' OR (working_tree_dirty IS NOT NULL "
            "AND source_content_hash IS NOT NULL "
            "AND source_manifest_version IS NOT NULL "
            "AND submitted_by_user_id IS NOT NULL "
            "AND submitting_token_id IS NOT NULL "
            "AND commit_sha IS NOT NULL)",
            name="ck_runs_local_provenance",
        ),
        CheckConstraint(
            "local_run_number IS NULL OR local_run_number > 0",
            name="ck_runs_local_run_number_positive",
        ),
        Index("ix_runs_project_started", "project_id", "started_at", "run_id"),
        Index("ix_runs_project_origin_started", "project_id", "origin", "started_at", "run_id"),
        Index("ix_runs_project_commit", "project_id", "commit_sha"),
        Index(
            "uq_runs_project_github_run_attempt",
            "project_id",
            "github_run_id",
            "github_run_attempt",
            unique=True,
        ),
        Index(
            "uq_runs_project_local_number",
            "project_id",
            "local_run_number",
            unique=True,
        ),
    )


class User(Base):
    """GitHub-backed UI account; application roles gate admin surfaces."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    github_login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SHA-256 of the user's MCP bearer token; the plaintext is shown once
    # at generation/rotation and never stored.
    mcp_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mcp_token_generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    github_app_access_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectMembership(Base):
    """One source of a user's current authorization for a project."""

    __tablename__ = "project_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    verified_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "project_id", "source", name="uq_project_memberships_source"),
        CheckConstraint(
            "permission IN ('view', 'upload', 'manage')",
            name="ck_project_memberships_permission",
        ),
        CheckConstraint("source = 'github_app'", name="ck_project_memberships_source"),
        CheckConstraint("expires_at IS NOT NULL", name="ck_project_memberships_github_app_expiry"),
        Index("ix_project_memberships_user_project", "user_id", "project_id"),
        Index("ix_project_memberships_project", "project_id"),
    )


class ApiToken(Base):
    """Soft-revocable, scoped API token. Only the secret digest is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    label_key: Mapped[str] = mapped_column(String(64), nullable=False)
    selector: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("selector", name="uq_api_tokens_selector"),
        CheckConstraint(
            "length(id) = 36",
            name="ck_api_tokens_id",
        ),
        CheckConstraint("length(secret_digest) = 32", name="ck_api_tokens_secret_digest"),
        CheckConstraint("token_version > 0", name="ck_api_tokens_version"),
        Index("ix_api_tokens_user_label", "user_id", "label_key"),
        Index("ix_api_tokens_user_revoked", "user_id", "revoked_at"),
    )


class ProjectCheckout(Base):
    """A user's local checkout path for a (possibly github:-anchored)
    project. Agents confirm the mapping once, then bootstrap returns it."""

    __tablename__ = "project_checkouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    checkout_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_project_checkouts_user_project"),
        Index("ix_project_checkouts_project", "project_id"),
    )


class GithubAccount(Base):
    """Immutable GitHub identity and encrypted expiring user credentials."""

    __tablename__ = "github_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    github_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    login_at_last_verify: Mapped[str | None] = mapped_column(String(128), nullable=True)
    encrypted_user_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_github_accounts_user_id", "user_id", unique=True),
        Index("uq_github_accounts_github_user_id", "github_user_id", unique=True),
        CheckConstraint("github_user_id > 0", name="ck_github_accounts_github_user_id"),
    )


class GithubAppInstallation(Base):
    """Authoritative GitHub App installation identity and reconciliation state."""

    __tablename__ = "github_app_installations"

    github_installation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    github_owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner_login_at_last_verify: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)
    repository_selection: Mapped[str] = mapped_column(String(16), nullable=False)
    suspended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repositories_etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reconciliation_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_reconciled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("github_installation_id > 0", name="ck_github_app_installations_id"),
        CheckConstraint("github_owner_id > 0", name="ck_github_app_installations_owner_id"),
        CheckConstraint(
            "account_type IN ('user', 'organization', 'enterprise')",
            name="ck_github_app_installations_account_type",
        ),
        CheckConstraint(
            "repository_selection IN ('all', 'selected')",
            name="ck_github_app_installations_selection",
        ),
        Index(
            "ix_github_app_installations_owner_active",
            "github_owner_id",
            "deleted_at",
            "suspended_at",
        ),
    )


class GithubInstallationRepository(Base):
    """Verified repository metadata within one active installation scope."""

    __tablename__ = "github_installation_repositories"

    github_installation_id: Mapped[int] = mapped_column(
        ForeignKey("github_app_installations.github_installation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    github_repository_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    repository_full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    github_owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(256), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    repository_verified_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    enabled_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("github_repository_id", name="uq_github_installation_repositories_repository"),
        CheckConstraint("github_repository_id > 0", name="ck_github_installation_repositories_id"),
        CheckConstraint("github_owner_id > 0", name="ck_github_installation_repositories_owner_id"),
        CheckConstraint(
            "visibility IN ('public', 'private', 'internal')",
            name="ck_github_installation_repositories_visibility",
        ),
        Index("ix_github_installation_repositories_project", "project_id"),
        Index(
            "ix_github_installation_repositories_active",
            "github_installation_id",
            "removed_at",
            "disabled",
            "archived",
        ),
    )


class BrowserSession(Base):
    """Server-side browser session; only a digest of the opaque cookie is stored."""

    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from_id: Mapped[str | None] = mapped_column(
        ForeignKey("browser_sessions.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(id) = 36", name="ck_browser_sessions_id"),
        CheckConstraint("length(session_digest) = 32", name="ck_browser_sessions_digest"),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_browser_sessions_expiry_order",
        ),
        Index("ix_browser_sessions_user_active", "user_id", "revoked_at"),
        Index("ix_browser_sessions_absolute_expiry", "absolute_expires_at"),
    )


class GithubSigninState(Base):
    """Single-use pre-authentication GitHub OAuth transaction."""

    __tablename__ = "github_signin_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    transaction_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    return_path: Mapped[str] = mapped_column(String(64), nullable=False)
    pkce_verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    credential_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("length(id) = 36", name="ck_github_signin_states_id"),
        CheckConstraint("length(state_digest) = 32", name="ck_github_signin_states_state_digest"),
        CheckConstraint("length(transaction_digest) = 32", name="ck_github_signin_states_transaction_digest"),
        CheckConstraint(
            "return_path IN ('/', '/projects', '/setup')",
            name="ck_github_signin_states_return_path",
        ),
        CheckConstraint("expires_at > created_at", name="ck_github_signin_states_expiry"),
        Index("ix_github_signin_states_transaction_expiry", "transaction_digest", "expires_at"),
    )


class GithubInstallationState(Base):
    """Single-use installation setup state, separate from OAuth/PKCE state."""

    __tablename__ = "github_installation_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    browser_session_id: Mapped[str] = mapped_column(
        ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False
    )
    return_path: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("length(id) = 36", name="ck_github_installation_states_id"),
        CheckConstraint("length(state_digest) = 32", name="ck_github_installation_states_digest"),
        CheckConstraint(
            "return_path IN ('/', '/projects', '/setup')",
            name="ck_github_installation_states_return_path",
        ),
        CheckConstraint("expires_at > created_at", name="ck_github_installation_states_expiry"),
        Index("ix_github_installation_states_expiry", "expires_at", "consumed_at"),
    )


class GithubWebhookDelivery(Base):
    """Bounded idempotency record for an authenticated GitHub webhook."""

    __tablename__ = "github_webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    github_installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(delivery_id) = 36", name="ck_github_webhook_deliveries_id"),
        CheckConstraint("length(body_hash) = 64", name="ck_github_webhook_deliveries_hash"),
        CheckConstraint(
            "github_installation_id IS NULL OR github_installation_id > 0",
            name="ck_github_webhook_deliveries_installation_id",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_github_webhook_deliveries_attempt_count"),
        CheckConstraint(
            "status IN ('received', 'processed', 'acknowledged', 'failed')",
            name="ck_github_webhook_deliveries_status",
        ),
        CheckConstraint("expires_at > received_at", name="ck_github_webhook_deliveries_expiry"),
        Index("ix_github_webhook_deliveries_expiry", "expires_at"),
        Index("ix_github_webhook_deliveries_work", "status", "available_at", "received_at"),
    )


class ScanJob(Base):
    """State machine record for a scan: queued | running | completed | failed | cancelled."""

    __tablename__ = "scan_jobs"

    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    queued_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestRequest(Base):
    """Durable, leased idempotency claim for an authenticated local upload."""

    __tablename__ = "ingest_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submitted_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    submitting_token_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("api_tokens.id", ondelete="RESTRICT"), nullable=False
    )
    client_request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"), nullable=True)
    lease_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstoned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstone_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "submitted_by_user_id",
            "client_request_id",
            name="uq_ingest_requests_user_request",
        ),
        UniqueConstraint("run_id", name="uq_ingest_requests_run"),
        CheckConstraint(
            "state IN ('processing', 'completed', 'failed', 'tombstoned')",
            name="ck_ingest_requests_state",
        ),
        CheckConstraint("accepted_bytes >= 0", name="ck_ingest_requests_accepted_bytes"),
        CheckConstraint(
            "length(payload_hash) = 64 AND payload_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_ingest_requests_payload_hash",
        ),
        CheckConstraint(
            "state != 'completed' OR run_id IS NOT NULL",
            name="ck_ingest_requests_completed_run",
        ),
        CheckConstraint(
            "state != 'processing' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_ingest_requests_processing_lease",
        ),
        CheckConstraint(
            "state != 'tombstoned' OR (run_id IS NULL AND tombstoned_at IS NOT NULL "
            "AND tombstone_expires_at IS NOT NULL)",
            name="ck_ingest_requests_tombstone",
        ),
        Index("ix_ingest_requests_project_created", "project_id", "created_at"),
        Index("ix_ingest_requests_state_lease", "state", "lease_expires_at"),
        Index("ix_ingest_requests_token_created", "submitting_token_id", "created_at"),
        Index("ix_ingest_requests_user_created", "submitted_by_user_id", "created_at"),
    )


class GithubIngestRequest(Base):
    """Durable leased claim for one authenticated GitHub run attempt."""

    __tablename__ = "github_ingest_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    github_repository_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    github_owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    github_run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"), nullable=True)
    lease_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstoned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tombstone_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "github_repository_id",
            "github_run_id",
            "run_attempt",
            name="uq_github_ingest_requests_run_attempt",
        ),
        UniqueConstraint("run_id", name="uq_github_ingest_requests_run"),
        CheckConstraint(
            "github_repository_id > 0 AND github_owner_id > 0 AND github_run_id > 0 AND run_attempt > 0",
            name="ck_github_ingest_requests_identity",
        ),
        CheckConstraint(
            "state IN ('processing', 'completed', 'failed', 'tombstoned')",
            name="ck_github_ingest_requests_state",
        ),
        CheckConstraint("accepted_bytes >= 0", name="ck_github_ingest_requests_accepted_bytes"),
        CheckConstraint(
            "length(payload_hash) = 64 AND payload_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_github_ingest_requests_payload_hash",
        ),
        CheckConstraint(
            "state != 'completed' OR run_id IS NOT NULL",
            name="ck_github_ingest_requests_completed_run",
        ),
        CheckConstraint(
            "state != 'processing' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_github_ingest_requests_processing_lease",
        ),
        CheckConstraint(
            "state != 'tombstoned' OR (run_id IS NULL AND tombstoned_at IS NOT NULL "
            "AND tombstone_expires_at IS NOT NULL)",
            name="ck_github_ingest_requests_tombstone",
        ),
        Index(
            "ix_github_ingest_requests_repository_created",
            "github_repository_id",
            "created_at",
        ),
        Index("ix_github_ingest_requests_state_lease", "state", "lease_expires_at"),
        Index("ix_github_ingest_requests_owner_created", "github_owner_id", "created_at"),
    )


class IngestAttempt(Base):
    """Minimized, expiring evidence for a project-bound upload attempt."""

    __tablename__ = "ingest_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    principal_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    wire_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id", ondelete="SET NULL"), nullable=True)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    __table_args__ = (
        CheckConstraint("origin IN ('github', 'local')", name="ck_ingest_attempts_origin"),
        CheckConstraint(
            "principal_kind IN ('github_oidc', 'local_token')",
            name="ck_ingest_attempts_principal_kind",
        ),
        CheckConstraint(
            "outcome IN ('accepted', 'replayed', 'rejected', 'failed_internal')",
            name="ck_ingest_attempts_outcome",
        ),
        CheckConstraint("wire_bytes >= 0", name="ck_ingest_attempts_wire_bytes"),
        CheckConstraint("expires_at > received_at", name="ck_ingest_attempts_expiry"),
        CheckConstraint("completed_at >= received_at", name="ck_ingest_attempts_completion"),
        CheckConstraint("length(id) = 36", name="ck_ingest_attempts_id"),
        CheckConstraint("length(correlation_id) = 36", name="ck_ingest_attempts_correlation"),
        CheckConstraint(
            "length(principal_reference_hash) = 64 AND length(canonical_request_key_hash) = 64",
            name="ck_ingest_attempts_hashes",
        ),
        CheckConstraint(
            "(origin = 'github' AND principal_kind = 'github_oidc' "
            "AND submitted_by_user_id IS NULL) OR "
            "(origin = 'local' AND principal_kind = 'local_token' "
            "AND submitted_by_user_id IS NOT NULL)",
            name="ck_ingest_attempts_identity",
        ),
        Index("ix_ingest_attempts_project_received", "project_id", "received_at"),
        Index("ix_ingest_attempts_expires", "expires_at"),
    )


class IngestQuotaLock(Base):
    """Singleton row serializing cross-origin quota reservation."""

    __tablename__ = "ingest_quota_locks"

    lock_name: Mapped[str] = mapped_column(String(32), primary_key=True)

    __table_args__ = (CheckConstraint("lock_name = 'global'", name="ck_ingest_quota_locks_global"),)


class IngestUsageCharge(Base):
    """Immutable short-lived accounting entry for one allowed work start."""

    __tablename__ = "ingest_usage_charges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    accepted_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    local_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    local_token_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    github_repository_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    github_owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    charged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("origin IN ('github', 'local')", name="ck_ingest_usage_charges_origin"),
        CheckConstraint("accepted_bytes >= 0", name="ck_ingest_usage_charges_bytes"),
        CheckConstraint("expires_at > charged_at", name="ck_ingest_usage_charges_expiry"),
        CheckConstraint(
            "(origin = 'local' AND local_user_id IS NOT NULL AND local_user_id > 0 "
            "AND local_token_id IS NOT NULL AND github_repository_id IS NULL "
            "AND github_owner_id IS NULL) OR "
            "(origin = 'github' AND local_user_id IS NULL AND local_token_id IS NULL "
            "AND github_repository_id IS NOT NULL AND github_repository_id > 0 "
            "AND github_owner_id IS NOT NULL AND github_owner_id > 0)",
            name="ck_ingest_usage_charges_identity",
        ),
        Index("ix_ingest_usage_charges_token_time", "local_token_id", "charged_at"),
        Index("ix_ingest_usage_charges_user_time", "local_user_id", "charged_at"),
        Index(
            "ix_ingest_usage_charges_repository_time",
            "github_repository_id",
            "charged_at",
        ),
        Index("ix_ingest_usage_charges_owner_time", "github_owner_id", "charged_at"),
        Index("ix_ingest_usage_charges_expires", "expires_at"),
    )


class GithubOidcReplay(Base):
    """Hashed, expiring evidence that one authenticated GitHub JWT was consumed."""

    __tablename__ = "github_oidc_replays"

    jti_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    github_repository_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(jti_digest) = 32", name="ck_github_oidc_replays_digest"),
        CheckConstraint(
            "github_repository_id > 0",
            name="ck_github_oidc_replays_repository_id",
        ),
        CheckConstraint(
            "expires_at > consumed_at",
            name="ck_github_oidc_replays_expiry",
        ),
        Index("ix_github_oidc_replays_expires", "expires_at"),
    )


class ScannerRun(Base):
    """Per-scanner execution record within a run."""

    __tablename__ = "scanner_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    scanner_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tool_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    database_version_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="scanner_runs")
    artifact: Mapped["ScannerArtifact | None"] = relationship(
        back_populates="scanner_run",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint("run_id", "scanner_kind", name="uq_scanner_runs_run_kind"),
        CheckConstraint(
            "image_digest IS NULL OR (length(image_digest) = 71 "
            "AND substr(image_digest, 1, 7) = 'sha256:' "
            "AND substr(image_digest, 8) NOT GLOB '*[^0-9a-f]*')",
            name="ck_scanner_runs_image_digest",
        ),
        Index("ix_scanner_runs_run_kind", "run_id", "scanner_kind"),
    )


class ScannerArtifact(Base):
    """Raw scanner output, gzip-compressed BLOB."""

    __tablename__ = "scanner_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scanner_run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scanner_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    scanner_run: Mapped[ScannerRun] = relationship(back_populates="artifact")


class Finding(Base):
    """One normalized finding extracted from a scanner artifact."""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    scanner_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fix_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    compliance_tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "finding_key", name="uq_findings_run_key"),
        Index("ix_findings_run", "run_id"),
        Index("ix_findings_run_severity", "run_id", "severity"),
        Index("ix_findings_run_file", "run_id", "file_path"),
    )


class SourceContext(Base):
    """One bounded, redacted source window uploaded with scan results."""

    __tablename__ = "source_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    context_key: Mapped[str] = mapped_column(String(36), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    window_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    highlight_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    highlight_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    highlight_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lines_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    redaction_version: Mapped[int] = mapped_column(Integer, nullable=False)
    redaction_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unavailable_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "context_key", name="uq_source_contexts_run_key"),
        Index("ix_source_contexts_run", "run_id"),
    )


class SourceContextFinding(Base):
    """Many-to-many link between deduplicated contexts and findings."""

    __tablename__ = "source_context_findings"

    context_id: Mapped[int] = mapped_column(ForeignKey("source_contexts.id", ondelete="CASCADE"), primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True)

    __table_args__ = (Index("ix_source_context_findings_finding", "finding_id"),)


# ---------------------------------------------------------------------------
# Test results group (v3 — replaces the v2 evidence table)
# ---------------------------------------------------------------------------


class TestResult(Base):
    """One test evaluation against collected data, for one FR in one run.

    A 'test' here is an entry in an FR's `tests` array. The orchestrator
    evaluates each test against the run's scanner findings and JUnit
    results, then stores the outcome here.
    """

    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    test_id: Mapped[str] = mapped_column(String(128), nullable=False)
    test_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)  # pass | fail | pending
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "fr_id", "test_id", name="uq_test_results_run_fr_test"),
        Index("ix_test_results_run", "run_id"),
        Index("ix_test_results_run_fr", "run_id", "fr_id"),
    )


# ---------------------------------------------------------------------------
# Legacy evidence table (deprecated, kept for migration reference)
# ---------------------------------------------------------------------------


class Evidence(Base):
    """Deprecated: v2 evidence table. Retained for historical data only;
    new code uses TestResult instead."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_json: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    artifact_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_evidence_run_fr", "run_id", "fr_id"),)


# ---------------------------------------------------------------------------
# State group
# ---------------------------------------------------------------------------


class FrState(Base):
    """Cached computed state of one FR. Recomputed on evidence/waiver/catalogue changes."""

    __tablename__ = "fr_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_fr_state_run", "run_id"),)


class Waiver(Base):
    """Standing waiver forcing an FR to 'waived' state."""

    __tablename__ = "waivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    waived_by: Mapped[str] = mapped_column(String(128), nullable=False)
    waived_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_waivers_project_fr", "project_id", "fr_id"),)


class FindingAcceptance(Base):
    """Per-finding risk acceptance. Persists across scans — when the same
    (scanner_kind, rule_id) appears in a future scan, the matcher filters
    it out so the finding doesn't fail the FR test. Unlike waivers (per-FR),
    acceptances are per-finding and carry a risk assessment + rationale."""

    __tablename__ = "finding_acceptances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    scanner_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(256), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    fix_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_by: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_finding_acceptances_lookup", "project_id", "scanner_kind", "rule_id"),)


# ---------------------------------------------------------------------------
# Audit group
# ---------------------------------------------------------------------------


class AgentAction(Base):
    """Audit log of state-mutating MCP/API calls."""

    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_agent_actions_run", "run_id"),)


# ---------------------------------------------------------------------------
# Compliance mapping group
# ---------------------------------------------------------------------------


class ComplianceMapping(Base):
    """Latest-loaded compliance mapping for a project.

    The mapping is a separate JSON artifact (fr-compliance-mapping.json)
    connecting project FRs to compliance framework rows. Loaded fresh on
    each scan if the file changes; one row per project (latest only).
    History is kept in ComplianceMappingSnapshot.
    """

    __tablename__ = "compliance_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    mapping_doc_json: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_compliance_mappings_project", "project_id"),)


class ComplianceMappingSnapshot(Base):
    """Immutable historical copy of a compliance mapping, with the targets it
    was authored against (catalogue hash + packs) so old runs and matrices
    stay interpretable when the mapping is later replaced."""

    __tablename__ = "compliance_mapping_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    catalogue_content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    packs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    mapping_doc_json: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (Index("ix_compliance_mapping_snapshots_project", "project_id", "loaded_at"),)


__all__ = [
    "Base",
    "CatalogueSnapshot",
    "Project",
    "Fr",
    "Run",
    "User",
    "ApiToken",
    "ProjectCheckout",
    "GithubAccount",
    "ScanJob",
    "IngestRequest",
    "ScannerRun",
    "ScannerArtifact",
    "Finding",
    "TestResult",
    "Evidence",  # deprecated v2 table
    "FrState",
    "Waiver",
    "FindingAcceptance",
    "AgentAction",
    "ComplianceMapping",
    "ComplianceMappingSnapshot",
]
