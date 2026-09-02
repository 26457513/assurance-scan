"""Security contract tests for dormant GitHub identity/session foundations."""

from __future__ import annotations

import datetime as dt
import base64
import hashlib

import pytest
from sqlalchemy import select

from app.infrastructure.db.models import BrowserSession, GithubOauthState, User
from app.infrastructure.db.repositories.identity_sessions import (
    SqlAlchemyBrowserSessionRepository,
    SqlAlchemyGithubOauthStateRepository,
)
from app.modules.atomic.access.github_oauth_state import (
    GithubOauthFlow,
    GithubOauthStateValidationError,
    issue_github_oauth_state,
)
from app.modules.atomic.access.server_session import (
    SESSION_ABSOLUTE_LIMIT,
    SESSION_IDLE_LIMIT,
    SessionDecision,
    authenticate_browser_session,
    issue_browser_session,
    refreshed_idle_expiry,
)


NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


class DeterministicRandom:
    def __init__(self) -> None:
        self.counter = 0

    def random_bytes(self, size: int) -> bytes:
        self.counter += 1
        return bytes([self.counter]) * size


def test_browser_session_uses_opaque_digest_and_enforces_both_expiries() -> None:
    issued = issue_browser_session(user_id=7, now=NOW, random=DeterministicRandom())

    assert issued.cookie_value.startswith("ass_v1_")
    assert len(issued.cookie_value.removeprefix("ass_v1_")) == 43
    assert issued.cookie_value.encode() not in issued.record.session_digest
    assert issued.record.session_digest == hashlib.sha256(issued.cookie_value.encode()).digest()
    assert issued.record.idle_expires_at == NOW + SESSION_IDLE_LIMIT
    assert issued.record.absolute_expires_at == NOW + SESSION_ABSOLUTE_LIMIT
    assert (
        authenticate_browser_session(issued.cookie_value, issued.record, now=NOW).decision
        is SessionDecision.AUTHENTICATED
    )
    assert (
        authenticate_browser_session(issued.cookie_value, issued.record, now=issued.record.idle_expires_at).decision
        is SessionDecision.IDLE_EXPIRED
    )
    assert (
        authenticate_browser_session(
            issued.cookie_value,
            issued.record,
            now=issued.record.absolute_expires_at,
        ).decision
        is SessionDecision.ABSOLUTE_EXPIRED
    )


def test_idle_refresh_never_crosses_absolute_limit() -> None:
    issued = issue_browser_session(user_id=7, now=NOW, random=DeterministicRandom())
    near_absolute = issued.record.absolute_expires_at - dt.timedelta(hours=1)
    assert refreshed_idle_expiry(issued.record, now=near_absolute) == issued.record.absolute_expires_at


def test_oauth_state_is_independent_256_bit_material_with_pkce_s256() -> None:
    material = issue_github_oauth_state(
        browser_session_id="session-id",
        flow_kind=GithubOauthFlow.LINK,
        return_path="/setup",
        now=NOW,
        random=DeterministicRandom(),
    )

    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(material.pkce_verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert len(material.state) == 43
    assert len(material.state_digest) == 32
    assert len(material.pkce_verifier) == 86
    assert material.pkce_challenge == expected_challenge
    assert material.state not in repr(material)
    assert material.pkce_verifier not in repr(material)


def test_oauth_return_path_is_an_exact_internal_allowlist() -> None:
    with pytest.raises(GithubOauthStateValidationError):
        issue_github_oauth_state(
            browser_session_id="session-id",
            flow_kind=GithubOauthFlow.SIGNIN,
            return_path="//attacker.example",
            now=NOW,
            random=DeterministicRandom(),
        )


@pytest.mark.asyncio
async def test_repositories_store_no_plaintext_and_consume_state_once(session) -> None:
    user = User(email="session-user@example.test", role="user", created_at=NOW)
    session.add(user)
    await session.commit()
    issued_session = issue_browser_session(user_id=user.id, now=NOW, random=DeterministicRandom())
    sessions = SqlAlchemyBrowserSessionRepository(session)
    await sessions.create(issued_session.record)

    stored_session = (await session.execute(select(BrowserSession))).scalar_one()
    assert issued_session.cookie_value.encode() not in bytes(stored_session.session_digest)
    assert (await sessions.find_by_cookie(issued_session.cookie_value)) == issued_session.record

    material = issue_github_oauth_state(
        browser_session_id=issued_session.record.session_id,
        flow_kind=GithubOauthFlow.LINK,
        return_path="/setup",
        now=NOW,
        random=DeterministicRandom(),
    )
    states = SqlAlchemyGithubOauthStateRepository(
        session,
        encryption_keys={"primary": "test-encryption-key"},
        active_key_id="primary",
    )
    await states.create(material)
    stored_state = (await session.execute(select(GithubOauthState))).scalar_one()
    assert material.state not in stored_state.pkce_verifier_encrypted
    assert material.pkce_verifier not in stored_state.pkce_verifier_encrypted

    assert (
        await states.consume(
            material.state,
            browser_session_id=issued_session.record.session_id,
            now=NOW + dt.timedelta(minutes=1),
        )
        is not None
    )
    assert (
        await states.consume(
            material.state,
            browser_session_id=issued_session.record.session_id,
            now=NOW + dt.timedelta(minutes=2),
        )
        is None
    )


@pytest.mark.asyncio
async def test_oauth_state_rejects_wrong_session_and_expiry_without_consuming(session) -> None:
    user = User(email="oauth-user@example.test", role="user", created_at=NOW)
    session.add(user)
    await session.commit()
    issued_session = issue_browser_session(user_id=user.id, now=NOW, random=DeterministicRandom())
    await SqlAlchemyBrowserSessionRepository(session).create(issued_session.record)
    material = issue_github_oauth_state(
        browser_session_id=issued_session.record.session_id,
        flow_kind=GithubOauthFlow.SIGNIN,
        return_path="/",
        now=NOW,
        random=DeterministicRandom(),
    )
    states = SqlAlchemyGithubOauthStateRepository(session, encryption_keys={"v1": "key"}, active_key_id="v1")
    await states.create(material)

    assert await states.consume(material.state, browser_session_id="wrong", now=NOW) is None
    assert (
        await states.consume(
            material.state,
            browser_session_id=issued_session.record.session_id,
            now=material.expires_at,
        )
        is None
    )
