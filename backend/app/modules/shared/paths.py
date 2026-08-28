"""Canonical paths for files bundled with the backend distribution."""

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
RESOURCES_ROOT = BACKEND_ROOT / "resources"


__all__ = ["BACKEND_ROOT", "RESOURCES_ROOT"]
