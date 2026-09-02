#!/usr/bin/env python3
"""Run the assurance-scan CI scanner subset and emit one unified SARIF file.

Designed for GitHub Actions compute: no DB, no server — findings go to the
SARIF file and the GitHub Step Summary, never fail the workflow.

Usage:
    python3 backend/scripts/ci-scan.py <project_path> --sarif out.sarif
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.atomic.scanning.result_builder import (
    SCANNER_DESCRIPTIONS,
    build_sarif,
    ci_payload,
    github_branch,
    github_run_url,
    summary_markdown,
)
from app.modules.workflows.github_scan_execution import run_scanners

SBOM_FILENAME = "sbom.cyclonedx.json"


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

    findings, status, durations = asyncio.run(run_scanners(project_path, args.image, sbom_path))
    sarif = build_sarif(findings)
    sarif_path.write_text(json.dumps(sarif, indent=2))
    repo = os.environ.get("ASSURANCE_SCAN_REPO") or os.environ.get("GITHUB_REPOSITORY")
    payload = ci_payload(
        findings, status, durations,
        repo=repo,
        run_url=github_run_url(),
        github_run_id=os.environ.get("GITHUB_RUN_ID"),
        branch=github_branch(),
        commit=os.environ.get("GITHUB_SHA"),
        source_root=Path(project_path),
    )
    sarif_path.with_name("findings.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {sarif_path}: {len(findings)} findings")

    SCANNER_DESCRIPTIONS.setdefault("tribal", "repo-defined checks")
    md = summary_markdown(findings, status, durations)
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
