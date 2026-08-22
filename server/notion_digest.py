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


SEV_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
BAR_CHARS = {"CRITICAL": "█", "HIGH": "▓", "MEDIUM": "▒", "LOW": "░", "UNKNOWN": "·"}
BAR_WIDTH = 32


def _bar(counts: dict[str, int]) -> str:
    """Proportional stacked bar: shading gets lighter as severity drops."""
    total = sum(counts.values())
    if total == 0:
        return ""
    out = []
    remaining = BAR_WIDTH
    for i, sev in enumerate(SEV_ORDER):
        n = counts.get(sev, 0)
        if n == 0:
            continue
        if i == len(SEV_ORDER) - 1 or sum(counts.get(x, 0) for x in SEV_ORDER[i:]) <= remaining:
            w = round(BAR_WIDTH * n / total)
        else:
            w = max(1, min(remaining, round(BAR_WIDTH * n / total)))
        out.append(BAR_CHARS[sev] * w)
        remaining -= w
        if remaining <= 0:
            break
    # keep the last segment honest about the width
    line = "".join(out)
    return line[:BAR_WIDTH].ljust(BAR_WIDTH, BAR_CHARS["LOW"])


async def build_digest() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Render the digest blocks + a small summary for the toast."""
    now = dt.datetime.now(dt.timezone.utc)

    async with get_sessionmaker()() as session:
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
        table_rows: list[list[str]] = []
        bars: list[tuple[str, dict[str, int]]] = []

        for path, run in sorted(latest.items()):
            base = path.replace("github:", "").split("/")[-1]
            if base in hidden_names:
                continue
            counts = dict((await session.execute(
                sa_select(Finding.severity, func.count()).where(Finding.run_id == run.run_id)
                .group_by(Finding.severity)
            )).all())
            crit, high = counts.get("CRITICAL", 0), counts.get("HIGH", 0)
            summary["projects"] += 1
            summary["critical"] += crit
            summary["high"] += high
            if run.status == "failed":
                summary["failed_runs"] += 1

            when = run.started_at.strftime("%d %b %H:%M") if run.started_at else "?"
            fr_cell = "—"
            if run.catalogue_snapshot_id:
                states = dict((await session.execute(
                    sa_select(FrState.state, func.count())
                    .where(FrState.run_id == run.run_id).group_by(FrState.state)
                )).all())
                ok = sum(states.get(x, 0) for x in ("passed", "accepted", "waived"))
                gaps = sum(states.get(x, 0) for x in ("untested", "pending", "failed", "blocked"))
                fr_cell = f"✓{ok} ✗{gaps}"

            table_rows.append([
                base,
                f"{run.git_branch or '?'} · {when}",
                run.status,
                str(crit) if crit else "—",
                str(high) if high else "—",
                str(counts.get("MEDIUM", 0)),
                str(counts.get("LOW", 0)),
                fr_cell,
            ])
            bars.append((base, counts))

    def cells(values: list[str]) -> list[list[dict[str, Any]]]:
        # each Notion table cell is an array of rich-text objects
        return [[{"type": "text", "text": {"content": v}}] for v in values]

    header = ["Project", "Latest scan", "Status", "CRIT", "HIGH", "MED", "LOW", "FRs"]
    table_block = {"object": "block", "type": "table", "table": {
        "table_width": len(header),
        "has_column_header": True,
        "has_row_header": False,
        "children": [
            {"object": "block", "type": "table_row",
             "table_row": {"cells": cells(header)}},
            *({"object": "block", "type": "table_row",
               "table_row": {"cells": cells(r)}} for r in table_rows),
        ],
    }}

    chart_lines = []
    for name, counts in bars:
        chart_lines.append(f"{name}  (total {sum(counts.values())})")
        chart_lines.append(f"  {_bar(counts)}")
        chart_lines.append(
            "  " + "  ".join(f"{BAR_CHARS[s]} {counts.get(s, 0)}" for s in SEV_ORDER)
        )
        chart_lines.append("")
    chart_text = "\n".join(chart_lines).rstrip() or "no scans yet"
    chart_block = {"object": "block", "type": "code", "code": {
        "rich_text": _text(chart_text), "language": "plain text"}}

    blocks = [
        {"object": "block", "type": "heading_1",
         "heading_1": {"rich_text": _text("Assurance Scan — standup digest")}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": _text(f"generated {now.strftime('%Y-%m-%d %H:%M UTC')}")}},
        table_block,
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": _text("Severity distribution")}},
        chart_block,
    ]
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
