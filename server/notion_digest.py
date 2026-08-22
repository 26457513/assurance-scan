"""Standup digest: render project assurance state and push it to a Notion page.

The page is fully repainted each run (existing blocks archived, new ones
appended), so the Notion side stays a dumb snapshot. Blocks are kept to
headings/bullets — no Notion tables, they're fiddly over the API.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import func, select as sa_select

from server.db.connection import get_sessionmaker
from server.db.models import Finding, FrState, Project, Run

log = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content}}]


async def build_digest() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Render the digest blocks + a small summary for the toast."""
    import asyncio

    now = dt.datetime.now(dt.timezone.utc)
    blocks: list[dict[str, Any]] = [
        {"object": "block", "type": "heading_1",
         "heading_1": {"rich_text": _text("Assurance Scan — standup digest")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": _text(f"generated {now.strftime('%Y-%m-%d %H:%M UTC')}")}},
    ]

    async with get_sessionmaker()() as session:
        # Latest run per visible project.
        rows = (await session.execute(
            sa_select(Run).where(Run.project_path.in_(
                sa_select(Project.local_path).where(Project.hidden.is_(False))
            )).order_by(Run.started_at.desc())
        )).scalars().all()
        latest: dict[str, Run] = {}
        for run in rows:  # newest first; first hit per project wins
            latest.setdefault(run.project_path, run)
        hidden_names = {r[0] for r in (await session.execute(
            sa_select(Project.local_path).where(Project.hidden.is_(True))
        )).all()}

        summary = {"projects": 0, "critical": 0, "high": 0, "failed_runs": 0}
        for path, run in sorted(latest.items()):
            base = path.replace("github:", "").split("/")[-1]
            if base in hidden_names:
                continue
            sev = dict((await session.execute(
                sa_select(Finding.severity, func.count()).where(Finding.run_id == run.run_id)
                .group_by(Finding.severity)
            )).all())
            crit, high = sev.get("CRITICAL", 0), sev.get("HIGH", 0)
            summary["projects"] += 1
            summary["critical"] += crit
            summary["high"] += high
            if run.status == "failed":
                summary["failed_runs"] += 1

            when = run.started_at.strftime("%d %b %H:%M") if run.started_at else "?"
            line = f"latest scan: {run.git_branch or '?'} · {when} · {run.status}"
            badge = " 🔴" if crit else (" 🟠" if high else "")
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {
                "rich_text": _text(base + badge)}})
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _text(line)}})
            counts = f"findings: {sum(sev.values())} total · CRITICAL {crit} · HIGH {high}"
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": _text(counts)}})

            if run.catalogue_snapshot_id:
                states = dict((await session.execute(
                    sa_select(FrState.state, func.count())
                    .where(FrState.run_id == run.run_id).group_by(FrState.state)
                )).all())
                ok = sum(states.get(s, 0) for s in ("passed", "accepted", "waived"))
                gaps = sum(states.get(s, 0) for s in ("untested", "pending", "failed", "blocked"))
                blocks.append({"object": "block", "type": "bulleted_list_item",
                               "bulleted_list_item": {"rich_text": _text(
                                   f"FR compliance: ✓{ok} · ✗{gaps}")}})

        if summary["projects"] == 0:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {
                "rich_text": _text("No scanned projects to report.")}})

    return blocks, summary


def _request(token: str, method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def push_to_notion(token: str, page_id: str, blocks: list[dict[str, Any]]) -> None:
    """Repaint the page: archive existing children, append the new blocks."""
    import time

    def once() -> None:
        children = _request(token, "GET", f"{NOTION_API}/blocks/{page_id}/children?page_size=100")
        for block in children.get("results", []):
            _request(token, "PATCH", f"{NOTION_API}/blocks/{block['id']}", {"archived": True})
        # Notion appends in 100-block batches.
        for i in range(0, len(blocks), 100):
            _request(token, "PATCH", f"{NOTION_API}/blocks/{page_id}/children",
                     {"children": blocks[i:i + 100]})

    try:
        once()
    except (urllib.error.URLError, TimeoutError):  # one retry on transport blips
        time.sleep(2)
        once()


async def post_digest(settings) -> dict[str, Any]:
    if not settings.notion_token or not settings.notion_page_id:
        return {"error": "NOTION_TOKEN / NOTION_PAGE_ID not configured"}
    blocks, summary = await build_digest()
    import asyncio

    await asyncio.to_thread(push_to_notion, settings.notion_token, settings.notion_page_id, blocks)
    return {"status": "posted", **summary, "blocks": len(blocks)}
