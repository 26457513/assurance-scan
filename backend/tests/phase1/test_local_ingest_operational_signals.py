"""Operational signals expose useful counts without accepting sensitive text."""

from __future__ import annotations

import json
import uuid

import pytest

from app.modules.atomic.ingestion.operational_signals import (
    LocalIngestRequestSignal,
    LocalIngestRetentionSignal,
    render_request_signal,
    render_retention_signal,
)


def test_request_signal_contains_only_allowlisted_machine_data() -> None:
    correlation_id = str(uuid.uuid4())
    rendered = render_request_signal(
        LocalIngestRequestSignal(
            outcome="created",
            status_code=201,
            duration_ms=42,
            code="scan_created",
            correlation_id=correlation_id,
            wire_bytes=4096,
            finding_count=3,
            scanner_count=6,
            redaction_count=2,
            project_id=7,
            replayed=False,
        )
    )

    assert json.loads(rendered) == {
        "event": "local_ingest_request",
        "outcome": "created",
        "status_code": 201,
        "duration_ms": 42,
        "code": "scan_created",
        "correlation_id": correlation_id,
        "wire_bytes": 4096,
        "finding_count": 3,
        "scanner_count": 6,
        "redaction_count": 2,
        "project_id": 7,
        "replayed": False,
    }
    assert "repository" not in rendered
    assert "token" not in rendered
    assert "/Users/" not in rendered


def test_retention_signal_contains_counts_only() -> None:
    rendered = render_retention_signal(
        LocalIngestRetentionSignal(
            outcome="completed",
            duration_ms=17,
            raw_artifacts=4,
            normalized_runs=2,
            token_audits=1,
            tombstones=3,
            webhook_deliveries=5,
        )
    )
    assert json.loads(rendered)["event"] == "local_ingest_retention"
    assert "completed" in rendered
    assert json.loads(rendered)["webhook_deliveries"] == 5


@pytest.mark.parametrize("value", ("UPPER", "contains path", "asu_v1_secret.value", "x" * 65))
def test_unbounded_or_sensitive_codes_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="machine code"):
        render_request_signal(
            LocalIngestRequestSignal(
                outcome="rejected",
                status_code=400,
                duration_ms=1,
                code=value,
                correlation_id=str(uuid.uuid4()),
            )
        )
