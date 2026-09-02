"""Source-neutral orchestration shared by GitHub and local result ingestion."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from typing import Any, Literal, Mapping, cast

from app.modules.atomic.ingestion.data_redactor import redact_json, redact_text
from app.modules.atomic.ingestion.finding_normalizer import normalize_findings
from app.modules.atomic.ingestion.result_persister import persist_result_bundle
from app.modules.atomic.ingestion.source_context import (
    sanitize_source_contexts,
    validate_source_context_links,
)
from app.modules.shared.contracts.ingest import (
    GitHubIngestEnvelope,
    IngestEnvelope,
    IngestStatus,
    LocalIngestEnvelope,
    ResolvedProject,
    ResultBundle,
    RunRecord,
    ScannerResult,
    ScannerStatus,
)
from app.modules.shared.contracts.findings import FindingPayload

from .models import IngestPersistencePort


log = logging.getLogger(__name__)


def github_run_id(github_run_id: int) -> str:
    """Return the stable server run ID for an authoritative GitHub run ID."""

    if github_run_id <= 0:
        raise ValueError("GitHub run ID must be a positive integer")
    return f"gh-{github_run_id}"


def build_github_inputs(
    project: ResolvedProject,
    metadata: Mapping[str, Any],
    payload: Mapping[str, Any] | None,
    blobs: Mapping[str, bytes] | None = None,
) -> tuple[GitHubIngestEnvelope, ResultBundle]:
    """Adapt GitHub API metadata and scanner output into separated contracts.

    Repository and run identity copies in the scanner artifact are checked but
    never copied into the source-neutral bundle. GitHub API metadata remains
    authoritative; ``commit`` is retained separately as the scanned checkout
    SHA because pull-request merge checkouts can differ from ``head_sha``.
    """

    api_run_id = int(metadata["github_run_id"])
    api_repository_id = int(metadata["github_repository_id"])
    api_repository = str(metadata["repo"])
    if project.github_repository_id != api_repository_id:
        raise ValueError("resolved project does not match GitHub repository ID")
    if project.repository.casefold() != api_repository.casefold():
        raise ValueError("resolved project does not match GitHub repository name")

    if payload is not None:
        payload_run_id = payload.get("github_run_id")
        if payload_run_id is not None and int(payload_run_id) != api_run_id:
            raise ValueError("result bundle GitHub run ID does not match API metadata")
        payload_repository = payload.get("repo")
        if (
            payload_repository is not None
            and str(payload_repository).casefold() != api_repository.casefold()
        ):
            raise ValueError("result bundle repository does not match API metadata")

    head_sha = str(metadata["head_sha"]).lower()
    checkout_sha = str((payload or {}).get("commit") or head_sha).lower()
    object_format = _git_object_format(checkout_sha)
    if _git_object_format(head_sha) != object_format:
        raise ValueError("GitHub head and checkout object formats differ")
    envelope = GitHubIngestEnvelope(
        project=project,
        github_run_id=api_run_id,
        checkout_sha=checkout_sha,
        head_sha=head_sha,
        git_object_format=object_format,
        branch=metadata.get("head_branch"),
        conclusion=metadata.get("conclusion"),
        started_at=metadata.get("started_at"),
        completed_at=metadata.get("completed_at"),
        run_number=metadata.get("run_number"),
        run_attempt=metadata.get("run_attempt"),
        run_url=metadata.get("run_url"),
        event=metadata.get("event"),
        actor=metadata.get("actor"),
        display_title=metadata.get("display_title"),
    )
    return envelope, _github_result_bundle(payload, blobs or {})


def build_local_result_bundle(
    findings_document: Mapping[str, Any],
    artifacts: Mapping[str, bytes],
) -> ResultBundle:
    """Adapt a strictly validated local findings document to the neutral bundle."""

    scanners = tuple(_local_scanner_result(item) for item in findings_document["scanners"])
    return ResultBundle(
        schema_version=int(findings_document["schema_version"]),
        scanners=scanners,
        findings=tuple(findings_document["findings"]),
        source_contexts=tuple(findings_document.get("source_contexts") or ()),
        artifacts=dict(artifacts),
    )


async def ingest_result_bundle(
    persistence: IngestPersistencePort,
    envelope: IngestEnvelope,
    bundle: ResultBundle,
) -> IngestStatus:
    """Persist one complete result graph using its authoritative origin envelope."""

    _validate_result_bundle(envelope, bundle)
    bundle = _redact_result_bundle(bundle)
    record = _run_record(envelope, bundle)
    if await persistence.get(record.run_id) is not None:
        return "exists"
    findings = normalize_findings(record.run_id, bundle.findings)
    await persist_result_bundle(
        persistence,
        record,
        bundle,
        findings,
        list(bundle.source_contexts),
    )
    log.info(
        "ingested %s run %s (%s, %d findings)",
        record.origin,
        record.run_id,
        record.status,
        len(findings),
    )
    return "ingested"


def _run_record(envelope: IngestEnvelope, bundle: ResultBundle) -> RunRecord:
    findings_json = _findings_json(bundle)
    if isinstance(envelope, GitHubIngestEnvelope):
        has_scanner_results = bool(bundle.scanners)
        return RunRecord(
            run_id=github_run_id(envelope.github_run_id),
            project_id=envelope.project.project_id,
            origin="github-actions",
            options_json=json.dumps(
                {"display_title": envelope.display_title},
                sort_keys=True,
                separators=(",", ":"),
            ),
            status="completed" if has_scanner_results else "failed",
            started_at=envelope.started_at,
            completed_at=envelope.completed_at,
            commit_sha=envelope.checkout_sha,
            git_branch=envelope.branch,
            error_message=(
                None if has_scanner_results else "GitHub workflow produced no scan results"
            ),
            findings_json=findings_json,
            repository_full_name_at_scan=envelope.project.repository,
            git_object_format=envelope.git_object_format,
            working_tree_dirty=False,
            github_run_id=envelope.github_run_id,
            github_run_number=envelope.run_number,
            github_run_attempt=envelope.run_attempt,
            github_run_url=envelope.run_url,
            github_event=envelope.event,
            github_actor=envelope.actor,
            github_head_sha=envelope.head_sha,
        )
    return RunRecord(
        run_id=envelope.run_id,
        project_id=envelope.project.project_id,
        origin="local",
        options_json="{}",
        status="completed",
        started_at=envelope.started_at,
        completed_at=envelope.completed_at,
        commit_sha=envelope.commit_sha,
        git_branch=envelope.branch,
        error_message=None,
        findings_json=findings_json,
        repository_full_name_at_scan=envelope.project.repository,
        git_object_format=envelope.git_object_format,
        working_tree_dirty=envelope.working_tree_dirty,
        source_content_hash=envelope.source_content_hash,
        source_manifest_version=envelope.source_manifest_version,
        submitted_by_user_id=envelope.submitted_by_user_id,
        submitting_token_id=envelope.submitting_token_id,
        local_machine_label=envelope.submitting_token_label,
        payload_hash=envelope.payload_hash,
        client_provenance_version=envelope.client_provenance_version,
        client_provenance_json=json.dumps(
            redact_json(_json_value(envelope.client_provenance)).value,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _validate_result_bundle(envelope: IngestEnvelope, bundle: ResultBundle) -> None:
    if bundle.schema_version != 1:
        raise ValueError("unsupported result-bundle schema version")
    kinds = [result.kind for result in bundle.scanners]
    if len(kinds) != len(set(kinds)):
        raise ValueError("result bundle contains duplicate scanner kinds")
    if not kinds:
        if isinstance(envelope, LocalIngestEnvelope) or envelope.conclusion == "success":
            raise ValueError("result bundle contains no scanner results")
    if bundle.source_contexts:
        validate_source_context_links(bundle.findings, bundle.source_contexts)


def _findings_json(bundle: ResultBundle) -> str:
    return json.dumps(
        {
            "schema_version": bundle.schema_version,
            "scanners": [asdict(result) for result in bundle.scanners],
            "findings": list(bundle.findings),
            "source_contexts": list(bundle.source_contexts),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _redact_result_bundle(bundle: ResultBundle) -> ResultBundle:
    redacted_findings = redact_json(_json_value(list(bundle.findings))).value
    if not isinstance(redacted_findings, list):
        raise ValueError("result findings must be a JSON array")
    findings = tuple(cast(FindingPayload, item) for item in redacted_findings)
    contexts = sanitize_source_contexts(bundle.source_contexts)
    scanners = tuple(
        replace(
            result,
            error_code=_redacted_optional_text(result.error_code),
            database_version=_redacted_optional_text(result.database_version),
            tool_version=_redacted_optional_text(result.tool_version),
        )
        for result in bundle.scanners
    )
    artifacts: dict[str, bytes] = {}
    for part_name, content in bundle.artifacts.items():
        if part_name == "findings":
            continue
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{part_name} artifact must be valid JSON") from exc
        clean = redact_json(document).value
        artifacts[part_name] = json.dumps(
            clean,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    clean_bundle = ResultBundle(
        schema_version=bundle.schema_version,
        scanners=scanners,
        findings=findings,
        source_contexts=contexts,
        artifacts=artifacts,
    )
    if "findings" in bundle.artifacts:
        clean_bundle = replace(
            clean_bundle,
            artifacts={
                **artifacts,
                "findings": _findings_json(clean_bundle).encode(),
            },
        )
    return clean_bundle


def _redacted_optional_text(value: str | None) -> str | None:
    return None if value is None else redact_text(value)[0]


def _json_value(value: Any) -> Any:
    """Detach dataclass mappings into the JSON tree accepted by the redactor."""

    return json.loads(json.dumps(value))


def _github_result_bundle(
    payload: Mapping[str, Any] | None,
    blobs: Mapping[str, bytes],
) -> ResultBundle:
    payload = payload or {}
    durations = payload.get("durations") or {}
    scanners = tuple(
        ScannerResult(
            kind=str(kind),
            status=_github_scanner_status(str(status)),
            duration_ms=_seconds_to_milliseconds(durations.get(kind)),
            error_code=None if status == "ok" else str(status),
        )
        for kind, status in sorted((payload.get("scanner_status") or {}).items())
    )
    return ResultBundle(
        schema_version=int(payload.get("schema_version", 1)),
        scanners=scanners,
        findings=tuple(payload.get("findings") or ()),
        source_contexts=tuple(payload.get("source_contexts") or ()),
        artifacts=_normalize_github_artifacts(blobs),
    )


def _local_scanner_result(item: Mapping[str, Any]) -> ScannerResult:
    image = item.get("image")
    image_digest = None if image is None else "sha256:" + str(image).rsplit("@sha256:", 1)[1]
    return ScannerResult(
        kind=str(item["kind"]),
        status=cast(ScannerStatus, item["status"]),
        duration_ms=int(item["duration_ms"]),
        image_reference=None if image is None else str(image),
        image_digest=image_digest,
        tool_version=item.get("tool_version"),
        database_version=item.get("database_version"),
        error_code=item.get("error_code"),
    )


def _normalize_github_artifacts(blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    normalized: dict[str, bytes] = {}
    for name, content in blobs.items():
        basename = name.rsplit("/", 1)[-1].casefold()
        if basename in {"findings", "findings.json"}:
            normalized["findings"] = content
        elif basename.endswith(".sarif") or basename == "sarif":
            normalized["sarif"] = content
        elif basename in {"sbom", "sbom.json", "sbom.cyclonedx.json"}:
            normalized["sbom"] = content
    return normalized


def _github_scanner_status(status: str) -> ScannerStatus:
    if status == "ok":
        return "completed"
    if status == "skipped":
        return "skipped"
    return "failed"


def _seconds_to_milliseconds(value: Any) -> int | None:
    if value is None:
        return None
    return max(0, round(float(value) * 1000))


def _git_object_format(commit_sha: str) -> Literal["sha1", "sha256"]:
    if len(commit_sha) == 40 and all(char in "0123456789abcdef" for char in commit_sha):
        return "sha1"
    if len(commit_sha) == 64 and all(char in "0123456789abcdef" for char in commit_sha):
        return "sha256"
    raise ValueError("commit SHA must be lowercase SHA-1 or SHA-256")
