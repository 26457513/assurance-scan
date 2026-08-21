"""SQLAlchemy ORM models.

Phase 1 schema: the full 13-table layout per `docs/mcp-stack-plan.md` §6.
Split into logical groups (catalogue, run, evidence, state, audit) for
readability — the table list itself is identical to the plan.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    Boolean,
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
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    catalogue_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    source_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Fr(Base):
    """One FR at a point in time. The same FR ID can appear in many snapshots."""

    __tablename__ = "frs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    catalogue_snapshot_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("catalogue_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
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
        Index("ix_frs_project", "project_path"),
        Index("ix_frs_snapshot", "catalogue_snapshot_id"),
    )


# ---------------------------------------------------------------------------
# Run group
# ---------------------------------------------------------------------------


class Project(Base):
    """User-declared project: tag + local path + optional GitHub repo.

    The registry is the identity source of truth; runs/snapshots keyed by
    either identity (local path or github:{owner}/{repo}) fold into it.
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    local_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    github_repo: Mapped[str | None] = mapped_column(String(256), nullable=True)
    default_scan_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Run(Base):
    """One scan execution against a project."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
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
    git_branch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapping_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_bundle_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scanner_runs: Mapped[list["ScannerRun"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ScannerRun.scanner_kind",
    )


class Organisation(Base):
    """A GitHub organisation whose repos this instance polls and serves."""

    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    """UI account. Provisioned on first Google login; role gates admin
    surfaces. `admin` rows are immutable through the API (break-glass);
    `superuser` is delegated admin, revocable."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SHA-256 of the user's MCP bearer token; the plaintext is shown once
    # at generation/rotation and never stored.
    mcp_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mcp_token_generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectCheckout(Base):
    """A user's local checkout path for a (possibly github:-anchored)
    project. Agents confirm the mapping once, then bootstrap returns it."""

    __tablename__ = "project_checkouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    checkout_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    __table_args__ = (
        UniqueConstraint("user_email", "project_path", name="uq_project_checkouts_user_project"),
        Index("ix_project_checkouts_project", "project_path"),
    )


class GithubAccount(Base):
    """A user's GitHub token, encrypted with TOKEN_ENCRYPTION_KEY."""

    __tablename__ = "github_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    login: Mapped[str | None] = mapped_column(String(128), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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

    run: Mapped[Run] = relationship(back_populates="scanner_runs")
    artifact: Mapped["ScannerArtifact | None"] = relationship(
        back_populates="scanner_run",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
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
        Index("ix_findings_run", "run_id"),
        Index("ix_findings_run_severity", "run_id", "severity"),
        Index("ix_findings_run_file", "run_id", "file_path"),
    )


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
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    test_id: Mapped[str] = mapped_column(String(128), nullable=False)
    test_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)   # pass | fail | pending
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "fr_id", "test_id", name="uq_test_results_run_fr_test"),
        Index("ix_test_results_run", "run_id"),
        Index("ix_test_results_run_fr", "run_id", "fr_id"),
        Index("ix_test_results_project_fr", "project_path", "fr_id"),
    )


# ---------------------------------------------------------------------------
# Legacy evidence table (deprecated, kept for migration reference)
# ---------------------------------------------------------------------------


class Evidence(Base):
    """Deprecated: v2 evidence table. Retained for historical data only;
    new code uses TestResult instead."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
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

    __table_args__ = (
        Index("ix_evidence_run_fr", "run_id", "fr_id"),
        Index("ix_evidence_project_fr", "project_path", "fr_id"),
    )


# ---------------------------------------------------------------------------
# State group
# ---------------------------------------------------------------------------


class FrState(Base):
    """Cached computed state of one FR. Recomputed on evidence/waiver/catalogue changes."""

    __tablename__ = "fr_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_fr_state_project", "project_path"),
        Index("ix_fr_state_run", "run_id"),
    )


class Waiver(Base):
    """Standing waiver forcing an FR to 'waived' state."""

    __tablename__ = "waivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    fr_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    waived_by: Mapped[str] = mapped_column(String(128), nullable=False)
    waived_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_waivers_project_fr", "project_path", "fr_id"),
    )


class FindingAcceptance(Base):
    """Per-finding risk acceptance. Persists across scans — when the same
    (scanner_kind, rule_id) appears in a future scan, the matcher filters
    it out so the finding doesn't fail the FR test. Unlike waivers (per-FR),
    acceptances are per-finding and carry a risk assessment + rationale."""

    __tablename__ = "finding_acceptances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    scanner_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(256), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    fix_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_by: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_finding_acceptances_lookup", "project_path", "scanner_kind", "rule_id"),
    )


# ---------------------------------------------------------------------------
# Audit group
# ---------------------------------------------------------------------------


class AgentAction(Base):
    """Audit log of state-mutating MCP/API calls."""

    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    mapping_doc_json: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_compliance_mappings_project", "project_path"),
    )


class ComplianceMappingSnapshot(Base):
    """Immutable historical copy of a compliance mapping, with the targets it
    was authored against (catalogue hash + packs) so old runs and matrices
    stay interpretable when the mapping is later replaced."""

    __tablename__ = "compliance_mapping_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    catalogue_content_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    packs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    mapping_doc_json: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_compliance_mapping_snapshots_project", "project_path"),
    )


__all__ = [
    "Base",
    "CatalogueSnapshot",
    "Fr",
    "Run",
    "ScanJob",
    "ScannerRun",
    "ScannerArtifact",
    "Finding",
    "TestResult",
    "Evidence",  # deprecated v2 table
    "FrState",
    "Waiver",
    "AgentAction",
    "ComplianceMapping",
    "ComplianceMappingSnapshot",
]
