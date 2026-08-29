"""Safe, deterministic rendering for the vendored CI workflow template."""

from __future__ import annotations

import re
from pathlib import Path

from app.modules.shared.paths import RESOURCES_ROOT


DEFAULT_TEMPLATE_PATH = RESOURCES_ROOT / "templates" / "assurance-scan.yml"
_DEFAULT_BRANCH_PLACEHOLDER = "<default branch>"
_BRANCH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}")


def render_ci_workflow(
    default_branch: str,
    *,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
) -> str:
    """Return the canonical workflow with one validated default branch substituted."""
    branch = default_branch.strip()
    if not _is_valid_branch_name(branch):
        raise ValueError("default branch name is invalid")

    template = template_path.read_text(encoding="utf-8")
    if template.count(_DEFAULT_BRANCH_PLACEHOLDER) != 1:
        raise RuntimeError("CI workflow template must contain exactly one default-branch placeholder")
    rendered = template.replace(_DEFAULT_BRANCH_PLACEHOLDER, branch)
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def _is_valid_branch_name(branch: str) -> bool:
    return bool(
        _BRANCH_NAME.fullmatch(branch)
        and not branch.endswith(("/", ".", ".lock"))
        and not branch.startswith(".")
        and ".." not in branch
        and "//" not in branch
        and "@{" not in branch
    )
