#!/usr/bin/env python3
"""Produce a canonical Assurance Scan v2 bundle for a GitHub default-branch push."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.modules.atomic.scanning.result_builder import summary_markdown
from app.modules.atomic.scanning.result_builder.models import Finding
from app.modules.workflows.github_result_production import (
    GitHubResultProductionCommand,
    produce_github_result_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_path", help="read-only checked-out repository root")
    parser.add_argument("--output", required=True, help="new directory for the result bundle")
    parser.add_argument(
        "--scanner-snapshot-path",
        required=True,
        help="host-visible path corresponding to <output>/.source-snapshot",
    )
    parser.add_argument("--image", help="prebuilt application image to scan")
    args = parser.parse_args()

    result = asyncio.run(
        produce_github_result_bundle(
            GitHubResultProductionCommand(
                project_root=Path(args.project_path),
                output_root=Path(args.output),
                scanner_snapshot_path=args.scanner_snapshot_path,
                environment=os.environ,
                application_image=args.image,
            )
        )
    )
    findings = result.scan.findings
    outcomes = result.scan.scanner_outcomes
    status = {
        item.kind: "ok" if item.status == "completed" else str(item.error_code)
        for item in outcomes
    }
    durations = {item.kind: round(item.duration_ms / 1000, 1) for item in outcomes}
    summary = summary_markdown(cast(Sequence[Finding], findings), status, durations)
    (result.output_root / "summary.md").write_text(summary, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8") as handle:
            handle.write(summary)
    make_bundle_readable(result.output_root)
    print(f"produced v2 bundle ({result.finding_count} findings)")
    return 0


def make_bundle_readable(root: Path) -> None:
    """Allow the distinct non-root upload container to read only final artifacts."""
    for artifact in root.iterdir():
        if artifact.is_file() and not artifact.is_symlink():
            artifact.chmod(0o444)
    root.chmod(0o555)


if __name__ == "__main__":
    sys.exit(main())
