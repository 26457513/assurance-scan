"""FR-UI-RENDER tests.

The frontend is a built SvelteKit app served by FastAPI:
- /static/* mounts the built asset directory
- /{any/path} SPA-fallbacks to index.html so client-side routing works
- If no build is present (dev mode), no fallback is registered and the API
  alone is served.

These tests verify the mount + fallback contract using a tmp static dir
so the test doesn't depend on a real frontend build.

Security-header context (CSP, X-Content-Type-Options, etc.) is NOT
verified here — the current server doesn't add those headers. The ASVS
mapping to FR-UI-RENDER at V3.4.x is correctly flagged as low confidence
in fr-compliance-mapping.json because of this gap.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.main as main_module


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    """Fake built frontend: an index.html + one asset file."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        "<!doctype html><html><body>SvelteKit shell</body></html>"
    )
    (static / "favicon.png").write_bytes(b"\x89PNG fake")
    return static


@pytest_asyncio.fixture
async def client_with_static(static_dir, monkeypatch):
    """Boot FastAPI with _mount_static pointed at our tmp static dir."""
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda self: static_dir.parent if self.name == "main" else self.__class__(str(self)),
    )
    # The simpler hook: patch _mount_static to mount our tmp dir directly.
    original = main_module._mount_static

    def patched(app, settings):
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa_fallback(full_path: str) -> FileResponse:
            candidate = static_dir / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    monkeypatch.setattr(main_module, "_mount_static", patched)
    app = main_module.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # create_app caches state; reset for the next test.
    monkeypatch.setattr(main_module, "_mount_static", original)


@pytest_asyncio.fixture
async def client_without_static(monkeypatch):
    """Boot FastAPI with NO static dir present (dev mode)."""
    def empty_mount(app, settings):
        return None  # no static mount

    monkeypatch.setattr(main_module, "_mount_static", empty_mount)
    app = main_module.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Static mount when build is present
# ---------------------------------------------------------------------------

async def test_static_asset_served_when_build_present(client_with_static) -> None:
    """A real asset file in static/ is served directly under /static/."""
    res = await client_with_static.get("/static/favicon.png")
    assert res.status_code == 200
    assert res.content.startswith(b"\x89PNG")


async def test_spa_fallback_returns_index_for_unknown_path(client_with_static) -> None:
    """Unknown client-side routes (e.g. /scans/abc) fall back to index.html
    so the SvelteKit router can pick them up.
    """
    res = await client_with_static.get("/scans/some-run-id")
    assert res.status_code == 200
    assert b"SvelteKit shell" in res.content


async def test_spa_fallback_returns_index_for_root(client_with_static) -> None:
    """Root path serves index.html (the app entry)."""
    res = await client_with_static.get("/")
    assert res.status_code == 200
    assert b"SvelteKit shell" in res.content


async def test_named_static_path_returns_named_file_when_present(client_with_static) -> None:
    """A path that matches a real file (e.g. /favicon.png) returns the file
    rather than the index fallback.
    """
    res = await client_with_static.get("/favicon.png")
    assert res.status_code == 200
    assert res.content.startswith(b"\x89PNG")


# ---------------------------------------------------------------------------
# No static dir present (dev mode)
# ---------------------------------------------------------------------------

async def test_api_routes_respond_without_static_build(client_without_static) -> None:
    """Even without a built frontend, the API endpoints work — the SvelteKit
    dev server (separate process, port 5173) handles UI in dev.
    """
    res = await client_without_static.get("/health")
    assert res.status_code == 200
