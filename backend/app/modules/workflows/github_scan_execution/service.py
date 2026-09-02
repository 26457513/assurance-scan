"""Orchestrate the existing GitHub Actions scanner execution path."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from app.modules.atomic.platform.docker_port import DockerRunner
from app.modules.atomic.scanning.finding_parser import ParsedFinding, parser_for
from app.modules.atomic.scanning.result_producer import (
    ScannerErrorCode,
    ScannerOutcome,
    ScannerStatus,
)
from app.modules.atomic.scanning.scanner_catalog import ScannerConfig, ci_scanner_set
from app.modules.atomic.scanning.tribal_checks import TRIBAL_FILENAME, load_checks, run_checks

from .models import ScanExecutionResult


async def _image_exists(tag: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "image",
        "inspect",
        tag,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def run_scanners(
    project_path: str,
    scanner_project_path: str,
    image: str | None,
    sbom_path: Path | None,
) -> ScanExecutionResult:
    """Run the established CI scanner set and return its normalized results."""
    if image and not await _image_exists(image):
        print(f"[trivy-image] skipped: image {image} not built")
        image = None
    scanners = ci_scanner_set(image)

    runner = DockerRunner(scanner_project_path)
    findings: list[ParsedFinding] = []
    outcomes: list[ScannerOutcome] = []
    sbom: dict[str, object] | None = None

    started = time.monotonic()
    try:
        tribal = run_checks(Path(project_path), load_checks(Path(project_path)))
        findings.extend(tribal)
        print(f"[tribal] ok ({len(tribal)} findings from {TRIBAL_FILENAME})")
        tribal_status: ScannerStatus = "completed"
        tribal_error: ScannerErrorCode | None = None
    except Exception:
        tribal_status = "failed"
        tribal_error = "scanner_output_invalid"
        print("[tribal] failed (scanner_output_invalid)", file=sys.stderr)
    outcomes.append(
        ScannerOutcome(
            kind="tribal",
            status=tribal_status,
            duration_ms=_duration_ms(started),
            image=None,
            tool_version=None,
            error_code=tribal_error,
        )
    )

    for scanner in scanners:
        started = time.monotonic()
        outcome, scanner_sbom = await _run_one(scanner, runner, findings, sbom_path)
        outcomes.append(
            ScannerOutcome(
                kind=scanner.kind,
                status=outcome[0],
                duration_ms=_duration_ms(started),
                image=scanner.image,
                tool_version=scanner.tool_version or None,
                error_code=outcome[1],
            )
        )
        if scanner_sbom is not None:
            sbom = scanner_sbom
    if not any(item.status == "completed" for item in outcomes):
        raise RuntimeError("no scanner produced a valid result")
    return ScanExecutionResult(tuple(findings), tuple(outcomes), sbom)


async def _run_one(
    scanner: ScannerConfig,
    runner: DockerRunner,
    findings: list[ParsedFinding],
    sbom_path: Path | None,
) -> tuple[tuple[ScannerStatus, ScannerErrorCode | None], dict[str, object] | None]:
    try:
        result = await runner.run(scanner, timeout=scanner.timeout_seconds)
    except TimeoutError:
        print(f"[{scanner.kind}] failed (scanner_timeout)", file=sys.stderr)
        return ("failed", "scanner_timeout"), None
    except Exception:  # Docker unavailable or another bounded execution failure.
        print(f"[{scanner.kind}] failed (scanner_dependency_failed)", file=sys.stderr)
        return ("failed", "scanner_dependency_failed"), None
    if result.returncode not in scanner.success_exit_codes:
        print(f"[{scanner.kind}] failed (scanner_exit_nonzero)", file=sys.stderr)
        return ("failed", "scanner_exit_nonzero"), None
    sbom: dict[str, object] | None = None
    if scanner.output_kind == "cyclonedx-json" and sbom_path is not None:
        sbom_path.write_bytes(result.stdout)
        try:
            parsed_sbom = json.loads(result.stdout)
            if isinstance(parsed_sbom, dict):
                sbom = parsed_sbom
            else:
                raise ValueError
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            print(f"[{scanner.kind}] failed (scanner_output_invalid)", file=sys.stderr)
            return ("failed", "scanner_output_invalid"), None
        print(f"[{scanner.kind}] ok (SBOM written to {sbom_path})")
    try:
        parsed = parser_for(scanner).parse(result.stdout)
    except Exception:
        print(f"[{scanner.kind}] failed (scanner_output_invalid)", file=sys.stderr)
        return ("failed", "scanner_output_invalid"), None
    findings.extend(parsed)
    print(f"[{scanner.kind}] ok ({len(parsed)} findings)")
    return ("completed", None), sbom


def _duration_ms(started: float) -> int:
    return min(86_400_000, round((time.monotonic() - started) * 1000))
