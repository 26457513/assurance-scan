"""Convenience helpers for publishing common event kinds."""
from __future__ import annotations

from app.events import bus


def publish_scan_started(run_id: str, project_path: str, scanner_kinds: list[str]) -> None:
    bus.publish(run_id, "scan_started", {
        "run_id": run_id,
        "project_path": project_path,
        "scanners": scanner_kinds,
    })


def publish_scanner_started(run_id: str, scanner_kind: str) -> None:
    bus.publish(run_id, "scanner_started", {
        "run_id": run_id,
        "scanner": scanner_kind,
    })


def publish_scanner_completed(
    run_id: str,
    scanner_kind: str,
    status: str,
    finding_count: int,
    error_message: str | None = None,
) -> None:
    bus.publish(run_id, "scanner_completed", {
        "run_id": run_id,
        "scanner": scanner_kind,
        "status": status,
        "finding_count": finding_count,
        "error_message": error_message,
    })


def publish_scan_completed(run_id: str, total_findings: int, status: str) -> None:
    bus.publish(run_id, "scan_completed", {
        "run_id": run_id,
        "status": status,
        "total_findings": total_findings,
    })
