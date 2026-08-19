"""Spawns scanner containers via the docker CLI.

Uses the host's docker socket (mounted into the server container). Each
scanner runs as a sibling container, not a child — that's how the
existing run-local.sh pattern works, and it lets scanners see the
project at the same path the user does.

`extra_mounts` keys may be prefixed with `volume:` to bind a Docker named
volume instead of a host path. The worker creates any missing named
volumes on first use.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass
from typing import Iterable

from server.worker.scanners import PROJECT_MOUNT_TARGET, ScannerConfig


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScannerResult:
    """Outcome of running one scanner."""

    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class DockerRunner:
    """Spawns scanner containers and captures their stdout."""

    def __init__(self, project_path: str) -> None:
        # project_path is the host path (== container path thanks to the
        # $PWD:$PWD mount trick).
        self.project_path = project_path
        self._ensured_volumes: set[str] = set()

    def _build_argv(self, scanner: ScannerConfig) -> list[str]:
        """Build the docker run argv for one scanner."""
        argv: list[str] = [
            "docker", "run", "--rm",
            "--label", "com.docker.compose.project=assurance-scan",
            "--label", f"com.docker.compose.service={scanner.kind}",
            "-v", f"{self.project_path}:{PROJECT_MOUNT_TARGET}:ro",
            "-w", scanner.working_dir,
        ]
        for k, v in scanner.env.items():
            argv.extend(["-e", f"{k}={v}"])
        for source, target in scanner.extra_mounts.items():
            # Strip the `volume:` prefix used by scanners.py to flag named volumes.
            # Docker just wants the bare volume name on the left side of `-v`.
            host_side = source[len("volume:"):] if source.startswith("volume:") else source
            argv.extend(["-v", f"{host_side}:{target}"])
        argv.extend([scanner.image])
        argv.extend(scanner.command)
        return argv

    async def ensure_volumes(self, scanner: ScannerConfig) -> None:
        """Create any named volumes this scanner needs if they don't exist."""
        for source in scanner.extra_mounts:
            if not source.startswith("volume:"):
                continue
            vol = source[len("volume:"):]
            if vol in self._ensured_volumes:
                continue
            exists = await _volume_exists(vol)
            if not exists:
                log.info("creating docker volume %s", vol)
                await _run_cmd(("docker", "volume", "create", vol))
            self._ensured_volumes.add(vol)

    async def run(self, scanner: ScannerConfig, timeout: int = 600) -> ScannerResult:
        """Spawn the scanner container and capture its output."""
        await self.ensure_volumes(scanner)

        argv = self._build_argv(scanner)
        log.info("running scanner kind=%s argv=%s", scanner.kind, shlex.join(argv))

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        returncode = proc.returncode if proc.returncode is not None else -1
        return ScannerResult(returncode=returncode, stdout=stdout or b"", stderr=stderr or b"")


async def _volume_exists(name: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker", "volume", "inspect", name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def _run_cmd(argv: Iterable[str]) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout or b"", stderr or b""
