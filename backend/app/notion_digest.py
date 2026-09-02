"""Standup digest: render project assurance state and push it to a Notion page.

The page is fully repainted each run (existing blocks archived, new ones
appended), so the Notion side stays a dumb snapshot. Blocks are kept to
headings/bullets — no Notion tables, they're fiddly over the API.
"""
from __future__ import annotations

import datetime as dt
import http.client
import json
import logging
import ssl
import urllib.error
from typing import Any

from sqlalchemy import func, select as sa_select

from app.infrastructure.db.connection import get_sessionmaker
from app.infrastructure.db.models import Finding, FrState, Project, Run

log = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content}}]


def _short_branch(name: str, limit: int = 22) -> str:
    """Keep branch names table-friendly: deep paths collapse to
    prefix/…tail, preserving the distinguishing hash suffix."""
    if len(name) <= limit:
        return name
    prefix = name.split("/", 1)[0]
    tail = name.rsplit("/", 1)[-1]
    keep = tail[-10:] if len(tail) > 10 else tail
    return f"{prefix}/…{keep}"


def _days_ago(iso: str | None) -> str:
    if not iso:
        return "?"
    d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    n = max(0, (dt.datetime.now(dt.timezone.utc) - d).days)
    return "today" if n == 0 else (f"{n}d ago")


async def _repo_stats(session, projects: list[tuple[str, str, list[str]]]) -> dict[str, dict[str, Any]]:
    """Never pull repository metadata; uploaded scan evidence is authoritative."""
    del session
    return {
        base: {"error": "GitHub metadata pull is disabled"}
        for base, _full_name, _scan_branches in projects
    }


