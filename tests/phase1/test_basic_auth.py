"""Tests for shared-credential Basic Auth."""
from __future__ import annotations

import base64

from server.auth import basic_auth_ok


def _header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_correct_credentials_accepted() -> None:
    assert basic_auth_ok(_header("team", "secret"), "team", "secret")


def test_wrong_password_rejected() -> None:
    assert not basic_auth_ok(_header("team", "wrong"), "team", "secret")
    assert not basic_auth_ok(_header("other", "secret"), "team", "secret")


def test_missing_or_malformed_rejected() -> None:
    assert not basic_auth_ok(None, "team", "secret")
    assert not basic_auth_ok("", "team", "secret")
    assert not basic_auth_ok("Bearer xyz", "team", "secret")
    assert not basic_auth_ok("Basic !!!not-base64!!!", "team", "secret")


def test_password_containing_colon() -> None:
    assert basic_auth_ok(_header("team", "pa:ss:word"), "team", "pa:ss:word")
