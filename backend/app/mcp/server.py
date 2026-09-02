"""MCP server using Streamable HTTP transport.

The MCP SDK is invoked through FastAPI's ASGI surface — the same uvicorn
worker serves both REST and MCP. Tools are registered with the MCP
`FastMCP` server and exposed at /mcp.

Each tool handler is an async function that opens its own DB session
from the global sessionmaker. Tools are deliberately thin: they map
arguments to repository calls and return JSON-serialisable dicts.

Settings and the scan queue are passed explicitly into `build_mcp_server`
so tool handlers don't need access to the FastAPI request context.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from sqlalchemy import select as sa_select

from app.catalogue.loader import load_catalogue, load_catalogue_from_dict
from app.mapping import load_mapping_from_dict
from app.config import Settings
from app.infrastructure.db.connection import get_sessionmaker
from app.infrastructure.db.repositories.agent_actions import AgentActionRepository
from app.infrastructure.db.repositories.findings import FindingRepository
from app.infrastructure.db.repositories.fr_state import FrStateRepository
from app.infrastructure.db.repositories.runs import RunRepository
from app.infrastructure.db.repositories.scanner_runs import ScannerRunRepository
from app.infrastructure.db.repositories.waivers import WaiverRepository
from app.modules.atomic.access.project_membership.service import ProjectPermission
from app.state.resolver import GAP_STATES
from app.worker.queue import ScanQueue


log = logging.getLogger(__name__)


def _resolve(path_str: str, base: str) -> Path:
    """Resolve a path against `base` (the project root) if relative.

    Agents often pass `./fr-catalog.json` because that's what they see in
    their shell. The server's process cwd usually matches (thanks to the
    `-w "$PWD"` docker run trick), but resolving explicitly avoids any
    ambiguity.
    """
    p = Path(path_str)
    if not p.is_absolute():
        p = Path(base) / p
    return p


@dataclass
class McpDeps:
    """Holds the FastAPI app; properties look up state live at tool-call time.

    Capturing settings/queue at construction time would freeze them before
    the lifespan runs (queue is created in the lifespan, not at app build).
    """
    app: FastAPI

    @property
    def settings(self) -> Settings:
        return self.app.state.settings

    @property
    def scan_queue(self) -> ScanQueue | None:
        return getattr(self.app.state, "scan_queue", None)


async def _discover_dashboard_url() -> str:
    """Discover the host-side dashboard URL by checking docker port mapping.

    Tries `docker port <container> 8000` to find the published port.
    Falls back to http://localhost:8000/frs if discovery fails.
    """
    import asyncio
    import os

    container_id = os.environ.get("HOSTNAME", "")
    if not container_id:
        return "http://localhost:8000/frs"

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "port", container_id, "8000",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0 and stdout:
            line = stdout.decode().strip().split("\n")[0].strip()
            # Parse "0.0.0.0:8742" or "127.0.0.1:8742" or "[::]:8742"
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                host = parts[0].strip("[]")
                port = parts[1]
                if host in ("0.0.0.0", "::"):
                    host = "localhost"
                return f"http://{host}:{port}/frs"
    except (asyncio.TimeoutError, Exception):
        pass

    return "http://localhost:8000/frs"


async def _mcp_user(ctx: Any, session: Any) -> Any | None:
    """Resolve the enabled user behind a per-user MCP bearer credential."""
    import hashlib

    try:
        header = ctx.request_context.request.headers.get("authorization", "")
    except Exception:
        return None
    if not header.startswith("Bearer "):
        return None
    from app.infrastructure.db.models import User

    h = hashlib.sha256(header[7:].encode()).hexdigest()
    return (
        await session.execute(
            sa_select(User).where(
                User.mcp_token_hash == h,
                User.disabled_at.is_(None),
            )
        )
    ).scalars().first()


async def _visible_project(
    session: Any,
    project_id: int,
    permission: ProjectPermission = "view",
) -> Any | None:
    """Resolve one durable, non-hidden project identity."""
    from app.infrastructure.project_access import CURRENT_PROJECT_ACCESS, require_project

    return await require_project(
        session, CURRENT_PROJECT_ACCESS.get(), project_id, permission
    )


async def _visible_run(session: Any, run_id: str) -> Any | None:
    """Resolve a run only through its non-hidden durable project."""
    from app.infrastructure.project_access import CURRENT_PROJECT_ACCESS, require_run

    return await require_run(session, CURRENT_PROJECT_ACCESS.get(), run_id)


async def _lookup_checkout(session: Any, user_id: int, project_id: int) -> str | None:
    """Return only this user's checkout locator for the durable project."""
    from app.infrastructure.db.models import ProjectCheckout

    return (
        await session.execute(
            sa_select(ProjectCheckout.checkout_path).where(
                ProjectCheckout.user_id == user_id,
                ProjectCheckout.project_id == project_id,
            )
        )
    ).scalars().first()


