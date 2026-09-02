"""Fixed-endpoint GitHub App API adapter for installation reconciliation."""

from __future__ import annotations

import base64
import datetime as dt
import json
import stat
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.modules.atomic.access.github_repository_reconciliation import (
    GithubAccountType,
    GithubInstallationSnapshot,
    GithubRepositorySnapshot,
    GithubRepositoryVisibility,
    GithubSelection,
    validate_installation_snapshot,
)
from app.modules.atomic.access.github_membership_projection import (
    GithubProjectPermission,
    GithubRepositoryEntitlement,
)


GITHUB_API_ROOT = "https://api.github.com"
_API_VERSION = "2022-11-28"
_MAX_PAGES = 100
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class GithubAppApiError(RuntimeError):
    """GitHub could not provide a complete, valid authorization snapshot."""


class GithubRateLimitError(GithubAppApiError):
    """GitHub explicitly instructed the caller to defer further requests."""

    def __init__(self, retry_at: dt.datetime) -> None:
        super().__init__("GitHub API rate limit reached")
        self.retry_at = _aware(retry_at)


@dataclass(frozen=True)
class GithubApiResponse:
    payload: dict[str, Any] | list[Any]
    headers: dict[str, str]


@dataclass(frozen=True)
class GithubAppInstallationState:
    github_installation_id: int
    suspended_at: dt.datetime | None


