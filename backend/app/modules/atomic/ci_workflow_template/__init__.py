"""Render the standard repository workflow used by GitHub Actions scans."""

from .service import render_ci_workflow

__all__ = ["render_ci_workflow"]
