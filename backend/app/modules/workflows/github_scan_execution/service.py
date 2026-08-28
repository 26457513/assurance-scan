"""Orchestrate the existing GitHub Actions scanner execution path."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from app.modules.atomic.platform.docker_port import DockerRunner
from app.modules.atomic.scanning.finding_parser import ParsedFinding, parser_for
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
    image: str | None,
    sbom_path: Path | None,
) -> ScanExecutionResult:
    """Run the established CI scanner set and return its normalized results."""
    if image and not await _image_exists(image):
        print(f"[trivy-image] skipped: image {image} not built")
        image = None
    scanners = ci_scanner_set(image)

    runner = DockerRunner(project_path)
    findings: list[ParsedFinding] = []
    status: dict[str, str] = {}
    durations: dict[str, float] = {}

    started = time.monotonic()
    try:
        tribal = run_checks(Path(project_path), load_checks(Path(project_path)))
        findings.extend(tribal)
        status["tribal"] = "ok"
        print(f"[tribal] ok ({len(tribal)} findings from {TRIBAL_FILENAME})")
    except Exception as exc:
        status["tribal"] = f"error: {exc}"
        print(f"[tribal] ERROR {exc}", file=sys.stderr)
    durations["tribal"] = round(time.monotonic() - started, 1)

    for scanner in scanners:
        started = time.monotonic()
        try:
            await _run_one(scanner, runner, findings, status, sbom_path)
        finally:
            durations[scanner.kind] = round(time.monotonic() - started, 1)
    return findings, status, durations


async def _run_one(
    scanner: ScannerConfig,
    runner: DockerRunner,
    findings: list[ParsedFinding],
    status: dict[str, str],
    sbom_path: Path | None,
) -> None:
    try:
        result = await runner.run(scanner, timeout=scanner.timeout_seconds)
    except Exception as exc:  # timeout, docker missing, etc.
        status[scanner.kind] = f"error: {exc}"
        print(f"[{scanner.kind}] ERROR {exc}", file=sys.stderr)
        return
    if result.returncode not in scanner.success_exit_codes:
        err = result.stderr.decode("utf-8", "replace")[:300]
        status[scanner.kind] = f"exit={result.returncode}"
        print(f"[{scanner.kind}] FAILED exit={result.returncode}: {err}", file=sys.stderr)
        return
    if scanner.output_kind == "cyclonedx-json" and sbom_path is not None:
        sbom_path.write_bytes(result.stdout)
        print(f"[{scanner.kind}] ok (SBOM written to {sbom_path})")
    try:
        parsed = parser_for(scanner).parse(result.stdout)
    except Exception as exc:
        status[scanner.kind] = f"parse-error: {exc}"
        print(f"[{scanner.kind}] PARSE ERROR {exc}", file=sys.stderr)
        return
    findings.extend(parsed)
    status[scanner.kind] = "ok"
    print(f"[{scanner.kind}] ok ({len(parsed)} findings)")