class GithubHttpPort(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> GithubApiResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibGithubHttp:
    """Network adapter restricted to the fixed GitHub API origin."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> GithubApiResponse:
        if not url.startswith(f"{GITHUB_API_ROOT}/"):
            raise GithubAppApiError("unexpected GitHub API endpoint")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with (
                urllib.request.build_opener(_NoRedirect()).open(request, timeout=15) as response
            ):  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                response_url = response.geturl()
                response_headers = {key.casefold(): value for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            response_headers = {
                key.casefold(): value for key, value in (exc.headers.items() if exc.headers else ())
            }
            retry_at = _rate_limit_retry_at(
                status=exc.code,
                headers=response_headers,
                now=dt.datetime.now(dt.timezone.utc),
            )
            if retry_at is not None:
                raise GithubRateLimitError(retry_at) from exc
            raise GithubAppApiError("GitHub API request failed") from exc
        except OSError as exc:
            raise GithubAppApiError("GitHub API request failed") from exc
        if not response_url.startswith(f"{GITHUB_API_ROOT}/"):
            raise GithubAppApiError("GitHub API redirected outside its fixed origin")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise GithubAppApiError("GitHub API response exceeded the safety limit")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GithubAppApiError("GitHub API returned invalid JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise GithubAppApiError("GitHub API returned invalid structured JSON")
        return GithubApiResponse(payload=payload, headers=response_headers)


class GithubAppUserEntitlementClient:
    """Load the repositories one user can access through this GitHub App."""

    def __init__(self, http: GithubHttpPort | None = None) -> None:
        self.http = http or UrllibGithubHttp()

    def fetch(self, user_token: str) -> tuple[GithubRepositoryEntitlement, ...]:
        if not user_token:
            raise GithubAppApiError("GitHub user authorization is unavailable")
        headers = _headers(user_token)
        installation_ids = _user_installation_ids(self.http, headers)
        entitlements: list[GithubRepositoryEntitlement] = []
        seen: set[int] = set()
        for installation_id in installation_ids:
            for repository in _user_installation_repositories(
                self.http,
                headers,
                installation_id,
            ):
                repository_id = _positive_integer(repository.get("id"), "repository id")
                if repository_id in seen:
                    raise GithubAppApiError("GitHub returned duplicate user repositories")
                seen.add(repository_id)
                permission = _repository_permission(repository.get("permissions"))
                if permission is not None:
                    entitlements.append(
                        GithubRepositoryEntitlement(
                            github_installation_id=installation_id,
                            github_repository_id=repository_id,
                            permission=permission,
                        )
                    )
        return tuple(entitlements)


def load_github_app_private_key(path_value: str) -> bytes:
    """Read a small, explicit, regular PEM file without following a symlink."""
    path = Path(path_value)
    if not path_value or path.is_symlink():
        raise GithubAppApiError("GitHub App private key file is invalid")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise GithubAppApiError("GitHub App private key file is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > 64 * 1024:
        raise GithubAppApiError("GitHub App private key file is invalid")
    try:
        return resolved.read_bytes()
    except OSError as exc:
        raise GithubAppApiError("GitHub App private key file is unavailable") from exc


def fetch_authoritative_installation_for_user(
    *,
    user_token: str,
    github_app_id: str,
    private_key_pem: bytes,
    github_installation_id: int,
    now: dt.datetime,
    http: GithubHttpPort | None = None,
) -> GithubInstallationSnapshot:
    """Prove user access, then fetch full scope with an installation token."""
    if not user_token:
        raise GithubAppApiError("GitHub user authorization is unavailable")
    installation_id = _positive_integer(github_installation_id, "installation id")
    current = _aware(now)
    transport = http or UrllibGithubHttp()
    user_headers = _headers(user_token)
    _prove_user_installation(transport, user_headers, installation_id)

    return fetch_authoritative_installation(
        github_app_id=github_app_id,
        private_key_pem=private_key_pem,
        github_installation_id=installation_id,
        now=current,
        http=transport,
    )


def fetch_authoritative_installation(
    *,
    github_app_id: str,
    private_key_pem: bytes,
    github_installation_id: int,
    now: dt.datetime,
    http: GithubHttpPort | None = None,
) -> GithubInstallationSnapshot:
    """Fetch one complete installation snapshot using only App credentials."""
    installation_id = _positive_integer(github_installation_id, "installation id")
    current = _aware(now)
    transport = http or UrllibGithubHttp()

    app_jwt = create_github_app_jwt(
        github_app_id=github_app_id,
        private_key_pem=private_key_pem,
        now=current,
    )
    app_headers = _headers(app_jwt)
    installation_response = transport.request(
        "GET",
        f"{GITHUB_API_ROOT}/app/installations/{installation_id}",
        headers=app_headers,
    )
    token_response = transport.request(
        "POST",
        f"{GITHUB_API_ROOT}/app/installations/{installation_id}/access_tokens",
        headers=app_headers,
        body=b"{}",
    )
    installation_token = _object(token_response.payload, "installation token").get("token")
    if not isinstance(installation_token, str) or not installation_token:
        raise GithubAppApiError("GitHub did not return an installation token")
    repositories, etag = _installation_repositories(transport, _headers(installation_token))
    snapshot = _snapshot(
        _object(installation_response.payload, "installation"),
        installation_id=installation_id,
        repositories=repositories,
        repositories_etag=etag,
    )
    try:
        return validate_installation_snapshot(snapshot)
    except ValueError as exc:
        raise GithubAppApiError("GitHub returned inconsistent installation metadata") from exc


def fetch_github_app_installation_states(
    *,
    github_app_id: str,
    private_key_pem: bytes,
    now: dt.datetime,
    http: GithubHttpPort | None = None,
) -> tuple[GithubAppInstallationState, ...]:
    """List the App's complete installation set for missed-event repair."""
    transport = http or UrllibGithubHttp()
    app_jwt = create_github_app_jwt(
        github_app_id=github_app_id,
        private_key_pem=private_key_pem,
        now=_aware(now),
    )
    headers = _headers(app_jwt)
    states: list[GithubAppInstallationState] = []
    seen: set[int] = set()
    for page in range(1, _MAX_PAGES + 1):
        response = transport.request(
            "GET",
            f"{GITHUB_API_ROOT}/app/installations?per_page=100&page={page}",
            headers=headers,
        )
        if not isinstance(response.payload, list):
            raise GithubAppApiError("GitHub returned invalid App installations")
        for item in response.payload:
            payload = _object(item, "App installation")
            installation_id = _positive_integer(payload.get("id"), "installation id")
            if installation_id in seen:
                raise GithubAppApiError("GitHub returned duplicate App installations")
            seen.add(installation_id)
            states.append(
                GithubAppInstallationState(
                    github_installation_id=installation_id,
                    suspended_at=_timestamp(payload.get("suspended_at")),
                )
            )
        if len(response.payload) < 100:
            return tuple(states)
    raise GithubAppApiError("GitHub App installation pagination exceeded the safety limit")


def create_github_app_jwt(*, github_app_id: str, private_key_pem: bytes, now: dt.datetime) -> str:
    """Create the short-lived RS256 application JWT required by GitHub."""
    current = _aware(now)
    if not github_app_id.isdigit() or int(github_app_id) <= 0:
        raise GithubAppApiError("GitHub App id is invalid")
    header = {"alg": "RS256", "typ": "JWT"}
    issued_at = int(current.timestamp()) - 60
    claims = {"iat": issued_at, "exp": issued_at + 600, "iss": github_app_id}
    signing_input = b".".join((_encoded_json(header), _encoded_json(claims)))
    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise GithubAppApiError("GitHub App private key is invalid") from exc
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise GithubAppApiError("GitHub App private key must be RSA with at least 2048 bits")
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return b".".join((signing_input, _base64url(signature))).decode("ascii")


def _prove_user_installation(http: GithubHttpPort, headers: dict[str, str], installation_id: int) -> None:
    for page in range(1, _MAX_PAGES + 1):
        response = http.request(
            "GET",
            f"{GITHUB_API_ROOT}/user/installations?per_page=100&page={page}",
            headers=headers,
        )
        installations = _object(response.payload, "user installations").get("installations")
        if not isinstance(installations, list):
            raise GithubAppApiError("GitHub returned invalid user installations")
        if any(isinstance(item, dict) and item.get("id") == installation_id for item in installations):
            return
        if len(installations) < 100:
            break
    raise GithubAppApiError("GitHub user cannot access the returned installation")


def _user_installation_ids(
    http: GithubHttpPort,
    headers: dict[str, str],
) -> tuple[int, ...]:
    installation_ids: list[int] = []
    seen: set[int] = set()
    for page in range(1, _MAX_PAGES + 1):
        response = http.request(
            "GET",
            f"{GITHUB_API_ROOT}/user/installations?per_page=100&page={page}",
            headers=headers,
        )
        installations = _object(response.payload, "user installations").get("installations")
        if not isinstance(installations, list):
            raise GithubAppApiError("GitHub returned invalid user installations")
        for item in installations:
            installation = _object(item, "user installation")
            installation_id = _positive_integer(installation.get("id"), "installation id")
            if installation_id in seen:
                raise GithubAppApiError("GitHub returned duplicate user installations")
            seen.add(installation_id)
            installation_ids.append(installation_id)
        if len(installations) < 100:
            return tuple(installation_ids)
    raise GithubAppApiError("GitHub user installation pagination exceeded the safety limit")


def _user_installation_repositories(
    http: GithubHttpPort,
    headers: dict[str, str],
    installation_id: int,
) -> tuple[dict[str, Any], ...]:
    repositories: list[dict[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        response = http.request(
            "GET",
            (
                f"{GITHUB_API_ROOT}/user/installations/{installation_id}/repositories"
                f"?per_page=100&page={page}"
            ),
            headers=headers,
        )
        items = _object(response.payload, "user installation repositories").get("repositories")
        if not isinstance(items, list):
            raise GithubAppApiError("GitHub returned invalid user installation repositories")
        repositories.extend(_object(item, "user repository") for item in items)
        if len(items) < 100:
            return tuple(repositories)
    raise GithubAppApiError("GitHub user repository pagination exceeded the safety limit")


def _repository_permission(value: object) -> GithubProjectPermission | None:
    if not isinstance(value, dict):
        raise GithubAppApiError("GitHub returned invalid repository permissions")
    if value.get("admin") is True or value.get("maintain") is True:
        return GithubProjectPermission.MANAGE
    if value.get("push") is True:
        return GithubProjectPermission.UPLOAD
    if value.get("pull") is True or value.get("triage") is True:
        return GithubProjectPermission.VIEW
    return None


def _installation_repositories(
    http: GithubHttpPort, headers: dict[str, str]
) -> tuple[tuple[GithubRepositorySnapshot, ...], str | None]:
    repositories: list[GithubRepositorySnapshot] = []
    etag: str | None = None
    for page in range(1, _MAX_PAGES + 1):
        response = http.request(
            "GET",
            f"{GITHUB_API_ROOT}/installation/repositories?per_page=100&page={page}",
            headers=headers,
        )
        if page == 1:
            etag = response.headers.get("etag")
        items = _object(response.payload, "installation repositories").get("repositories")
        if not isinstance(items, list):
            raise GithubAppApiError("GitHub returned invalid installation repositories")
        repositories.extend(_repository(item) for item in items)
        if len(items) < 100:
            return tuple(repositories), etag
    raise GithubAppApiError("GitHub repository pagination exceeded the safety limit")


def _snapshot(
    payload: dict[str, Any],
    *,
    installation_id: int,
    repositories: tuple[GithubRepositorySnapshot, ...],
    repositories_etag: str | None,
) -> GithubInstallationSnapshot:
    if payload.get("id") != installation_id:
        raise GithubAppApiError("GitHub installation identity did not match")
    account = payload.get("account")
    if not isinstance(account, dict):
        raise GithubAppApiError("GitHub installation owner is invalid")
    owner_id = _positive_integer(account.get("id"), "owner id")
    owner_login = account.get("login")
    account_type = account.get("type")
    selection = payload.get("repository_selection")
    if not isinstance(owner_login, str) or not isinstance(account_type, str) or not isinstance(selection, str):
        raise GithubAppApiError("GitHub installation metadata is incomplete")
    try:
        normalized_type = GithubAccountType(account_type.casefold())
        normalized_selection = GithubSelection(selection.casefold())
    except ValueError as exc:
        raise GithubAppApiError("GitHub installation metadata is unsupported") from exc
    return GithubInstallationSnapshot(
        github_installation_id=installation_id,
        github_owner_id=owner_id,
        owner_login=owner_login,
        account_type=normalized_type,
        repository_selection=normalized_selection,
        suspended_at=_timestamp(payload.get("suspended_at")),
        deleted_at=None,
        repositories_etag=repositories_etag,
        reconciliation_cursor=None,
        repositories=repositories,
    )


def _repository(value: object) -> GithubRepositorySnapshot:
    if not isinstance(value, dict):
        raise GithubAppApiError("GitHub returned an invalid repository")
    owner = value.get("owner")
    if not isinstance(owner, dict):
        raise GithubAppApiError("GitHub returned an invalid repository owner")
    full_name = value.get("full_name")
    default_branch = value.get("default_branch")
    visibility = value.get("visibility")
    if not all(isinstance(item, str) for item in (full_name, default_branch, visibility)):
        raise GithubAppApiError("GitHub returned incomplete repository metadata")
    try:
        normalized_visibility = GithubRepositoryVisibility(cast(str, visibility).casefold())
    except ValueError as exc:
        raise GithubAppApiError("GitHub returned unsupported repository visibility") from exc
    archived = value.get("archived")
    disabled = value.get("disabled")
    if not isinstance(archived, bool) or not isinstance(disabled, bool):
        raise GithubAppApiError("GitHub returned invalid repository state")
    return GithubRepositorySnapshot(
        github_repository_id=_positive_integer(value.get("id"), "repository id"),
        github_owner_id=_positive_integer(owner.get("id"), "repository owner id"),
        full_name=cast(str, full_name),
        default_branch=cast(str, default_branch),
        visibility=normalized_visibility,
        archived=archived,
        disabled=disabled,
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": _API_VERSION,
    }


def _rate_limit_retry_at(
    *,
    status: int,
    headers: Mapping[str, str],
    now: dt.datetime,
) -> dt.datetime | None:
    if status not in {403, 429}:
        return None
    retry_seconds: int | None = None
    retry_after = headers.get("retry-after")
    if retry_after is not None:
        try:
            retry_seconds = int(retry_after)
        except ValueError:
            retry_seconds = None
    if retry_seconds is None and headers.get("x-ratelimit-remaining") == "0":
        try:
            reset_at = int(headers.get("x-ratelimit-reset", ""))
        except ValueError:
            reset_at = 0
        if reset_at > 0:
            retry_seconds = int(reset_at - now.timestamp()) + 1
    if retry_seconds is None:
        return None
    bounded_seconds = min(60 * 60, max(1, retry_seconds))
    return now + dt.timedelta(seconds=bounded_seconds)


def _encoded_json(value: Mapping[str, object]) -> bytes:
    return _base64url(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _base64url(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise GithubAppApiError(f"GitHub {label} is invalid")
    return value


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GithubAppApiError(f"GitHub returned invalid {label}")
    return value


def _timestamp(value: object) -> dt.datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GithubAppApiError("GitHub timestamp is invalid")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GithubAppApiError("GitHub timestamp is invalid") from exc
    return _aware(parsed)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise GithubAppApiError("GitHub API timestamp must be timezone-aware")
    return value


__all__ = [
    "GITHUB_API_ROOT",
    "GithubApiResponse",
    "GithubAppInstallationState",
    "GithubAppApiError",
    "GithubAppUserEntitlementClient",
    "GithubRateLimitError",
    "GithubHttpPort",
    "UrllibGithubHttp",
    "create_github_app_jwt",
    "fetch_authoritative_installation",
    "fetch_authoritative_installation_for_user",
    "fetch_github_app_installation_states",
    "load_github_app_private_key",
]
