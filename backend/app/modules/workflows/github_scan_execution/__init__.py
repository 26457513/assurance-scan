"""Public API for GitHub Actions scanner execution."""

from .models import ScanExecutionResult
from .service import run_scanners

__all__ = ["ScanExecutionResult", "run_scanners"]
