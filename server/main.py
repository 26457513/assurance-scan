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

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.api.routes import catalogue_drift, compliance, config, findings, folders, frs, frs_list, github, health, poller, projects, scans, stream, test_source, trends, versions
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
            GitHubClient(settings.github_poll_token),
            settings.poll_repos,
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
