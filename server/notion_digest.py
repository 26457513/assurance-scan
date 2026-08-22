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


async def _fetch_json(client, url: str, attempts: int = 2):
    import asyncio as _a

    for attempt in range(1, attempts + 1):
        try:
            return await _a.to_thread(client._get, url)
        except urllib.error.HTTPError:
            raise  # 403/404 are not transient
        except Exception:
            if attempt == attempts:
                raise
            await _a.sleep(1.5 * attempt)
    raise RuntimeError("unreachable")


async def _repo_stats(session, projects: list[tuple[str, str, list[str]]]) -> dict[str, dict[str, Any]]:
    """Per-repo GitHub stats via the org token chain: branches, commits in
    the last 7 days, open PRs. One retry per call; errors are classified
    so the digest can say *why* something is missing."""
    from server.config import load_settings
    from server.db.models import Organisation
    from server.github_poller import GitHubClient
    from server.secrets import decrypt

    settings = load_settings()
    tokens: dict[str, str] = {}
    if settings.github_poll_token and settings.github_org:
        tokens[settings.github_org.lower()] = settings.github_poll_token
    if settings.token_encryption_key:
        for row in (await session.execute(sa_select(Organisation))).scalars().all():
            tok = decrypt(row.token_encrypted, settings.token_encryption_key)
            if tok:
                tokens[row.name.lower()] = tok

    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")

    out: dict[str, dict[str, Any]] = {}
    for base, full_name, scan_branches in projects:
        owner = full_name.split("/")[0].lower()
        token = tokens.get(owner)
        if not token:
            out[base] = {"error": "no token for this org"}
            continue
        client = GitHubClient(token)
        stats: dict[str, Any] = {}
        for key, url in (
            ("branches", f"https://api.github.com/repos/{full_name}/branches?per_page=100"),
            ("commits", f"https://api.github.com/repos/{full_name}/commits?since={since}&per_page=100"),
            ("prs", f"https://api.github.com/repos/{full_name}/pulls?state=open&per_page=10"),
        ):
            try:
                stats[key] = await _fetch_json(client, url)
            except urllib.error.HTTPError as exc:
                stats[key] = {"error": "permission" if exc.code == 403 else f"http {exc.code}"}
            except Exception:
                stats[key] = {"error": "network"}

        if isinstance(stats.get("prs"), list):
            for pr in stats["prs"]:
                try:
                    detail = await _fetch_json(
                        client,
                        f"https://api.github.com/repos/{full_name}/pulls/{pr['number']}",
                    )
                    pr["changed_files"] = detail.get("changed_files")
                    pr["additions"] = detail.get("additions")
                    pr["deletions"] = detail.get("deletions")
                except Exception:
                    pass  # diff stats are optional garnish

        # Commits per branch in the window, attributed to where they
        # happened. Repos can carry 100+ stale branches, so we only look at
        # branches this instance has actually scanned — the team-relevant
        # set — fetched concurrently (commit listings are the flakiest
        # call from this box).
        import asyncio as _a

        async def branch_dates(name: str) -> tuple[str, list[str]] | None:
            try:
                cms = await _fetch_json(
                    client,
                    f"https://api.github.com/repos/{full_name}/commits"
                    f"?sha={name}&since={since}&per_page=100",
                    attempts=3,
                )
            except Exception:
                return None
            return name, [
                (c.get("commit", {}).get("author", {}).get("date") or "")[:10]
                for c in cms
            ]

        interesting = list(dict.fromkeys(scan_branches))[:6]
        results = await _a.gather(*(branch_dates(b) for b in interesting))
        per_branch = {n: ds for r in results if r for n, ds in [(r[0], r[1])] if ds}
        if per_branch:
            stats["per_branch"] = per_branch
        out[base] = stats
    return out


