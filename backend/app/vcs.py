"""Best-effort git helpers. Return None when the path isn't a repo or git is missing."""
from __future__ import annotations

import asyncio


async def git_head(project_path: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", project_path, "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return out.decode("utf-8", "replace").strip()[:64] or None


async def git_branch(project_path: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", project_path, "rev-parse", "--abbrev-ref", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return out.decode("utf-8", "replace").strip()[:64] or None
