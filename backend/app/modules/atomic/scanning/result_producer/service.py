"""Render one canonical, redacted source-neutral v2 result envelope."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from app.modules.atomic.ingestion.data_redactor import redact_text
from app.modules.atomic.ingestion.envelope_contract import (
    canonical_json_bytes,
    envelope_payload_hash,
)
from app.modules.atomic.ingestion.source_context import extract_source_contexts
from app.modules.atomic.scanning.result_builder import build_sarif
from app.modules.shared.contracts.findings import FindingPayload
from app.modules.shared.contracts.ingest_v2 import (
    ENVELOPE_LIMITS_V2,
    SCANNER_ERROR_CODES,
    SCANNER_KINDS,
)

from .models import (
    GitHubProducerIdentity,
    LocalProducerIdentity,
    ProduceEnvelopeCommand,
    ProducedEnvelope,
    ScannerOutcome,
)


def produce_envelope_v2(command: ProduceEnvelopeCommand) -> ProducedEnvelope:
    """Build canonical v2 documents from a scanner run over one snapshot."""

    _validate_command(command)
    safe_findings = tuple(_safe_finding(finding) for finding in command.findings)
    raw_findings = [_finding_document(finding) for finding in safe_findings]
    extracted = extract_source_contexts(
        command.source.snapshot_root,
        cast(list[FindingPayload], raw_findings),
        schema_version=2,
    )
    findings_document: dict[str, Any] = {
        "schema_version": 2,
        "scanners": [_scanner_document(item) for item in command.scanner_outcomes],
        "findings": list(extracted.findings),
    }
    contexts_document: dict[str, Any] = {
        "schema_version": 2,
        "contexts": list(extracted.contexts),
    }
    documents: dict[str, dict[str, Any]] = {
        "metadata": _metadata_document(command),
        "findings": findings_document,
        "source_contexts": contexts_document,
    }
    if command.sarif:
        documents["sarif"] = build_sarif(safe_findings)
    if command.sbom is not None:
        documents["sbom"] = dict(command.sbom)
    canonical_parts = {
        name: canonical_json_bytes(document) for name, document in documents.items()
    }
    hash_documents: dict[str, dict[str, Any] | None] = {
        name: documents.get(name)
        for name in ("metadata", "findings", "source_contexts", "sarif", "sbom")
    }
    return ProducedEnvelope(
        documents=documents,
        canonical_parts=canonical_parts,
        payload_hash=envelope_payload_hash(hash_documents),
    )


def _validate_command(command: ProduceEnvelopeCommand) -> None:
    if not command.scanner_outcomes:
        raise ValueError("at least one scanner outcome is required")
    if len(command.scanner_outcomes) > ENVELOPE_LIMITS_V2.scanner_results:
        raise ValueError("scanner outcome limit exceeded")
    if len(command.findings) > ENVELOPE_LIMITS_V2.findings_count:
        raise ValueError("finding limit exceeded")
    kinds = [item.kind for item in command.scanner_outcomes]
    if len(kinds) != len(set(kinds)):
        raise ValueError("scanner outcomes must have unique kinds")
    if any(finding.scanner_kind not in kinds for finding in command.findings):
        raise ValueError("every finding must reference a scanner outcome")
    if any(
        finding.file_path is not None
        and len(finding.file_path) > ENVELOPE_LIMITS_V2.path_chars
        for finding in command.findings
    ):
        raise ValueError("finding path limit exceeded")
    for outcome in command.scanner_outcomes:
        if outcome.kind not in SCANNER_KINDS:
            raise ValueError("scanner kind is unsupported")
        if outcome.status == "completed" and outcome.error_code is not None:
            raise ValueError("completed scanner cannot have an error code")
        if outcome.status != "completed" and outcome.error_code not in SCANNER_ERROR_CODES:
            raise ValueError("non-completed scanner requires a stable error code")
        expected_image = command.scanner_release.images.get(outcome.kind)
        if outcome.status != "skipped" and outcome.image != expected_image:
            raise ValueError("scanner image does not match release manifest")


def _safe_finding(finding: Any) -> Any:
    message, _ = redact_text(str(finding.message)[: ENVELOPE_LIMITS_V2.message_chars])
    return replace(finding, message=message)


def _finding_document(finding: Any) -> dict[str, Any]:
    return {
        "scanner": finding.scanner_kind,
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "file_path": finding.file_path,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "message": finding.message,
        "theme": finding.theme,
        "fix_strategy": finding.fix_strategy,
        "compliance_tags": list(dict.fromkeys(finding.compliance_tags))[:64],
        "package_name": finding.package_name,
        "package_version": finding.package_version,
        "package_ecosystem": finding.package_ecosystem,
        "package_purl": finding.package_purl,
    }


def _scanner_document(outcome: ScannerOutcome) -> dict[str, Any]:
    return {
        "kind": outcome.kind,
        "status": outcome.status,
        "duration_ms": outcome.duration_ms,
        "image": outcome.image,
        "tool_version": outcome.tool_version,
        "database_version": outcome.database_version,
        "error_code": outcome.error_code,
    }


def _metadata_document(command: ProduceEnvelopeCommand) -> dict[str, Any]:
    repository = command.repository
    source = command.source
    return {
        "schema_version": 2,
        "repository": {"provider": "github", "full_name": repository.full_name},
        "commit": repository.commit,
        "git_object_format": repository.git_object_format,
        "branch": repository.branch,
        "ref": f"refs/heads/{repository.branch}" if repository.branch else None,
        "working_tree_dirty": repository.working_tree_dirty,
        "source": {
            "content_hash": source.content_hash,
            "manifest_version": source.manifest_version,
            "lfs_state": source.lfs_state,
            "submodules": [dict(item) for item in source.submodules],
        },
        "scanner_release": {
            "manifest_version": command.scanner_release.manifest_version,
            "manifest_digest": command.scanner_release.manifest_digest,
            "images": dict(command.scanner_release.images),
        },
        "artifacts": {"sarif": command.sarif, "sbom": command.sbom is not None},
        "producer": _producer_document(command.producer),
    }


def _producer_document(producer: LocalProducerIdentity | GitHubProducerIdentity) -> dict[str, Any]:
    if isinstance(producer, LocalProducerIdentity):
        return {
            "kind": "local-cli",
            "request_id": producer.request_id,
            "cli_installation_id": producer.cli_installation_id,
            "cli_version": producer.cli_version,
            "cli_build_revision": producer.cli_build_revision,
            "cli_image": producer.cli_image,
        }
    return {
        "kind": "github-actions",
        "repository_id": producer.repository_id,
        "repository_owner_id": producer.repository_owner_id,
        "run_id": producer.run_id,
        "run_number": producer.run_number,
        "run_attempt": producer.run_attempt,
        "event_name": "push",
        "workflow_ref": producer.workflow_ref,
        "workflow_sha": producer.workflow_sha,
        "actor": producer.actor,
        "actor_id": producer.actor_id,
    }


__all__ = ["produce_envelope_v2"]
