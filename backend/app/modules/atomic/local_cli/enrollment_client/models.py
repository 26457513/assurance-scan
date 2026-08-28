"""Contracts for validating a copied local-scan token before persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EnrollmentConfig:
    api_url: str
    token: str = field(repr=False)
    custom_ca_file: Path | None = field(default=None, repr=False)
    allow_loopback_http: bool = False


@dataclass(frozen=True)
class TokenIdentity:
    account: str
    token_label: str
    scopes: tuple[str, ...]
    expires_at: str


class EnrollmentError(RuntimeError):
    """Token validation failed without retaining or exposing the credential."""


__all__ = ["EnrollmentConfig", "EnrollmentError", "TokenIdentity"]
