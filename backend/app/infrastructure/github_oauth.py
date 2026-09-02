"""Fixed-endpoint HTTP adapter for GitHub OAuth and immutable user identity."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


@dataclass(frozen=True)
class VerifiedGithubAuthorization:
    github_user_id: int
    login: str
    access_token: str
    refresh_token: str
    expires_in_seconds: int


def exchange_and_verify_github_authorization(
    *, code: str, verifier: str, client_id: str, client_secret: str
) -> VerifiedGithubAuthorization:
    token_request = urllib.request.Request(
        GITHUB_TOKEN_URL,
        data=urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": verifier,
            }
        ).encode(),
        headers={"Accept": "application/json"},
        method="POST",
    )
    token_payload = _request_json(token_request)
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    expires_in = token_payload.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or not isinstance(expires_in, int)
        or expires_in <= 0
    ):
        raise ValueError("GitHub did not return an expiring user authorization")
    user_request = urllib.request.Request(
        GITHUB_USER_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    user_payload = _request_json(user_request)
    github_user_id = user_payload.get("id")
    login = user_payload.get("login")
    if (
        not isinstance(github_user_id, int)
        or github_user_id <= 0
        or not isinstance(login, str)
        or not login
        or len(login) > 128
    ):
        raise ValueError("GitHub returned an invalid immutable user identity")
    return VerifiedGithubAuthorization(
        github_user_id=github_user_id,
        login=login,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=expires_in,
    )


def _request_json(request: urllib.request.Request) -> dict[str, object]:
    if request.full_url not in {GITHUB_TOKEN_URL, GITHUB_USER_URL}:
        raise ValueError("unexpected GitHub OAuth endpoint")
    with (
        urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            request, timeout=15
        ) as response
    ):
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned an invalid response")
    return payload
