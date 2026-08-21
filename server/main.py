"""FastAPI application factory.

The app is assembled at import time so uvicorn can target it directly via
`uvicorn server.main:app`. Routes are registered by including routers from
`server.api.routes`.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.api.routes import catalogue_drift, compliance, config, findings, folders, frs, frs_list, gh_tokens, github, health, poller, projects, scans, stream, test_source, trends, versions
from server.config import Settings, load_settings
from server.db.connection import dispose_engine
from server.mcp import build_mcp_server, mount_mcp_on_app
from server.worker.queue import ScanQueue


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)r}',
    )


def _mount_static(app: FastAPI, settings: Settings) -> None:
    """Mount the built SvelteKit frontend if present.

    The Dockerfile copies the built assets into `server/static`. In dev, this
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
    queue = ScanQueue(settings)
    app.state.scan_queue = queue
    await queue.start()

    poller_task = None
    if settings.github_poll_token and (settings.poll_repos or settings.github_org):
        from server.db.connection import get_sessionmaker
        from server.github_poller import GitHubClient, poller_loop

        poller_task = asyncio.create_task(poller_loop(
            get_sessionmaker(settings),
            settings.github_poll_token,
            settings.github_org,
            settings.poll_interval_seconds,
        ))

    # The MCP server's session manager needs lifespan initialization.
    mcp_server = app.state.mcp_server
    async with mcp_server.session_manager.run():
        try:
            yield
        finally:
            if poller_task is not None:
                poller_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poller_task
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

    google_on = bool(
        settings.google_client_id and settings.google_client_secret
        and settings.session_secret and settings.public_base_url
    )

    if google_on or (settings.app_auth_user and settings.app_auth_password):
        import asyncio
        import urllib.parse as _urlparse

        from fastapi.responses import JSONResponse, RedirectResponse

        from server.auth import (
            GOOGLE_AUTH_URL,
            allowed_google_account,
            basic_auth_ok,
            exchange_google_code,
            mint_session,
            verify_session,
        )

        @app.middleware("http")
        async def _auth(request, call_next):  # type: ignore[no-untyped-def]
            path = request.url.path
            # Healthcheck (container-internal) and the login flow stay open.
            if path == "/health" or path.startswith("/auth/"):
                return await call_next(request)
            # MCP clients authenticate with a bearer token; the browser
            # login redirect is useless to them.
            if path == "/mcp" or path.startswith("/mcp/"):
                header = request.headers.get("authorization", "")
                if settings.mcp_token and header == f"Bearer {settings.mcp_token}":
                    return await call_next(request)
                return JSONResponse(
                    {"detail": "unauthorized: MCP requires 'Authorization: Bearer $MCP_TOKEN'"},
                    status_code=401,
                )
            if google_on and verify_session(request.cookies.get("as_session"), settings.session_secret):
                return await call_next(request)
            if settings.app_auth_user and basic_auth_ok(
                request.headers.get("authorization"),
                settings.app_auth_user,
                settings.app_auth_password,
            ):
                return await call_next(request)
            if google_on and not path.startswith("/api/"):
                # Browsers get the login redirect; API clients get JSON 401s.
                nxt = _urlparse.quote(path)
                return RedirectResponse(f"/auth/login?next={nxt}")
            return JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="assurance-scan"'},
            )

        @app.get("/auth/login")
        async def auth_login(next: str = "/"):  # type: ignore[no-untyped-def]
            params = _urlparse.urlencode({
                "client_id": settings.google_client_id,
                "redirect_uri": f"{settings.public_base_url}/auth/callback",
                "response_type": "code",
                "scope": "openid email",
                "access_type": "online",
                "prompt": "select_account",
            })
            resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")
            resp.set_cookie("as_next", next, max_age=600, httponly=True, samesite="lax")
            return resp

        @app.get("/auth/callback")
        async def auth_callback(request: Request, code: str = "", error: str = "", error_description: str = ""):  # type: ignore[no-untyped-def]
            if error:
                return JSONResponse(
                    {"detail": f"google auth error: {error}", "description": error_description},
                    status_code=401,
                )
            if not code:
                return JSONResponse({"detail": "missing code"}, status_code=400)
            try:
                payload = await asyncio.to_thread(
                    exchange_google_code,
                    code, settings.google_client_id, settings.google_client_secret,
                    f"{settings.public_base_url}/auth/callback",
                )
            except Exception:
                return JSONResponse({"detail": "google exchange failed"}, status_code=502)
            if not allowed_google_account(payload, settings.google_domain):
                return JSONResponse(
                    {"detail": f"account not in @{settings.google_domain}"},
                    status_code=403,
                )
            nxt = request.cookies.get("as_next") or "/"
            if not nxt.startswith("/"):  # internal paths only
                nxt = "/"
            resp = RedirectResponse(nxt, status_code=302)
            resp.set_cookie(
                "as_session",
                mint_session(payload["email"], settings.session_secret),
                max_age=30 * 24 * 3600,
                httponly=True,
                # Secure cookies are dropped by browsers (Safari notably) on
                # plain http — set only when the instance is actually https.
                secure=settings.public_base_url.startswith("https://"),
                samesite="lax",
            )
            resp.delete_cookie("as_next")
            return resp

        @app.get("/auth/logout")
        async def auth_logout():  # type: ignore[no-untyped-def]
            resp = RedirectResponse("/")
            resp.delete_cookie("as_session")
            return resp

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
    app.include_router(projects.router, prefix="/api")
    app.include_router(poller.router, prefix="/api")
    app.include_router(github.router, prefix="/api")
    app.include_router(gh_tokens.router, prefix="/api")
    app.include_router(versions.router, prefix="/api")
    app.include_router(compliance.router, prefix="/api")

    # MCP Streamable HTTP endpoint at /mcp. Build the server first so we can
    # expose its session manager to the lifespan for initialization.
    mcp_server = build_mcp_server(app)
    app.state.mcp_server = mcp_server
    mount_mcp_on_app(app, mcp=mcp_server)

    _mount_static(app, settings)
    return app


app = create_app()
