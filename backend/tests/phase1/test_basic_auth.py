"""Tests for shared-credential Basic Auth."""
from __future__ import annotations

import base64

from app.modules.atomic.access.browser_auth import (
    allowed_google_account,
    basic_auth_ok,
    mint_session,
    verify_session,
)


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
    assert allowed_google_account({"email": "a@barkleygen.com", "hd": "barkleygen.com"}, "barkleygen.com")
    assert not allowed_google_account({"email": "a@gmail.com", "hd": None}, "barkleygen.com")
    assert not allowed_google_account({"email": "a@other.com", "hd": "other.com"}, "barkleygen.com")

def test_secret_box_roundtrip_and_tamper() -> None:
    from app.secrets import decrypt, encrypt

    token = "ghp_abc123def456"
    blob = encrypt(token, "key-one")
    assert decrypt(blob, "key-one") == token
    assert decrypt(blob, "key-two") is None          # wrong key
    assert decrypt(blob[:-3] + "xyz", "key-one") is None  # tampered
    assert decrypt("garbage", "key-one") is None
    assert encrypt(token, "k1") != encrypt(token, "k1")   # randomized nonce


async def test_github_account_store_roundtrip(session) -> None:
    import datetime as dt
    from sqlalchemy import select as sa_select

    from app.infrastructure.db.models import GithubAccount
    from app.secrets import decrypt, encrypt

    session.add(GithubAccount(
        email="a@barkleygen.com",
        login="auser",
        token_encrypted=encrypt("tok-1", "key"),
        created_at=dt.datetime.now(dt.timezone.utc),
    ))
    await session.commit()
    row = (await session.execute(sa_select(GithubAccount))).scalars().one()
    assert row.login == "auser"
    assert decrypt(row.token_encrypted, "key") == "tok-1"
