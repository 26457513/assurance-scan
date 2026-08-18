#!/usr/bin/env python3
"""Run the assurance-scan CI scanner subset and emit one unified SARIF file.

Designed for GitHub Actions compute: no DB, no server — findings go to the
SARIF file and the GitHub Step Summary, never fail the workflow.

Usage:
    python3 scripts/ci-scan.py <project_path> --sarif out.sarif
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.worker.parsers import parser_for
from server.worker.parsers.base import ParsedFinding
from server.worker.runner import DockerRunner
from server.worker.sarif import build_sarif, summary_markdown
from server.worker.scanners import ci_scanner_set

SBOM_FILENAME = "sbom.cyclonedx.json"


async def _image_exists(tag: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", tag,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def run_scanners(
    project_path: str,
    image: str | None,
    sbom_path: Path | None,
) -> tuple[list[ParsedFinding], dict[str, str], dict[str, float], bool]:
    image_scanned = True
    if image and not await _image_exists(image):
        print(f"[trivy-image] skipped: image {image} not built")
        image = None
        image_scanned = False
    scanners = ci_scanner_set(image)

    runner = DockerRunner(project_path)
    findings: list[ParsedFinding] = []
    status: dict[str, str] = {}
    durations: dict[str, float] = {}
    for scanner in scanners:
        t0 = time.monotonic()
        try:
            await _run_one(scanner, runner, findings, status, sbom_path)
        finally:
            durations[scanner.kind] = round(time.monotonic() - t0, 1)
    return findings, status, durations, image_scanned


async def _run_one(
    scanner,
    runner: DockerRunner,
    findings: list[ParsedFinding],
    status: dict[str, str],
    sbom_path: Path | None,
) -> None:
    try:
        result = await runner.run(scanner, timeout=900)
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_path", help="path to the repo to scan")
    ap.add_argument("--sarif", required=True, help="output SARIF path")
    ap.add_argument("--image", help="docker image tag to scan with trivy-image (must already be built)")
    args = ap.parse_args()

    project_path = str(Path(args.project_path).resolve())
    sarif_path = Path(args.sarif)
    sbom_path = sarif_path.with_name(SBOM_FILENAME)
    print(f"scanning {project_path} (image={args.image or 'none'})")

    findings, status, durations, image_scanned = asyncio.run(run_scanners(project_path, args.image, sbom_path))
    sarif = build_sarif(findings)
    sarif_path.write_text(json.dumps(sarif, indent=2))
    print(f"wrote {sarif_path}: {len(findings)} findings")

    md = summary_markdown(findings, status, durations, image_scanned)
    sarif_path.with_name("summary.md").write_text(md)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(md)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
