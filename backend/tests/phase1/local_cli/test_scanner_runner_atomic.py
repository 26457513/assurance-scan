"""Security and contract tests for the local sibling-container runner."""

from __future__ import annotations

import uuid
from dataclasses import replace
import json
import subprocess
from pathlib import Path

import pytest

from app.modules.atomic.local_cli.scanner_runner import (
    DockerLocalScannerRunner,
    build_local_scanner_argv,
    findings_document,
    scanner_container_name,
)
from app.modules.atomic.scanning.finding_parser import ParsedFinding
from app.modules.atomic.scanning.scanner_catalog import SCANNER_MANIFEST_PATH, SEMGREP, TRIVY_IMAGE


REQUEST_ID = "018f47a2-4c72-4c9e-9f60-780cb70b8fe4"


def test_scanner_command_is_request_scoped_pinned_and_hardened() -> None:
    argv = build_local_scanner_argv(
        "/cache/runs/request/source",
        SEMGREP,
        REQUEST_ID,
    )

    assert argv[:5] == ["docker", "run", "--rm", "--name", f"assurance-scan-{REQUEST_ID}-semgrep"]
    assert "--read-only" in argv
    assert ["--network", "none"] == argv[argv.index("--network") : argv.index("--network") + 2]
    assert ["--security-opt", "no-new-privileges"] == argv[
        argv.index("--security-opt") : argv.index("--security-opt") + 2
    ]
    assert "ALL" in argv and "@sha256:" in SEMGREP.image
    assert "--interactive" in argv
    assert f"dev.assurance-scan.request-id={REQUEST_ID}" in argv
    assert not any("compose.project" in item for item in argv)
    assert not any("docker.sock" in item for item in argv)


def test_third_party_scanner_never_receives_the_docker_socket() -> None:
    with pytest.raises(ValueError, match="Docker socket"):
        build_local_scanner_argv(
            "/cache/source",
            TRIVY_IMAGE,
            REQUEST_ID,
        )


def test_cleanup_name_requires_exact_uuid_and_sanitizes_kind() -> None:
    assert uuid.UUID(REQUEST_ID).version == 4
    assert scanner_container_name(REQUEST_ID, "Example.Scanner") == (
        f"assurance-scan-{REQUEST_ID}-example-scanner"
    )
    with pytest.raises(ValueError, match="UUIDv4"):
        scanner_container_name("not-a-request", "semgrep")


def test_findings_document_is_strict_bounded_and_deduplicates_tags() -> None:
    finding = ParsedFinding(
        scanner_kind="semgrep",
        rule_id="rule",
        severity="HIGH",
        file_path="src/app.py",
        line_start=3,
        line_end=3,
        message="x" * 9000,
        compliance_tags=("ASVS-1", "ASVS-1"),
    )
    scanner = {
        "kind": "semgrep",
        "status": "completed",
        "duration_ms": 10,
        "image": SEMGREP.image,
        "tool_version": SEMGREP.tool_version,
    }

    document = findings_document([finding], [scanner])

    assert document["schema_version"] == 1
    assert len(document["findings"][0]["message"]) == 8192
    assert document["findings"][0]["compliance_tags"] == ["ASVS-1"]


def test_command_rejects_socket_even_if_catalog_regresses() -> None:
    regressed = replace(SEMGREP, extra_mounts={"/var/run/docker.sock": "/var/run/docker.sock"})
    with pytest.raises(ValueError, match="Docker socket"):
        build_local_scanner_argv(
            "/cache/source",
            regressed,
            REQUEST_ID,
        )


def test_docker_adapter_normalizes_mocked_scanner_outputs_without_raw_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.atomic.local_cli.scanner_runner._adapters as adapter_module

    source = tmp_path / REQUEST_ID / "source"
    source.mkdir(parents=True)
    policy = SCANNER_MANIFEST_PATH.parent / "semgrep-reviewed.yml"

    def fake_run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 0, b"27.0.0\n", b"")

    outputs = {
        "semgrep": {"runs": []},
        "gitleaks": [],
        "trivy-fs": {"Results": []},
        "trivy-config": {"Results": []},
        "syft": {"bomFormat": "CycloneDX", "components": []},
        "grype": {"matches": []},
        "osv-scanner": {"results": []},
    }

    def fake_capture(
        argv: list[str],
        stdout_path: Path,
        stderr_path: Path,
        **_kwargs: object,
    ) -> int:
        scanner_label = next(value for value in argv if value.startswith("dev.assurance-scan.scanner="))
        kind = scanner_label.partition("=")[2]
        stdout_path.write_text(json.dumps(outputs[kind]))
        stderr_path.write_bytes(b"")
        return 0

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    monkeypatch.setattr(adapter_module, "_capture_bounded", fake_capture)

    result = DockerLocalScannerRunner(reviewed_policy_path=policy).scan(source, REQUEST_ID)

    assert len(result.findings_document["scanners"]) == 8
    assert result.findings_document["scanners"][0]["kind"] == "tribal"
    assert result.findings_document["scanners"][0]["status"] == "completed"
    assert result.findings_document["findings"] == []
    assert result.findings_path.stat().st_mode & 0o077 == 0
    assert result.sarif_path is not None and result.sarif_path.exists()
    assert result.sbom_path is not None and result.sbom_path.exists()
    assert not (source / ".assurance-scan").exists()
    assert not list(result.findings_path.parent.glob("*.stdout"))
    assert not list(result.findings_path.parent.glob("*.stderr"))


