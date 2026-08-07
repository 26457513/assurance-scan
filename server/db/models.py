"""SQLAlchemy ORM models.

Phase 1 schema: the full 13-table layout per `docs/mcp-stack-plan.md` §6.
Split into logical groups (catalogue, run, evidence, state, audit) for
readability — the table list itself is identical to the plan.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
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
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
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
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_bundle_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scanner_runs: Mapped[list["ScannerRun"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="ScannerRun.scanner_kind",
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
    raw_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_findings_run", "run_id"),
        Index("ix_findings_run_severity", "run_id", "severity"),
        Index("ix_findings_run_file", "run_id", "file_path"),
    )


# ---------------------------------------------------------------------------
# Evidence group
# ---------------------------------------------------------------------------


class Evidence(Base):
    """Typed artifact supporting an FR. Has type, source, result, hash."""

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


__all__ = [
    "Base",
    "CatalogueSnapshot",
    "Fr",
    "Run",
    "ScanJob",
    "ScannerRun",
    "ScannerArtifact",
    "Finding",
    "Evidence",
    "FrState",
    "Waiver",
    "AgentAction",
]
