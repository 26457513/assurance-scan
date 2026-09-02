"""Safe, deterministic rendering for the vendored CI workflow template."""

from __future__ import annotations

from pathlib import Path

from app.modules.shared.paths import RESOURCES_ROOT


DEFAULT_TEMPLATE_PATH = RESOURCES_ROOT / "templates" / "assurance-scan.yml"
def render_ci_workflow(
    *,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
) -> str:
    """Return the canonical workflow guarded by GitHub's live default branch."""
    rendered = template_path.read_text(encoding="utf-8")
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered
