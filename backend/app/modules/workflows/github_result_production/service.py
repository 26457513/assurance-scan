"""Produce a validated GitHub v2 bundle from one immutable source snapshot."""
from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from app.modules.atomic.local_cli.git_metadata import SubprocessGitCommand, collect_git_metadata
from app.modules.atomic.local_cli.source_snapshot import GitSnapshotIndex, create_source_snapshot
from app.modules.atomic.scanning.result_producer import (
    GitHubProducerIdentity,
    ProduceEnvelopeCommand,
    RepositoryProvenance,
    ScannerRelease,
    SourceProvenance,
    produce_envelope_v2,
)
from app.modules.atomic.scanning.scanner_catalog import SCANNER_RELEASE_SET, ci_scanner_set
from app.modules.workflows.github_scan_execution import run_scanners

from .models import (
    GitHubResultProductionCommand,
    GitHubResultProductionResult,
    GitHubScannerPort,
)


async def produce_github_result_bundle(
    command: GitHubResultProductionCommand,
    *,
    scanner: GitHubScannerPort = run_scanners,
) -> GitHubResultProductionResult:
    """Scan a stable snapshot and atomically materialize its canonical envelope."""

    identity = _identity(command.environment)
    project_root = command.project_root.resolve(strict=True)
    output_root = command.output_root.resolve(strict=False)
    if output_root.exists() or output_root.is_symlink():
        raise ValueError("bundle output already exists")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(mode=0o700)
    snapshot_root = output_root / ".source-snapshot"
    successful = False
    try:
        git = SubprocessGitCommand()
        metadata = collect_git_metadata(project_root, git)
        _validate_checkout(
            identity,
            metadata.repository,
            metadata.commit,
            metadata.git_object_format,
            metadata.branch,
            metadata.working_tree_dirty,
        )
        snapshot = create_source_snapshot(
            project_root,
            snapshot_root,
            GitSnapshotIndex(git),
            excluded_roots=(output_root,),
        )
        raw_sbom_path = output_root / ".scanner-sbom.json"
        scan = await scanner(
            str(snapshot.root),
            command.scanner_snapshot_path,
            command.application_image,
            raw_sbom_path,
        )
        scanners = ci_scanner_set(command.application_image)
        release_images = {item.kind: item.image for item in scanners}
        envelope = produce_envelope_v2(
            ProduceEnvelopeCommand(
                repository=RepositoryProvenance(
                    full_name=identity["repository"],
                    commit=identity["sha"],
                    git_object_format=cast(Literal["sha1", "sha256"], metadata.git_object_format),
                    branch=identity["branch"],
                    working_tree_dirty=False,
                ),
                source=SourceProvenance(
                    snapshot_root=snapshot.root,
                    content_hash=snapshot.source_content_hash,
                    manifest_version=snapshot.source_manifest_version,
                    lfs_state=cast(
                        Literal["none", "pointers", "hydrated", "mixed"],
                        snapshot.lfs_state,
                    ),
                ),
                scanner_release=ScannerRelease(
                    manifest_version=SCANNER_RELEASE_SET.schema_version,
                    manifest_digest=SCANNER_RELEASE_SET.sha256,
                    images=release_images,
                ),
                producer=GitHubProducerIdentity(
                    repository_id=int(identity["repository_id"]),
                    repository_owner_id=int(identity["repository_owner_id"]),
                    run_id=int(identity["run_id"]),
                    run_number=int(identity["run_number"]),
                    run_attempt=int(identity["run_attempt"]),
                    workflow_ref=identity["workflow_ref"],
                    workflow_sha=identity["workflow_sha"],
                    actor=identity["actor"],
                    actor_id=int(identity["actor_id"]),
                ),
                scanner_outcomes=scan.scanner_outcomes,
                findings=scan.findings,
                sarif=True,
                sbom=scan.sbom,
            )
        )
        _write_bundle(output_root, envelope.canonical_parts, envelope.payload_hash)
        successful = True
        return GitHubResultProductionResult(envelope, output_root, scan)
    finally:
        shutil.rmtree(snapshot_root, ignore_errors=True)
        (output_root / ".scanner-sbom.json").unlink(missing_ok=True)
        if not successful:
            shutil.rmtree(output_root, ignore_errors=True)


def _identity(environment: Mapping[str, str]) -> dict[str, str]:
    required = {
        "repository": "GITHUB_REPOSITORY",
        "repository_id": "GITHUB_REPOSITORY_ID",
        "repository_owner_id": "GITHUB_REPOSITORY_OWNER_ID",
        "run_id": "GITHUB_RUN_ID",
        "run_number": "GITHUB_RUN_NUMBER",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
        "event_name": "GITHUB_EVENT_NAME",
        "ref": "GITHUB_REF",
        "sha": "GITHUB_SHA",
        "workflow_ref": "GITHUB_WORKFLOW_REF",
        "workflow_sha": "GITHUB_WORKFLOW_SHA",
        "actor": "GITHUB_ACTOR",
        "actor_id": "GITHUB_ACTOR_ID",
    }
    result: dict[str, str] = {}
    for name, variable in required.items():
        value = environment.get(variable)
        if not value:
            raise ValueError(f"required GitHub identity field is absent: {variable}")
        result[name] = value
    if result["event_name"] != "push":
        raise ValueError("only GitHub push events are supported")
    prefix = "refs/heads/"
    if not result["ref"].startswith(prefix) or len(result["ref"]) == len(prefix):
        raise ValueError("GitHub ref must identify a branch")
    result["branch"] = result["ref"][len(prefix) :]
    for field in ("repository_id", "repository_owner_id", "run_id", "run_number", "run_attempt", "actor_id"):
        try:
            if int(result[field]) < 1:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"GitHub identity field is invalid: {field}") from exc
    return result


def _validate_checkout(
    identity: dict[str, str],
    repository: str,
    commit: str,
    object_format: str,
    branch: str | None,
    working_tree_dirty: bool,
) -> None:
    if repository.casefold() != identity["repository"].casefold():
        raise ValueError("checkout repository does not match GitHub identity")
    if commit != identity["sha"]:
        raise ValueError("checkout commit does not match GitHub identity")
    if branch is not None and branch != identity["branch"]:
        raise ValueError("checkout branch does not match GitHub identity")
    if working_tree_dirty:
        raise ValueError("GitHub checkout must be clean before snapshotting")
    expected_length = 40 if object_format == "sha1" else 64 if object_format == "sha256" else 0
    if expected_length == 0 or len(commit) != expected_length:
        raise ValueError("checkout Git object format is invalid")


def _write_bundle(
    output_root: Path,
    parts: Mapping[str, bytes],
    payload_hash: str,
) -> None:
    filenames = {
        "metadata": "metadata.json",
        "findings": "findings.json",
        "source_contexts": "source-contexts.json",
        "sarif": "results.sarif",
        "sbom": "sbom.cyclonedx.json",
    }
    for name, payload in parts.items():
        if name not in filenames or not isinstance(payload, bytes):
            raise ValueError("canonical envelope part is invalid")
        temporary = output_root / f".{filenames[name]}.tmp"
        temporary.write_bytes(payload)
        temporary.replace(output_root / filenames[name])
    (output_root / "envelope.sha256").write_text(payload_hash + "\n", encoding="ascii")


__all__ = ["produce_github_result_bundle"]
