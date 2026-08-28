"""Pure Docker command construction for scanner execution."""
from __future__ import annotations

from app.modules.atomic.scanning.scanner_catalog import PROJECT_MOUNT_TARGET, ScannerConfig


def build_docker_argv(project_path: str, scanner: ScannerConfig) -> list[str]:
    """Build the exact ``docker run`` argument vector for a scanner."""
    argv: list[str] = [
        "docker", "run", "--rm",
        "--label", "com.docker.compose.project=assurance-scan",
        "--label", f"com.docker.compose.service={scanner.kind}",
        "-v", f"{project_path}:{PROJECT_MOUNT_TARGET}:ro",
        "-w", scanner.working_dir,
    ]
    for key, value in scanner.env.items():
        argv.extend(["-e", f"{key}={value}"])
    for source, target in scanner.extra_mounts.items():
        host_side = source[len("volume:"):] if source.startswith("volume:") else source
        argv.extend(["-v", f"{host_side}:{target}"])
    argv.append(scanner.image)
    argv.extend(scanner.command)
    return argv


def named_volumes(scanner: ScannerConfig) -> tuple[str, ...]:
    """Return the named Docker volumes required by a scanner."""
    return tuple(
        source[len("volume:"):]
        for source in scanner.extra_mounts
        if source.startswith("volume:")
    )
