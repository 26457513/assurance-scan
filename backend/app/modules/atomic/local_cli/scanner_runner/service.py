"""Pure command construction and normalized local-result rendering."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from app.modules.atomic.scanning.finding_parser import ParsedFinding
from app.modules.atomic.scanning.scanner_catalog import PROJECT_MOUNT_TARGET, ScannerConfig


_REQUEST_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def scanner_container_name(request_id: str, kind: str) -> str:
    """Return a request-scoped name safe for exact cleanup selection."""
    if not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("request_id must be a canonical UUIDv4")
    safe_kind = re.sub(r"[^a-z0-9-]", "-", kind.casefold()).strip("-")
    if not safe_kind:
        raise ValueError("scanner kind is invalid")
    return f"assurance-scan-{request_id}-{safe_kind}"


def build_local_scanner_argv(
    snapshot_path: str,
    scanner: ScannerConfig,
    request_id: str,
) -> list[str]:
    """Build a hardened sibling-container invocation for one pinned scanner."""
    name = scanner_container_name(request_id, scanner.kind)
    argv = [
        "docker", "run", "--rm", "--name", name,
        "--label", f"dev.assurance-scan.request-id={request_id}",
        "--label", f"dev.assurance-scan.scanner={scanner.kind}",
        "--mount", f"type=bind,src={snapshot_path},dst={PROJECT_MOUNT_TARGET},readonly",
        "--workdir", scanner.working_dir,
        "--memory", f"{scanner.memory_mib}m",
        "--cpus", str(scanner.cpus),
    ]
    if scanner.requires_stdin:
        argv.append("--interactive")
    if scanner.read_only:
        argv.append("--read-only")
    if scanner.network == "none":
        argv.extend(("--network", "none"))
    if scanner.no_new_privileges:
        argv.extend(("--security-opt", "no-new-privileges"))
    for capability in scanner.cap_drop:
        argv.extend(("--cap-drop", capability))
    for temporary in scanner.tmpfs:
        argv.extend(("--tmpfs", temporary))
    if scanner.user:
        argv.extend(("--user", scanner.user))
    for key, value in scanner.env.items():
        argv.extend(("--env", f"{key}={value}"))
    for source, target in scanner.extra_mounts.items():
        if source == "/var/run/docker.sock":
            raise ValueError("third-party scanner containers cannot receive the Docker socket")
        if source.startswith("volume:"):
            argv.extend(("--mount", f"type=volume,src={source[7:]},dst={target}"))
        else:
            argv.extend(("--mount", f"type=bind,src={source},dst={target},readonly"))
    argv.append(scanner.image)
    argv.extend(scanner.command)
    return argv


def findings_document(
    findings: Sequence[ParsedFinding],
    scanner_results: Sequence[dict[str, Any]],
    *,
    snapshot_root: Path | None = None,
) -> dict[str, Any]:
    """Render the strict source-neutral v1 findings upload document."""
    document: dict[str, Any] = {
        "schema_version": 1,
        "scanners": list(scanner_results),
        "findings": [
            {
                "scanner": finding.scanner_kind,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "message": finding.message[:8192],
                "theme": finding.theme,
                "fix_strategy": finding.fix_strategy,
                "compliance_tags": list(dict.fromkeys(finding.compliance_tags))[:64],
            }
            for finding in findings[:20_000]
        ],
    }
    if snapshot_root is not None:
        from app.modules.atomic.ingestion.source_context import extract_source_contexts

        extracted = extract_source_contexts(
            snapshot_root,
            cast(Sequence[Any], document["findings"]),
            schema_version=1,
        )
        document["findings"] = list(extracted.findings)
        document["source_contexts"] = list(extracted.contexts)
    return document


__all__ = ["build_local_scanner_argv", "findings_document", "scanner_container_name"]
