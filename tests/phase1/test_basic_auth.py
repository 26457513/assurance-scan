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


def test_session_roundtrip_and_tamper() -> None:
    from server.auth import mint_session, verify_session

    token = mint_session("user@barkleygen.com", "sekrit")
    assert verify_session(token, "sekrit") == "user@barkleygen.com"
    # Wrong secret / tampered token rejected.
    assert verify_session(token, "other") is None
    assert verify_session(token[:-2] + "zz", "sekrit") is None
    assert verify_session(None, "sekrit") is None
    # Expired sessions rejected.
    expired = mint_session("u@x", "sekrit", ttl=-10)
    assert verify_session(expired, "sekrit") is None


def test_google_account_domain_gate() -> None:
    from server.auth import allowed_google_account

    assert allowed_google_account({"email": "a@barkleygen.com", "hd": "barkleygen.com"}, "barkleygen.com")
    assert not allowed_google_account({"email": "a@gmail.com", "hd": None}, "barkleygen.com")
    assert not allowed_google_account({"email": "a@other.com", "hd": "other.com"}, "barkleygen.com")
