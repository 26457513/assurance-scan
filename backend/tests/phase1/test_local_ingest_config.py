"""Local ingest must remain an explicit deployment opt-in."""

from __future__ import annotations

import pytest

from app.config import load_settings


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
