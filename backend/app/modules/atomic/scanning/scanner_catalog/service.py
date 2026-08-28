"""Declarative scanner catalogue and deterministic set selection."""
from __future__ import annotations

from dataclasses import replace

from .models import ScannerConfig

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

PROJECT_MOUNT_TARGET = "/src"

SEMGREP = ScannerConfig(
    kind="semgrep",
    image="semgrep/semgrep:latest",
    command=(
        "semgrep",
        "scan",
        "--config",
        "auto",
        "--timeout",
        "30",
        "--sarif",
        "--quiet",
        PROJECT_MOUNT_TARGET,
    ),
    output_kind="sarif",
)

GITLEAKS = ScannerConfig(
    kind="gitleaks",
    image="zricethezav/gitleaks:latest",
    command=(
        "detect",
        "--source", PROJECT_MOUNT_TARGET,
        "--report-format", "json",
        "--report-path", "-",
        "--no-banner",
        "--no-git",
        "--exit-code", "0",
    ),
    output_kind="json",
)

TRIVY_FS = ScannerConfig(
    kind="trivy-fs",
    image="aquasec/trivy:latest",
    command=("fs", "--scanners", "vuln", "--format", "json", "--quiet", PROJECT_MOUNT_TARGET),
    output_kind="json",
    group="image",
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)

TRIVY_CONFIG = ScannerConfig(
    kind="trivy-config",
    image="aquasec/trivy:latest",
    command=("config", "--skip-check-update", "--format", "json", "--quiet", PROJECT_MOUNT_TARGET),
    output_kind="json",
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)

SYFT = ScannerConfig(
    kind="syft",
    image="anchore/syft:latest",
    command=(PROJECT_MOUNT_TARGET, "-o", "cyclonedx-json"),
    output_kind="cyclonedx-json",
    produces_findings=False,
    group="image",
)

GRYPE = ScannerConfig(
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

TRIVY_IMAGE = ScannerConfig(
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
    extra_mounts={
        f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/",
        "/var/run/docker.sock": "/var/run/docker.sock",
    },
)

OSV_SCANNER = ScannerConfig(
    kind="osv-scanner",
    image="ghcr.io/google/osv-scanner:latest",
    command=("scan", "source", "--recursive", "--format", "json", PROJECT_MOUNT_TARGET),
    output_kind="json",
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


def ci_scanner_set(image: str | None = None) -> tuple[ScannerConfig, ...]:
    """Return the CI scanner set, optionally including an application image."""
    scanners = tuple(scanner for scanner in CODE_SCANNERS if scanner.kind != "trivy-image")
    if image:
        scanners += (replace(TRIVY_IMAGE, command=TRIVY_IMAGE.command[:-1] + (image,)),)
    return scanners
