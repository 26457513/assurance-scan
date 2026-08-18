"""Poll GitHub for completed assurance-scan runs and ingest them.

Pull model (see docs/plan-github-polling-ingest.md): no inbound exposure —
the server fetches completed workflow runs, downloads the results artifact
zip, and ingests findings.json + SARIF + SBOM via server.ci_ingest.

HTTP is stdlib urllib wrapped in asyncio.to_thread; the poll cadence is one
listing call per repo per cycle, so no HTTP dependency is warranted.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.ci_ingest import ci_run_id, ingest_ci_run


log = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
WORKFLOW_NAME = "assurance-scan"
ARTIFACT_NAME = "assurance-scan-results"


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects but never re-send the Authorization header —
    artifact downloads redirect to a pre-signed CDN URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        req_headers = {k: v for k, v in req.headers.items() if k.lower() != "authorization"}
        return urllib.request.Request(newurl, headers=req_headers, method=req.get_method())


class GitHubClient:
    """Minimal read-only GitHub REST client (stdlib)."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._opener = urllib.request.build_opener(_NoAuthRedirect)

    def _get(self, url: str, accept: str = "application/vnd.github+json") -> Any:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "User-Agent": "assurance-scan-poller",
        })
        with self._opener.open(req, timeout=30) as resp:
            return json.loads(resp.read())

    def list_runs(self, repo: str) -> list[dict[str, Any]]:
        doc = self._get(f"{API_ROOT}/repos/{repo}/actions/runs?per_page=15")
        return [
            r for r in doc.get("workflow_runs", [])
            if r.get("name") == WORKFLOW_NAME and r.get("status") == "completed"
        ]

    def download_artifact_zip(self, repo: str, github_run_id: int) -> dict[str, bytes] | None:
        doc = self._get(f"{API_ROOT}/repos/{repo}/actions/runs/{github_run_id}/artifacts")
        art = next(
            (a for a in doc.get("artifacts", []) if a.get("name") == ARTIFACT_NAME and not a.get("expired")),
            None,
        )
        if art is None:
            return None
        req = urllib.request.Request(art["archive_download_url"], headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "assurance-scan-poller",
        })
        with self._opener.open(req, timeout=60) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # Artifact zips nest files in a directory named after the artifact.
            return {
                name.rsplit("/", 1)[-1]: zf.read(name)
                for name in zf.namelist()
            }


def _meta_from_run(repo: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "github_run_id": run["id"],
        "repo": repo,
        "conclusion": run.get("conclusion"),
        "head_branch": run.get("head_branch"),
        "head_sha": run.get("head_sha"),
        "run_url": run.get("html_url"),
        "started_at": _parse_ts(run.get("created_at")),
        "completed_at": _parse_ts(run.get("updated_at")),
    }


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


async def poll_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    client: GitHubClient,
    repos: tuple[str, ...],
) -> dict[str, Any]:
    """One poll pass. Per-repo/per-run failures are logged, never raised."""
    result: dict[str, Any] = {"repos": {}, "ingested": 0, "skipped": 0, "failed": 0}
    for repo in repos:
        counts = {"ingested": 0, "skipped": 0, "failed": 0}
        try:
            runs = await asyncio.to_thread(client.list_runs, repo)
        except Exception as exc:
            log.warning("poll %s: listing failed: %s", repo, exc)
            result["repos"][repo] = {"error": str(exc)}
            continue
        for run in sorted(runs, key=lambda r: r["id"], reverse=True):
            run_id = f"gh-{run['id']}"
            async with session_factory() as session:
                try:
                    from server.db.repositories.runs import RunRepository
                    if await RunRepository(session).get(run_id) is not None:
                        counts["skipped"] += 1
                        continue
                    blobs: dict[str, bytes] | None = None
                    payload: dict[str, Any] | None = None
                    try:
                        blobs = await asyncio.to_thread(
                            client.download_artifact_zip, repo, run["id"]
                        )
                    except Exception as exc:
                        log.warning("poll %s run %s: artifact download failed: %s", repo, run_id, exc)
                    if blobs and "findings.json" in blobs:
                        payload = json.loads(blobs["findings.json"])
                        payload.setdefault("github_run_id", run["id"])
                        payload.setdefault("repo", repo)
                    status = await ingest_ci_run(
                        session, payload, _meta_from_run(repo, run), blobs,
                    )
                    counts["ingested" if status == "ingested" else "skipped"] += 1
                except Exception as exc:
                    log.exception("poll %s run %s: ingest failed", repo, run_id)
                    counts["failed"] += 1
        result["repos"][repo] = counts
        result["ingested"] += counts["ingested"]
        result["skipped"] += counts["skipped"]
        result["failed"] += counts["failed"]
    return result


async def poller_loop(
    session_factory: async_sessionmaker[AsyncSession],
    client: GitHubClient,
    repos: tuple[str, ...],
    interval_seconds: int,
) -> None:
    log.info("github poller started: repos=%s interval=%ss", repos, interval_seconds)
    while True:
        try:
            await poll_cycle(session_factory, client, repos)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poll cycle crashed; continuing")
        await asyncio.sleep(interval_seconds)
