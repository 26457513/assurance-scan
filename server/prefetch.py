"""Prefetch scanner databases into the named cache volumes.

Phase 1 scanners that need DBs:
  - Trivy   → vuln DB (downloaded via `trivy --download-db-only`)
  - Grype   → vuln DB (via `grype db update`)
  - osv-scanner → offline DBs (via `--download-offline-databases`)
  - ClamAV  → signatures (via `freshclam`)

Each prefetch spawns a sibling container that writes into the named
volume. The volume persists across scans.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterable

from server.worker.runner import DockerRunner
from server.worker.scanners import (
    CLAMAV_DB_VOLUME,
    GRYPE_DB_VOLUME,
    OSV_SCANNER_DB_VOLUME,
    TRIVY_CACHE_VOLUME,
)


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PrefetchConfig:
    name: str                          # short id
    image: str
    command: tuple[str, ...]
    extra_mounts: dict[str, str]
    env: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.env is None:
            object.__setattr__(self, "env", {})


_TRIVY = _PrefetchConfig(
    name="trivy",
    image="aquasec/trivy:latest",
    command=("image", "--download-db-only"),
    extra_mounts={f"volume:{TRIVY_CACHE_VOLUME}": "/root/.cache/"},
)

_GRYPE = _PrefetchConfig(
    name="grype",
    image="anchore/grype:latest",
    command=("db", "update"),
    extra_mounts={f"volume:{GRYPE_DB_VOLUME}": "/.cache/grype"},
    env={"GRYPE_DB_AUTO_UPDATE": "true"},
)

_OSV = _PrefetchConfig(
    name="osv",
    image="ghcr.io/google/osv-scanner:latest",
    command=(
        "scan", "source",
        "--download-offline-databases",
        "--offline-vulnerabilities",
        "--recursive",
        "--allow-no-lockfiles",
        "/tmp",  # scan empty dir to trigger DB download only
    ),
    extra_mounts={f"volume:{OSV_SCANNER_DB_VOLUME}": "/root/.cache/osv-scanner"},
)

_CLAMAV = _PrefetchConfig(
    name="clamav",
    image="clamav/clamav:latest",
    command=("freshclam", "--stdout"),
    extra_mounts={f"volume:{CLAMAV_DB_VOLUME}": "/var/lib/clamav"},
)


_ALL: dict[str, _PrefetchConfig] = {
    "trivy": _TRIVY,
    "grype": _GRYPE,
    "osv": _OSV,
    "clamav": _CLAMAV,
}


async def prefetch(names: Iterable[str], project_path: str) -> dict[str, str]:
    """Prefetch one or more scanner DBs. Returns name -> 'ok' | 'failed: msg'."""
    unknown = [n for n in names if n not in _ALL]
    if unknown:
        raise ValueError(f"unknown scanner(s) for prefetch: {unknown}")

    runner = DockerRunner(project_path=project_path)
    results: dict[str, str] = {}
    for name in names:
        cfg = _ALL[name]
        # Ensure the volume exists.
        from server.worker.scanners import ScannerConfig
        # Build a transient ScannerConfig to satisfy ensure_volumes typing.
        proxy = ScannerConfig(
            kind=f"prefetch-{name}",
            image=cfg.image,
            command=cfg.command,
            output_kind="text",
            extra_mounts=cfg.extra_mounts,
            env=cfg.env or {},
            produces_findings=False,
            group="prefetch",
        )
        await runner.ensure_volumes(proxy)

        log.info("prefetching scanner DB: %s", name)
        argv = ["docker", "run", "--rm"]
        for k, v in cfg.env.items() if cfg.env else []:
            argv.extend(["-e", f"{k}={v}"])
        for source, target in cfg.extra_mounts.items():
            argv.extend(["-v", f"{source}:{target}"])
        argv.extend([cfg.image])
        argv.extend(cfg.command)

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            results[name] = "failed: timeout after 600s"
            continue

        if proc.returncode == 0:
            results[name] = "ok"
            log.info("prefetched %s", name)
        else:
            err = (stderr or b"").decode("utf-8", "replace")[:300]
            results[name] = f"failed: exit={proc.returncode} stderr={err}"
            log.warning("prefetch failed for %s: %s", name, err)

    return results


def available_scanners() -> list[str]:
    """Names that can be prefetched."""
    return sorted(_ALL.keys())
