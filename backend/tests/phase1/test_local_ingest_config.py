"""Local ingest must remain an explicit deployment opt-in."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.config import account_identity_is_ready, load_settings
from app.modules.shared.contracts.local_scan import UPLOAD_LIMITS
from app.modules.shared.contracts.ingest_v2 import GITHUB_USAGE_LIMITS_V2


def test_local_ingest_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_INGEST_ENABLED", raising=False)
    monkeypatch.delenv("SCAN_TOKEN_CREATION_ENABLED", raising=False)
    monkeypatch.delenv("SCAN_TOKEN_CREATION_USER_ALLOWLIST", raising=False)
    monkeypatch.delenv("LOCAL_INGEST_REPOSITORY_ALLOWLIST", raising=False)
    monkeypatch.delenv("GITHUB_OIDC_INGEST_ENABLED", raising=False)
    settings = load_settings()
    assert settings.local_ingest_enabled is False
    assert settings.scan_token_creation_enabled is False
    assert settings.scan_token_creation_user_allowlist == frozenset()
    assert settings.local_ingest_repository_allowlist == frozenset()
    assert settings.github_oidc_ingest_enabled is False


def test_github_oidc_ingest_requires_an_explicit_strict_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_OIDC_INGEST_ENABLED", "true")
    assert load_settings().github_oidc_ingest_enabled is True
    monkeypatch.setenv("GITHUB_OIDC_INGEST_ENABLED", "enable-ish")
    with pytest.raises(ValueError, match="GITHUB_OIDC_INGEST_ENABLED"):
        load_settings()


def test_local_ingest_accepts_explicit_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_INGEST_ENABLED", "true")
    assert load_settings().local_ingest_enabled is True
    monkeypatch.setenv("LOCAL_INGEST_ENABLED", "off")
    assert load_settings().local_ingest_enabled is False


def test_local_ingest_rejects_ambiguous_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_INGEST_ENABLED", "perhaps")
    with pytest.raises(ValueError, match="LOCAL_INGEST_ENABLED"):
        load_settings()


def test_token_creation_requires_an_explicit_strict_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCAN_TOKEN_CREATION_ENABLED", "true")
    assert load_settings().scan_token_creation_enabled is True
    monkeypatch.setenv("SCAN_TOKEN_CREATION_ENABLED", "enable-ish")
    with pytest.raises(ValueError, match="SCAN_TOKEN_CREATION_ENABLED"):
        load_settings()


def test_canary_allowlist_is_canonical_case_insensitive_and_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LOCAL_INGEST_REPOSITORY_ALLOWLIST",
        "26457513/assurance-scan,Owner/Repository",
    )
    assert load_settings().local_ingest_repository_allowlist == frozenset(
        {"26457513/assurance-scan", "owner/repository"}
    )

    for invalid in (
        "26457513/assurance-scan,",
        "26457513/assurance-scan,  Owner/Repository",
        "https://github.com/26457513/assurance-scan",
        "Owner/Repository,owner/repository",
        "not-a-repository",
    ):
        monkeypatch.setenv("LOCAL_INGEST_REPOSITORY_ALLOWLIST", invalid)
        with pytest.raises(ValueError, match="LOCAL_INGEST_REPOSITORY_ALLOWLIST"):
            load_settings()


def test_token_creation_user_allowlist_normalizes_and_rejects_ambiguous_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SCAN_TOKEN_CREATION_USER_ALLOWLIST",
        "Admin@Example.COM,tester@example.com",
    )
    assert load_settings().scan_token_creation_user_allowlist == frozenset({"admin@example.com", "tester@example.com"})
    for invalid in (
        "admin@example.com,",
        "admin@example.com, tester@example.com",
        "admin@example.com,ADMIN@example.com",
        "not-an-email",
        "admin@localhost",
    ):
        monkeypatch.setenv("SCAN_TOKEN_CREATION_USER_ALLOWLIST", invalid)
        with pytest.raises(ValueError, match="SCAN_TOKEN_CREATION_USER_ALLOWLIST"):
            load_settings()


def test_account_identity_readiness_requires_https_origin_and_strong_session_secret() -> None:
    ready = SimpleNamespace(
        google_client_id="client",
        google_client_secret="secret",
        session_secret="session-secret-at-least-32-bytes-long",
        public_base_url="https://scan.example.test",
    )
    assert account_identity_is_ready(ready) is True
    ready.session_secret = "short"
    assert account_identity_is_ready(ready) is False
    ready.session_secret = "session-secret-at-least-32-bytes-long"
    ready.public_base_url = "http://scan.example.test"
    assert account_identity_is_ready(ready) is False
    ready.public_base_url = "http://127.0.0.1:8000"
    assert account_identity_is_ready(ready) is True
    ready.public_base_url = "http://localhost:8000"
    assert account_identity_is_ready(ready) is True
    ready.public_base_url = "http://localhost.attacker.example"
    assert account_identity_is_ready(ready) is False
    ready.public_base_url = "https://scan.example.test/path"
    assert account_identity_is_ready(ready) is False


def test_local_ingest_limits_may_only_be_configured_lower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_INGEST_WIRE_BYTES", "1048576")
    monkeypatch.setenv("LOCAL_INGEST_UPLOADS_PER_TOKEN_HOUR", "3")
    monkeypatch.setenv("GITHUB_INGEST_UPLOADS_PER_REPOSITORY_HOUR", "4")
    monkeypatch.setenv("INGEST_INFLIGHT_PER_INSTANCE", "5")
    settings = load_settings()
    assert settings.local_ingest_upload_limits.wire_bytes == 1_048_576
    assert settings.local_ingest_usage_limits.uploads_per_token_hour == 3
    assert settings.github_ingest_usage_limits.uploads_per_repository_hour == 4
    assert settings.shared_ingest_usage_limits.inflight_per_instance == 5

    monkeypatch.setenv(
        "LOCAL_INGEST_WIRE_BYTES",
        str(UPLOAD_LIMITS.wire_bytes + 1),
    )
    with pytest.raises(ValueError, match="LOCAL_INGEST_WIRE_BYTES"):
        load_settings()

    monkeypatch.setenv("LOCAL_INGEST_WIRE_BYTES", "1048576")
    monkeypatch.setenv(
        "GITHUB_INGEST_UPLOADS_PER_REPOSITORY_HOUR",
        str(GITHUB_USAGE_LIMITS_V2.uploads_per_repository_hour + 1),
    )
    with pytest.raises(ValueError, match="GITHUB_INGEST_UPLOADS_PER_REPOSITORY_HOUR"):
        load_settings()
