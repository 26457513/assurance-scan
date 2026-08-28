"""Prepare existing CI inputs for source-neutral ingestion.

WSR deliberately retains the legacy permissive contract. Strict protocol
validation belongs to the later versioned upload feature.
"""
from __future__ import annotations

from typing import Any

from app.modules.shared.contracts.ingest import ResultBundle


def validate_bundle(
    payload: dict[str, Any] | None,
    metadata: dict[str, Any],
    blobs: dict[str, bytes] | None = None,
) -> ResultBundle:
    """Return a normalized bundle without changing legacy validation behavior."""

    return ResultBundle(payload=payload, metadata=metadata, blobs=blobs or {})
