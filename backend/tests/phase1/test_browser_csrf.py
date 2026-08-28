"""Boundary tests for signed browser mutation protection."""

from __future__ import annotations

from app.modules.atomic.access.browser_csrf import (
    mint_csrf_token,
    validate_csrf_request,
)


def _valid(**overrides: object) -> bool:
    token = overrides.pop("token", mint_csrf_token(user_key="7", secret="secret", now=100))
    values = {
        "cookie_token": token,
        "header_token": token,
        "request_origin": "https://scan.example.test",
        "public_base_url": "https://scan.example.test/app",
        "user_key": "7",
        "secret": "secret",
        "now": 101,
        **overrides,
    }
    return validate_csrf_request(**values)  # type: ignore[arg-type]


def test_csrf_accepts_exact_origin_and_matching_signed_submissions() -> None:
    assert _valid()


def test_csrf_normalizes_only_default_origin_ports() -> None:
    assert _valid(
        request_origin="https://scan.example.test:443",
        public_base_url="https://scan.example.test",
    )
    assert not _valid(request_origin="https://scan.example.test:8443")


def test_csrf_rejects_missing_mismatched_or_cross_origin_submission() -> None:
    assert not _valid(header_token=None)
    assert not _valid(header_token="different")
    assert not _valid(request_origin="https://evil.example.test")
    assert not _valid(request_origin=None)


def test_csrf_rejects_tampering_wrong_user_and_expiry() -> None:
    token = mint_csrf_token(user_key="7", secret="secret", now=100)
    replacement = "0" if token[-1] != "0" else "1"
    assert not _valid(token=f"{token[:-1]}{replacement}")
    assert not _valid(token=token, user_key="8")
    assert not _valid(token=token, now=3_701)
