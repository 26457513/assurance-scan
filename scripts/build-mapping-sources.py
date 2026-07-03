#!/usr/bin/env python3
"""Build normalized source snapshots for ASVS mapping generation.

Fetches each upstream source (ASVS spec, scanner rule catalogs), normalizes
to a common JSON shape, and writes snapshots under ``data/sources/``.

Snapshots are committed to the repo so mapping generation is deterministic
and works without network access on the maintainer's machine.

Usage:
    python3 scripts/build-mapping-sources.py [--only asvs,semgrep,...]

Each snapshot JSON has the shape::

    {
      "meta": {
        "source": "<url>",
        "fetched_at": "<UTC ISO timestamp>",
        "source_ref": "<commit sha or version tag>",
        "license": "<SPDX identifier>",
        "count": <int>
      },
      "<entries>": [...]
    }

The script is idempotent — re-running overwrites snapshots in place. A diff
of added/removed/changed entry IDs is printed to stdout for reviewer
visibility when refreshing.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import re
import sys
from pathlib import Path

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"

ASVS_REPO = "OWASP/ASVS"
ASVS_TAG = "v5.0.0"
ASVS_RAW_BASE = f"https://raw.githubusercontent.com/{ASVS_REPO}/{ASVS_TAG}/5.0/en"
ASVS_TREE_API = f"https://api.github.com/repos/{ASVS_REPO}/contents/5.0/en?ref={ASVS_TAG}"

# Filename pattern for chapter markdown files (e.g. 0x10-V1-Encoding-and-Sanitization.md).
CHAPTER_FILE_RE = re.compile(r"^0x\w+-(V\d+)-.*\.md$")

# Section header inside a chapter: "## V<chapter>.<section> <Section Name>"
SECTION_HEADER_RE = re.compile(r"^##\s+(V\d+\.\d+)\s+(.+?)\s*$")

# Requirement row inside a section table: | **1.1.1** | description | level |
REQUIREMENT_ROW_RE = re.compile(
    r"^\|\s*\*\*(?P<id>\d+\.\d+\.\d+)\*\*\s*\|\s*(?P<desc>.+?)\s*\|\s*(?P<level>\d)\s*\|$"
)


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_get(url: str) -> bytes:
    if requests is None:
        raise RuntimeError(
            "requests is not installed. Run: pip install -r requirements-mapping.txt"
        )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.content


def _list_asvs_chapter_files() -> list[tuple[str, str]]:
    """Return [(chapter_designation, filename)] for every chapter markdown."""
    raw = _http_get(ASVS_TREE_API)
    items = json.loads(raw)
    out: list[tuple[str, str]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        name = item.get("name", "")
        m = CHAPTER_FILE_RE.match(name)
        if m:
            out.append((m.group(1), name))
    return out


def _parse_asvs_chapter(markdown: str, chapter_filename: str) -> list[dict]:
    """Parse a single ASVS chapter markdown into requirement dicts."""
    requirements: list[dict] = []
    current_section_id: str | None = None
    current_section_name: str | None = None
    for line in io.StringIO(markdown):
        m_section = SECTION_HEADER_RE.match(line)
        if m_section:
            current_section_id = m_section.group(1)  # e.g. "V1.1"
            current_section_name = m_section.group(2).strip()
            continue
        m_req = REQUIREMENT_ROW_RE.match(line)
        if m_req and current_section_id and current_section_name:
            requirements.append(
                {
                    "id": f"v5.0.0-{m_req.group('id')}",  # e.g. "v5.0.0-1.1.1"
                    "chapter": current_section_id.split(".")[0],  # "V1"
                    "section": current_section_id,  # "V1.1"
                    "section_name": current_section_name,
                    "level": int(m_req.group("level")),
                    "description": m_req.group("desc").strip(),
                    "source_file": chapter_filename,
                }
            )
    return requirements


def fetch_asvs() -> dict:
    """Fetch and parse the ASVS 5.0 spec into a normalized JSON snapshot."""
    chapters = _list_asvs_chapter_files()
    if not chapters:
        raise RuntimeError(f"No ASVS chapter files found at {ASVS_TREE_API}")

    all_reqs: list[dict] = []
    for chapter_designation, filename in chapters:
        url = f"{ASVS_RAW_BASE}/{filename}"
        markdown = _http_get(url).decode("utf-8", errors="replace")
        reqs = _parse_asvs_chapter(markdown, filename)
        all_reqs.extend(reqs)
        print(f"  ASVS {chapter_designation}: {len(reqs):3d} requirements ({filename})")

    all_reqs.sort(key=lambda r: tuple(int(p) for p in r["id"].rsplit("-", 1)[1].split(".")))
    return {
        "meta": {
            "source": f"https://github.com/{ASVS_REPO}/tree/{ASVS_TAG}",
            "fetched_at": _utc_now_iso(),
            "source_ref": ASVS_TAG,
            "license": "CC-BY-SA-4.0",
            "count": len(all_reqs),
        },
        "requirements": all_reqs,
    }


def _previous_entry_ids(snapshot_path: Path, entry_key: str, id_field: str = "id") -> set[str]:
    if not snapshot_path.exists():
        return set()
    try:
        data = json.loads(snapshot_path.read_text())
    except Exception:
        return set()
    return {entry.get(id_field, "") for entry in data.get(entry_key, [])}


def _diff_ids(label: str, prev: set[str], curr: set[str]) -> None:
    added = sorted(curr - prev)
    removed = sorted(prev - curr)
    if added:
        print(f"    {label}: added {len(added):3d} new ID(s)")
        for ident in added[:5]:
            print(f"      + {ident}")
        if len(added) > 5:
            print(f"      ... and {len(added) - 5} more")
    if removed:
        print(f"    {label}: removed {len(removed):3d} ID(s)")
        for ident in removed[:5]:
            print(f"      - {ident}")
        if len(removed) > 5:
            print(f"      ... and {len(removed) - 5} more")
    if not added and not removed:
        print(f"    {label}: unchanged")


def _write_snapshot(filename: str, payload: dict, entry_key: str, id_field: str = "id") -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    target = SOURCES_DIR / filename
    prev = _previous_entry_ids(target, entry_key, id_field)
    curr = {entry.get(id_field, "") for entry in payload.get(entry_key, [])}
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {target.relative_to(REPO_ROOT)} ({payload['meta']['count']} entries)")
    _diff_ids(filename, prev, curr)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

FETCHERS = {
    "asvs": ("asvs_requirements.json", "requirements", fetch_asvs),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        default="",
        help="Comma-separated list of sources to fetch (default: all). "
        "Choices: " + ", ".join(FETCHERS.keys()),
    )
    args = ap.parse_args()

    selected = [s.strip() for s in args.only.split(",") if s.strip()] or list(FETCHERS.keys())
    unknown = [s for s in selected if s not in FETCHERS]
    if unknown:
        print(f"ERROR: unknown source(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Choices: {', '.join(FETCHERS.keys())}", file=sys.stderr)
        return 2

    for source in selected:
        print(f"\n== {source} ==")
        out_file, entry_key, fn = FETCHERS[source]
        try:
            payload = fn()
        except Exception as exc:
            print(f"ERROR fetching {source}: {exc}", file=sys.stderr)
            return 1
        _write_snapshot(out_file, payload, entry_key)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
