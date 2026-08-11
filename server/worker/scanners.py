"""Declarative per-scanner configuration.

One dataclass per scanner kind. Each defines the image, command, volume
mounts (cache + extra), and which parser to use. Adding a new scanner
is one dataclass plus one parser module.

Cache volumes use an `assurance-` prefix to avoid collisions with any
user-named volumes. The worker creates them on first scan if missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Scanner cache volumes — persistent Docker named volumes.
# ---------------------------------------------------------------------------

TRIVY_CACHE_VOLUME = "assurance-trivy-cache"
GRYPE_DB_VOLUME = "assurance-grype-db"
OSV_SCANNER_DB_VOLUME = "assurance-osv-scanner-db"
CLAMAV_DB_VOLUME = "assurance-clamav-db"

ALL_CACHE_VOLUMES: tuple[str, ...] = (
    TRIVY_CACHE_VOLUME,
    GRYPE_DB_VOLUME,
    OSV_SCANNER_DB_VOLUME,
    CLAMAV_DB_VOLUME,
)


# Project bind-mount target (read-only inside scanner containers).
PROJECT_MOUNT_TARGET = "/src"


@dataclass(frozen=True)
class ScannerConfig:
    """All the worker needs to spawn and parse one scanner."""

    kind: str                              # short id, e.g. "semgrep"
    image: str                             # docker image
    command: tuple[str, ...]               # args after the image
    output_kind: str                       # 'sarif' | 'json' | 'text' | 'cyclonedx-json'
    # Exit codes that indicate a successful scan. Most scanners use 0 only,
    # but some (osv-scanner, gitleaks) exit 1 to signal "findings detected" —
    # the output is still valid and must be parsed.
    success_exit_codes: tuple[int, ...] = (0,)
    # Mounts in addition to the project bind-mount. host path -> container path.
    # Use docker-volume: prefixed names for named volumes (e.g. "volume:foo:/path").
    extra_mounts: dict[str, str] = field(default_factory=dict)
    # Working dir inside the container. Defaults to /src.
    working_dir: str = "/src"
    # Environment variables passed to the scanner container.
    env: dict[str, str] = field(default_factory=dict)
    # Optional: this scanner produces no findings (e.g. SBOM-only). The raw
    # artifact is still stored, just no parsed rows.
    produces_findings: bool = True
    # Optional: a label used for grouping in the UI / findings.json summary.
    group: str = "code"


# ---------------------------------------------------------------------------
# Code scanners (always run for source scans)
# ---------------------------------------------------------------------------


SEMGREP: ScannerConfig = ScannerConfig(
    kind="semgrep",
    image="semgrep/semgrep:latest",
    # Official semgrep image has no ENTRYPOINT — executable name must be first.
    command=("semgrep", "scan", "--config", "auto", "--sarif", "--quiet", PROJECT_MOUNT_TARGET),
    output_kind="sarif",
)


GITLEAKS: ScannerConfig = ScannerConfig(
    kind="gitleaks",
    image="zricethezav/gitleaks:latest",
    # Gitleaks returns non-zero exit when leaks are found; treat as success.
    # Use `-` for report path so output goes to stdout.
    command=(
        "detect",
        "--source", PROJECT_MOUNT_TARGET,
        "--report-format", "json",
        "--report-path", "-",  # dash = stdout
        "--no-banner",
        "--no-git",
        "--exit-code", "0",
    ),
    output_kind="json",
)


TRIVY_FS: ScannerConfig = ScannerConfig(
    kind="trivy-fs",
    image="aquasec/trivy:latest",
    command=(
        "fs",
        "--scanners", "vuln",
        "--format", "json",
        "--quiet",
        PROJECT_MOUNT_TARGET,
    ),
    output_kind="json",
    group="image",
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)


TRIVY_CONFIG: ScannerConfig = ScannerConfig(
    kind="trivy-config",
    image="aquasec/trivy:latest",
    command=(
        "config",
        "--skip-check-update",
        "--format", "json",
        "--quiet",
        PROJECT_MOUNT_TARGET,
    ),
    output_kind="json",
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)


SYFT: ScannerConfig = ScannerConfig(
    kind="syft",
    image="anchore/syft:latest",
    command=(PROJECT_MOUNT_TARGET, "-o", "cyclonedx-json"),
    output_kind="cyclonedx-json",
    produces_findings=False,
    group="image",
)


GRYPE: ScannerConfig = ScannerConfig(
    kind="grype",
    image="anchore/grype:latest",
    command=(
        "dir:" + PROJECT_MOUNT_TARGET,
        "-o", "json",
        "--exclude", "**/node_modules/**",
        "--exclude", "**/frontend/build/**",
    ),
    output_kind="json",
    group="image",
    extra_mounts={f"volume:{GRYPE_DB_VOLUME}": "/.cache/grype"},
    env={"GRYPE_DB_AUTO_UPDATE": "true"},
)


TRIVY_IMAGE: ScannerConfig = ScannerConfig(
    kind="trivy-image",
    image="aquasec/trivy:latest",
    command=(
        "image",
        "--scanners", "vuln",
        "--format", "json",
        "--quiet",
        "--ignore-unfixed",
        "assurance-scan:v3",
    ),
    output_kind="json",
    group="image",
    # Needs the Docker socket to inspect the local image.
    extra_mounts={
        f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/",
        "/var/run/docker.sock": "/var/run/docker.sock",
    },
)


OSV_SCANNER: ScannerConfig = ScannerConfig(
    kind="osv-scanner",
    image="ghcr.io/google/osv-scanner:latest",
    # No --offline-vulnerabilities: queries OSV API on first run, caches after.
    command=(
        "scan", "source",
        "--recursive",
        "--format", "json",
        PROJECT_MOUNT_TARGET,
    ),
    output_kind="json",
    # osv-scanner exits 1 when vulnerabilities are found — that's a successful
    # scan with findings, not an error. The JSON output is still valid.
    success_exit_codes=(0, 1),
    extra_mounts={f"volume:{OSV_SCANNER_DB_VOLUME}": "/root/.cache/osv-scanner"},
)


CODE_SCANNERS: tuple[ScannerConfig, ...] = (
    SEMGREP,
    GITLEAKS,
    TRIVY_FS,
    TRIVY_CONFIG,
    TRIVY_IMAGE,
    SYFT,
    GRYPE,
    OSV_SCANNER,
)


def get_scanner(kind: str) -> ScannerConfig:
    """Look up a scanner config by kind. Raises KeyError if unknown."""
    for scanner in CODE_SCANNERS:
        if scanner.kind == kind:
            return scanner
    raise KeyError(f"unknown scanner kind: {kind}")
