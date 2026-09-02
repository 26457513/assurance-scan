"""Abuse-boundary tests for unknown GitHub OIDC signing key IDs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.infrastructure.github_oidc import GithubOidcJwksClient


def test_unknown_kids_cannot_amplify_jwks_refresh_within_cooldown(monkeypatch) -> None:
    calls: list[int] = []

    def fetch():
        calls.append(1)
        return {"keys": [{"kid": "known"}]}

    monkeypatch.setattr("app.infrastructure.github_oidc._fetch_jwks", fetch)
    client = GithubOidcJwksClient()
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)

    assert client.get(now=now, required_kid="known")["keys"]
    assert client.get(now=now, required_kid="unknown-one")["keys"]
    assert client.get(now=now + timedelta(seconds=1), required_kid="unknown-two")["keys"]
    assert client.get(now=now + timedelta(seconds=59), required_kid="unknown-three")["keys"]

    assert len(calls) == 2


def test_unknown_kid_may_refresh_again_after_cooldown(monkeypatch) -> None:
    calls: list[int] = []

    def fetch():
        calls.append(1)
        return {"keys": [{"kid": "known"}]}

    monkeypatch.setattr("app.infrastructure.github_oidc._fetch_jwks", fetch)
    client = GithubOidcJwksClient()
    now = datetime(2026, 9, 2, tzinfo=timezone.utc)

    client.get(now=now, required_kid="missing")
    client.get(now=now + timedelta(seconds=61), required_kid="still-missing")

    assert len(calls) == 2

