"""Render allowlisted, machine-readable local-ingest operational signals."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from .models import LocalIngestRequestSignal, LocalIngestRetentionSignal


_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_MAX_COUNTER = 1 << 63


def render_request_signal(signal: LocalIngestRequestSignal) -> str:
    """Return stable JSON with no repository, credential, path, or principal fields."""
    _validate_code(signal.outcome, field="outcome")
    _validate_code(signal.code, field="code")
    if not 100 <= signal.status_code <= 599:
        raise ValueError("status_code must be an HTTP status")
    fields = _without_none(asdict(signal))
    _validate_counters(fields, exclude={"status_code"})
    return _render("local_ingest_request", fields)


def render_retention_signal(signal: LocalIngestRetentionSignal) -> str:
    """Return stable JSON containing cleanup counts only."""
    _validate_code(signal.outcome, field="outcome")
    fields = asdict(signal)
    _validate_counters(fields)
    return _render("local_ingest_retention", fields)


def _render(event: str, fields: dict[str, Any]) -> str:
    return json.dumps({"event": event, **fields}, sort_keys=True, separators=(",", ":"))


def _without_none(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def _validate_code(value: str, *, field: str) -> None:
    if not _CODE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded machine code")


def _validate_counters(fields: dict[str, Any], *, exclude: set[str] | None = None) -> None:
    ignored = exclude or set()
    for key, value in fields.items():
        if key in ignored or isinstance(value, (str, bool)):
            continue
        if not isinstance(value, int) or value < 0 or value > _MAX_COUNTER:
            raise ValueError(f"{key} must be a bounded non-negative integer")


__all__ = ["render_request_signal", "render_retention_signal"]
