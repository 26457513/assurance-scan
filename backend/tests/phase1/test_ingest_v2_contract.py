"""Golden corpus for the frozen, disabled v2 ingestion contract."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.modules.atomic.ingestion.envelope_contract import (
    CanonicalJSONError,
    canonical_json_bytes,
    envelope_payload_hash,
    parse_strict_json,
)
from app.modules.atomic.ingestion.source_context import SourceContextLimits
from app.modules.shared.contracts.ingest_v2 import (
    ENVELOPE_DOMAIN,
    ENVELOPE_LIMITS_V2,
    ENVELOPE_PARTS,
    GITHUB_USAGE_LIMITS_V2,
    INGEST_ATTEMPT_OUTCOMES,
    INGEST_REASON_CODES,
    LOCAL_USAGE_LIMITS_V2,
    OIDC_POLICY_V2,
    OIDC_REQUIRED_CLAIMS,
    OPTIONAL_PARTS,
    PART_MEDIA_TYPES,
    PROBLEM_CODES,
    PROBLEM_POLICIES_V2,
    REQUIRED_PARTS,
    SCHEMA_VERSION,
    SCANNER_ERROR_CODES,
    SCANNER_KINDS,
    SCANNER_STATUSES,
    SHARED_USAGE_LIMITS_V2,
    SOURCE_CONTEXT_LIMITS_V2,
    WEBHOOK_EVENT_ACTIONS,
    WEBHOOK_POLICY_V2,
)
from app.modules.workflows.result_ingest_v2_contract import (
    EnvelopeValidationError,
    validate_envelope_relationships,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = BACKEND_ROOT / "resources" / "schemas"
FIXTURES = BACKEND_ROOT / "resources" / "fixtures" / "ingest-v2"
SCHEMA_BY_FIXTURE = {
    "local-metadata.json": "scan-metadata.v2.schema.json",
    "github-metadata.json": "scan-metadata.v2.schema.json",
    "findings.json": "scan-findings.v2.schema.json",
    "source-contexts.json": "source-contexts.v2.schema.json",
    "problem.json": "ingest-problem.v2.schema.json",
}


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _validator(name: str) -> Draft202012Validator:
    schema = _json(SCHEMAS / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize(("fixture", "schema"), SCHEMA_BY_FIXTURE.items())
def test_positive_corpus_satisfies_frozen_schemas(fixture: str, schema: str) -> None:
    _validator(schema).validate(_json(FIXTURES / fixture))


def test_every_negative_schema_fixture_is_rejected() -> None:
    corpus = _json(FIXTURES / "negative-cases.json")
    for case in corpus["cases"]:
        document = copy.deepcopy(_json(FIXTURES / case["fixture"]))
        _replace_pointer(document, case["pointer"], case["replacement"])
        errors = list(_validator(SCHEMA_BY_FIXTURE[case["fixture"]]).iter_errors(document))
        assert errors, case


def test_protocol_fixture_matches_code_constants_exactly() -> None:
    protocol = _json(FIXTURES / "protocol.json")

    assert protocol["schema_version"] == SCHEMA_VERSION
    assert protocol["parts"] == list(ENVELOPE_PARTS)
    assert set(protocol["required_parts"]) == REQUIRED_PARTS
    assert set(protocol["optional_parts"]) == OPTIONAL_PARTS
    assert protocol["domain_separator"].encode("ascii") == ENVELOPE_DOMAIN
    assert protocol["part_media_types"] == {
        name: list(media_types) for name, media_types in PART_MEDIA_TYPES.items()
    }
    assert protocol["limits"] == asdict(ENVELOPE_LIMITS_V2)
    assert protocol["shared_quotas"] == asdict(SHARED_USAGE_LIMITS_V2)
    assert protocol["local_quotas"] == asdict(LOCAL_USAGE_LIMITS_V2)
    assert protocol["github_quotas"] == asdict(GITHUB_USAGE_LIMITS_V2)
    assert protocol["source_context_limits"] == asdict(SOURCE_CONTEXT_LIMITS_V2)
    runtime_context_limits = SourceContextLimits()
    assert asdict(SOURCE_CONTEXT_LIMITS_V2) == {
        "unique_windows": runtime_context_limits.max_windows,
        "lines_per_window": runtime_context_limits.max_lines,
        "bytes_per_line": runtime_context_limits.max_line_bytes,
        "bytes_per_window": runtime_context_limits.max_window_bytes,
        "decoded_bytes_per_request": runtime_context_limits.max_request_bytes,
    }
    assert protocol["oidc_policy"] == asdict(OIDC_POLICY_V2)
    assert protocol["oidc_required_claims"] == list(OIDC_REQUIRED_CLAIMS)
    assert protocol["webhook_policy"] == asdict(WEBHOOK_POLICY_V2)
    assert protocol["webhook_event_actions"] == [list(item) for item in WEBHOOK_EVENT_ACTIONS]
    assert protocol["ingest_attempt_outcomes"] == list(INGEST_ATTEMPT_OUTCOMES)
    assert protocol["reason_codes"] == list(INGEST_REASON_CODES)
    assert protocol["problem_policies"] == [asdict(item) for item in PROBLEM_POLICIES_V2]
    assert {item.code for item in PROBLEM_POLICIES_V2} == set(PROBLEM_CODES)


def test_schema_vocabularies_and_ceilings_match_code_constants() -> None:
    findings_schema = _json(SCHEMAS / "scan-findings.v2.schema.json")
    metadata_schema = _json(SCHEMAS / "scan-metadata.v2.schema.json")
    context_schema = _json(SCHEMAS / "source-contexts.v2.schema.json")
    problem_schema = _json(SCHEMAS / "ingest-problem.v2.schema.json")

    assert findings_schema["$defs"]["kind"]["enum"] == list(SCANNER_KINDS)
    scanner_properties = findings_schema["$defs"]["scanner"]["properties"]
    assert scanner_properties["status"]["enum"] == list(SCANNER_STATUSES)
    assert scanner_properties["error_code"]["oneOf"][1]["enum"] == list(
        SCANNER_ERROR_CODES
    )
    release_names = metadata_schema["$defs"]["scannerRelease"]["properties"]["images"][
        "propertyNames"
    ]["enum"]
    assert release_names == list(SCANNER_KINDS)
    assert context_schema["properties"]["contexts"]["maxItems"] == (
        ENVELOPE_LIMITS_V2.findings_count
    )
    assert problem_schema["properties"]["code"]["enum"] == list(PROBLEM_CODES)


def test_jcs_and_envelope_hash_vectors_are_stable() -> None:
    vectors = _json(FIXTURES / "hash-vectors.json")
    for vector in vectors["canonical_json"]:
        assert canonical_json_bytes(vector["value"]).decode() == vector["canonical"]
    assert envelope_payload_hash(vectors["envelope"]["parts"]) == vectors["envelope"]["payload_hash"]


def test_positive_parts_satisfy_cross_part_contract() -> None:
    parts = {
        "metadata": _json(FIXTURES / "local-metadata.json"),
        "findings": _json(FIXTURES / "findings.json"),
        "source_contexts": _json(FIXTURES / "source-contexts.json"),
        "sarif": {"version": "2.1.0", "runs": []},
        "sbom": None,
    }
    validate_envelope_relationships(parts)


@pytest.mark.parametrize(
    "mutation", ("artifact", "branch", "scanner", "scanner_image", "range", "context")
)
def test_cross_part_contract_rejects_inconsistent_documents(mutation: str) -> None:
    parts = {
        "metadata": _json(FIXTURES / "local-metadata.json"),
        "findings": _json(FIXTURES / "findings.json"),
        "source_contexts": _json(FIXTURES / "source-contexts.json"),
        "sarif": {"version": "2.1.0", "runs": []},
        "sbom": None,
    }
    if mutation == "artifact":
        parts["metadata"]["artifacts"]["sarif"] = False
    elif mutation == "branch":
        parts["metadata"]["ref"] = "refs/heads/other"
    elif mutation == "scanner":
        parts["findings"]["scanners"].append(parts["findings"]["scanners"][0])
    elif mutation == "scanner_image":
        parts["findings"]["scanners"][0]["image"] = (
            "docker.io/semgrep/semgrep@sha256:" + "9" * 64
        )
    elif mutation == "range":
        parts["findings"]["findings"][0]["line_end"] = 5
    else:
        parts["source_contexts"]["contexts"][0]["path"] = "src/other.py"
    with pytest.raises(EnvelopeValidationError):
        validate_envelope_relationships(parts)


@pytest.mark.parametrize(
    "payload",
    (
        b'{"key":1,"key":2}',
        b'{"fraction":1.5}',
        b'{"constant":NaN}',
        b'\xff',
    ),
)
def test_strict_json_parser_rejects_ambiguous_inputs(payload: bytes) -> None:
    with pytest.raises(CanonicalJSONError):
        parse_strict_json(payload)


def test_jcs_profile_rejects_unsafe_integer_and_excessive_depth() -> None:
    with pytest.raises(CanonicalJSONError, match="interoperable"):
        canonical_json_bytes(9_007_199_254_740_992)
    with pytest.raises(CanonicalJSONError, match="nesting"):
        parse_strict_json(b'[[[[]]]]', maximum_depth=3)


def test_oidc_jwks_and_webhook_fixture_manifests_are_content_safe() -> None:
    header = _json(FIXTURES / "oidc" / "jose-header.json")
    claims = _json(FIXTURES / "oidc" / "claims.json")
    jwks = _json(FIXTURES / "oidc" / "jwks.json")
    oidc_cases = _json(FIXTURES / "oidc" / "negative-cases.json")["cases"]
    webhook_cases = _json(FIXTURES / "webhooks" / "cases.json")["cases"]

    assert header == {"alg": "RS256", "kid": "assurance-scan-test-key-1", "typ": "JWT"}
    assert claims["iss"] == "https://token.actions.githubusercontent.com"
    assert set(claims) == set(OIDC_REQUIRED_CLAIMS)
    assert isinstance(claims["aud"], str)
    assert jwks["keys"][0]["kid"] == header["kid"]
    assert set(jwks["keys"][0]) == {"kty", "use", "alg", "kid", "n", "e"}
    modulus = jwks["keys"][0]["n"]
    assert len(base64.urlsafe_b64decode(modulus + "=" * (-len(modulus) % 4))) == 256
    assert {case["code"] for case in oidc_cases} <= set(INGEST_REASON_CODES)
    assert {case["signature"] for case in webhook_cases} >= {"valid-current", "sha1", "invalid"}
    for case in webhook_cases:
        assert (FIXTURES / "webhooks" / case["fixture"]).is_file()
    assert all(case["operation"] in {"add", "remove", "replace"} for case in oidc_cases)
    assert {tuple(item) for item in _json(FIXTURES / "protocol.json")["webhook_event_actions"]} == {
        tuple(item) for item in WEBHOOK_EVENT_ACTIONS
    }


def test_webhook_signatures_are_over_exact_raw_fixture_bytes() -> None:
    corpus = _json(FIXTURES / "webhooks" / "signature-vectors.json")
    secrets = corpus["secrets"]
    for vector in corpus["vectors"]:
        body = (FIXTURES / "webhooks" / vector["fixture"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == vector["body_sha256"]
        for secret_name in ("current", "previous"):
            signature = "sha256=" + hmac.new(
                secrets[secret_name].encode(), body, hashlib.sha256
            ).hexdigest()
            assert hmac.compare_digest(signature, vector[f"{secret_name}_signature"])


def test_problem_response_corpus_is_exhaustively_policy_bound() -> None:
    validator = _validator("ingest-problem.v2.schema.json")
    policies = {item.code: item for item in PROBLEM_POLICIES_V2}
    cases = _json(FIXTURES / "problem-cases.json")["cases"]
    for case in cases:
        body = case["body"]
        headers = case["headers"]
        validator.validate(body)
        policy = policies[body["code"]]
        assert body["status"] == policy.status
        assert body["retryable"] is policy.retryable
        assert ("Retry-After" in headers) is policy.retry_after
        assert headers["Content-Type"] == "application/problem+json"


def _replace_pointer(document: Any, pointer: str, value: Any) -> None:
    parts = pointer.lstrip("/").split("/")
    parent = document
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    final = parts[-1]
    if isinstance(parent, list):
        parent[int(final)] = value
    else:
        parent[final] = value
