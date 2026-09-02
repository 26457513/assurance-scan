"""Deterministic, bounded source context extraction from an immutable snapshot."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import cast

from app.modules.atomic.ingestion.data_redactor import redact_text
from app.modules.shared.contracts.findings import FindingPayload
from app.modules.shared.contracts.source_context import (
    SourceContextPayload,
    SourceContextUnavailableReason,
    SourceLinePayload,
)

from .models import REDACTION_VERSION, SourceContextExtraction, SourceContextLimits


_FINDING_NAMESPACE = uuid.UUID("8eaeddb2-76ef-5a75-95d2-f4f86c91a00e")
_TRUNCATION_MARKER = "…[truncated]"


def extract_source_contexts(
    snapshot_root: Path,
    findings: Sequence[FindingPayload],
    *,
    schema_version: int,
    limits: SourceContextLimits = SourceContextLimits(),
) -> SourceContextExtraction:
    """Assign finding keys and extract safe source windows from ``snapshot_root``."""

    root = snapshot_root.resolve(strict=True)
    occurrences: Counter[str] = Counter()
    keyed: list[FindingPayload] = []
    contexts_by_window: dict[str, SourceContextPayload] = {}
    request_bytes = 0
    available_windows = 0

    for raw in findings:
        finding = cast(FindingPayload, dict(raw))
        signature = _finding_signature(finding, schema_version)
        ordinal = occurrences[signature]
        occurrences[signature] += 1
        finding_key = str(uuid.uuid5(_FINDING_NAMESPACE, f"{signature}|{ordinal}"))
        finding["finding_key"] = finding_key
        keyed.append(finding)

        context = _extract_one(root, finding, limits)
        window_key = context["context_key"]
        existing = contexts_by_window.get(window_key)
        if existing is not None:
            existing["finding_keys"].append(finding_key)
            continue
        if context["available"] and available_windows >= limits.max_windows:
            context = _unavailable(finding_key, "context_limit")
            window_key = context["context_key"]
        context_bytes = _context_text_bytes(context)
        if context["available"] and request_bytes + context_bytes > limits.max_request_bytes:
            context = _unavailable(finding_key, "request_limit")
            window_key = context["context_key"]
            context_bytes = 0
        request_bytes += context_bytes
        contexts_by_window[window_key] = context
        available_windows += int(context["available"])

    return SourceContextExtraction(tuple(keyed), tuple(contexts_by_window.values()))


def validate_source_context_links(
    findings: Sequence[FindingPayload],
    contexts: Sequence[SourceContextPayload],
) -> None:
    """Reject duplicate finding keys, duplicate contexts, and broken references."""

    finding_keys = [str(item.get("finding_key") or "") for item in findings]
    if (
        not all(_is_uuid5(key) for key in finding_keys)
        or len(finding_keys) != len(set(finding_keys))
    ):
        raise ValueError("findings must contain unique finding_key values")
    context_keys = [item.get("context_key") for item in contexts]
    if (
        not all(isinstance(key, str) and _is_uuid5(key) for key in context_keys)
        or len(context_keys) != len(set(context_keys))
    ):
        raise ValueError("source contexts contain duplicate context_key values")
    referenced: list[str] = []
    valid = set(finding_keys)
    for context in contexts:
        keys = context.get("finding_keys") or []
        if not keys or len(keys) != len(set(keys)) or not set(keys).issubset(valid):
            raise ValueError("source context contains orphan or duplicate finding keys")
        referenced.extend(keys)
    if set(referenced) != valid or len(referenced) != len(finding_keys):
        raise ValueError("every finding must reference exactly one source context")


def sanitize_source_contexts(
    contexts: Sequence[SourceContextPayload],
    *,
    limits: SourceContextLimits = SourceContextLimits(),
) -> tuple[SourceContextPayload, ...]:
    """Validate hard limits and deterministically re-redact uploaded contexts."""

    total = 0
    available_count = 0
    clean_contexts: list[SourceContextPayload] = []
    for raw_context in contexts:
        context = cast(SourceContextPayload, dict(raw_context))
        if context.get("provider") != "snapshot":
            raise ValueError("unsupported source context provider")
        if context.get("redaction_version") != REDACTION_VERSION:
            raise ValueError("unsupported source context redaction version")
        if not context.get("available"):
            if context.get("lines") or context.get("source_hash"):
                raise ValueError("unavailable source context contains source text")
            clean_contexts.append(context)
            continue
        available_count += 1
        if available_count > limits.max_windows:
            raise ValueError("source context count exceeds limit")
        lines = context.get("lines")
        if not isinstance(lines, list) or not lines or len(lines) > limits.max_lines:
            raise ValueError("source context line count is invalid")
        window_start = context.get("window_start")
        window_end = context.get("window_end")
        if not isinstance(window_start, int) or not isinstance(window_end, int):
            raise ValueError("source context window is invalid")
        if window_end < window_start or window_end - window_start + 1 > limits.max_lines:
            raise ValueError("source context window is invalid")
        expected_numbers = list(range(window_start, window_start + len(lines)))
        if [line.get("number") for line in lines] != expected_numbers:
            raise ValueError("source context lines are not contiguous")
        if expected_numbers[-1] != window_end:
            raise ValueError("source context lines do not fill their declared window")
        highlight_start = context.get("highlight_start")
        highlight_end = context.get("highlight_end")
        if (
            not isinstance(highlight_start, int)
            or not isinstance(highlight_end, int)
            or highlight_start < window_start
            or highlight_start > window_end
            or highlight_end < highlight_start
            or (
                highlight_end > window_end
                and not bool(context.get("highlight_truncated"))
            )
        ):
            raise ValueError("source context highlight is invalid")
        source_hash = context.get("source_hash")
        if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError("source context hash is invalid")

        clean_lines: list[SourceLinePayload] = []
        changed = bool(context.get("redaction_changed"))
        window_bytes = 0
        for line in lines:
            value = line.get("text")
            if not isinstance(value, str):
                raise ValueError("source context line text is invalid")
            clean, replacements = redact_text(value)
            changed |= replacements > 0
            size = len(clean.encode("utf-8"))
            if size > limits.max_line_bytes:
                raise ValueError("source context line exceeds byte limit")
            window_bytes += size
            clean_lines.append(
                {
                    "number": line["number"],
                    "text": clean,
                    "truncated": bool(line.get("truncated")),
                }
            )
        if window_bytes > limits.max_window_bytes:
            raise ValueError("source context window exceeds byte limit")
        total += window_bytes
        if total > limits.max_request_bytes:
            raise ValueError("source contexts exceed request byte limit")
        context["lines"] = clean_lines
        context["redaction_changed"] = changed
        clean_contexts.append(context)
    return tuple(clean_contexts)


def _finding_signature(finding: FindingPayload, schema_version: int) -> str:
    path = _normalized_path(finding.get("file_path")) or ""
    message = str(finding.get("message") or "")
    message_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    values = (
        str(schema_version),
        str(finding.get("scanner") or ""),
        str(finding.get("rule_id") or ""),
        path,
        str(finding.get("line_start") or ""),
        str(finding.get("line_end") or ""),
        message_hash,
    )
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _extract_one(
    root: Path,
    finding: FindingPayload,
    limits: SourceContextLimits,
) -> SourceContextPayload:
    finding_key = str(finding["finding_key"])
    raw_path = finding.get("file_path")
    if not raw_path:
        return _unavailable(finding_key, "missing_path")
    path = _normalized_path(raw_path)
    if path is None:
        return _unavailable(finding_key, "invalid_path")
    line_start = finding.get("line_start")
    line_end = finding.get("line_end")
    if line_start is None:
        return _unavailable(finding_key, "missing_line", path=path)
    if not isinstance(line_start, int) or line_start < 1:
        return _unavailable(finding_key, "untrusted_range", path=path)
    if line_end is None:
        line_end = line_start
    if not isinstance(line_end, int) or line_end < line_start:
        return _unavailable(finding_key, "untrusted_range", path=path)

    source = root.joinpath(*PurePosixPath(path).parts)
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or source.is_symlink():
            return _unavailable(finding_key, "missing_file", path=path)
        size = resolved.stat().st_size
        if size > limits.max_source_file_bytes:
            return _unavailable(finding_key, "file_too_large", path=path)
        raw = resolved.read_bytes()
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return _unavailable(finding_key, "missing_file", path=path)
    if b"\0" in raw[:8192]:
        return _unavailable(finding_key, "binary", path=path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _unavailable(finding_key, "decode_error", path=path)
    source_lines = text.splitlines()
    if line_start > len(source_lines):
        return _unavailable(finding_key, "untrusted_range", path=path)

    highlight_end = min(line_end, len(source_lines))
    affected = highlight_end - line_start + 1
    if affected >= limits.max_lines:
        window_start = line_start
        window_end = min(len(source_lines), line_start + limits.max_lines - 1)
        highlight_truncated = line_end > window_end
    else:
        remaining = limits.max_lines - affected
        before = min(5, remaining // 2)
        after = min(5, remaining - before)
        window_start = max(1, line_start - before)
        window_end = min(len(source_lines), highlight_end + after)
        spare = limits.max_lines - (window_end - window_start + 1)
        if spare:
            window_start = max(1, window_start - spare)
            spare = limits.max_lines - (window_end - window_start + 1)
            window_end = min(len(source_lines), window_end + spare)
        highlight_truncated = line_end > window_end

    redaction_changed = False
    rendered: list[SourceLinePayload] = []
    used = 0
    for number in range(window_start, window_end + 1):
        clean, replacements = redact_text(source_lines[number - 1])
        redaction_changed |= replacements > 0
        clean, line_truncated = _truncate_utf8(clean, limits.max_line_bytes)
        remaining_bytes = limits.max_window_bytes - used
        clean, window_truncated = _truncate_utf8(clean, max(0, remaining_bytes))
        encoded = clean.encode("utf-8")
        used += len(encoded)
        rendered.append(
            {"number": number, "text": clean, "truncated": line_truncated or window_truncated}
        )
        if window_truncated or used >= limits.max_window_bytes:
            break

    actual_window_end = rendered[-1]["number"]
    highlight_truncated |= line_end > actual_window_end

    key_basis = (
        f"{path}|{window_start}|{actual_window_end}|{line_start}|{line_end}|"
        f"{hashlib.sha256(raw).hexdigest()}"
    )
    return {
        "context_key": str(uuid.uuid5(_FINDING_NAMESPACE, key_basis)),
        "finding_keys": [finding_key],
        "available": True,
        "provider": "snapshot",
        "path": path,
        "window_start": window_start,
        "window_end": actual_window_end,
        "highlight_start": line_start,
        "highlight_end": line_end,
        "highlight_truncated": highlight_truncated,
        "lines": rendered,
        "source_hash": hashlib.sha256(raw).hexdigest(),
        "redaction_version": REDACTION_VERSION,
        "redaction_changed": redaction_changed,
    }


def _normalized_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return None
    return unicodedata.normalize("NFC", pure.as_posix())


def _unavailable(
    finding_key: str,
    reason: SourceContextUnavailableReason,
    *,
    path: str | None = None,
) -> SourceContextPayload:
    context: SourceContextPayload = {
        "context_key": str(uuid.uuid5(_FINDING_NAMESPACE, f"unavailable|{finding_key}|{reason}")),
        "finding_keys": [finding_key],
        "available": False,
        "provider": "snapshot",
        "redaction_version": REDACTION_VERSION,
        "redaction_changed": False,
        "unavailable_reason": reason,
    }
    if path is not None:
        context["path"] = path
    return context


def _context_text_bytes(context: SourceContextPayload) -> int:
    return sum(len(line["text"].encode("utf-8")) for line in context.get("lines", []))


def _truncate_utf8(value: str, maximum: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum:
        return value, False
    marker = _TRUNCATION_MARKER.encode("utf-8")
    if maximum <= len(marker):
        return marker[:maximum].decode("utf-8", errors="ignore"), True
    prefix = encoded[: maximum - len(marker)].decode("utf-8", errors="ignore")
    return prefix + _TRUNCATION_MARKER, True


def _is_uuid5(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 5 and str(parsed) == value


__all__ = [
    "extract_source_contexts",
    "sanitize_source_contexts",
    "validate_source_context_links",
]
