"""Production composition for GitHub Actions OIDC upload authentication."""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.infrastructure.db.repositories.github_oidc_replays import (
    SqlAlchemyGithubOidcReplayRepository,
)
from app.infrastructure.db.repositories.github_upload_authorization import (
    SqlAlchemyGithubUploadAuthorizationRepository,
)
from app.infrastructure.github_app_api import (
    fetch_authoritative_repository,
    load_github_app_private_key,
)
from app.infrastructure.github_oidc import (
    CryptographyRsaSignatureVerifier,
    GithubOidcJwksClient,
)
from app.modules.atomic.access.github_oidc import (
    GithubOidcClaims,
    authenticate_github_oidc,
    github_oidc_audience,
    github_oidc_key_id,
)
from app.modules.workflows.github_actions_authentication import (
    GithubActionsUploadPrincipal,
    authorize_github_actions_upload,
)


class SqlAlchemyGithubActionsRequestAuthenticator:
    """Authenticate signed workload identity and verify current App scope."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        jwks: GithubOidcJwksClient,
    ) -> None:
        self._session = session
        self._settings = settings
        self._jwks = jwks
        self._signature_verifier = CryptographyRsaSignatureVerifier()

    async def authenticate(self, token: str, *, now: dt.datetime) -> GithubOidcClaims:
        audience = github_oidc_audience(self._settings.public_base_url)
        kid = github_oidc_key_id(token)
        keys = await asyncio.to_thread(self._jwks.get, now=now, required_kid=kid)
        return authenticate_github_oidc(
            token,
            audience=audience,
            jwks=keys,
            now=now,
            signature_verifier=self._signature_verifier,
        )

    async def authorize(
        self,
        claims: GithubOidcClaims,
        *,
        now: dt.datetime,
    ) -> GithubActionsUploadPrincipal:
        private_key = await asyncio.to_thread(
            load_github_app_private_key,
            self._settings.github_app_private_key_path,
        )

        async def load_repository(
            installation_id: int,
            repository: str,
            verified_at: dt.datetime,
        ):
            return await asyncio.to_thread(
                fetch_authoritative_repository,
                github_app_id=self._settings.github_app_id,
                private_key_pem=private_key,
                github_installation_id=installation_id,
                repository_full_name=repository,
                now=verified_at,
            )

        return await authorize_github_actions_upload(
            claims,
            now=now,
            repository_loader=load_repository,
            authorization_repository=SqlAlchemyGithubUploadAuthorizationRepository(
                self._session
            ),
            replay_repository=SqlAlchemyGithubOidcReplayRepository(self._session),
        )


__all__ = ["SqlAlchemyGithubActionsRequestAuthenticator"]
