"""Strict parsing, authentication and workload policy for GitHub OIDC JWTs."""

from __future__ import annotations

import base64
import datetime as dt
import json
import hashlib
import re
from collections.abc import Mapping
from typing import Any, NoReturn
from urllib.parse import urlsplit

from app.modules.shared.contracts.ingest_v2 import OIDC_POLICY_V2, OIDC_REQUIRED_CLAIMS

from .models import GithubOidcClaims, GithubRepositoryTrust, OidcValidationError
from .ports import GithubOidcReplayRepository, RsaSignatureVerifier


_ASCII_KID = re.compile(r"[\x21-\x7e]{1,128}\Z")
_POSITIVE_DIGITS = re.compile(r"[1-9][0-9]*\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
_REF = re.compile(r"refs/heads/[^\x00-\x20~^:?*\\\[][^\x00~^:?*\\\[]*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_DATABASE_INTEGER = 2**63 - 1


def github_oidc_audience(public_base_url: str) -> str:
    """Construct the single accepted audience from a canonical HTTPS origin."""
    try:
        parsed = urlsplit(public_base_url)
        port = parsed.port
    except ValueError:
        _invalid()
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        _invalid()
    origin = f"https://{parsed.hostname}"
    if port is not None:
        origin += f":{port}"
    return origin + OIDC_POLICY_V2.audience_path


def authenticate_github_oidc(
    token: str,
    *,
    audience: str,
    jwks: Mapping[str, Any],
    now: dt.datetime,
    signature_verifier: RsaSignatureVerifier,
) -> GithubOidcClaims:
    """Authenticate one compact JWT and return only validated signed claims."""
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError:
        _invalid()
    if not token_bytes or len(token_bytes) > OIDC_POLICY_V2.maximum_jwt_bytes:
        _invalid()
    segments = token.split(".")
    if len(segments) != 3 or any(not segment for segment in segments):
        _invalid()
    header = _json_object(_decode_segment(segments[0]))
    claims = _json_object(_decode_segment(segments[1]))
    signature = _decode_segment(segments[2])

    if set(header) != {"alg", "kid", "typ"}:
        _invalid()
    kid = header.get("kid")
    if (
        header.get("alg") != OIDC_POLICY_V2.algorithm
        or header.get("typ") != OIDC_POLICY_V2.token_type
        or not isinstance(kid, str)
        or not _ASCII_KID.fullmatch(kid)
        or len(kid.encode("ascii")) > OIDC_POLICY_V2.maximum_kid_bytes
    ):
        _invalid()
    jwk = _select_jwk(jwks, kid)
    if not signature_verifier.verify(
        signing_input=f"{segments[0]}.{segments[1]}".encode("ascii"),
        signature=signature,
        jwk=jwk,
    ):
        _invalid()

    if not set(OIDC_REQUIRED_CLAIMS).issubset(claims):
        _invalid()
    if claims.get("iss") != OIDC_POLICY_V2.issuer or claims.get("aud") != audience:
        _invalid()

    current = _aware(now)
    iat = _time_claim(claims, "iat")
    nbf = _time_claim(claims, "nbf")
    exp = _time_claim(claims, "exp")
    skew = dt.timedelta(seconds=OIDC_POLICY_V2.clock_skew_seconds)
    if (
        exp <= iat
        or nbf > iat
        or exp - iat > dt.timedelta(seconds=OIDC_POLICY_V2.maximum_lifetime_seconds)
        or iat > current + skew
        or nbf > current + skew
        or exp < current - skew
    ):
        _invalid()

    return GithubOidcClaims(
        subject=_string(claims, "sub", 512),
        repository_id=_positive_integer(claims, "repository_id"),
        repository_owner_id=_positive_integer(claims, "repository_owner_id"),
        repository=_matched_string(claims, "repository", _REPOSITORY),
        run_id=_positive_integer(claims, "run_id"),
        run_number=_positive_integer(claims, "run_number"),
        run_attempt=_positive_integer(claims, "run_attempt"),
        sha=_matched_string(claims, "sha", _SHA),
        ref=_matched_string(claims, "ref", _REF),
        event_name=_string(claims, "event_name", 64),
        actor=_string(claims, "actor", 128),
        actor_id=_positive_integer(claims, "actor_id"),
        workflow_ref=_string(claims, "workflow_ref", 1024),
        workflow_sha=_matched_string(claims, "workflow_sha", _SHA),
        issued_at=iat,
        not_before=nbf,
        expires_at=exp,
        jti=_string(claims, "jti", 255),
    )


def authorize_default_branch_push(
    claims: GithubOidcClaims,
    trust: GithubRepositoryTrust,
) -> None:
    """Authorize only the installed repository's canonical default-branch workflow."""
    if claims.event_name != "push":
        raise OidcValidationError("unsupported_event")
    expected_ref = f"refs/heads/{trust.default_branch}"
    if claims.ref != expected_ref:
        raise OidcValidationError("non_default_branch")
    if (
        claims.repository_id != trust.repository_id
        or claims.repository_owner_id != trust.owner_id
        or claims.repository != trust.full_name
    ):
        raise OidcValidationError("repository_not_authorized")
    expected_workflow = (
        f"{trust.full_name}/.github/workflows/assurance-scan.yml@{expected_ref}"
    )
    expected_subject = f"repo:{_encode_subject_value(trust.full_name)}:ref:{_encode_subject_value(expected_ref)}"
    if (
        claims.workflow_ref != expected_workflow
        or claims.workflow_sha != claims.sha
        or claims.subject != expected_subject
    ):
        _invalid()


def validate_github_payload_metadata(
    claims: GithubOidcClaims,
    metadata: Mapping[str, Any],
) -> None:
    """Bind every duplicated bundle identity field to its signed OIDC claim."""
    repository = metadata.get("repository")
    producer = metadata.get("producer")
    if not isinstance(repository, Mapping) or not isinstance(producer, Mapping):
        raise OidcValidationError("artifact_mismatch")
    expected_producer = {
        "kind": "github-actions",
        "repository_id": claims.repository_id,
        "repository_owner_id": claims.repository_owner_id,
        "run_id": claims.run_id,
        "run_number": claims.run_number,
        "run_attempt": claims.run_attempt,
        "event_name": claims.event_name,
        "workflow_ref": claims.workflow_ref,
        "workflow_sha": claims.workflow_sha,
        "actor": claims.actor,
        "actor_id": claims.actor_id,
    }
    if (
        repository.get("provider") != "github"
        or repository.get("full_name") != claims.repository
        or metadata.get("commit") != claims.sha
        or metadata.get("ref") != claims.ref
        or metadata.get("branch") != claims.ref.removeprefix("refs/heads/")
        or metadata.get("working_tree_dirty") is not False
        or dict(producer) != expected_producer
    ):
        raise OidcValidationError("artifact_mismatch")


async def consume_github_oidc_jti(
    claims: GithubOidcClaims,
    *,
    repository: GithubOidcReplayRepository,
    now: dt.datetime,
) -> None:
    """Atomically consume replay evidence until after the JWT can no longer validate."""
    current = _aware(now)
    expires_at = claims.expires_at + dt.timedelta(
        seconds=OIDC_POLICY_V2.consumed_jti_extra_retention_seconds
    )
    consumed = await repository.consume(
        jti_digest=hashlib.sha256(claims.jti.encode("utf-8")).digest(),
        repository_id=claims.repository_id,
        consumed_at=current,
        expires_at=expires_at,
    )
    if not consumed:
        raise OidcValidationError("oidc_replayed")


def _select_jwk(jwks: Mapping[str, Any], kid: str) -> Mapping[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or len(keys) > 32:
        _invalid()
    matches = [key for key in keys if isinstance(key, Mapping) and key.get("kid") == kid]
    if len(matches) != 1:
        _invalid()
    key = matches[0]
    if (
        key.get("kty") != "RSA"
        or key.get("use") != "sig"
        or key.get("alg") != OIDC_POLICY_V2.algorithm
        or not isinstance(key.get("n"), str)
        or not isinstance(key.get("e"), str)
    ):
        _invalid()
    return key


def _decode_segment(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        _invalid()
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        _invalid()


def _json_object(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _invalid()
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _invalid()
    if not isinstance(value, dict):
        _invalid()
    return value


def _time_claim(claims: Mapping[str, Any], name: str) -> dt.datetime:
    value = claims.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _invalid()
    try:
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        _invalid()


def _positive_integer(claims: Mapping[str, Any], name: str) -> int:
    value = claims.get(name)
    if not isinstance(value, str) or not _POSITIVE_DIGITS.fullmatch(value):
        _invalid()
    parsed = int(value)
    if parsed > _MAX_DATABASE_INTEGER:
        _invalid()
    return parsed


def _string(claims: Mapping[str, Any], name: str, maximum: int) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        _invalid()
    return value


def _matched_string(claims: Mapping[str, Any], name: str, pattern: re.Pattern[str]) -> str:
    value = _string(claims, name, 1024)
    if not pattern.fullmatch(value):
        _invalid()
    return value


def _encode_subject_value(value: str) -> str:
    return value.replace(":", "%3A")


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        _invalid()
    return value.astimezone(dt.timezone.utc)


def _invalid() -> NoReturn:
    raise OidcValidationError()


__all__ = [
    "authenticate_github_oidc",
    "authorize_default_branch_push",
    "consume_github_oidc_jti",
    "github_oidc_audience",
    "validate_github_payload_metadata",
]
