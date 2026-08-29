"""Bounded, scanner-neutral diagnostics for failed Docker executions."""

from __future__ import annotations

import json

from .models import ScannerResult


def scanner_failure_detail(result: ScannerResult, *, limit: int = 800) -> str:
    """Return the most useful bounded diagnostic without assuming stderr.

    SARIF-producing scanners can report execution errors inside stdout while
    Docker writes image-pull progress to stderr. Prefer those structured error
    notifications, then fall back to the tail of stderr or stdout.
    """

    if limit < 1:
        raise ValueError("diagnostic limit must be positive")
    notifications = _sarif_error_notifications(result.stdout)
    if notifications:
        return _bounded("; ".join(notifications), limit)
    stderr = result.stderr.decode("utf-8", "replace").strip()
    if stderr:
        return _bounded_tail(stderr, limit)
    stdout = result.stdout.decode("utf-8", "replace").strip()
    if stdout:
        return _bounded_tail(stdout, limit)
    return "no diagnostic output"


def _sarif_error_notifications(payload: bytes) -> list[str]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(document, dict):
        return []
    messages: list[str] = []
    for run in document.get("runs", []):
        if not isinstance(run, dict):
            continue
        for invocation in run.get("invocations", []):
            if not isinstance(invocation, dict):
                continue
            for item in invocation.get("toolExecutionNotifications", []):
                if not isinstance(item, dict) or item.get("level") != "error":
                    continue
                message = item.get("message")
                text = message.get("text") if isinstance(message, dict) else None
                if isinstance(text, str) and text.strip():
                    messages.append(" ".join(text.split()))
    return messages


def _bounded(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _bounded_tail(value: str, limit: int) -> str:
    return value if len(value) <= limit else "…" + value[-(limit - 1) :]


__all__ = ["scanner_failure_detail"]
