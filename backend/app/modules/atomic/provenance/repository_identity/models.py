"""Contracts for canonical repository identity handling."""

from __future__ import annotations

class InvalidRepositoryIdentityError(ValueError):
    """Raised when a value cannot identify a supported repository."""
