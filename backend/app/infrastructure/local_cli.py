"""Production composition for the public container-based local scan CLI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from app.modules.atomic.local_cli.config_store import load_config, resolve_config
from app.modules.atomic.local_cli.git_metadata import (
    SubprocessGitCommand,
    collect_git_metadata,
)
from app.modules.atomic.local_cli.outbox_storage import OutboxStore
from app.modules.atomic.local_cli.scanner_runner import DockerLocalScannerRunner
from app.modules.atomic.local_cli.source_snapshot import (
    GitSnapshotIndex,
    create_source_snapshot,
)
from app.modules.atomic.local_cli.upload_client import UploadBundle, UploadResult
from app.modules.atomic.scanning.scanner_catalog import SEMGREP_POLICY_PATH
from app.modules.workflows.local_scan_execution import (
    DefaultLocalUploadPort,
    GitProvenance,
    LocalCLIConfig,
    LocalScanExecutionDependencies,
    ScanOutput,
    SourceSnapshot,
)


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


class FilesystemConfigPort:
    def __init__(
        self,
        config_path: Path,
        *,
        host_uid: int,
        environ: Mapping[str, str],
    ) -> None:
        self.config_path = config_path
        self.host_uid = host_uid
        self.environ = environ

    def load(self) -> LocalCLIConfig:
        allow_loopback = self.environ.get("ASSURANCE_SCAN_ALLOW_LOOPBACK_HTTP") == "1"
        stored = load_config(
            self.config_path,
            expected_uid=self.host_uid,
            allow_insecure_loopback=allow_loopback,
        )
        resolved = resolve_config(
            stored,
            self.environ,
            allow_insecure_loopback=allow_loopback,
        ).config
        version = self.environ.get("ASSURANCE_SCAN_CLI_VERSION", "0.0.0-dev")
        revision = self.environ.get("ASSURANCE_SCAN_CLI_REVISION", "0" * 40)
        if not _REVISION.fullmatch(revision):
            raise RuntimeError("CLI build revision is unavailable")
        image_id, image_digest = _cli_image_identity(self.environ)
        return LocalCLIConfig(
            api_base_url=resolved.api_url,
            installation_id=resolved.installation_id,
            cli_version=version,
            cli_build_revision=revision,
            cli_image_id=image_id,
            cli_image_digest=image_digest,
            token=resolved.token,
            custom_ca_file=_optional_path(self.environ.get("ASSURANCE_SCAN_CA_FILE")),
            allow_loopback_http=allow_loopback,
        )


class GitProvenanceAdapter:
    def __init__(self, *, project_override: str | None = None) -> None:
        self.git = SubprocessGitCommand()
        self.project_override = project_override

    def inspect(self, project_path: Path) -> GitProvenance:
        metadata = collect_git_metadata(
            project_path,
            self.git,
            project_override=self.project_override,
        )
        return GitProvenance(
            repository=metadata.repository,
            branch=metadata.branch,
            commit=metadata.commit,
            git_object_format=metadata.git_object_format,
            working_tree_dirty=metadata.working_tree_dirty,
            project_override=metadata.project_override,
        )


class SourceSnapshotAdapter:
    def __init__(self, cache_root: Path, *, host_uid: int, host_gid: int) -> None:
        self.cache_root = cache_root
        self.host_uid = host_uid
        self.host_gid = host_gid
        self.git = SubprocessGitCommand()
        self.index = GitSnapshotIndex(self.git)

    def create(self, project_path: Path, request_id: str) -> SourceSnapshot:
        root = self.cache_root / "runs" / request_id / "source"
        snapshot = create_source_snapshot(
            project_path,
            root,
            self.index,
            excluded_roots=(self.cache_root,),
            owner_uid=self.host_uid,
            owner_gid=self.host_gid,
        )
        return SourceSnapshot(
            request_id=request_id,
            source_content_hash=snapshot.source_content_hash,
            source_manifest_version=snapshot.source_manifest_version,
            opaque_handle=str(snapshot.root),
            lfs_state=snapshot.lfs_state,
            submodules=(),
        )

    def cleanup(self, snapshot: SourceSnapshot) -> None:
        shutil.rmtree(Path(snapshot.opaque_handle), ignore_errors=True)


class LocalScannerAdapter:
    def __init__(self, reviewed_policy_path: Path) -> None:
        self.runner = DockerLocalScannerRunner(reviewed_policy_path=reviewed_policy_path)

    def scan(self, snapshot: SourceSnapshot, request_id: str) -> ScanOutput:
        output = self.runner.scan(Path(snapshot.opaque_handle), request_id)
        return ScanOutput(
            findings_document=output.findings_document,
            findings_path=output.findings_path,
            scanner_manifest_version=output.scanner_manifest_version,
            scanner_manifest_digest=output.scanner_manifest_digest,
            scanner_image_digests=output.scanner_image_digests,
            sarif_path=output.sarif_path,
            sbom_path=output.sbom_path,
        )


class LocalOutboxAdapter:
    def __init__(self, store: OutboxStore) -> None:
        self.store = store

    def create(
        self,
        request_id: str,
        metadata: Mapping[str, object],
        output: ScanOutput,
    ) -> UploadBundle:
        artifacts = {
            "metadata.json": json.dumps(
                metadata,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8"),
            "findings.json": output.findings_path.read_bytes(),
        }
        if output.sarif_path is not None:
            artifacts["results.sarif"] = output.sarif_path.read_bytes()
        if output.sbom_path is not None:
            artifacts["sbom.cyclonedx.json"] = output.sbom_path.read_bytes()
        try:
            entry = self.store.save(request_id, artifacts)
            return _bundle(entry.path, entry.artifact_names, request_id)
        finally:
            _remove_transient_output(output)

    def load(self, request_id: str) -> UploadBundle:
        entry = self.store.load(request_id)
        return _bundle(entry.path, entry.artifact_names, request_id)

    def retain(self, request_id: str, reason_code: str) -> None:
        retryable = reason_code in {
            "network_error",
            "network_retry_exhausted",
            "no_upload",
            "not_enrolled",
            "server_retry_exhausted",
            "upload_in_progress",
        }
        self.store.update_retry(
            request_id,
            retryable=retryable,
            error_code=reason_code,
        )

    def mark_uploaded(self, request_id: str, result: UploadResult) -> None:
        self.store.mark_uploaded(request_id, run_url=result.run_url or "")


def build_local_scan_dependencies(
    *,
    config_path: Path,
    cache_root: Path,
    host_uid: int,
    host_gid: int,
    project_override: str | None,
    environ: Mapping[str, str],
) -> tuple[LocalScanExecutionDependencies, OutboxStore]:
    """Build all CLI ports at the infrastructure boundary."""
    store = OutboxStore(
        cache_root / "outbox",
        expected_uid=host_uid,
        expected_gid=host_gid,
    )
    store.prune()
    dependencies = LocalScanExecutionDependencies(
        config=FilesystemConfigPort(
            config_path,
            host_uid=host_uid,
            environ=environ,
        ),
        git=GitProvenanceAdapter(project_override=project_override),
        snapshots=SourceSnapshotAdapter(
            cache_root,
            host_uid=host_uid,
            host_gid=host_gid,
        ),
        scanners=LocalScannerAdapter(SEMGREP_POLICY_PATH),
        outbox=LocalOutboxAdapter(store),
        uploader=DefaultLocalUploadPort(),
    )
    return dependencies, store


def _bundle(root: Path, names: tuple[str, ...], request_id: str) -> UploadBundle:
    available = set(names)
    required = {"metadata.json", "findings.json"}
    if not required.issubset(available):
        raise RuntimeError("outbox request has no retryable upload bundle")
    return UploadBundle(
        request_id=request_id,
        metadata_path=root / "metadata.json",
        findings_path=root / "findings.json",
        sarif_path=root / "results.sarif" if "results.sarif" in available else None,
        sbom_path=root / "sbom.cyclonedx.json" if "sbom.cyclonedx.json" in available else None,
    )


def _remove_transient_output(output: ScanOutput) -> None:
    parents: set[Path] = set()
    for path in (output.findings_path, output.sarif_path, output.sbom_path):
        if path is not None:
            parents.add(path.parent)
            path.unlink(missing_ok=True)
    for parent in sorted(parents, key=lambda item: len(item.parts), reverse=True):
        shutil.rmtree(parent, ignore_errors=True)
        run_root = parent.parent
        try:
            run_root.rmdir()
        except OSError:
            pass


def _cli_image_identity(environ: Mapping[str, str]) -> tuple[str, str | None]:
    configured_id = environ.get("ASSURANCE_SCAN_CLI_IMAGE_ID")
    configured_digest = environ.get("ASSURANCE_SCAN_CLI_IMAGE_DIGEST")
    if configured_id is not None:
        if not _SHA256.fullmatch(configured_id):
            raise RuntimeError("configured CLI image ID is invalid")
        if configured_digest is not None and not _IMAGE_DIGEST.fullmatch(configured_digest):
            raise RuntimeError("configured CLI image digest is invalid")
        return configured_id, configured_digest

    container_id = environ.get("HOSTNAME", "")
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise RuntimeError("CLI container identity is unavailable")
    result = subprocess.run(
        ("docker", "container", "inspect", container_id, "--format", "{{.Image}}"),
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    image_id = result.stdout.decode("ascii", "ignore").strip()
    if result.returncode != 0 or not _SHA256.fullmatch(image_id):
        raise RuntimeError("CLI container image identity is unavailable")
    return image_id, None


def _optional_path(value: str | None) -> Path | None:
    return None if not value else Path(value)


__all__ = [
    "FilesystemConfigPort",
    "GitProvenanceAdapter",
    "LocalOutboxAdapter",
    "LocalScannerAdapter",
    "SourceSnapshotAdapter",
    "build_local_scan_dependencies",
]
