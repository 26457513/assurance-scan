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
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.worker.parsers import parser_for
from server.worker.parsers.base import ParsedFinding
from server.worker.runner import DockerRunner
from server.worker.sarif import build_sarif
from server.worker.scanners import ci_scanner_set

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "UNKNOWN"]
SUMMARY_TOP_FINDINGS = 15

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
) -> tuple[list[ParsedFinding], dict[str, str]]:
    if image and not await _image_exists(image):
        print(f"[trivy-image] skipped: image {image} not built")
        image = None
    scanners = ci_scanner_set(image)

    runner = DockerRunner(project_path)
    findings: list[ParsedFinding] = []
    status: dict[str, str] = {}
    for scanner in scanners:
        try:
            result = await runner.run(scanner, timeout=900)
        except Exception as exc:  # timeout, docker missing, etc.
            status[scanner.kind] = f"error: {exc}"
            print(f"[{scanner.kind}] ERROR {exc}", file=sys.stderr)
            continue
        if result.returncode not in scanner.success_exit_codes:
            err = result.stderr.decode("utf-8", "replace")[:300]
            status[scanner.kind] = f"exit={result.returncode}"
            print(f"[{scanner.kind}] FAILED exit={result.returncode}: {err}", file=sys.stderr)
            continue
        if scanner.output_kind == "cyclonedx-json" and sbom_path is not None:
            sbom_path.write_bytes(result.stdout)
            print(f"[{scanner.kind}] ok (SBOM written to {sbom_path})")
        try:
            parsed = parser_for(scanner).parse(result.stdout)
        except Exception as exc:
            status[scanner.kind] = f"parse-error: {exc}"
            print(f"[{scanner.kind}] PARSE ERROR {exc}", file=sys.stderr)
            continue
        findings.extend(parsed)
        status[scanner.kind] = "ok"
        print(f"[{scanner.kind}] ok ({len(parsed)} findings)")
    return findings, status


def summary_markdown(findings: list[ParsedFinding], status: dict[str, str]) -> str:
    by_severity = Counter(f.severity for f in findings)
    by_scanner = Counter(f.scanner_kind for f in findings)
    failed = {k: v for k, v in status.items() if v != "ok"}

    lines = ["## assurance-scan", ""]
    lines.append(f"**{len(findings)} findings** "
                 + " · ".join(f"{s}: {by_severity[s]}" for s in SEVERITY_ORDER if by_severity[s]))
    lines.append("")
    lines.append("By scanner: " + " · ".join(f"{k} {v}" for k, v in sorted(by_scanner.items())))
    lines.append("")

    if findings:
        lines.append("| Severity | Scanner | Rule | Location |")
        lines.append("|---|---|---|---|")
        ranked = sorted(findings, key=lambda f: SEVERITY_ORDER.index(f.severity) if f.severity in SEVERITY_ORDER else 99)
        for f in ranked[:SUMMARY_TOP_FINDINGS]:
            if f.file_path and f.line_start is not None:
                loc = f"{f.file_path}:{f.line_start}"
            else:
                loc = f.file_path or "-"
            rule = f.rule_id or "(unclassified)"
            lines.append(f"| {f.severity} | {f.scanner_kind} | {rule} | {loc} |")
        if len(findings) > SUMMARY_TOP_FINDINGS:
            lines.append("")
            lines.append(f"_…and {len(findings) - SUMMARY_TOP_FINDINGS} more — see the SARIF artifact._")

    if failed:
        lines.append("")
        lines.append("**Scanners with problems:**")
        for kind, why in sorted(failed.items()):
            lines.append(f"- `{kind}` — {why}")
    return "\n".join(lines) + "\n"


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

    findings, status = asyncio.run(run_scanners(project_path, args.image, sbom_path))
    sarif = build_sarif(findings)
    sarif_path.write_text(json.dumps(sarif, indent=2))
    print(f"wrote {sarif_path}: {len(findings)} findings")

    md = summary_markdown(findings, status)
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