def _project_locator(project: Any) -> str:
    """Return a display/validation locator, never a database identity."""
    return project.local_path or project.github_repo or project.tag


def build_mcp_server(app: FastAPI, deps: McpDeps | None = None) -> FastMCP:
    """Construct the FastMCP server with all 9 tools registered."""
    if deps is None:
        deps = McpDeps(app=app)

    from mcp.server.transport_security import TransportSecuritySettings

    # DNS-rebind host check off: the app middleware already rejects every
    # /mcp request without a valid bearer token, and the check 421s the
    # public domain behind the proxy.
    mcp = FastMCP(
        "assurance-scan",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool()
    async def load_fr_catalog(
        project_id: int,
        fr_catalog_path: str,
    ) -> dict[str, Any]:
        """Validate the FR catalogue. Returns the catalogue's project,
        version, fr_count, and content hash.

        Relative paths are resolved against the visible registered project's
        server-side local checkout.
        """
        async with get_sessionmaker()() as session:
            project = await _visible_project(session, project_id)
            if project is None:
                return {"error": "not_found", "project_id": project_id}
            if project.local_path is None:
                return {"error": "checkout_unavailable", "project_id": project_id}
            catalogue = load_catalogue(
                _resolve(fr_catalog_path, project.local_path),
                project.local_path,
            )
        return {
            "project_id": project_id,
            "project": catalogue.doc.get("project"),
            "catalogue_version": catalogue.doc.get("catalogue_version"),
            "fr_count": len(catalogue.doc.get("frs", [])),
            "content_hash": catalogue.content_hash,
            "path": str(catalogue.path),
        }

    @mcp.tool()
    async def save_catalogue(
        catalogue_json: str,
        project_id: int,
        tag: str = "",
        source_commit: str | None = None,
        source_branch: str | None = None,
    ) -> dict[str, Any]:
        """Validate and store an FR catalogue in the DB. No file write needed.

        Pass the catalogue as a JSON string. The server validates it against
        the v3 schema, computes a content hash, and stores it as a snapshot.
        Subsequent scans for this project_id will use the stored snapshot.

        Capture provenance from the local checkout (git rev-parse HEAD and
        the branch name) and pass source_commit + source_branch — the server
        cannot read the checkout itself on hosted instances.
        """
        import json as _json
        from app.infrastructure.db.connection import get_sessionmaker
        from app.infrastructure.db.repositories.catalogue_snapshots import CatalogueSnapshotRepository
        from app.infrastructure.db.repositories.frs import FrRepository

        try:
            doc = _json.loads(catalogue_json)
        except _json.JSONDecodeError as exc:
            return {"error": "invalid_json", "detail": str(exc)}

        sessionmaker = get_sessionmaker(deps.settings)
        async with sessionmaker() as session:
            project = await _visible_project(session, project_id, "manage")
            if project is None:
                return {"error": "not_found", "project_id": project_id}
            try:
                catalogue = load_catalogue_from_dict(doc, _project_locator(project))
            except Exception as exc:
                return {"error": "validation_failed", "detail": str(exc)}
            snap_repo = CatalogueSnapshotRepository(session)
            fr_repo = FrRepository(session)
            snapshot = await snap_repo.store(
                project_id=project_id,
                catalogue=catalogue.doc,
                catalogue_version=catalogue.doc.get("catalogue_version"),
                tag=tag,
                source_commit=source_commit,
                source_branch=source_branch,
            )
            await fr_repo.bulk_insert_for_snapshot(
                snapshot.id, catalogue.doc.get("frs", []),
            )
            await session.commit()

        return {
            "status": "saved",
            "project_id": project_id,
            "project": catalogue.doc.get("project"),
            "catalogue_version": catalogue.doc.get("catalogue_version"),
            "fr_count": len(catalogue.doc.get("frs", [])),
            "content_hash": catalogue.content_hash,
        }

    @mcp.tool()
    async def save_mapping(
        mapping_json: str,
        project_id: int,
    ) -> dict[str, Any]:
        """Validate and store a compliance mapping in the DB. No file write needed.

        Pass the mapping as a JSON string. The server validates it against
        the mapping schema and stores it. Subsequent scans for this
        project_id will use the stored mapping.
        """
        import json as _json
        from app.infrastructure.db.connection import get_sessionmaker
        from app.infrastructure.db.repositories.compliance_mappings import ComplianceMappingRepository

        try:
            doc = _json.loads(mapping_json)
        except _json.JSONDecodeError as exc:
            return {"error": "invalid_json", "detail": str(exc)}

        sessionmaker = get_sessionmaker(deps.settings)
        async with sessionmaker() as session:
            project = await _visible_project(session, project_id, "manage")
            if project is None:
                return {"error": "not_found", "project_id": project_id}
            try:
                mapping = load_mapping_from_dict(doc, _project_locator(project))
            except Exception as exc:
                return {"error": "validation_failed", "detail": str(exc)}
            repo = ComplianceMappingRepository(session)
            await repo.upsert(
                project_id=project_id,
                content_hash=mapping.content_hash,
                mapping_doc=mapping.doc,
            )
            await session.commit()

        return {
            "status": "saved",
            "project_id": project_id,
            "content_hash": mapping.content_hash,
            "mapping_count": len(mapping.doc.get("mappings", [])),
        }

    @mcp.tool()
    async def start_scan(
        project_id: int,
        fr_catalog_path: str | None = None,
        images: list[str] | None = None,
        urls: list[str] | None = None,
        uploads: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start a scan. Returns run_id immediately; scan runs async.

        The registered project must have an available server-side local_path.
        If the catalogue was saved via `save_catalogue`, the server uses the
        DB snapshot; otherwise it reads `fr-catalog.json` from that checkout.
        """
        if deps.scan_queue is None:
            return {"error": "queue_not_initialized"}

        async with get_sessionmaker()() as session:
            project = await _visible_project(session, project_id, "upload")
            if project is None:
                return {"error": "not_found", "project_id": project_id}
            if project.local_path is None or not Path(project.local_path).is_dir():
                return {"error": "checkout_unavailable", "project_id": project_id}
            local_path = project.local_path
            if fr_catalog_path:
                resolved_catalogue = _resolve(fr_catalog_path, local_path)
            else:
                resolved_catalogue = Path(local_path) / "fr-catalog.json"
            options: dict[str, Any] = {"fr_catalog_path": str(resolved_catalogue)}
            if images:
                options["images"] = images
            if urls:
                options["urls"] = urls
            if uploads:
                options["uploads"] = uploads
            run_id = deps.scan_queue.enqueue(
                project_id=project_id,
                local_path=local_path,
                options=options,
            )
            runs = RunRepository(session)
            run = await runs.create(
                run_id=run_id,
                project_id=project_id,
                origin="server",
                options_json=json.dumps(options),
            )
            run.repository_full_name_at_scan = project.github_repo
            actions = AgentActionRepository(session)
            await actions.record(
                action_kind="start_scan",
                actor="mcp",
                project_id=project_id,
                run_id=run_id,
                payload=options,
            )
            await session.commit()

        return {"run_id": run_id, "project_id": project_id, "status": "queued"}

    @mcp.tool()
    async def get_scan_status(run_id: str) -> dict[str, Any]:
        """Poll a scan: state, scanner outcomes, error if any."""
        async with get_sessionmaker()() as session:
            scanner_runs_repo = ScannerRunRepository(session)
            run = await _visible_run(session, run_id)
            if run is None:
                return {"error": "not_found", "run_id": run_id}

            scanner_rows = await scanner_runs_repo.list_for_run(run_id)
            return {
                "run_id": run.run_id,
                "project_id": run.project_id,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
                "scanners": [
                    {
                        "kind": r.scanner_kind,
                        "status": r.status,
                        "error_message": r.error_message,
                    }
                    for r in scanner_rows
                ],
            }

    @mcp.tool()
    async def cancel_scan(run_id: str) -> dict[str, Any]:
        """Cancel a running scan. Idempotent."""
        async with get_sessionmaker()() as session:
            runs = RunRepository(session)
            from app.infrastructure.project_access import CURRENT_PROJECT_ACCESS, require_run

            run = await require_run(
                session, CURRENT_PROJECT_ACCESS.get(), run_id, "manage"
            )
            if run is None:
                return {"error": "not_found", "run_id": run_id}
            if run.status in ("completed", "failed", "cancelled"):
                return {"run_id": run_id, "status": run.status, "cancelled": False}
            await runs.mark_failed(run_id, "cancelled by user")
            await session.commit()
            return {"run_id": run_id, "status": "cancelled", "cancelled": True}

    @mcp.tool()
    async def list_scans(limit: int = 50) -> dict[str, Any]:
        """List recent runs."""
        from app.infrastructure.db.models import Project, Run

        async with get_sessionmaker()() as session:
            findings_repo = FindingRepository(session)
            from app.infrastructure.project_access import (
                CURRENT_PROJECT_ACCESS,
                run_access_clause,
            )

            rows = (
                await session.execute(
                    sa_select(Run)
                    .join(Project, Project.id == Run.project_id)
                    .where(run_access_clause(CURRENT_PROJECT_ACCESS.get()))
                    .order_by(Run.started_at.desc(), Run.run_id.desc())
                    .limit(limit)
                )
            ).scalars().all()
            scans = []
            for run in rows:
                count = await findings_repo.count_for_run(run.run_id)
                scans.append({
                    "run_id": run.run_id,
                    "project_id": run.project_id,
                    "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "finding_count": count,
                })
            return {"scans": scans}

    @mcp.tool()
    async def get_findings(run_id: str, severity: str | None = None) -> dict[str, Any]:
        """Return the agent-facing findings.json payload for a run."""
        async with get_sessionmaker()() as session:
            run = await _visible_run(session, run_id)
            if run is None:
                return {"error": "not_found", "run_id": run_id}
            if not run.findings_json:
                return {"error": "not_ready", "run_id": run_id, "status": run.status}

            payload = json.loads(run.findings_json)
            if severity:
                payload["findings"] = [
                    f for f in payload.get("findings", [])
                    if f.get("severity") == severity.upper()
                ]
                payload["filtered_total"] = len(payload["findings"])
            return payload

    @mcp.tool()
    async def get_project_findings(
        project_id: int,
        severity: str | None = None,
    ) -> dict[str, Any]:
        """Detailed findings for a project's latest completed scan.

        The durable project_id is the only accepted identity. Returns the full
        findings payload plus the run's repo/branch/commit context.
        """
        from sqlalchemy import select as sa_select

        from app.infrastructure.db.models import Project, Run

        async with get_sessionmaker()() as session:
            project = await _visible_project(session, project_id)
            if project is None:
                return {"error": "not_found", "project_id": project_id}
            from app.infrastructure.project_access import (
                CURRENT_PROJECT_ACCESS,
                run_access_clause,
            )

            run = (
                await session.execute(
                    sa_select(Run)
                    .join(Project, Project.id == Run.project_id)
                    .where(
                        Run.project_id == project_id,
                        run_access_clause(CURRENT_PROJECT_ACCESS.get()),
                        Run.status == "completed",
                        Run.findings_json.isnot(None),
                    )
                    .order_by(Run.started_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if run is None:
                return {
                    "error": "not_found",
                    "project_id": project_id,
                    "hint": "no completed scan for this project — start one via start_scan or Scan now",
                }
            findings_json = run.findings_json
            if findings_json is None:
                return {"error": "not_found", "project_id": project_id}
            payload = json.loads(findings_json)
            payload["run_id"] = run.run_id
            payload["project_id"] = run.project_id
            if severity:
                payload["findings"] = [
                    f for f in payload.get("findings", [])
                    if f.get("severity") == severity.upper()
                ]
                payload["filtered_total"] = len(payload["findings"])
            return payload

    @mcp.tool()
    async def get_gap_analysis(run_id: str) -> dict[str, Any]:
        """Return FRs in 'gapped' states with their reasons."""
        async with get_sessionmaker()() as session:
            if await _visible_run(session, run_id) is None:
                return {"error": "not_found", "run_id": run_id}
            states_repo = FrStateRepository(session)
            rows = await states_repo.list_for_run(run_id)
            gaps = [
                {
                    "fr_id": row.fr_id,
                    "state": row.state,
                    "reason": json.loads(row.reason_json or "{}"),
                }
                for row in rows
                if row.state in GAP_STATES
            ]
            return {"run_id": run_id, "gap_count": len(gaps), "gaps": gaps}

    @mcp.tool()
    async def add_waiver(
        project_id: int,
        fr_id: str,
        reason: str,
        waived_by: str,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a standing waiver for an FR."""
        async with get_sessionmaker()() as session:
            if await _visible_project(session, project_id, "manage") is None:
                return {"error": "not_found", "project_id": project_id}
            waivers_repo = WaiverRepository(session)
            actions = AgentActionRepository(session)
            expires_dt = dt.datetime.fromisoformat(expires_at) if expires_at else None
            waiver = await waivers_repo.create(
                project_id=project_id,
                fr_id=fr_id,
                reason=reason,
                waived_by=waived_by,
                expires_at=expires_dt,
            )
            await actions.record(
                action_kind="add_waiver",
                actor=waived_by,
                project_id=project_id,
                payload={"fr_id": fr_id, "waiver_id": waiver.id, "reason": reason},
            )
            await session.commit()
            return {
                "waiver_id": waiver.id,
                "project_id": project_id,
                "fr_id": fr_id,
                "expires_at": expires_at,
            }

    @mcp.tool()
    async def revoke_waiver(project_id: int, waiver_id: int) -> dict[str, Any]:
        """Revoke a waiver by ID."""
        async with get_sessionmaker()() as session:
            from app.infrastructure.db.models import Waiver
            from app.infrastructure.db.repositories.waivers import WaiverRepository

            if await _visible_project(session, project_id, "manage") is None:
                return {"error": "not_found", "project_id": project_id}
            waiver = await session.get(Waiver, waiver_id)
            if waiver is None or waiver.project_id != project_id:
                return {"error": "not_found", "waiver_id": waiver_id}
            waivers_repo = WaiverRepository(session)
            actions = AgentActionRepository(session)
            ok = await waivers_repo.delete(waiver_id)
            if not ok:
                return {"error": "not_found", "waiver_id": waiver_id}
            await actions.record(
                action_kind="revoke_waiver",
                actor="mcp",
                project_id=project_id,
                payload={"waiver_id": waiver_id},
            )
            await session.commit()
            return {"waiver_id": waiver_id, "project_id": project_id, "revoked": True}

    @mcp.tool()
    async def list_workflows() -> dict[str, Any]:
        """List available agent workflows.

        Each workflow is a templated prompt that walks through one common
        task (e.g. "scan and propose fixes", "close a gap via a unit test").
        Use `get_workflow` to fetch the rendered prompt for a specific name.
        """
        from app.modules.atomic.agent_workflow_catalog import list_workflows as _list
        return {"workflows": _list()}

    @mcp.tool()
    async def get_workflow(
        name: str,
        parameters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a workflow prompt, with `parameters` substituted into {{name}} placeholders.

        If the agent already knows the parameter values from conversation
        context, pass them. Missing parameters stay as placeholders in the
        returned prompt.
        """
        from app.modules.atomic.agent_workflow_catalog import get_workflow as _get
        return _get(name, parameters)

    @mcp.tool()
    async def save_checkout_mapping(
        project_id: int, checkout_path: str, ctx: Any = None
    ) -> dict[str, Any]:
        """Persist where a project lives on this machine, scoped to you.

        Call this once the user confirms the local checkout path (verify the
        folder exists first). bootstrap returns it as checkout_path from then
        on, so the question is never asked twice. Re-call if the path moves.
        """
        from datetime import datetime, timezone

        from app.infrastructure.db.models import ProjectCheckout

        async with get_sessionmaker()() as session:
            user = await _mcp_user(ctx, session)
            if user is None:
                return {"error": "authentication_required"}
            if await _visible_project(session, project_id) is None:
                return {"error": "not_found", "project_id": project_id}
            existing = (
                await session.execute(
                    sa_select(ProjectCheckout).where(
                        ProjectCheckout.user_id == user.id,
                        ProjectCheckout.project_id == project_id,
                    )
                )
            ).scalars().first()
            if existing is not None:
                existing.checkout_path = checkout_path
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(ProjectCheckout(
                    user_id=user.id,
                    project_id=project_id,
                    checkout_path=checkout_path,
                    updated_at=datetime.now(timezone.utc),
                ))
            await session.commit()
        return {
            "status": "saved",
            "project_id": project_id,
            "checkout_path": checkout_path,
        }

    @mcp.tool()
    async def bootstrap(project_id: int, ctx: Any = None) -> dict[str, Any]:
        """Check project state and return step-by-step guidance.

        Call this FIRST in any new session with a visible registered project ID.

        Checks the DB (for catalogues/mappings stored via save_catalogue /
        save_mapping), the filesystem (for legacy ./fr-catalog.json files),
        recent runs for this project, and the dashboard URL. Returns a
        `next_steps` list the agent can follow.

        The server stays deterministic — it doesn't draft catalogues or
        mappings. It tells the agent what to do next so the user doesn't
        have to remember the exact workflow names.
        """
        from pathlib import Path
        from sqlalchemy import select as sa_select
        from app.infrastructure.db.models import (
            CatalogueSnapshot, ComplianceMapping, Run,
        )

        # Check DB first (artefacts saved via MCP), then filesystem (legacy).
        catalogue_in_db = False
        mapping_in_db = False
        catalogue_version: str | None = None
        catalogue_fr_count: int | None = None
        mapping_count: int | None = None
        steps: list[str] = []

        async with get_sessionmaker()() as session:
            user = await _mcp_user(ctx, session)
            if user is None:
                return {"error": "authentication_required"}
            project = await _visible_project(session, project_id)
            if project is None:
                return {"error": "not_found", "project_id": project_id}
            checkout_path = await _lookup_checkout(session, user.id, project_id)
            source_root = checkout_path or project.local_path
            catalogue_path = (
                Path(source_root).resolve() / "fr-catalog.json" if source_root else None
            )
            mapping_path = (
                Path(source_root).resolve() / "fr-compliance-mapping.json"
                if source_root
                else None
            )
            snap_row = (await session.execute(
                sa_select(CatalogueSnapshot)
                .where(CatalogueSnapshot.project_id == project_id)
                .order_by(CatalogueSnapshot.created_at.desc())
                .limit(1)
            )).scalars().first()
            if snap_row:
                catalogue_in_db = True
                _doc = json.loads(snap_row.snapshot_json)
                catalogue_version = _doc.get("catalogue_version")
                catalogue_fr_count = len(_doc.get("frs", []))

            map_row = (await session.execute(
                sa_select(ComplianceMapping)
                .where(ComplianceMapping.project_id == project_id)
                .order_by(ComplianceMapping.loaded_at.desc())
                .limit(1)
            )).scalars().first()
            if map_row:
                mapping_in_db = True
                _mdoc = json.loads(map_row.mapping_doc_json or "{}")
                mapping_count = len(_mdoc.get("mappings", []))

            from app.infrastructure.project_access import (
                CURRENT_PROJECT_ACCESS,
                run_visibility_clause,
            )

            run_row = (await session.execute(
                sa_select(Run)
                .where(
                    Run.project_id == project_id,
                    run_visibility_clause(CURRENT_PROJECT_ACCESS.get()),
                )
                .order_by(Run.started_at.desc())
                .limit(1)
            )).scalars().first()
            latest_run_id = run_row.run_id if run_row else None
            latest_run_status = run_row.status if run_row else None
            latest_run_commit = run_row.commit_sha if run_row else None
            latest_run_branch = run_row.git_branch if run_row else None
            catalogue_commit = snap_row.source_commit_sha if snap_row else None
            catalogue_branch = snap_row.source_branch if snap_row else None

        if checkout_path is None and project.local_path is None:
            steps.append(
                "No local checkout path is known for this GitHub project. If the user "
                "has a local checkout, ask for its path, verify the folder exists, then "
                "call save_checkout_mapping — it is remembered per user, so you only "
                "ask once. If you are already running inside the project folder, save "
                "that path."
            )

        catalogue_on_disk = catalogue_path is not None and catalogue_path.exists()
        mapping_on_disk = mapping_path is not None and mapping_path.exists()
        catalogue_exists = catalogue_in_db or catalogue_on_disk
        mapping_exists = mapping_in_db or mapping_on_disk

        # Provenance mismatch: catalogue authored against a different
        # branch/commit than the latest scan — surface it to the agent.
        provenance_mismatch = bool(
            catalogue_commit
            and latest_run_commit
            and (catalogue_commit != latest_run_commit
                 or (catalogue_branch and latest_run_branch
                     and catalogue_branch != latest_run_branch))
        )
        if provenance_mismatch:
            assert catalogue_commit is not None
            assert latest_run_commit is not None
            steps.append(
                f"Provenance mismatch: the catalogue was authored against "
                f"{catalogue_branch or '?'}@{catalogue_commit[:10]} but the latest scan "
                f"ran on {latest_run_branch or '?'}@{latest_run_commit[:10]}. "
                "Tell the user before proceeding — the catalogue may not describe "
                "the code that was scanned."
            )

        dashboard_url = await _discover_dashboard_url()

        # Build step-by-step guidance
        recommended_workflow: str

        if not catalogue_exists:
            steps.append(
                f"No catalogue found for project {project_id}. Read the codebase, "
                "identify the project's functional capabilities, and draft a v3 "
                "catalogue. Show the user, then call save_catalogue with the "
                "catalogue JSON + this project_id. Do NOT write to disk — "
                "save_catalogue stores it in the DB."
            )
            recommended_workflow = "author-fr-catalogue"
        else:
            if catalogue_in_db:
                steps.append(
                    f"Catalogue already stored in DB ({catalogue_fr_count} FRs, "
                    f"version {catalogue_version}). No load needed."
                )
            else:
                steps.append(
                    "Catalogue exists on disk only. Call save_catalogue with the "
                    "file's contents + this project_id to migrate it into the DB, "
                    "then remove the file from the project folder."
                )
            steps.append(
                f"Call start_scan with project_id={project_id} to run an "
                "initial scan (~90 seconds; first run may take ~3-5 minutes for "
                "scanner DB downloads)."
            )
            if not mapping_exists:
                steps.append(
                    "After the scan completes, draft a compliance mapping: read the "
                    "ASVS pack via `docker exec assurance-scan cat /opt/assurance-scan/"
                    "resources/compliance-packs/asvs-5.0.0.json`, match ASVS rows to FRs, "
                    "then call save_mapping with the mapping JSON + this project_id. "
                    "Do NOT write to disk."
                )
                recommended_workflow = "author-fr-compliance-map"
            else:
                steps.append(
                    f"Mapping stored ({mapping_count} entries). Call get_findings and "
                    "get_gap_analysis on the latest run to see the current state."
                )
                recommended_workflow = "scan-project"

        return {
            "project_id": project_id,
            "dashboard_url": dashboard_url,
            "catalogue_exists": catalogue_exists,
            "catalogue_in_db": catalogue_in_db,
            "catalogue_on_disk": catalogue_on_disk,
            "catalogue_path": str(catalogue_path) if catalogue_path else None,
            "catalogue_version": catalogue_version,
            "catalogue_fr_count": catalogue_fr_count,
            "mapping_exists": mapping_exists,
            "mapping_in_db": mapping_in_db,
            "mapping_on_disk": mapping_on_disk,
            "mapping_path": str(mapping_path) if mapping_path else None,
            "mapping_count": mapping_count,
            "latest_run_id": latest_run_id,
            "latest_run_status": latest_run_status,
            "checkout_path": checkout_path,
            "catalogue_source_commit": catalogue_commit,
            "catalogue_source_branch": catalogue_branch,
            "latest_run_commit": latest_run_commit,
            "latest_run_branch": latest_run_branch,
            "recommended_workflow": recommended_workflow,
            "next_steps": steps,
        }

    return mcp


def mount_mcp_on_app(app: FastAPI, mcp: FastMCP | None = None) -> None:
    """Expose the MCP Streamable HTTP endpoint at /mcp on the FastAPI app."""
    if mcp is None:
        mcp = build_mcp_server(app)

    # Force lazy session-manager creation.
    mcp.streamable_http_app()

    from starlette.routing import Route
    mcp_app = mcp.streamable_http_app()
    endpoint = None
    for r in mcp_app.routes:
        if isinstance(r, Route) and r.path == "/mcp":
            endpoint = r.endpoint
            break
    if endpoint is None:
        raise RuntimeError("FastMCP app has no Route at /mcp")

    app.router.routes.append(Route("/mcp", endpoint=endpoint, methods=["GET", "POST"]))