async def build_digest() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Render the digest blocks + a small summary for the toast."""
    now = dt.datetime.now(dt.timezone.utc)

    from server.config import load_settings

    allowed_orgs = {o.strip().lower() for o in load_settings().notion_orgs.split(",") if o.strip()}

    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            sa_select(Run).where(Run.project_path.in_(
                sa_select(Project.local_path).where(Project.hidden.is_(False))
            )).order_by(Run.started_at.desc())
        )).scalars().all()
        # runs grouped per project (for PR/branch context) and per
        # (project, branch) — the top table shows one row per branch that
        # has been scanned in the last 7 days.
        recent: dict[str, list[Run]] = {}
        branch_runs: dict[tuple[str, str], list[Run]] = {}
        for run in rows:  # newest first
            recent.setdefault(run.project_path, []).append(run)
            if run.git_branch:
                branch_runs.setdefault((run.project_path, run.git_branch), []).append(run)
        registry = {r.local_path: r for r in (await session.execute(
            sa_select(Project).where(Project.hidden.is_(False))
        )).scalars().all()}
        hidden_names = {p.split("/")[-1] for p in (await session.execute(
            sa_select(Project.local_path).where(Project.hidden.is_(True))
        )).scalars().all()}

        def scoped(path: str) -> bool:
            if path.replace("github:", "").split("/")[-1] in hidden_names:
                return False
            reg_row = registry.get(path)
            owner = (reg_row.github_repo if reg_row is not None and reg_row.github_repo
                     else (path.split(":")[1] if path.startswith("github:") else ""))
            org = owner.split("/")[0] if "/" in owner else ""
            return not allowed_orgs or org.lower() in allowed_orgs

        summary = {"projects": 0, "critical": 0, "high": 0, "failed_runs": 0}
        table_rows: list[list[str]] = []
        pr_projects: list[tuple[str, str, list[str]]] = []
        seen_projects: set[str] = set()
        cutoff = now - dt.timedelta(days=7)

        for (path, branch), brs in sorted(
                branch_runs.items(),
                key=lambda kv: (kv[0][0], kv[1][0].started_at or now), reverse=True):
            if not scoped(path):
                continue
            run, prev = brs[0], (brs[1] if len(brs) > 1 else None)
            started = run.started_at
            if started is not None and started.tzinfo is None:  # sqlite gives naive
                started = started.replace(tzinfo=dt.timezone.utc)
            if started is None or started < cutoff:
                continue  # only branches scanned in the last 7 days
            base = path.replace("github:", "").split("/")[-1]
            counts = dict((await session.execute(
                sa_select(Finding.severity, func.count()).where(Finding.run_id == run.run_id)
                .group_by(Finding.severity)
            )).all())
            crit, high = counts.get("CRITICAL", 0), counts.get("HIGH", 0)
            summary["critical"] += crit
            summary["high"] += high
            if run.status == "failed":
                summary["failed_runs"] += 1
            if path not in seen_projects:
                seen_projects.add(path)
                summary["projects"] += 1

            scan_cell = f"{run.started_at.strftime('%d %b %H:%M')} ({run.status})"
            fr_cell = "—"
            if run.catalogue_snapshot_id:
                states = dict((await session.execute(
                    sa_select(FrState.state, func.count())
                    .where(FrState.run_id == run.run_id).group_by(FrState.state)
                )).all())
                ok = sum(states.get(x, 0) for x in ("passed", "accepted", "waived"))
                gaps = sum(states.get(x, 0) for x in ("untested", "pending", "failed", "blocked"))
                fr_cell = f"✓{ok} ✗{gaps}"

            delta = "—"
            if prev is not None:
                prev_total = (await session.execute(
                    sa_select(func.count()).select_from(Finding)
                    .where(Finding.run_id == prev.run_id)
                )).scalar()
                d = sum(counts.values()) - prev_total
                delta = ("+" if d > 0 else "") + str(d) if d else "±0"

            table_rows.append([
                base, _short_branch(branch), scan_cell,
                str(crit) if crit else "—", str(high) if high else "—",
                str(counts.get("MEDIUM", 0)), str(counts.get("LOW", 0)),
                delta, fr_cell,
            ])

        for path, runs_ in recent.items():
            if not scoped(path):
                continue
            reg_row = registry.get(path)
            if reg_row is not None and reg_row.github_repo:
                base = path.replace("github:", "").split("/")[-1]
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
    day_keys = {(dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(7)}
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

    header = ["Project", "Branch", "Last scan", "CRIT", "HIGH", "MED", "LOW", "Δ", "FRs"]
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

    def bullets(lines: list[str]) -> list[dict[str, Any]]:
        return [{"object": "block", "type": "bulleted_list_item",
                 "bulleted_list_item": {"rich_text": _text(l)}} for l in lines]

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
