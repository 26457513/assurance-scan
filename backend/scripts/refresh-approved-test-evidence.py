#!/usr/bin/env python3
"""Refresh a report from approved-test JUnit without running a full scan."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(errors="replace"))
    except Exception:
        return {}
    return {}


def existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def framework_gate_count(path: Path) -> tuple[int, int, int]:
    data = load_json(path)
    processes = data.get("processes") or []
    gates = sum(len(process.get("gates") or []) for process in processes)
    criteria = sum(
        len(gate.get("criteria") or [])
        for process in processes
        for gate in process.get("gates") or []
    )
    versioned = 1 if data.get("version") else 0
    return gates, criteria, versioned


def richest_framework_path(*paths: Path) -> Path | None:
    candidates = [path for path in paths if path.exists()]
    if not candidates:
        return None
    return max(candidates, key=framework_gate_count)


def runtime_dir_for(report_dir: Path, script_dir: Path) -> Path:
    for parent in [report_dir, *report_dir.parents]:
        if parent.name == "runtime" and (parent / "scripts").exists():
            return parent
    return script_dir.parent


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--junit-xml", type=Path)
    args = parser.parse_args()

    report_dir = args.report_dir.resolve()
    if not report_dir.is_dir():
      raise SystemExit(f"report directory not found: {report_dir}")

    reports_dir = report_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_junit = reports_dir / "junit.xml"
    junit_xml = args.junit_xml.resolve() if args.junit_xml else report_junit
    if not junit_xml.exists():
        raise SystemExit(f"JUnit XML not found: {junit_xml}")
    if junit_xml != report_junit:
        shutil.copyfile(junit_xml, report_junit)

    script_dir = Path(__file__).resolve().parent
    runtime_dir = runtime_dir_for(report_dir, script_dir)
    manifest = load_json(report_dir / "evidence-manifest.json")
    target_dir = manifest.get("source_repo") or manifest.get("target_dir") or str(report_dir.parent)
    run_id = manifest.get("run_id") or report_dir.name
    fr_catalog = existing_path(report_dir / "fr-catalog.snapshot.json")

    evidence_cmd = [
        sys.executable,
        str(script_dir / "generate-evidence-bundle.py"),
        "--report-dir",
        str(report_dir),
        "--target-dir",
        str(target_dir),
        "--run-id",
        str(run_id),
    ]
    for image in manifest.get("image_scanned") or []:
        evidence_cmd.extend(["--image-name", str(image)])
    for url in manifest.get("url_scanned") or []:
        evidence_cmd.extend(["--target-url", str(url)])
    for uploads in manifest.get("uploads_scanned") or []:
        evidence_cmd.extend(["--uploads-dir", str(uploads)])
    if fr_catalog:
        evidence_cmd.extend(["--fr-catalog", str(fr_catalog)])
    run_command(evidence_cmd)

    fixtures = runtime_dir / "resources" / "fixtures" / "target-schemas"
    reusable_framework = runtime_dir / "resources" / "assurance-frameworks" / "jsp-453" / "1.0.0-draft.json"
    dashboard_cmd = [
        sys.executable,
        str(script_dir / "generate_dashboard.py"),
        "--report-dir",
        str(report_dir),
        "--junit-xml",
        str(report_junit),
    ]
    if fr_catalog:
        dashboard_cmd.extend(["--fr-catalog", str(fr_catalog)])
    framework_path = richest_framework_path(
        report_dir / "assurance-framework.snapshot.json",
        reusable_framework,
        runtime_dir / "jsp-453.assurance-framework.draft.json",
        fixtures / "assurance-framework.example.json",
    )
    if framework_path and framework_path != report_dir / "assurance-framework.snapshot.json":
        shutil.copyfile(framework_path, report_dir / "assurance-framework.snapshot.json")
        framework_path = report_dir / "assurance-framework.snapshot.json"

    optional_inputs = [
        ("--assurance-framework", framework_path),
        ("--assurance-instance", existing_path(report_dir / "assurance-instance.snapshot.json")),
        ("--compliance-mapping-pack", existing_path(report_dir / "compliance-mapping-pack.snapshot.json", fixtures / "compliance-mapping-pack.example.json")),
        ("--scanner-compliance-mapping-pack", existing_path(report_dir / "scanner-compliance-mapping-packs", runtime_dir / "resources" / "scanner-mappings")),
    ]
    for flag, path in optional_inputs:
        if path:
            dashboard_cmd.extend([flag, str(path)])
    run_command(dashboard_cmd)

    print(f"approved-test evidence refreshed: {report_dir}")
    print(f"junit: {report_junit}")
    print(f"dashboard: {report_dir / 'dashboard.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
