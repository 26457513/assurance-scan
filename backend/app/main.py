"""FastAPI application factory.

The app is assembled at import time so uvicorn can target it directly via
`uvicorn app.main:app`. Routes are registered by including routers from
`app.api.routes`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    accounts,
    catalogue_drift,
    cli_releases,
    ci_setup,
    compliance,
    config,
    findings,
    folders,
    frs,
    frs_list,
    github_auth,
    github_app_setup,
    github_app_webhook,
    github_actions_ingest,
    health,
    local_ingest,
    notion,
    projects,
    scan_tokens,
    scans,
    setup,
    stream,
    test_source,
    trends,
    versions,
    workflows,
)
from app.config import Settings, load_settings
from app.infrastructure.db.connection import dispose_engine
from app.mcp import build_mcp_server, mount_mcp_on_app
from app.modules.atomic.access.auth_failure_limiter import AuthenticationFailureLimiter
from app.modules.atomic.ingestion.operational_signals import (
    LocalIngestRetentionSignal,
    render_retention_signal,
)
from app.worker.queue import ScanQueue


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}',
    )


def _mount_static(app: FastAPI, settings: Settings) -> None:
    """Mount the built SvelteKit frontend if present.

    The Dockerfile copies the built assets into `app/static`. In dev, this
    directory is empty and SvelteKit runs separately on port 5173.
    """
    static_dir = Path(__file__).resolve().parent / "static"
    index_file = static_dir / "index.html"
    if not static_dir.exists() or not index_file.exists():
        return

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str) -> FileResponse:
        # SvelteKit client-side routing fallback.
        candidate = static_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Run startup/shutdown hooks for the worker queue, MCP server, and DB."""
    settings: Settings = app.state.settings
    github_worker_configuration: tuple[str, bytes] | None = None
    if settings.github_webhook_enabled:
        from app.infrastructure.github_app_api import (
            create_github_app_jwt,
            load_github_app_private_key,
        )

        private_key = load_github_app_private_key(settings.github_app_private_key_path)
        create_github_app_jwt(
            github_app_id=settings.github_app_id,
            private_key_pem=private_key,
            now=dt.datetime.now(dt.timezone.utc),
        )
        github_worker_configuration = (settings.github_app_id, private_key)
    queue = ScanQueue(settings)
    app.state.scan_queue = queue
    await queue.start()

    async def _retention_loop() -> None:
        from app.infrastructure.db.connection import get_sessionmaker
        from app.infrastructure.db.retention import run_retention_cleanup

        while True:
            started = time.monotonic()
            try:
                async with get_sessionmaker(settings)() as session:
                    result = await run_retention_cleanup(session)
                signal = LocalIngestRetentionSignal(
                    outcome="completed",
                    duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                    raw_artifacts=result.raw_artifacts,
                    normalized_runs=result.runs,
                    token_audits=result.token_audits,
                    tombstones=result.tombstones,
                    webhook_deliveries=result.webhook_deliveries,
                    ingest_attempts=result.ingest_attempts,
                    usage_charges=result.usage_charges,
                )
                logging.getLogger(__name__).info(render_retention_signal(signal))
            except Exception:
                # Exception messages and tracebacks may contain database paths.
                # The operations signal intentionally records only the failure.
                signal = LocalIngestRetentionSignal(
                    outcome="failed",
                    duration_ms=max(0, round((time.monotonic() - started) * 1000)),
                )
                logging.getLogger(__name__).error(render_retention_signal(signal))
            await asyncio.sleep(6 * 60 * 60)

    retention_task = asyncio.create_task(_retention_loop())

    github_webhook_worker_task = None
    github_reconciliation_task = None
    if github_worker_configuration is not None:
        from app.infrastructure.db.connection import get_sessionmaker
        from app.infrastructure.github_reconciliation_scheduler import github_reconciliation_loop
        from app.infrastructure.github_webhook_worker import github_webhook_worker_loop

        github_app_id, private_key = github_worker_configuration
        github_webhook_worker_task = asyncio.create_task(
            github_webhook_worker_loop(
                get_sessionmaker(settings),
                github_app_id=github_app_id,
                private_key_pem=private_key,
            )
        )
        github_reconciliation_task = asyncio.create_task(
            github_reconciliation_loop(
                get_sessionmaker(settings),
                github_app_id=github_app_id,
                private_key_pem=private_key,
            )
        )

    # The MCP server's session manager needs lifespan initialization.
    mcp_server = app.state.mcp_server
    async with mcp_server.session_manager.run():
        try:
            yield
        finally:
            if github_reconciliation_task is not None:
                github_reconciliation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await github_reconciliation_task
            if github_webhook_worker_task is not None:
                github_webhook_worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await github_webhook_worker_task
            retention_task.cancel()
            with suppress(asyncio.CancelledError):
                await retention_task
            await queue.stop()
            await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    settings = settings or load_settings()
    _configure_logging(settings)

    app = FastAPI(
        title="Assurance Scan",
        version="2.0.0-dev",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.scan_token_failure_limiter = AuthenticationFailureLimiter()

    hosted_mode = bool(settings.public_base_url)

    if hosted_mode:
        import urllib.parse as _urlparse

        from fastapi.responses import JSONResponse, RedirectResponse

        async def _mcp_user_principal(header: str):
            """A per-user MCP token (Setup → My account) matches by hash."""
            import hashlib

            if not header.startswith("Bearer "):
                return None
            from app.infrastructure.db.connection import get_sessionmaker
            from app.infrastructure.db.models import User
            from app.infrastructure.project_access import (
                ProjectAccessPrincipal,
                sync_github_app_memberships,
            )

            h = hashlib.sha256(header[7:].encode()).hexdigest()
            sessionmaker = get_sessionmaker()
            async with sessionmaker() as session:
                from sqlalchemy import select as _select

                row = (
                    (
                        await session.execute(
                            _select(User).where(
                                User.mcp_token_hash == h,
                                User.disabled_at.is_(None),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if row is None:
                    return None
                await sync_github_app_memberships(session, row, settings)
                return ProjectAccessPrincipal(user_id=row.id, role=row.role)

        async def _browser_user_id(cookie: str) -> int | None:
            from app.infrastructure.db.connection import get_sessionmaker
            from app.infrastructure.db.repositories.identity_sessions import (
                SqlAlchemyBrowserSessionRepository,
            )
            from app.modules.atomic.access.server_session import (
                authenticate_browser_session,
                refreshed_idle_expiry,
            )

            now = dt.datetime.now(dt.timezone.utc)
            async with get_sessionmaker(settings)() as session:
                repository = SqlAlchemyBrowserSessionRepository(session)
                record = await repository.find_by_cookie(cookie)
                result = authenticate_browser_session(cookie, record, now=now)
                if not result.authenticated or record is None:
                    return None
                await repository.touch(
                    record.session_id,
                    now=now,
                    idle_expires_at=refreshed_idle_expiry(record, now=now),
                )
                return result.user_id

        @app.middleware("http")
        async def _auth(request, call_next):
            path = request.url.path
            # Healthcheck, browser authentication, and immutable frontend
            # assets stay public. The branded login page is part of the SPA;
            # GitHub credentials are still entered only on github.com.
            if (
                path == "/health"
                or path.startswith("/auth/")
                or path.startswith("/_app/")
                or path.startswith("/static/")
                or path == "/favicon.svg"
            ):
                return await call_next(request)
            # GitHub authenticates the webhook's exact raw body using its own
            # HMAC boundary; browser login must never intercept this endpoint.
            if path == "/api/v2/github/webhook":
                return await call_next(request)
            # Ingest routes authenticate dedicated local or GitHub workload
            # credentials. Browser and MCP credentials are not alternatives.
            if (
                path == "/api/v1/ingest"
                or path.startswith("/api/v1/ingest/")
                or path == "/api/v2/ingest"
                or path.startswith("/api/v2/ingest/")
            ):
                return await call_next(request)
            # MCP clients authenticate with a bearer token; the browser
            # login redirect is useless to them. The env MCP_TOKEN is the
            # service path; per-user tokens come from the users table.
            if path == "/mcp" or path.startswith("/mcp/"):
                header = request.headers.get("authorization", "")
                from app.infrastructure.project_access import (
                    CURRENT_PROJECT_ACCESS,
                    SYSTEM_PRINCIPAL,
                )

                if settings.mcp_token and header == f"Bearer {settings.mcp_token}":
                    context_token = CURRENT_PROJECT_ACCESS.set(SYSTEM_PRINCIPAL)
                    try:
                        return await call_next(request)
                    finally:
                        CURRENT_PROJECT_ACCESS.reset(context_token)
                principal = await _mcp_user_principal(header)
                if principal is not None:
                    context_token = CURRENT_PROJECT_ACCESS.set(principal)
                    try:
                        return await call_next(request)
                    finally:
                        CURRENT_PROJECT_ACCESS.reset(context_token)
                return JSONResponse(
                    {"detail": "unauthorized: MCP requires a bearer token — generate one in Setup → My account"},
                    status_code=401,
                )
            user_id = await _browser_user_id(request.cookies.get("as_session", ""))
            if user_id is not None:
                request.state.authenticated_user_id = user_id
                return await call_next(request)
            if not path.startswith("/api/"):
                # Browsers get the login redirect; API clients get JSON 401s.
                nxt = _urlparse.quote(path)
                return RedirectResponse(f"/auth/login?next={nxt}")
            return JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
            )

    app.include_router(health.router)
    app.include_router(scans.router, prefix="/api")
    app.include_router(findings.router, prefix="/api")
    app.include_router(frs.router, prefix="/api")
    app.include_router(frs_list.router, prefix="/api")
    app.include_router(stream.router, prefix="/api")
    app.include_router(trends.router, prefix="/api")
    app.include_router(test_source.router, prefix="/api")
    app.include_router(config.router, prefix="/api")
    app.include_router(folders.router, prefix="/api")
    app.include_router(catalogue_drift.router, prefix="/api")
    app.include_router(ci_setup.router, prefix="/api")
    app.include_router(cli_releases.router, prefix="/api")
    app.include_router(projects.router, prefix="/api")
    app.include_router(github_auth.router)
    app.include_router(github_app_setup.router, prefix="/api")
    app.include_router(github_app_webhook.router, prefix="/api")
    app.include_router(github_actions_ingest.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(scan_tokens.router, prefix="/api")
    app.include_router(setup.router, prefix="/api")
    app.include_router(local_ingest.router, prefix="/api")
    app.include_router(versions.router, prefix="/api")
    app.include_router(notion.router, prefix="/api")
    app.include_router(workflows.router, prefix="/api")
    app.include_router(compliance.router, prefix="/api")

    # MCP Streamable HTTP endpoint at /mcp. Build the server first so we can
    # expose its session manager to the lifespan for initialization.
    mcp_server = build_mcp_server(app)
    app.state.mcp_server = mcp_server
    mount_mcp_on_app(app, mcp=mcp_server)

    _mount_static(app, settings)
    return app


app = create_app()
