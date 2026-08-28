"""Poll GitHub for completed assurance-scan runs and ingest them.

Pull model (see docs/plan-github-polling-ingest.md): no inbound exposure —
the server fetches completed workflow runs, downloads the results artifact
zip, and ingests findings.json + SARIF + SBOM through the ingestion workflow.

HTTP is stdlib urllib wrapped in asyncio.to_thread; the poll cadence is one
listing call per repo per cycle, so no HTTP dependency is warranted.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.atomic.ingestion.result_persister._adapters import (
    SqlAlchemyIngestPersistence,
)
from app.modules.atomic.provenance.repository_identity import (
    InvalidRepositoryIdentityError,
    normalize_github_repository_key,
    parse_github_repository,
)
from app.modules.workflows.github_result_ingest import ingest_ci_run


log = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
WORKFLOW_NAME = "assurance-scan"
ARTIFACT_NAME = "assurance-scan-results"


def _require_github_api_url(url: str) -> None:
    """Reject authenticated requests to anything outside GitHub's API host."""
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("GitHub API request URL must use https://api.github.com")


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects but never re-send the Authorization header —
    artifact downloads redirect to a pre-signed CDN URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        req_headers = {k: v for k, v in req.headers.items() if k.lower() != "authorization"}
        return urllib.request.Request(newurl, headers=req_headers, method=req.get_method())


class GitHubClient:
    """Minimal read-only GitHub REST client (stdlib)."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._opener = urllib.request.build_opener(_NoAuthRedirect)

    def _open_api_request(self, req: urllib.request.Request, timeout: int) -> Any:
        _require_github_api_url(req.full_url)
        # The URL is allowlisted immediately above. Redirects are handled by
        # _NoAuthRedirect, which strips the authorization header.
        return self._opener.open(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            req, timeout=timeout
        )

    def _get(self, url: str, accept: str = "application/vnd.github+json") -> Any:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "User-Agent": "assurance-scan-poller",
        })
        try:
            with self._open_api_request(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError:
            # One retry — transient container-to-GitHub timeouts are common
            # (observed on Docker Desktop DNS/IPv6 flakiness).
            import time as _t
            _t.sleep(1)
            with self._open_api_request(req, timeout=30) as resp:
                return json.loads(resp.read())

    def _get_raw(self, url: str, accept: str) -> bytes:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "User-Agent": "assurance-scan-poller",
        })
        with self._open_api_request(req, timeout=30) as resp:
            return resp.read()

    def org_repos(self, org: str) -> list[dict[str, Any]]:
        """GitHub identity documents for non-archived organisation repositories."""
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

    def repository(self, repo: str) -> dict[str, Any]:
        """Return GitHub's authoritative repository identity document."""
        return self._get(f"{API_ROOT}/repos/{repo}")

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
        try:
            with self._open_api_request(req, timeout=30):
                pass  # 204 No Content
        except urllib.error.URLError:
            import time as _t
            _t.sleep(1)
            with self._open_api_request(req, timeout=30):
                pass

    def repo_branches(self, repo: str) -> list[str]:
        """All branch names, paginated to completion, case-insensitive order."""
        names: list[str] = []
        page = 1
        while True:
            doc = self._get(f"{API_ROOT}/repos/{repo}/branches?per_page=100&page={page}")
            names.extend(b["name"] for b in doc)
            if len(doc) < 100:
                return sorted(names, key=str.lower)
            page += 1
            if page > 30:  # ponytail: 3000 branches is plenty
                return sorted(names, key=str.lower)

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
        with self._open_api_request(req, timeout=60) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # Artifact zips nest files in a directory named after the artifact.
            return {
                name.rsplit("/", 1)[-1]: zf.read(name)
                for name in zf.namelist()
            }


