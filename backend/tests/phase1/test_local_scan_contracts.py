"""Executable WS0 contracts for the version-one local-scan boundary."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from app.modules.shared.contracts.local_scan import (
    API_PREFIX,
    RETENTION_DAYS,
    SCHEMA_VERSION,
    TOKEN_ACTIVE_LIMIT,
    TOKEN_DEFAULT_EXPIRY_DAYS,
    TOKEN_MAX_EXPIRY_DAYS,
    TOKEN_PREFIX,
    TOKEN_SECRET_BYTES,
    TOKEN_SELECTOR_BYTES,
    UPLOAD_LIMITS,
    USAGE_LIMITS,
)


BACKEND_ROOT = Path(__file__).parents[2]
SCHEMA_ROOT = BACKEND_ROOT / "resources" / "schemas"
FIXTURE_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "local-scan"
SCANNER_MANIFEST = BACKEND_ROOT / "resources" / "scanners" / "release-set.v1.json"
SEMGREP_POLICY = BACKEND_ROOT / "resources" / "scanners" / "semgrep-reviewed.yml"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    schema = _json(SCHEMA_ROOT / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def test_locked_product_and_security_defaults() -> None:
    assert SCHEMA_VERSION == 1
    assert API_PREFIX == "/api/v1/ingest"
    assert TOKEN_PREFIX == "asu_v1_"
    assert (TOKEN_SELECTOR_BYTES, TOKEN_SECRET_BYTES) == (12, 32)
    assert (TOKEN_DEFAULT_EXPIRY_DAYS, TOKEN_MAX_EXPIRY_DAYS) == (90, 365)
    assert TOKEN_ACTIVE_LIMIT == 5
    assert UPLOAD_LIMITS.wire_bytes == 32 * 1024 * 1024
    assert UPLOAD_LIMITS.findings_count == 20_000
    assert USAGE_LIMITS.inflight_per_instance == 4
    assert RETENTION_DAYS.raw_artifacts == 30
    assert RETENTION_DAYS.normalized_history == 365


def test_valid_metadata_and_findings_match_checked_in_schemas() -> None:
    metadata = _json(FIXTURE_ROOT / "valid" / "metadata.json")
    findings = _json(FIXTURE_ROOT / "valid" / "findings.json")

    _validator("local-scan-metadata.v1.schema.json").validate(metadata)
    _validator("local-scan-findings.v1.schema.json").validate(findings)


def test_duplicate_keys_are_rejected_before_schema_validation() -> None:
    raw = (FIXTURE_ROOT / "invalid" / "metadata-duplicate-key.json").read_text(
        encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        json.loads(raw, object_pairs_hook=_reject_duplicate_keys)


def test_unsupported_schema_and_absolute_path_fixtures_are_rejected() -> None:
    metadata = _json(FIXTURE_ROOT / "invalid" / "metadata-unsupported-version.json")
    findings = _json(FIXTURE_ROOT / "invalid" / "findings-path-leak.json")

    assert list(_validator("local-scan-metadata.v1.schema.json").iter_errors(metadata))
    assert list(_validator("local-scan-findings.v1.schema.json").iter_errors(findings))


def test_oversized_message_is_rejected_at_the_contract_boundary() -> None:
    findings = _json(FIXTURE_ROOT / "valid" / "findings.json")
    findings["findings"][0]["message"] = "x" * (UPLOAD_LIMITS.message_chars + 1)

    assert list(_validator("local-scan-findings.v1.schema.json").iter_errors(findings))


def test_canary_fixture_is_reserved_for_redaction_tests() -> None:
    findings = _json(FIXTURE_ROOT / "invalid" / "findings-canary-secret.json")
    _validator("local-scan-findings.v1.schema.json").validate(findings)
    assert "AS_CANARY_SECRET_DO_NOT_PERSIST" in findings["findings"][0]["message"]


def test_scanner_release_set_is_immutable_and_dual_architecture() -> None:
    manifest_bytes = SCANNER_MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    metadata = _json(FIXTURE_ROOT / "valid" / "metadata.json")

    assert manifest["schema_version"] == 1
    assert manifest["required_platforms"] == ["linux/amd64", "linux/arm64"]
    assert len(manifest["scanners"]) == 8
    assert all(
        re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", scanner["image"])
        for scanner in manifest["scanners"]
    )
    assert all(
        set(scanner["platform_digests"]) == {"linux/amd64", "linux/arm64"}
        and all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            for digest in scanner["platform_digests"].values()
        )
        for scanner in manifest["scanners"]
    )
    assert hashlib.sha256(manifest_bytes).hexdigest() == metadata["scanner_manifest_digest"]
    assert hashlib.sha256(SEMGREP_POLICY.read_bytes()).hexdigest() == manifest[
        "semgrep_policy"
    ]["sha256"]
