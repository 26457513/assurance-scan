"""Bounded subprocess adapter for Git metadata commands."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from .models import GitCommandResult, GitMetadataError


class SubprocessGitCommand:
    """Invoke Git with explicit safe-directory and bounded captured output."""

    def __init__(self, *, timeout_seconds: int = 60, max_output_bytes: int = 64 * 1024 * 1024) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run(self, arguments: Sequence[str], *, cwd: Path) -> GitCommandResult:
        resolved = cwd.resolve(strict=True)
        environment = os.environ.copy()
        environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
        command = ["git", "-c", f"safe.directory={resolved}", *arguments]
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                completed = subprocess.run(
                    command,
                    cwd=resolved,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    check=False,
                    timeout=self.timeout_seconds,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GitMetadataError("Git command could not be completed") from exc
            stdout.seek(0, os.SEEK_END)
            stdout_size = stdout.tell()
            stderr.seek(0, os.SEEK_END)
            stderr_size = stderr.tell()
            if stdout_size > self.max_output_bytes or stderr_size > self.max_output_bytes:
                raise GitMetadataError("Git command output exceeded its safety bound")
            stdout.seek(0)
            stderr.seek(0)
            return GitCommandResult(completed.returncode, stdout.read(), stderr.read())


__all__ = ["SubprocessGitCommand"]
