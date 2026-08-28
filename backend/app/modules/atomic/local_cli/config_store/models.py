"""Contracts for owner-only local CLI configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CliConfig:
    api_url: str
    installation_id: str
    token: str | None = None
    token_label: str | None = None


@dataclass(frozen=True)
class ResolvedCliConfig:
    config: CliConfig
    environment_override_used: bool


class ConfigStoreError(ValueError):
    """Configuration is unsafe, invalid, or cannot be persisted."""


__all__ = ["CliConfig", "ConfigStoreError", "ResolvedCliConfig"]