def _meta_from_run(repo: str, repository_id: int, run: dict[str, Any]) -> dict[str, Any]:
    run_repository = run.get("repository") or {}
    if int(run_repository.get("id", 0)) != repository_id:
        raise ValueError("workflow run repository ID does not match polled repository")
    run_repo = parse_github_repository(str(run_repository.get("full_name", "")))
    if (
        run_repo is None
        or normalize_github_repository_key(run_repo)
        != normalize_github_repository_key(repo)
    ):
        raise ValueError("workflow run repository name does not match polled repository")
    github_run_id = int(run["id"])
    if github_run_id <= 0:
        raise ValueError("workflow run ID must be a positive integer")
    head_sha = str(run.get("head_sha") or "").lower()
    if len(head_sha) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in head_sha):
        raise ValueError("workflow run head SHA is invalid")
    return {
        "github_run_id": github_run_id,
        "github_repository_id": repository_id,
        "repo": repo,
        "conclusion": run.get("conclusion"),
        "head_branch": run.get("head_branch"),
        "head_sha": head_sha,
        "run_url": run.get("html_url"),
        "run_number": run.get("run_number"),
        "run_attempt": run.get("run_attempt"),
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


async def resolve_registered_repository(
    session: AsyncSession,
    repository: dict[str, Any],
) -> tuple[str, int, int | None, str]:
    """Resolve GitHub identity to a visible project and safely record renames.

    The immutable repository ID is authoritative once known. The normalized
    name is only a bootstrap fallback for projects registered before GitHub's
    numeric ID was observed.
    """
    from app.infrastructure.db.models import Project

    repository_id = int(repository["id"])
    repo = parse_github_repository(str(repository["full_name"]))
    if repository_id <= 0 or repo is None:
        raise ValueError("GitHub repository identity is incomplete")
    repo_key = normalize_github_repository_key(repo)

    project = (
        await session.execute(
            sa_select(Project).where(Project.github_repository_id == repository_id)
        )
    ).scalars().first()
    if project is not None:
        if project.hidden:
            return repo, repository_id, None, "hidden"
        key_owner = (
            await session.execute(
                sa_select(Project).where(
                    Project.github_repo_key == repo_key,
                    Project.id != project.id,
                )
            )
        ).scalars().first()
        if key_owner is not None:
            return repo, repository_id, None, "identity_conflict"
        if project.github_repo != repo or project.github_repo_key != repo_key:
            project.github_repo = repo
            project.github_repo_key = repo_key
            await session.commit()
        return repo, repository_id, project.id, "registered"

    project = (
        await session.execute(
            sa_select(Project).where(Project.github_repo_key == repo_key)
        )
    ).scalars().first()
    if project is None:
        return repo, repository_id, None, "unregistered"
    if project.hidden:
        return repo, repository_id, None, "hidden"
    if (
        project.github_repository_id is not None
        and project.github_repository_id != repository_id
    ):
        return repo, repository_id, None, "identity_conflict"
    project.github_repository_id = repository_id
    project.github_repo = repo
    project.github_repo_key = repo_key
    await session.commit()
    return repo, repository_id, project.id, "registered"


async def poll_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    client: GitHubClient,
    repos: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """One poll pass. Per-repo/per-run failures are logged, never raised."""
    result: dict[str, Any] = {"repos": {}, "ingested": 0, "skipped": 0, "failed": 0}
    for repository in repos:
        try:
            async with session_factory() as session:
                repo, repository_id, _project_id, resolution = (
                    await resolve_registered_repository(session, repository)
                )
        except (KeyError, TypeError, ValueError, InvalidRepositoryIdentityError) as exc:
            log.warning("skipping malformed GitHub repository document: %s", exc)
            result["failed"] += 1
            continue
        if resolution != "registered":
            result["repos"][repo] = {f"skipped_{resolution}": 1}
            result["failed" if resolution == "identity_conflict" else "skipped"] += 1
            continue
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
                    from app.infrastructure.db.repositories.runs import RunRepository
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
                        SqlAlchemyIngestPersistence(session),
                        payload,
                        _meta_from_run(repo, repository_id, run),
                        blobs,
                    )
                    counts["ingested" if status == "ingested" else "skipped"] += 1
                except Exception:
                    log.exception("poll %s run %s: ingest failed", repo, run_id)
                    counts["failed"] += 1
        result["repos"][repo] = counts
        result["ingested"] += counts["ingested"]
        result["skipped"] += counts["skipped"]
        result["failed"] += counts["failed"]
    return result


_repo_cache: dict[Any, Any] = {}
_REPO_CACHE_TTL = 3600.0


def resolve_repos(
    client: GitHubClient, poll_repos: tuple[str, ...], org: str
) -> tuple[dict[str, Any], ...]:
    """Resolve configured names or an organisation to GitHub identity documents."""
    import time as _time

    if poll_repos:
        return tuple(client.repository(repo) for repo in poll_repos)
    if not org:
        return ()
    key = ("org", org)
    now = _time.monotonic()
    cached = _repo_cache.get(key)
    if cached and now - cached["at"] < _REPO_CACHE_TTL:
        return cached["repos"]
    repos = tuple(client.org_repos(org))
    _repo_cache[key] = {"repos": repos, "at": now}
    return repos


async def poll_all_orgs(session_factory, default_token: str, default_org: str) -> dict[str, Any]:
    """Poll the configured org plus every registered organisation.

    Registered orgs live in the organisations table; each carries its own
    token so this instance can read that org's runs and artifacts.
    """
    from app.infrastructure.db.models import Organisation

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
                from app.config import load_settings

                key_enc = load_settings().token_encryption_key
            from app.secrets import decrypt

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
