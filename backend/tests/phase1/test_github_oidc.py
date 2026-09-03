"""Strict GitHub Actions OIDC authentication and workload-policy tests."""

from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.infrastructure.github_oidc import CryptographyRsaSignatureVerifier
from app.modules.atomic.access.github_oidc import (
    GithubOidcClaims,
    GithubRepositoryTrust,
    OidcValidationError,
    authenticate_github_oidc,
    authorize_default_branch_push,
    github_oidc_audience,
    github_oidc_key_id,
    validate_github_payload_metadata,
)


FIXTURES = Path(__file__).resolve().parents[2] / "resources" / "fixtures" / "ingest-v2" / "oidc"
NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def signing_material() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": "test-key",
        "n": _b64(numbers.n.to_bytes(256, "big")),
        "e": _b64(numbers.e.to_bytes(3, "big")),
    }
    return key, {"keys": [jwk]}


def test_authenticates_signed_claims_and_authorizes_default_branch(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    key, jwks = signing_material
    claims = _claims()
    token = _token(key, claims)

    identity = authenticate_github_oidc(
        token,
        audience="https://scan.squease.ai/api/v2/ingest/github-actions",
        jwks=jwks,
        now=NOW,
        signature_verifier=CryptographyRsaSignatureVerifier(),
    )
    authorize_default_branch_push(
        identity,
        GithubRepositoryTrust(
            repository_id=424242,
            owner_id=26457513,
            full_name="26457513/assurance-scan",
            default_branch="main",
        ),
    )
    assert identity.run_id == 123456789
    assert identity.run_attempt == 1
    assert github_oidc_key_id(token) == "test-key"


def test_accepts_github_certificate_thumbprint_header(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    key, jwks = signing_material
    token = _token(
        key,
        _claims(),
        header={
            "alg": "RS256",
            "kid": "test-key",
            "typ": "JWT",
            "x5t": "W7u7j4YfKsD1XfO-pZIpxHAT4Yw",
        },
    )

    identity = authenticate_github_oidc(
        token,
        audience="https://scan.squease.ai/api/v2/ingest/github-actions",
        jwks=jwks,
        now=NOW,
        signature_verifier=CryptographyRsaSignatureVerifier(),
    )

    assert identity.repository_id == 424242
    assert github_oidc_key_id(token) == "test-key"


def test_authorizes_github_immutable_repository_subject() -> None:
    claims = _identity_from_fixture(_claims())
    claims = replace(
        claims,
        subject="repo:26457513@26457513/assurance-scan@424242:ref:refs/heads/main",
    )

    authorize_default_branch_push(claims, _trust())


@pytest.mark.parametrize(
    ("target", "field", "value", "code"),
    (
        ("header", "alg", "HS256", "oidc_invalid"),
        ("header", "jku", "https://attacker.example/jwks", "oidc_invalid"),
        ("header", "x5t", "not a base64url thumbprint", "oidc_invalid"),
        ("claims", "iss", "https://attacker.example", "oidc_invalid"),
        ("claims", "aud", ["https://scan.squease.ai/api/v2/ingest/github-actions"], "oidc_invalid"),
        ("claims", "repository_id", None, "oidc_invalid"),
        ("claims", "event_name", "pull_request", "unsupported_event"),
        ("claims", "ref", "refs/heads/feature", "non_default_branch"),
    ),
)
def test_fails_closed_for_frozen_negative_policy_cases(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
    target: str,
    field: str,
    value: object,
    code: str,
) -> None:
    key, jwks = signing_material
    header = {"alg": "RS256", "kid": "test-key", "typ": "JWT"}
    claims = _claims()
    document = header if target == "header" else claims
    if value is None:
        document.pop(field)
    else:
        document[field] = value
    token = _token(key, claims, header=header)

    with pytest.raises(OidcValidationError) as raised:
        identity = authenticate_github_oidc(
            token,
            audience="https://scan.squease.ai/api/v2/ingest/github-actions",
            jwks=jwks,
            now=NOW,
            signature_verifier=CryptographyRsaSignatureVerifier(),
        )
        authorize_default_branch_push(identity, _trust())
    assert raised.value.code == code


def test_rejects_tampering_duplicate_json_and_oversized_tokens(
    signing_material: tuple[rsa.RSAPrivateKey, dict[str, Any]],
) -> None:
    key, jwks = signing_material
    valid = _token(key, _claims())
    encoded_header, encoded_claims, encoded_signature = valid.split(".")
    signature = bytearray(base64.urlsafe_b64decode(encoded_signature + "=="))
    signature[0] ^= 1
    tampered = f"{encoded_header}.{encoded_claims}.{_b64(bytes(signature))}"
    duplicate_header = _raw_token(
        key,
        b'{"alg":"RS256","alg":"RS256","kid":"test-key","typ":"JWT"}',
        _json(_claims()),
    )
    for token in (tampered, duplicate_header, "x" * 16_385):
        with pytest.raises(OidcValidationError, match="oidc_invalid"):
            authenticate_github_oidc(
                token,
                audience="https://scan.squease.ai/api/v2/ingest/github-actions",
                jwks=jwks,
                now=NOW,
                signature_verifier=CryptographyRsaSignatureVerifier(),
            )


@pytest.mark.parametrize(
    "url",
    (
        "http://scan.squease.ai",
        "https://scan.squease.ai/path",
        "https://user@scan.squease.ai",
        "https://scan.squease.ai?alternate=true",
    ),
)
def test_audience_requires_one_canonical_https_origin(url: str) -> None:
    with pytest.raises(OidcValidationError):
        github_oidc_audience(url)


def test_audience_is_exact_endpoint() -> None:
    assert github_oidc_audience("https://scan.squease.ai/") == (
        "https://scan.squease.ai/api/v2/ingest/github-actions"
    )


def test_payload_metadata_is_bound_to_every_signed_identity_field() -> None:
    claims = _claims()
    identity = _identity_from_fixture(claims)
    metadata = json.loads(
        (FIXTURES.parent / "github-metadata.json").read_text()
    )
    validate_github_payload_metadata(identity, metadata)

    metadata["producer"]["run_attempt"] = 2
    with pytest.raises(OidcValidationError, match="artifact_mismatch"):
        validate_github_payload_metadata(identity, metadata)


def _claims() -> dict[str, Any]:
    fixture = json.loads((FIXTURES / "claims.json").read_text())
    fixture["iat"] = int(NOW.timestamp()) - 60
    fixture["nbf"] = int(NOW.timestamp()) - 60
    fixture["exp"] = int(NOW.timestamp()) + 540
    return fixture


def _trust() -> GithubRepositoryTrust:
    return GithubRepositoryTrust(424242, 26457513, "26457513/assurance-scan", "main")


def _identity_from_fixture(claims: dict[str, Any]) -> GithubOidcClaims:
    return GithubOidcClaims(
        subject=claims["sub"],
        repository_id=int(claims["repository_id"]),
        repository_owner_id=int(claims["repository_owner_id"]),
        repository=claims["repository"],
        run_id=int(claims["run_id"]),
        run_number=int(claims["run_number"]),
        run_attempt=int(claims["run_attempt"]),
        sha=claims["sha"],
        ref=claims["ref"],
        event_name=claims["event_name"],
        actor=claims["actor"],
        actor_id=int(claims["actor_id"]),
        workflow_ref=claims["workflow_ref"],
        workflow_sha=claims["workflow_sha"],
        issued_at=NOW - dt.timedelta(minutes=1),
        not_before=NOW - dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(minutes=9),
        jti=claims["jti"],
    )


def _token(
    key: rsa.RSAPrivateKey,
    claims: dict[str, Any],
    *,
    header: dict[str, Any] | None = None,
) -> str:
    return _raw_token(
        key,
        _json(header or {"alg": "RS256", "kid": "test-key", "typ": "JWT"}),
        _json(claims),
    )


def _raw_token(key: rsa.RSAPrivateKey, header: bytes, claims: bytes) -> str:
    signing_input = _b64(header) + "." + _b64(claims)
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return signing_input + "." + _b64(signature)


def _json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