def test_docker_adapter_runs_repository_tribal_checks_with_external_scanners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.atomic.local_cli.scanner_runner._adapters as adapter_module

    source = tmp_path / REQUEST_ID / "source"
    source.mkdir(parents=True)
    (source / "tribal-checks.json").write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": "required-policy",
                        "title": "Repository policy is required",
                        "type": "file_exists",
                        "severity": "HIGH",
                        "path": "POLICY.md",
                    }
                ]
            }
        )
    )

    monkeypatch.setattr(
        adapter_module.DockerLocalScannerRunner,
        "_docker_preflight",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        adapter_module.DockerLocalScannerRunner,
        "_ensure_image",
        staticmethod(lambda _image: None),
    )

    def fake_capture(
        argv: list[str], stdout_path: Path, stderr_path: Path, **_kwargs: object
    ) -> int:
        scanner_label = next(
            value for value in argv if value.startswith("dev.assurance-scan.scanner=")
        )
        kind = scanner_label.partition("=")[2]
        payload: object = {"bomFormat": "CycloneDX", "components": []} if kind == "syft" else []
        if kind in {"semgrep", "trivy-fs", "trivy-config", "osv-scanner"}:
            payload = {"runs": []} if kind == "semgrep" else {"Results": []}
        stdout_path.write_text(json.dumps(payload))
        stderr_path.write_bytes(b"")
        return 0

    monkeypatch.setattr(adapter_module, "_capture_bounded", fake_capture)

    result = DockerLocalScannerRunner(
        reviewed_policy_path=SCANNER_MANIFEST_PATH.parent / "semgrep-reviewed.yml"
    ).scan(source, REQUEST_ID)

    tribal = result.findings_document["scanners"][0]
    assert tribal["kind"] == "tribal"
    assert tribal["status"] == "completed"
    assert tribal["error_code"] is None
    assert len(result.findings_document["findings"]) == 1
    tribal_finding = result.findings_document["findings"][0]
    assert tribal_finding["scanner"] == "tribal"
    assert tribal_finding["rule_id"] == "required-policy"
    assert tribal_finding["severity"] == "HIGH"
    assert tribal_finding["file_path"] == "POLICY.md"
    assert tribal_finding["line_start"] is None
    assert tribal_finding["message"] == (
        "Repository policy is required: required file missing: POLICY.md"
    )


def test_docker_adapter_mounts_host_source_but_reads_container_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.atomic.local_cli.scanner_runner._adapters as adapter_module

    source = tmp_path / "container" / "source"
    source.mkdir(parents=True)
    host_source = Path("/host/cache/assurance-scan/runs") / REQUEST_ID / "source"
    seen_argv: list[list[str]] = []

    monkeypatch.setattr(
        adapter_module.DockerLocalScannerRunner,
        "_docker_preflight",
        staticmethod(lambda: None),
    )
    monkeypatch.setattr(
        adapter_module.DockerLocalScannerRunner,
        "_ensure_image",
        staticmethod(lambda _image: None),
    )

    def fake_capture(
        argv: list[str], stdout_path: Path, stderr_path: Path, **_kwargs: object
    ) -> int:
        seen_argv.append(argv)
        scanner_label = next(
            value for value in argv if value.startswith("dev.assurance-scan.scanner=")
        )
        kind = scanner_label.partition("=")[2]
        payload: object = {"bomFormat": "CycloneDX", "components": []} if kind == "syft" else []
        if kind in {"semgrep", "trivy-fs", "trivy-config", "osv-scanner"}:
            payload = {"runs": []} if kind == "semgrep" else {"Results": []}
        stdout_path.write_text(json.dumps(payload))
        stderr_path.write_bytes(b"")
        return 0

    monkeypatch.setattr(adapter_module, "_capture_bounded", fake_capture)

    DockerLocalScannerRunner(
        reviewed_policy_path=SCANNER_MANIFEST_PATH.parent / "semgrep-reviewed.yml"
    ).scan(source, REQUEST_ID, scanner_snapshot_root=host_source)

    assert seen_argv
    assert all(
        any(f"src={host_source}," in item for item in argv) for argv in seen_argv
    )
    assert all(
        not any(f"src={source}," in item for item in argv) for argv in seen_argv
    )
