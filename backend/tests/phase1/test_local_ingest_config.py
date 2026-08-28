"""Local ingest must remain an explicit deployment opt-in."""

from __future__ import annotations

import pytest

from app.config import load_settings
from app.modules.shared.contracts.local_scan import UPLOAD_LIMITS


def test_local_ingest_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_INGEST_ENABLED", raising=False)
    assert load_settings().local_ingest_enabled is False


def test_local_ingest_accepts_explicit_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_INGEST_ENABLED", "true")
    assert load_settings().local_ingest_enabled is True
    monkeypatch.setenv("LOCAL_INGEST_ENABLED", "off")
    assert load_settings().local_ingest_enabled is False


def test_local_ingest_rejects_ambiguous_boolean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_INGEST_ENABLED", "perhaps")
    with pytest.raises(ValueError, match="LOCAL_INGEST_ENABLED"):
        load_settings()


def test_local_ingest_limits_may_only_be_configured_lower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_INGEST_WIRE_BYTES", "1048576")
    monkeypatch.setenv("LOCAL_INGEST_UPLOADS_PER_TOKEN_HOUR", "3")
    settings = load_settings()
    assert settings.local_ingest_upload_limits.wire_bytes == 1_048_576
    assert settings.local_ingest_usage_limits.uploads_per_token_hour == 3

    monkeypatch.setenv(
        "LOCAL_INGEST_WIRE_BYTES",
        str(UPLOAD_LIMITS.wire_bytes + 1),
    )
    with pytest.raises(ValueError, match="LOCAL_INGEST_WIRE_BYTES"):
        load_settings()