async def build_digest() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Render the digest blocks + a small summary for the toast."""
    now = dt.datetime.now(dt.timezone.utc)

    from app.config import load_settings

    allowed_orgs = {o.strip().lower() for o in load_settings().notion_orgs.split(",") if o.strip()}

    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            sa_select(Run).where(Run.project_id.in_(
                sa_select(Project.id).where(Project.hidden.is_(False))
            )).order_by(Run.started_at.desc())
        )).scalars().all()
        # runs grouped per project (for PR/branch context) and per
        # (project, branch) — the top table shows one row per branch that
        # has been scanned in the last 7 days.
        recent: dict[int, list[Run]] = {}
        branch_runs: dict[tuple[int, str], list[Run]] = {}
        for run in rows:  # newest first
            recent.setdefault(run.project_id, []).append(run)
            if run.git_branch:
                branch_runs.setdefault((run.project_id, run.git_branch), []).append(run)
        registry = {r.id: r for r in (await session.execute(
            sa_select(Project).where(Project.hidden.is_(False))
        )).scalars().all()}

        def scoped(project_id: int) -> bool:
            reg_row = registry.get(project_id)
            owner = reg_row.github_repo if reg_row is not None and reg_row.github_repo else ""
            org = owner.split("/")[0] if "/" in owner else ""
            return not allowed_orgs or org.lower() in allowed_orgs

        def project_name(project_id: int) -> str:
            project = registry[project_id]
            if project.github_repo:
                return project.github_repo.rsplit("/", 1)[-1]
            if project.local_path:
                return project.local_path.rstrip("/").rsplit("/", 1)[-1]
            return project.tag

        summary = {"projects": 0, "critical": 0, "high": 0, "failed_runs": 0}
        table_rows: list[list[str]] = []
        pr_projects: list[tuple[str, str, list[str]]] = []
        seen_projects: set[int] = set()
        cutoff = now - dt.timedelta(days=7)

        for (project_id, branch), brs in sorted(
                branch_runs.items(),
                key=lambda kv: (kv[0][0], kv[1][0].started_at or now), reverse=True):
            if not scoped(project_id):
                continue
            run, prev = brs[0], (brs[1] if len(brs) > 1 else None)
            started = run.started_at
            if started is not None and started.tzinfo is None:  # sqlite gives naive
                started = started.replace(tzinfo=dt.timezone.utc)
            if started is None or started < cutoff:
                continue  # only branches scanned in the last 7 days
            base = project_name(project_id)
            count_rows = (await session.execute(
                sa_select(Finding.severity, func.count()).where(Finding.run_id == run.run_id)
                .group_by(Finding.severity)
            )).all()
            counts: dict[str, int] = {severity: count for severity, count in count_rows}
            crit, high = counts.get("CRITICAL", 0), counts.get("HIGH", 0)
            summary["critical"] += crit
            summary["high"] += high
            if run.status == "failed":
                summary["failed_runs"] += 1
            if project_id not in seen_projects:
                seen_projects.add(project_id)
                summary["projects"] += 1

            scan_cell = f"{run.started_at.strftime('%d %b %H:%M')} ({run.status})"
            fr_cell = "—"
            if run.catalogue_snapshot_id:
                state_rows = (await session.execute(
                    sa_select(FrState.state, func.count())
                    .where(FrState.run_id == run.run_id).group_by(FrState.state)
                )).all()
                states: dict[str, int] = {state: count for state, count in state_rows}
                ok = sum(states.get(x, 0) for x in ("passed", "accepted", "waived"))
                gaps = sum(states.get(x, 0) for x in ("untested", "pending", "failed", "blocked"))
                fr_cell = f"✓{ok} ✗{gaps}"

            delta = "—"
            if prev is not None:
                prev_total = (await session.execute(
                    sa_select(func.count()).select_from(Finding)
                    .where(Finding.run_id == prev.run_id)
                )).scalar()
                d = sum(counts.values()) - (prev_total or 0)
                delta = ("+" if d > 0 else "") + str(d) if d else "±0"

            table_rows.append([
                base, _short_branch(branch), scan_cell,
                str(crit) if crit else "—", str(high) if high else "—",
                str(counts.get("MEDIUM", 0)), str(counts.get("LOW", 0)),
                delta, fr_cell,
            ])

        for project_id, runs_ in recent.items():
            if not scoped(project_id):
                continue
            reg_row = registry.get(project_id)
            if reg_row is not None and reg_row.github_repo:
                base = project_name(project_id)
                pr_projects.append((base, reg_row.github_repo,
                                    [r.git_branch for r in runs_ if r.git_branch]))

        repo_stats = await _repo_stats(session, pr_projects)
        pr_rows: list[list[str]] = []
        for base, _full, _brs in pr_projects:
            st = repo_stats.get(base, {})
            if "error" in st:
                pr_rows.append([f"{base} — GitHub unavailable ({st['error']})", "", "", "", ""])
                continue
            prs = st.get("prs")
            if isinstance(prs, dict) and "error" in prs:
                note = ("add Pull requests: Read to the org token"
                        if prs["error"] == "permission" else prs["error"])
                pr_rows.append([f"{base} — PRs unavailable ({note})", "", "", "", ""])
            else:
                for pr in prs or []:
                    head = _short_branch(pr.get("head", {}).get("ref", "?"))
                    pr_base = _short_branch(pr.get("base", {}).get("ref", "?"))
                    files = pr.get("changed_files")
                    adds, dels = pr.get("additions"), pr.get("deletions")
                    lines = (f"+{adds} −{dels}" if adds is not None else "—")
                    pr_rows.append([
                        f"#{pr['number']} {pr['title'][:40]}",
                        f"{pr_base} ← {head}",
                        str(files) if files is not None else "—",
                        lines,
                        _days_ago(pr.get("created_at")),
                    ])

    # Commits per day: rows = last 7 days, columns = projects.
    days = [(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=i)).strftime("%a %d")
            for i in range(6, -1, -1)]
    day_counts: dict[str, dict[str, int]] = {d: {} for d in days}
    commit_columns: list[tuple[str, list[str]]] = []  # header, commit dates
    for base, _full, _branches in pr_projects:
        st = repo_stats.get(base, {})
        for branch, dates in sorted((st.get("per_branch") or {}).items(),
                                    key=lambda kv: -len(kv[1])):
            commit_columns.append((f"{base} ({_short_branch(branch)})", [d for d in dates if d]))
    for i, day in enumerate(days):
        key = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=6 - i)).strftime("%Y-%m-%d")
        for header, dates in commit_columns:
            day_counts[day][header] = sum(1 for d in dates if d == key)

    def cells(values: list[str]) -> list[list[dict[str, Any]]]:
        # each Notion table cell is an array of rich-text objects
        return [[{"type": "text", "text": {"content": v}}] for v in values]

    table_header = ["Project", "Branch", "Last scan", "CRIT", "HIGH", "MED", "LOW", "Δ", "FRs"]
    table_block = {"object": "block", "type": "table", "table": {
        "table_width": len(table_header),
        "has_column_header": True,
        "has_row_header": False,
        "children": [
            {"object": "block", "type": "table_row",
             "table_row": {"cells": cells(table_header)}},
            *({"object": "block", "type": "table_row",
               "table_row": {"cells": cells(r)}} for r in table_rows),
        ],
    }}

    def bullets(lines: list[str]) -> list[dict[str, Any]]:
        return [{"object": "block", "type": "bulleted_list_item",
                 "bulleted_list_item": {"rich_text": _text(line)}} for line in lines]

    blocks = [
        {"object": "block", "type": "heading_1",
         "heading_1": {"rich_text": _text("Stand-up digest")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": _text(f"generated {now.strftime('%Y-%m-%d %H:%M UTC')}")}},
        table_block,
        *( [{
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": _text("Commits per day")}},
            {"object": "block", "type": "table", "table": {
                "table_width": 1 + len(commit_columns),
                "has_column_header": True, "has_row_header": True,
                "children": [
                    {"object": "block", "type": "table_row", "table_row": {"cells": cells(
                        ["Day"] + [h for h, _ in commit_columns])}},
                    *({"object": "block", "type": "table_row", "table_row": {"cells": cells(
                        [day] + [str(day_counts[day].get(h, 0)) for h, _ in commit_columns]
                    )}} for day in days),
                ],
            }},
        ] if commit_columns else []),
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": _text("Open PRs")}},
        *([{"object": "block", "type": "table", "table": {
            "table_width": 5, "has_column_header": True, "has_row_header": False,
            "children": [
                {"object": "block", "type": "table_row", "table_row": {"cells": cells(
                    ["PR", "branches", "files", "lines", "opened"])}},
                *({"object": "block", "type": "table_row", "table_row": {"cells": cells(r)}}
                  for r in pr_rows),
            ],
        }}] if pr_rows else [{"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _text("none open")}}]),
    ]
    return blocks, summary


def _request(token: str, method: str, path: str, body: dict | None = None) -> dict:
    """Call the fixed Notion HTTPS origin.

    Accepting only an origin-relative path prevents dynamic URL schemes from
    reaching the transport while retaining the existing stdlib-only client.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    tls_context = ssl.create_default_context()
    # Python >=3.11 plus an explicit default context verifies the Notion
    # certificate and hostname. The audit rule targets legacy Python where
    # HTTPSConnection did not verify certificates by default.
    connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        "api.notion.com", timeout=30, context=tls_context
    )
    try:
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        if response.status >= 400:
            raise urllib.error.HTTPError(
                f"{NOTION_API}{path}",
                response.status,
                response.reason,
                response.headers,
                None,
            )
    finally:
        connection.close()
    return json.loads(raw) if raw else {}


def push_to_notion(token: str, page_id: str, blocks: list[dict[str, Any]]) -> None:
    """Repaint the page: archive existing children, append the new blocks."""
    import time

    def once() -> None:
        children = _request(token, "GET", f"/v1/blocks/{page_id}/children?page_size=100")
        for block in children.get("results", []):
            _request(token, "PATCH", f"/v1/blocks/{block['id']}", {"archived": True})
        # Notion appends in 100-block batches.
        for i in range(0, len(blocks), 100):
            _request(token, "PATCH", f"/v1/blocks/{page_id}/children",
                     {"children": blocks[i:i + 100]})

    try:
        once()
    except (OSError, TimeoutError):  # one retry on transport blips
        time.sleep(2)
        once()


async def post_digest(settings) -> dict[str, Any]:
    if not settings.notion_token or not settings.notion_page_id:
        return {"error": "NOTION_TOKEN / NOTION_PAGE_ID not configured"}
    blocks, summary = await build_digest()
    import asyncio

    await asyncio.to_thread(push_to_notion, settings.notion_token, settings.notion_page_id, blocks)
    return {"status": "posted", **summary, "blocks": len(blocks)}
