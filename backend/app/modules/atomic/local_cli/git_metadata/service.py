"""Strict GitHub remote normalization and Git metadata collection."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .models import GitCommandPort, GitMetadataError, GitRepositoryMetadata


_REPOSITORY = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCP_REMOTE = re.compile(r"^git@github\.com:(?P<path>[^?#]+)$", re.IGNORECASE)


def normalize_github_repository(value: str) -> str:
    """Normalize supported GitHub HTTPS/SSH remotes or an owner/repo override."""
    candidate = value.strip()
    match = _SCP_REMOTE.fullmatch(candidate)
    if match:
        path = match.group("path")
    elif "://" in candidate:
        parsed = urlsplit(candidate)
        if parsed.scheme not in ("https", "ssh") or parsed.hostname is None:
            raise GitMetadataError("unsupported Git remote")
        if parsed.hostname.casefold() != "github.com" or parsed.query or parsed.fragment:
            raise GitMetadataError("remote must be hosted on github.com")
        if parsed.scheme == "ssh" and parsed.username != "git":
            raise GitMetadataError("SSH GitHub remote must use the git user")
        if parsed.scheme == "https" and (parsed.username or parsed.password):
            raise GitMetadataError("HTTPS GitHub remote must not contain credentials")
        path = unquote(parsed.path).lstrip("/")
    else:
        path = candidate
    if path.endswith(".git"):
        path = path[:-4]
    if not _REPOSITORY.fullmatch(path):
        raise GitMetadataError("repository must be a canonical owner/repo")
    return path


def collect_git_metadata(
    root: Path,
    git: GitCommandPort,
    *,
    project_override: str | None = None,
) -> GitRepositoryMetadata:
    """Collect authoritative metadata from a repository-root invocation."""
    resolved_root = root.resolve(strict=True)
    top = _required(git, ("rev-parse", "--show-toplevel"), resolved_root).decode().strip()
    try:
        reported_root = Path(top).resolve(strict=True)
    except OSError as exc:
        raise GitMetadataError("Git reported an invalid repository root") from exc
    if reported_root != resolved_root:
        raise GitMetadataError("scan must be invoked from the Git repository root")

    if project_override:
        override = normalize_github_repository(project_override)
        repository = override
    else:
        remote = _required(git, ("config", "--get", "remote.origin.url"), resolved_root).decode().strip()
        repository = normalize_github_repository(remote)
        override = None

    branch_result = git.run(("symbolic-ref", "--quiet", "--short", "HEAD"), cwd=resolved_root)
    if branch_result.returncode == 0:
        branch = branch_result.stdout.decode("utf-8").strip()
        if not branch or len(branch) > 512 or "\x00" in branch or "\n" in branch:
            raise GitMetadataError("Git branch is invalid")
    elif branch_result.returncode == 1:
        branch = None
    else:
        raise GitMetadataError("unable to determine Git branch")

    object_format = _required(git, ("rev-parse", "--show-object-format"), resolved_root).decode().strip()
    commit = _required(git, ("rev-parse", "HEAD"), resolved_root).decode().strip()
    if object_format == "sha1" and not _SHA1.fullmatch(commit):
        raise GitMetadataError("Git commit is not a lowercase SHA-1")
    if object_format == "sha256" and not _SHA256.fullmatch(commit):
        raise GitMetadataError("Git commit is not a lowercase SHA-256")
    if object_format not in ("sha1", "sha256"):
        raise GitMetadataError("Git object format is unsupported")
    status = _required(git, ("status", "--porcelain=v1", "-z"), resolved_root)
    return GitRepositoryMetadata(
        repository=repository,
        branch=branch,
        commit=commit,
        git_object_format=object_format,
        working_tree_dirty=bool(status),
        project_override=override,
    )


def _required(git: GitCommandPort, arguments: tuple[str, ...], cwd: Path) -> bytes:
    result = git.run(arguments, cwd=cwd)
    if result.returncode != 0:
        raise GitMetadataError(f"Git command failed: {' '.join(arguments)}")
    return result.stdout


__all__ = ["collect_git_metadata", "normalize_github_repository"]
