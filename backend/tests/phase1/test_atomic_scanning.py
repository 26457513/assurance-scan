"""Characterization checks for atomic scanner extraction boundaries."""
from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

from app.modules.atomic.platform.docker_port import (
    ScannerResult,
    build_docker_argv,
    named_volumes,
    scanner_failure_detail,
)
from app.modules.atomic.scanning.scanner_catalog import (
    GRYPE,
    SEMGREP,
    SEMGREP_POLICY_PATH,
    ScannerConfig,
    TRIVY_IMAGE,
)
from app.modules.atomic.scanning.result_builder import build_sarif
from app.modules.workflows.github_result_production import produce_github_result_bundle
from app.modules.atomic.scanning.finding_parser import ParsedFinding


def test_scanner_catalog_exposes_atomic_contracts() -> None:
    assert isinstance(GRYPE, ScannerConfig)
    assert TRIVY_IMAGE.kind == "trivy-image"
    assert SEMGREP_POLICY_PATH.is_file()
    assert SEMGREP_POLICY_PATH.name == "semgrep-reviewed.yml"


def test_docker_argv_preserves_mount_environment_and_command_order() -> None:
    argv = build_docker_argv("/repo with spaces", GRYPE)

    assert argv == [
        "docker", "run", "--rm",
        "--label", "com.docker.compose.project=assurance-scan",
        "--label", "com.docker.compose.service=grype",
        "-v", "/repo with spaces:/src:ro",
        "-w", "/src",
        "-e", "GRYPE_DB_AUTO_UPDATE=true",
        "-v", "assurance-grype-db:/.cache/grype",
        "anchore/grype@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7",
        "dir:/src", "-o", "json",
        "--exclude", "**/node_modules/**",
        "--exclude", "**/frontend/build/**",
    ]
    assert named_volumes(GRYPE) == ("assurance-grype-db",)


def test_atomic_result_builder_renders_normalized_findings() -> None:
    finding = ParsedFinding(
        scanner_kind="semgrep",
        rule_id="python.lang.correctness",
        severity="HIGH",
        file_path="src/app.py",
        line_start=7,
        line_end=7,
        message="example",
    )

    sarif = build_sarif([finding])
    assert sarif["runs"][0]["results"][0]["ruleId"] == "semgrep/python.lang.correctness"


def test_semgrep_materializes_the_reviewed_stdin_policy_before_scanning() -> None:
    command = " ".join(SEMGREP.command)

    assert SEMGREP.requires_stdin
    assert SEMGREP.command[:3] == ("sh", "-eu", "-c")
    assert 'cat > "$policy_path"' in command
    assert 'semgrep scan --config "$policy_path"' in command
    assert "/tmp/assurance-scan-semgrep-policy.yml" in command
    assert "--interactive" in build_docker_argv("/repo", SEMGREP)


def test_failed_sarif_scanner_prefers_structured_error_over_docker_stderr() -> None:
    stdout = json.dumps({
        "runs": [{
            "invocations": [{
                "toolExecutionNotifications": [{
                    "level": "error",
                    "message": {"text": "invalid configuration\nfile"},
                }],
            }],
        }],
    }).encode()
    result = ScannerResult(
        returncode=7,
        stdout=stdout,
        stderr=b"Pulling layer\nPull complete",
    )

    assert scanner_failure_detail(result) == "invalid configuration file"


def test_failed_non_sarif_scanner_uses_bounded_stderr_tail() -> None:
    result = ScannerResult(returncode=2, stdout=b"", stderr=b"pull noise: actual failure")

    assert scanner_failure_detail(result, limit=14) == "…ctual failure"


def test_ci_script_delegates_result_production_to_workflow() -> None:
    script = Path(__file__).parents[2] / "scripts" / "ci-scan.py"
    spec = importlib.util.spec_from_file_location("assurance_scan_ci_entrypoint", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.produce_github_result_bundle is produce_github_result_bundle


def test_ci_script_makes_finished_bundle_readable_by_isolated_uploader(
    tmp_path: Path,
) -> None:
    script = Path(__file__).parents[2] / "scripts" / "ci-scan.py"
    spec = importlib.util.spec_from_file_location("assurance_scan_ci_permissions", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    artifact = tmp_path / "metadata.json"
    artifact.write_text("{}", encoding="utf-8")

    module.make_bundle_readable(tmp_path)

    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o555
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o444
