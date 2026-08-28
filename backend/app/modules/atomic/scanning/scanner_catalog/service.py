"""Reviewed scanner release catalogue and deterministic set selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from .models import ScannerConfig, ScannerReleaseSet

TRIVY_CACHE_VOLUME = "assurance-trivy-cache"
GRYPE_DB_VOLUME = "assurance-grype-db"
OSV_SCANNER_DB_VOLUME = "assurance-osv-scanner-db"
CLAMAV_DB_VOLUME = "assurance-clamav-db"
ALL_CACHE_VOLUMES: tuple[str, ...] = (
    TRIVY_CACHE_VOLUME, GRYPE_DB_VOLUME, OSV_SCANNER_DB_VOLUME, CLAMAV_DB_VOLUME,
)
PROJECT_MOUNT_TARGET = "/src"

_BACKEND_ROOT = Path(__file__).resolve().parents[5]
SCANNER_MANIFEST_PATH = _BACKEND_ROOT / "resources" / "scanners" / "release-set.v1.json"
_MANIFEST_BYTES = SCANNER_MANIFEST_PATH.read_bytes()
_MANIFEST = cast(dict[str, Any], json.loads(_MANIFEST_BYTES))


def _required_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"scanner release manifest has invalid {key}")
    return value


def _scanner_record(kind: str) -> dict[str, Any]:
    scanners = _MANIFEST.get("scanners")
    if not isinstance(scanners, list):
        raise RuntimeError("scanner release manifest has no scanners")
    matches = [item for item in scanners if isinstance(item, dict) and item.get("kind") == kind]
    if len(matches) != 1:
        raise RuntimeError(f"scanner release manifest must define {kind} exactly once")
    return cast(dict[str, Any], matches[0])


def _config(kind: str, command: tuple[str, ...], output_kind: str, **overrides: Any) -> ScannerConfig:
    record = _scanner_record(kind)
    image = _required_text(record, "image")
    if "@sha256:" not in image or image.endswith(":latest"):
        raise RuntimeError(f"scanner {kind} is not pinned to an immutable index digest")
    platforms = record.get("platform_digests")
    if not isinstance(platforms, dict):
        raise RuntimeError(f"scanner {kind} has no platform qualification")
    required_platforms = tuple(cast(list[str], _MANIFEST["required_platforms"]))
    if set(platforms) != set(required_platforms):
        raise RuntimeError(f"scanner {kind} does not qualify every required platform")
    values: dict[str, Any] = {
        "kind": kind,
        "image": image,
        "command": command,
        "output_kind": output_kind,
        "tool_version": _required_text(record, "tool_version"),
        "platform_digests": dict(platforms),
        "success_exit_codes": tuple(cast(list[int], record["success_exit_codes"])),
        "timeout_seconds": int(record["timeout_seconds"]),
        "network": "none" if record.get("network") == "none" else "bridge",
        "memory_mib": int(record["memory_mib"]),
        "cpus": float(record["cpus"]),
        "env": dict(cast(dict[str, str], record.get("environment", {}))),
    }
    if "tmpfs" in record:
        values["tmpfs"] = tuple(cast(list[str], record["tmpfs"]))
    values.update(overrides)
    return ScannerConfig(**values)


_policy = cast(dict[str, Any], _MANIFEST["semgrep_policy"])
SCANNER_RELEASE_SET = ScannerReleaseSet(
    schema_version=int(_MANIFEST["schema_version"]),
    name=_required_text(_MANIFEST, "release_set"),
    sha256=hashlib.sha256(_MANIFEST_BYTES).hexdigest(),
    required_platforms=tuple(cast(list[str], _MANIFEST["required_platforms"])),
    vulnerability_database_max_age_hours=int(_MANIFEST["vulnerability_database_max_age_hours"]),
    semgrep_policy_path=_required_text(_policy, "path"),
    semgrep_policy_container_path=_required_text(_policy, "container_path"),
    semgrep_policy_sha256=_required_text(_policy, "sha256"),
)

SEMGREP = _config(
    "semgrep",
    ("semgrep", "scan", "--config", SCANNER_RELEASE_SET.semgrep_policy_container_path,
     "--timeout", "30", "--sarif", "--quiet", PROJECT_MOUNT_TARGET),
    "sarif",
)
GITLEAKS = _config(
    "gitleaks",
    ("detect", "--source", PROJECT_MOUNT_TARGET, "--report-format", "json",
     "--report-path", "-", "--no-banner", "--no-git", "--exit-code", "0"),
    "json",
)
TRIVY_FS = _config(
    "trivy-fs",
    ("fs", "--scanners", "vuln", "--format", "json", "--quiet", PROJECT_MOUNT_TARGET),
    "json", group="image",
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)
TRIVY_CONFIG = _config(
    "trivy-config",
    ("config", "--skip-check-update", "--format", "json", "--quiet", PROJECT_MOUNT_TARGET),
    "json", extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)
SYFT = _config(
    "syft", (PROJECT_MOUNT_TARGET, "-o", "cyclonedx-json"), "cyclonedx-json",
    produces_findings=False, group="image",
)
GRYPE = _config(
    "grype",
    ("dir:" + PROJECT_MOUNT_TARGET, "-o", "json", "--exclude", "**/node_modules/**",
     "--exclude", "**/frontend/build/**"),
    "json", group="image", extra_mounts={f"volume:{GRYPE_DB_VOLUME}": "/.cache/grype"},
    env={"GRYPE_DB_AUTO_UPDATE": "true"},
)
TRIVY_IMAGE = _config(
    "trivy-image",
    ("image", "--scanners", "vuln", "--format", "json", "--quiet", "--ignore-unfixed",
     "assurance-scan:v3"),
    "json", group="image",
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/",
                  "/var/run/docker.sock": "/var/run/docker.sock"},
)
OSV_SCANNER = _config(
    "osv-scanner",
    ("scan", "source", "--recursive", "--format", "json", PROJECT_MOUNT_TARGET),
    "json", extra_mounts={f"volume:{OSV_SCANNER_DB_VOLUME}": "/root/.cache/osv-scanner"},
)

CODE_SCANNERS: tuple[ScannerConfig, ...] = (
    SEMGREP, GITLEAKS, TRIVY_FS, TRIVY_CONFIG, TRIVY_IMAGE, SYFT, GRYPE, OSV_SCANNER,
)


def ci_scanner_set(image: str | None = None) -> tuple[ScannerConfig, ...]:
    """Return the pinned CI scanner set, optionally including an application image."""
    scanners = tuple(scanner for scanner in CODE_SCANNERS if scanner.kind != "trivy-image")
    if image:
        scanners += (replace(TRIVY_IMAGE, command=TRIVY_IMAGE.command[:-1] + (image,)),)
    return scanners


__all__ = [
    "ALL_CACHE_VOLUMES", "CLAMAV_DB_VOLUME", "CODE_SCANNERS", "GITLEAKS", "GRYPE",
    "GRYPE_DB_VOLUME", "OSV_SCANNER", "OSV_SCANNER_DB_VOLUME", "PROJECT_MOUNT_TARGET",
    "SCANNER_MANIFEST_PATH", "SCANNER_RELEASE_SET", "SEMGREP", "SYFT",
    "TRIVY_CACHE_VOLUME", "TRIVY_CONFIG", "TRIVY_FS", "TRIVY_IMAGE", "ci_scanner_set",
]
