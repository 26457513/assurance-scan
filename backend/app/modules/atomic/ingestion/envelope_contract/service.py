"""RFC 8785 canonicalization and domain-separated v2 envelope hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.shared.contracts.ingest_v2 import (
    ENVELOPE_DOMAIN,
    ENVELOPE_PARTS,
    OPTIONAL_PARTS,
    REQUIRED_PARTS,
)

from .models import CanonicalJSONError, EnvelopeHashError


_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def parse_strict_json(payload: bytes, *, maximum_depth: int = 20) -> Any:
    """Parse UTF-8 JSON while rejecting duplicates and the non-integer profile."""

    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalJSONError("payload is not strict UTF-8 JSON") from exc
    _validate_value(value, depth=1, maximum_depth=maximum_depth)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Encode the frozen integer-only subset of RFC 8785/JCS."""

    _validate_value(value, depth=1, maximum_depth=20)
    return _encode(value).encode("utf-8")


def envelope_payload_hash(parts: Mapping[str, Any | None]) -> str:
    """Hash all five canonical parts, including explicit optional absence."""

    names = set(parts)
    if not REQUIRED_PARTS.issubset(names) or not names.issubset(set(ENVELOPE_PARTS)):
        raise EnvelopeHashError("envelope part set is invalid")
    digest = hashlib.sha256()
    digest.update(ENVELOPE_DOMAIN)
    digest.update(b"\0")
    for name in ENVELOPE_PARTS:
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        value = parts.get(name)
        if value is None:
            if name not in OPTIONAL_PARTS:
                raise EnvelopeHashError(f"required part {name} is absent")
            digest.update(b"absent\0")
            continue
        payload = canonical_json_bytes(value)
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalJSONError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(_value: str) -> None:
    raise CanonicalJSONError("non-integer JSON numbers are forbidden")


def _validate_value(value: Any, *, depth: int, maximum_depth: int) -> None:
    if depth > maximum_depth:
        raise CanonicalJSONError("JSON nesting exceeds the protocol limit")
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            try:
                value.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise CanonicalJSONError("JSON strings must contain Unicode scalar values") from exc
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise CanonicalJSONError("integer exceeds the JCS interoperable range")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError("JSON object keys must be strings")
            _validate_value(key, depth=depth, maximum_depth=maximum_depth)
            _validate_value(child, depth=depth + 1, maximum_depth=maximum_depth)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for child in value:
            _validate_value(child, depth=depth + 1, maximum_depth=maximum_depth)
        return
    raise CanonicalJSONError("value is outside the frozen JSON profile")


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list) or isinstance(value, tuple):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, Mapping):
        keys = sorted(value, key=lambda item: item.encode("utf-16-be"))
        return "{" + ",".join(f"{_encode(key)}:{_encode(value[key])}" for key in keys) + "}"
    raise CanonicalJSONError("value is outside the frozen JSON profile")


__all__ = [
    "canonical_json_bytes",
    "envelope_payload_hash",
    "parse_strict_json",
]
