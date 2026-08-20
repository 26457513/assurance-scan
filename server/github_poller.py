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

from sqlalchemy import select as sa_select
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

    def _get_raw(self, url: str, accept: str) -> bytes:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "User-Agent": "assurance-scan-poller",
        })
        with self._opener.open(req, timeout=30) as resp:
            return resp.read()

    def org_repos(self, org: str) -> list[dict[str, Any]]:
        """Full names of the org's non-archived repos, paginated to completion."""
        repos: list[dict[str, Any]] = []
        page = 1
        while True:
            doc = self._get(f"{API_ROOT}/orgs/{org}/repos?per_page=100&page={page}")
            batch = [r for r in doc if not r.get("archived")]
            repos.extend(batch)
            if len(doc) < 100:
                return repos
            page += 1
            if page > 20:  # ponytail: 2000 repos is plenty; raise if an org exceeds it
                return repos

    def file_contents(self, repo: str, commit: str, path: str) -> bytes:
        """Raw file bytes at a commit. Raises urllib.error.HTTPError on 404/403."""
        return self._get_raw(
            f"{API_ROOT}/repos/{repo}/contents/{path}?ref={commit}",
            accept="application/vnd.github.raw",
        )

    def repo_default_branch(self, repo: str) -> str:
        doc = self._get(f"{API_ROOT}/repos/{repo}")
        return doc.get("default_branch") or "main"

    def user_login(self) -> str:
        return self._get(f"{API_ROOT}/user").get("login") or ""

    def has_workflow(self, repo: str, filename: str) -> bool:
        import urllib.error

        try:
            self._get_raw(
                f"{API_ROOT}/repos/{repo}/actions/workflows/{filename}",
                accept="application/vnd.github+json",
            )
            return True
        except urllib.error.HTTPError:
            return False
        except Exception:
            return False

    def dispatch(self, repo: str, workflow_filename: str, ref: str, inputs: dict[str, str] | None = None) -> None:
        body = json.dumps({"ref": ref, **({"inputs": inputs} if inputs else {})}).encode()
        req = urllib.request.Request(
            f"{API_ROOT}/repos/{repo}/actions/workflows/{workflow_filename}/dispatches",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "assurance-scan-poller",
            },
        )
        with self._opener.open(req, timeout=20):
            pass  # 204 No Content

    def repo_branches(self, repo: str) -> list[str]:
        """Branch names (up to 100, case-insensitive order)."""
        doc = self._get(f"{API_ROOT}/repos/{repo}/branches?per_page=100")
        return sorted((b["name"] for b in doc), key=str.lower)

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
        "run_number": run.get("run_number"),
        "event": run.get("event"),
        "actor": (run.get("actor") or {}).get("login"),
        "display_title": run.get("display_title"),
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


_repo_cache: dict[Any, Any] = {}
_REPO_CACHE_TTL = 3600.0


def resolve_repos(client: GitHubClient, poll_repos: tuple[str, ...], org: str) -> tuple[str, ...]:
    """Manual POLL_REPOS wins; otherwise the org's repos, cached 1h."""
    import time as _time

    if poll_repos:
        return poll_repos
    if not org:
        return ()
    key = ("org", org)
    now = _time.monotonic()
    cached = _repo_cache.get(key)
    if cached and now - cached["at"] < _REPO_CACHE_TTL:
        return cached["repos"]
    repos = tuple(r["full_name"] for r in client.org_repos(org))
    _repo_cache[key] = {"repos": repos, "at": now}
    return repos


async def poll_all_orgs(session_factory, default_token: str, default_org: str) -> dict[str, Any]:
    """Poll the configured org plus every registered organisation.

    Registered orgs live in the organisations table; each carries its own
    token so this instance can read that org's runs and artifacts.
    """
    from server.db.models import Organisation

    result: dict[str, Any] = {"orgs": {}, "ingested": 0, "skipped": 0, "failed": 0}
    targets: list[tuple[str, str]] = []
    if default_token and default_org:
        targets.append((default_org, default_token))
    async with session_factory() as session:
        rows = (
            await session.execute(sa_select(Organisation).order_by(Organisation.name))
        ).scalars().all()
        key_enc = None
        for row in rows:
            if key_enc is None:
                from server.config import load_settings

                key_enc = load_settings().token_encryption_key
            from server.secrets import decrypt

            token = decrypt(row.token_encrypted, key_enc) if key_enc else None
            if token:
                targets.append((row.name, token))
    for org, token in targets:
        client = GitHubClient(token)
        repos = await asyncio.to_thread(resolve_repos, client, (), org)
        counts = await poll_cycle(session_factory, client, repos)
        result["orgs"][org] = counts
        for k in ("ingested", "skipped", "failed"):
            result[k] += counts[k]
    return result


async def poller_loop(
    session_factory: async_sessionmaker[AsyncSession],
    default_token: str,
    default_org: str,
    interval_seconds: int,
) -> None:
    log.info("github poller started: default_org=%s interval=%ss", default_org, interval_seconds)
    while True:
        try:
            await poll_all_orgs(session_factory, default_token, default_org)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poll cycle crashed; continuing")
        await asyncio.sleep(interval_seconds)
