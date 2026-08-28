"""Characterization checks for atomic scanner extraction boundaries."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.modules.atomic.platform.docker_port import build_docker_argv, named_volumes
from app.modules.atomic.scanning.scanner_catalog import GRYPE, ScannerConfig, TRIVY_IMAGE
from app.modules.atomic.scanning.result_builder import build_sarif
from app.modules.workflows.github_scan_execution import run_scanners
from app.modules.atomic.scanning.finding_parser import ParsedFinding


def test_scanner_catalog_exposes_atomic_contracts() -> None:
    assert isinstance(GRYPE, ScannerConfig)
    assert TRIVY_IMAGE.kind == "trivy-image"


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


def test_ci_script_delegates_scanner_execution_to_workflow() -> None:
    script = Path(__file__).parents[2] / "scripts" / "ci-scan.py"
    spec = importlib.util.spec_from_file_location("assurance_scan_ci_entrypoint", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.run_scanners is run_scanners
