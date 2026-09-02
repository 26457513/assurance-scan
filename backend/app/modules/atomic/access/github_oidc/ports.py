"""Cryptographic boundary for GitHub OIDC authentication."""

from __future__ import annotations

from collections.abc import Mapping
import datetime as dt
from typing import Any, Protocol


class RsaSignatureVerifier(Protocol):
    def verify(
        self,
        *,
        signing_input: bytes,
        signature: bytes,
        jwk: Mapping[str, Any],
    ) -> bool: ...


class GithubOidcReplayRepository(Protocol):
    async def consume(
        self,
        *,
        jti_digest: bytes,
        repository_id: int,
        consumed_at: dt.datetime,
        expires_at: dt.datetime,
    ) -> bool: ...


__all__ = ["GithubOidcReplayRepository", "RsaSignatureVerifier"]
