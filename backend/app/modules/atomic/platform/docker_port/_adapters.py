"""Async subprocess adapter for the Docker execution port."""
from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import Iterable

from app.modules.atomic.scanning.scanner_catalog import ScannerConfig

from .models import ScannerResult
from .service import build_docker_argv, named_volumes

log = logging.getLogger(__name__)


class DockerRunner:
    """Spawn scanner containers and capture their output."""

    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self._ensured_volumes: set[str] = set()

    def _build_argv(self, scanner: ScannerConfig) -> list[str]:
        return build_docker_argv(self.project_path, scanner)

    async def ensure_volumes(self, scanner: ScannerConfig) -> None:
        for volume in named_volumes(scanner):
            if volume in self._ensured_volumes:
                continue
            if not await _volume_exists(volume):
                log.info("creating docker volume %s", volume)
                await _run_cmd(("docker", "volume", "create", volume))
            self._ensured_volumes.add(volume)

    async def run(self, scanner: ScannerConfig, timeout: int = 600) -> ScannerResult:
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
