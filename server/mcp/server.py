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

from server.catalogue import load_catalogue
from server.config import Settings
from server.db.connection import get_sessionmaker
from server.db.repositories.agent_actions import AgentActionRepository
from server.db.repositories.findings import FindingRepository
from server.db.repositories.fr_state import FrStateRepository
from server.db.repositories.runs import RunRepository
from server.db.repositories.scanner_runs import ScannerRunRepository
from server.state.resolver import GAP_STATES
from server.worker.queue import ScanQueue


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


def build_mcp_server(app: FastAPI, deps: McpDeps | None = None) -> FastMCP:
    """Construct the FastMCP server with all 9 tools registered."""
    if deps is None:
        deps = McpDeps(app=app)

    mcp = FastMCP("assurance-scan")

    @mcp.tool()
    async def load_fr_catalog(
        fr_catalog_path: str,
    ) -> dict[str, Any]:
        """Validate the FR catalogue. Returns the catalogue's project,
        version, fr_count, and content hash.

        Relative paths are resolved against the server's project root (the
        project folder the server was started against).
        """
        project_path = str(deps.settings.project_root)
        catalogue = load_catalogue(_resolve(fr_catalog_path, project_path), project_path)
        return {
            "project": catalogue.doc.get("project"),
            "catalogue_version": catalogue.doc.get("catalogue_version"),
            "fr_count": len(catalogue.doc.get("frs", [])),
            "content_hash": catalogue.content_hash,
            "path": str(catalogue.path),
        }

    @mcp.tool()
    async def start_scan(
        fr_catalog_path: str | None = None,
        images: list[str] | None = None,
        urls: list[str] | None = None,
        uploads: list[str] | None = None,
    ) -> dict[str, Any]:
        """Start a scan. Returns run_id immediately; scan runs async.

        Defaults `fr_catalog_path` to `<project_root>/fr-catalog.json`.
        Relative paths are resolved against the project root.
        """
        if deps.scan_queue is None:
            return {"error": "queue_not_initialized"}

        project_path = str(deps.settings.project_root)
        resolved_catalogue = (
            _resolve(fr_catalog_path, project_path)
            if fr_catalog_path
            else Path(project_path) / "fr-catalog.json"
        )
        options: dict[str, Any] = {"fr_catalog_path": str(resolved_catalogue)}
        if images:
            options["images"] = images
        if urls:
            options["urls"] = urls
        if uploads:
            options["uploads"] = uploads

        async with get_sessionmaker()() as session:
            run_id = deps.scan_queue.enqueue(project_path=project_path, options=options)
            runs = RunRepository(session)
            await runs.create(
                run_id=run_id,
                project_path=project_path,
                options_json=json.dumps(options),
            )
            actions = AgentActionRepository(session)
            await actions.record(
                action_kind="start_scan",
                actor="mcp",
                project_path=project_path,
                run_id=run_id,
                payload=options,
            )
            await session.commit()

        return {"run_id": run_id, "project_path": project_path, "status": "queued"}

    @mcp.tool()
    async def get_scan_status(run_id: str) -> dict[str, Any]:
        """Poll a scan: state, scanner outcomes, error if any."""
        async with get_sessionmaker()() as session:
            runs = RunRepository(session)
            scanner_runs_repo = ScannerRunRepository(session)
            run = await runs.get(run_id)
            if run is None:
                return {"error": "not_found", "run_id": run_id}

            scanner_rows = await scanner_runs_repo.list_for_run(run_id)
            return {
                "run_id": run.run_id,
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
            run = await runs.get(run_id)
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
        async with get_sessionmaker()() as session:
            runs = RunRepository(session)
            findings_repo = FindingRepository(session)
            rows = await runs.list_recent(limit=limit)
            scans = []
            for run in rows:
                count = await findings_repo.count_for_run(run.run_id)
                scans.append({
                    "run_id": run.run_id,
                    "project_path": run.project_path,
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
            runs = RunRepository(session)
            run = await runs.get(run_id)
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
    async def get_gap_analysis(run_id: str) -> dict[str, Any]:
        """Return FRs in 'gapped' states with their reasons."""
        async with get_sessionmaker()() as session:
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
        fr_id: str,
        reason: str,
        waived_by: str,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a standing waiver for an FR."""
        project_path = str(deps.settings.project_root)
        async with get_sessionmaker()() as session:
            waivers_repo = WaiverRepository(session)
            actions = AgentActionRepository(session)
            expires_dt = dt.datetime.fromisoformat(expires_at) if expires_at else None
            waiver = await waivers_repo.create(
                project_path=project_path,
                fr_id=fr_id,
                reason=reason,
                waived_by=waived_by,
                expires_at=expires_dt,
            )
            await actions.record(
                action_kind="add_waiver",
                actor=waived_by,
                project_path=project_path,
                payload={"fr_id": fr_id, "waiver_id": waiver.id, "reason": reason},
            )
            await session.commit()
            return {"waiver_id": waiver.id, "fr_id": fr_id, "expires_at": expires_at}

    @mcp.tool()
    async def revoke_waiver(waiver_id: int) -> dict[str, Any]:
        """Revoke a waiver by ID."""
        project_path = str(deps.settings.project_root)
        async with get_sessionmaker()() as session:
            from server.db.repositories.waivers import WaiverRepository
            waivers_repo = WaiverRepository(session)
            actions = AgentActionRepository(session)
            ok = await waivers_repo.delete(waiver_id)
            if not ok:
                return {"error": "not_found", "waiver_id": waiver_id}
            await actions.record(
                action_kind="revoke_waiver",
                actor="mcp",
                project_path=project_path,
                payload={"waiver_id": waiver_id},
            )
            await session.commit()
            return {"waiver_id": waiver_id, "revoked": True}

    @mcp.tool()
    async def list_workflows() -> dict[str, Any]:
        """List available agent workflows.

        Each workflow is a templated prompt that walks through one common
        task (e.g. "scan and propose fixes", "close a gap via a unit test").
        Use `get_workflow` to fetch the rendered prompt for a specific name.
        """
        from server.workflows import list_workflows as _list
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
        from server.workflows import get_workflow as _get
        return _get(name, parameters)

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


# Late import to avoid circularity with build_mcp_server
from server.db.repositories.waivers import WaiverRepository  # noqa: E402

