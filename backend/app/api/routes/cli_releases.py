"""Public, cache-safe distribution of signed local-CLI release metadata."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.modules.atomic.local_cli.release_manifest import (
    ReleaseManifestError,
    validate_release_manifest,
)
from app.modules.shared.paths import RESOURCES_ROOT


router = APIRouter(prefix="/v2/cli/releases", tags=["cli-releases"])
PUBLIC_CLI_RELEASE_PATHS = frozenset(
    {
        "/api/v2/cli/releases/wrapper",
        "/api/v2/cli/releases/wrapper.sha256",
        "/api/v2/cli/releases/latest",
        "/api/v2/cli/releases/latest.sigstore.json",
    }
)
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_BUNDLE_BYTES = 1024 * 1024
_WRAPPER_PATH = RESOURCES_ROOT / "bootstrap" / "assurance-scan"


@router.get("/wrapper", response_class=FileResponse)
async def cli_wrapper() -> FileResponse:
    """Return the reviewed host wrapper as an inert downloadable file."""

    return FileResponse(
        _WRAPPER_PATH,
        media_type="text/x-shellscript",
        filename="assurance-scan",
        headers={
            "Cache-Control": "public, max-age=300, no-transform",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/wrapper.sha256", response_class=PlainTextResponse)
async def cli_wrapper_sha256() -> PlainTextResponse:
    """Return the exact digest shown beside the reviewed wrapper download."""

    digest = hashlib.sha256(_WRAPPER_PATH.read_bytes()).hexdigest()
    return PlainTextResponse(
        digest + "\n",
        headers={
            "Cache-Control": "public, max-age=300, no-transform",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/latest", response_class=Response)
async def latest_cli_release(request: Request) -> Response:
    """Return the pre-signed manifest; never synthesize trust metadata at runtime."""

    path = _configured_file(request, "cli_release_manifest_path", _MAX_MANIFEST_BYTES)
    try:
        content = path.read_bytes()
        document = json.loads(content)
        if not isinstance(document, dict):
            raise ValueError
        validate_release_manifest(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, ReleaseManifestError):
        raise HTTPException(status_code=503, detail="CLI release manifest is unavailable") from None
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=300, no-transform",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/latest.sigstore.json", response_class=FileResponse)
async def latest_cli_release_bundle(request: Request) -> FileResponse:
    """Return the immutable Sigstore bundle that verifies the manifest bytes."""

    path = _configured_file(request, "cli_release_bundle_path", _MAX_BUNDLE_BYTES)
    try:
        document: Any = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="CLI release signature is unavailable") from None
    if not isinstance(document, dict):
        raise HTTPException(status_code=503, detail="CLI release signature is unavailable")
    return FileResponse(
        path,
        media_type="application/vnd.dev.sigstore.bundle+json",
        headers={
            "Cache-Control": "public, max-age=300, no-transform",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _configured_file(request: Request, setting: str, maximum: int) -> Path:
    raw = getattr(request.app.state.settings, setting, "")
    if not isinstance(raw, str) or not raw:
        raise HTTPException(status_code=503, detail="CLI release metadata is unavailable")
    path = Path(raw)
    try:
        info = path.stat()
    except OSError:
        raise HTTPException(status_code=503, detail="CLI release metadata is unavailable") from None
    if not path.is_absolute() or not path.is_file() or info.st_size < 2 or info.st_size > maximum:
        raise HTTPException(status_code=503, detail="CLI release metadata is unavailable")
    return path


__all__ = ["router"]
