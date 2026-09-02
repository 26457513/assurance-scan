"""Cryptographic boundary for GitHub OIDC authentication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class RsaSignatureVerifier(Protocol):
    def verify(
        self,
        *,
        signing_input: bytes,
        signature: bytes,
        jwk: Mapping[str, Any],
    ) -> bool: ...


__all__ = ["RsaSignatureVerifier"]
