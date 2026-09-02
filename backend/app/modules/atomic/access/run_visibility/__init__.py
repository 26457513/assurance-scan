"""Framework-free visibility policy for source-neutral scan runs."""

from .models import RunVisibilityContext
from .service import can_view_run

__all__ = ["RunVisibilityContext", "can_view_run"]
