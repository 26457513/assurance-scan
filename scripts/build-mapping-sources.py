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
    if prev == curr and target.exists():
        # Entries unchanged — don't rewrite, just report.
        print(f"  unchanged: {target.relative_to(REPO_ROOT)} ({payload['meta']['count']} entries)")
        return
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {target.relative_to(REPO_ROOT)} ({payload['meta']['count']} entries)")
    _diff_ids(filename, prev, curr)


# ---------------------------------------------------------------------------
# security-headers (in-repo)
# ---------------------------------------------------------------------------

def fetch_security_headers() -> dict:
    """Extract the 6 hardcoded header checks from scripts/security-headers.py."""
    import importlib.util

    sh_path = REPO_ROOT / "scripts" / "security-headers.py"
    spec = importlib.util.spec_from_file_location("security_headers", sh_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {sh_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    entries = []
    for name, spec_dict in sorted(mod.EXPECTED_HEADERS.items()):  # type: ignore[attr-defined]
        entries.append(
            {
                "id": name,
                "title": name,
                "description": spec_dict.get("advice", ""),
                "severity": spec_dict.get("severity", "UNKNOWN"),
                "kind": "missing_header",
            }
        )
    return {
        "meta": {
            "source": "scripts/security-headers.py (in-repo)",
            "fetched_at": _utc_now_iso(),
            "source_ref": "in-repo",
            "license": "project",
            "count": len(entries),
        },
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Gitleaks (TOML)
# ---------------------------------------------------------------------------

GITLEAKS_TOML_URL = (
    "https://raw.githubusercontent.com/gitleaks/gitleaks/master/config/gitleaks.toml"
)


def fetch_gitleaks() -> dict:
    """Fetch and parse gitleaks default rules from the TOML config."""
    try:
        import tomllib  # Python 3.11+
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("tomllib requires Python 3.11+; update your interpreter") from exc

    raw = _http_get(GITLEAKS_TOML_URL)
    data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    entries = []
    for rule in data.get("rules", []) or []:
        entries.append(
            {
                "id": rule.get("id", ""),
                "title": rule.get("id", ""),  # gitleaks rules have no separate title
                "description": rule.get("description", ""),
                "severity": "HIGH",  # gitleaks doesn't ship per-rule severity; treat all as HIGH
                "keywords": rule.get("keywords", []),
            }
        )
    entries.sort(key=lambda r: r["id"])
    return {
        "meta": {
            "source": GITLEAKS_TOML_URL,
            "fetched_at": _utc_now_iso(),
            "source_ref": "master",
            "license": "MIT",
            "count": len(entries),
        },
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Trivy misconfiguration checks (Rego metadata from aquasecurity/trivy-checks)
# ---------------------------------------------------------------------------

TRIVY_CHECKS_REPO = "aquasecurity/trivy-checks"
TRIVY_CHECKS_API_BASE = f"https://api.github.com/repos/{TRIVY_CHECKS_REPO}/contents/checks"
TRIVY_CHECKS_RAW = f"https://raw.githubusercontent.com/{TRIVY_CHECKS_REPO}/main/checks"


def _trivy_api_url(path: str = "") -> str:
    """Build a Trivy checks API URL with the ref query param correctly placed."""
    url = TRIVY_CHECKS_API_BASE
    if path:
        url += f"/{path}"
    return f"{url}?ref=main"

# METADATA block keys we care about (parsed from # comment lines in .rego files).
_TRIVY_METADATA_LINE_RE = re.compile(r"^#\s*(\w[\w\s]*?):\s*(.*)$")


def _list_trivy_families() -> list[str]:
    raw = _http_get(_trivy_api_url())
    items = json.loads(raw)
    if not isinstance(items, list):
        return []
    return [
        item["name"]
        for item in items
        if item.get("type") == "dir" and not item["name"].startswith(".")
    ]


def _list_trivy_family_files(family: str) -> list[str]:
    raw = _http_get(_trivy_api_url(family))
    items = json.loads(raw)
    if not isinstance(items, list):
        return []
    return [
        item["name"]
        for item in items
        if item.get("type") == "file" and item["name"].endswith(".rego")
    ]


def _parse_rego_metadata(rego_text: str) -> dict:
    """Parse the `# METADATA` block at the top of a Trivy Rego file."""
    meta: dict = {"aliases": []}
    in_metadata = False
    for line in io.StringIO(rego_text):
        stripped = line.rstrip()
        if stripped == "# METADATA":
            in_metadata = True
            continue
        if not in_metadata:
            if stripped.startswith("#"):
                continue
            break  # hit the first non-comment line; metadata block is over
        # We're inside the metadata block.
        if not stripped.startswith("#"):
            break  # block ended
        m = _TRIVY_METADATA_LINE_RE.match(stripped)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if key == "title":
            meta["title"] = value
        elif key == "description":
            meta["description"] = value
        elif key == "id":
            meta["short_id"] = value  # e.g. "DS-0002"
        elif key == "severity":
            meta["severity"] = value
        elif key == "recommended_action":
            meta["recommended_action"] = value
        elif key == "aliases":
            # next non-empty `- ` lines belong to aliases; handled by a simple
            # lookahead in the loop below
            pass
        elif key.startswith("-"):
            meta["aliases"].append(key[1:].strip())
    return meta


def fetch_trivy_config() -> dict:
    """Fetch all Trivy misconfig rules across all families (docker, kubernetes, cloud, ...)."""
    families = _list_trivy_families()
    entries: list[dict] = []
    for family in families:
        rego_files = _list_trivy_family_files(family)
        for rego_file in rego_files:
            url = f"{TRIVY_CHECKS_RAW}/{family}/{rego_file}"
            try:
                rego_text = _http_get(url).decode("utf-8", errors="replace")
            except Exception as exc:
                print(f"    WARN: failed to fetch {family}/{rego_file}: {exc}", file=sys.stderr)
                continue
            meta = _parse_rego_metadata(rego_text)
            if not meta.get("short_id"):
                # Rego file without a custom.id — skip (likely a helper module, not a check).
                continue
            entries.append(
                {
                    "id": meta.get("short_id", rego_file.removesuffix(".rego")),
                    "aliases": meta.get("aliases", []),
                    "title": meta.get("title", ""),
                    "description": meta.get("description", ""),
                    "severity": meta.get("severity", "UNKNOWN"),
                    "recommended_action": meta.get("recommended_action", ""),
                    "family": family,
                }
            )
        print(f"  trivy-config/{family}: {len([e for e in entries if e['family'] == family])} rules")
    entries.sort(key=lambda r: (r["family"], r["id"]))
    return {
        "meta": {
            "source": f"https://github.com/{TRIVY_CHECKS_REPO}/tree/main/checks",
            "fetched_at": _utc_now_iso(),
            "source_ref": "main",
            "license": "Apache-2.0",
            "count": len(entries),
        },
        "entries": entries,
    }


def fetch_trivy_vuln() -> dict:
    """Trivy vuln findings are CVE IDs from external feeds — no static catalog.

    Emit a single wildcard entry that the mapping can glob against as `CVE-*`.
    """
    return {
        "meta": {
            "source": "NVD + GitHub Advisories (via Trivy)",
            "fetched_at": _utc_now_iso(),
            "source_ref": "external",
            "license": "external",
            "count": 1,
        },
        "entries": [
            {
                "id": "CVE-*",
                "title": "Any CVE discovered by Trivy dependency scanning",
                "description": (
                    "Trivy vulnerabilities are CVE IDs sourced from NVD and GitHub "
                    "Advisories at scan time. There is no static rule catalog — map "
                    "ASVS requirements to this entry with the glob 'CVE-*'."
                ),
                "severity": "VARIES",
                "family": "vulnerability",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Semgrep rules
# ---------------------------------------------------------------------------
#
# The original semgrep-old/rules-owasp-asvs repo has been gutted (only LICENSE,
# README, and cheatsheet-asvs-mapping.md remain — no rule YAML files). The
# community rules live at semgrep/semgrep-rules (4000+ rules organised by
# language). Scraping all of those and filtering to ASVS-relevant rules is a
# curation effort that is deferred to a follow-up task (see plan §1.1, Phase
# 1.1c).
#
# For v1, the mapping generator (Phase 1.2) will rely on:
#   1. The ASVS section name + description (already in asvs_requirements.json)
#   2. The Barkley CSV's "Automated Scan Tool" hint column
#   3. The LLM's knowledge of common Semgrep rule namespaces
#      (e.g. python.django.security.injection.sql.* for SQL injection rows)
#
# This is sufficient for v1 because Semgrep rule IDs are semantically named
# and the LLM can suggest glob patterns that will match real rules at scan
# time without us needing to enumerate the full rule catalog up front.
#
# To re-enable enumeration in a future iteration:
#   - Pull from semgrep/semgrep-rules (default branch: develop)
#   - Filter to security-affecting rules via metadata.confidence/impact/owasp
#   - Or query the Semgrep Registry API once one is documented


def fetch_semgrep_asvs() -> dict:
    """Placeholder for Semgrep ASVS-mapped rules.

    See module docstring above for why this is intentionally empty for v1.
    Mapping generation will rely on ASVS section names + CSV hints + LLM
    knowledge of Semgrep rule namespaces.
    """
    return {
        "meta": {
            "source": "https://github.com/semgrep/semgrep-rules",
            "fetched_at": _utc_now_iso(),
            "source_ref": "deferred",
            "license": "Semgrep Rules License",
            "count": 0,
            "note": (
                "Semgrep rule enumeration deferred for v1. The mapping "
                "generator will rely on ASVS section names + CSV hints + LLM "
                "knowledge of common Semgrep rule namespaces. See source code "
                "comment in build-mapping-sources.py for details."
            ),
        },
        "entries": [],
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

FETCHERS = {
    "asvs": ("asvs_requirements.json", "requirements", fetch_asvs),
    "security-headers": ("security_headers_rules.json", "entries", fetch_security_headers),
    "gitleaks": ("gitleaks_rules.json", "entries", fetch_gitleaks),
    "trivy-config": ("trivy_config_rules.json", "entries", fetch_trivy_config),
    "trivy-vuln": ("trivy_vuln_rules.json", "entries", fetch_trivy_vuln),
    "semgrep-asvs": ("semgrep_asvs_rules.json", "entries", fetch_semgrep_asvs),
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
