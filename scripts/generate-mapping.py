#!/usr/bin/env python3
"""LLM-assisted generator for ``data/asvs_mapping.yaml``.

For each (ASVS chapter × scanner) pair in scope, asks Claude to map the
chapter's requirements to scanner rules, then merges the results into the
canonical YAML.

Usage::

    export ANTHROPIC_API_KEY=...
    python3 scripts/generate-mapping.py \\
        --chapters V1,V2,V13,V14 \\
        --compliance-csv /path/to/Barkley_csv \\
        --output data/asvs_mapping.yaml

Pass ``--merge`` to preserve existing reviewed entries (default behaviour
when the output file already exists). Without ``--merge``, the output is
overwritten.

Pass ``--dry-run`` to print the prompts that would be sent without making
any LLM calls — useful for reviewing prompt quality before spending tokens.

See ``scripts/prompts/asvs-mapping.md`` for the prompt design.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "asvs_mapping.yaml"
DEFAULT_CHAPTERS = ["V1", "V2", "V13", "V14"]
ASVS_VERSION = "5.0.0"

# Chapter × scanner matrix for v1. Scanners without a static catalog
# (syft, osv-scanner, grype, trivy-secret, semgrep) are listed here so the
# generator can emit fallback glob-pattern mappings for them, but no LLM
# call is made — see ``_fallback_mappings_for_uncatalogued``.
CHAPTER_SCANNERS: dict[str, list[str]] = {
    "V1": ["semgrep"],
    "V2": ["semgrep"],
    "V13": ["trivy-config"],
    "V14": ["trivy-vuln", "trivy-secret", "grype", "gitleaks", "syft", "osv-scanner"],
}

# Scanners we have real rule catalogs for. These trigger LLM calls.
CATALOGUED_SCANNERS = {"trivy-config", "trivy-vuln", "gitleaks", "security-headers"}

# Heuristic glob patterns for ASVS sections when a scanner has no static
# catalog. The dashboard matches via fnmatch at scan time. These are
# deliberately permissive — reviewers tighten them during review.
SEMGREP_HEURISTIC_PATTERNS: dict[str, list[str]] = {
    # V1 chapters — keyed by section prefix (e.g. "V1.2")
    "V1.2": ["*.security.*injection*", "*.security.audit.*injection*"],  # Injection Prevention
    "V1.3": ["*.security.*xss*", "*.security.*sanitiz*", "*.security.*escape*"],  # Sanitization
    "V1.4": ["*.security.*overflow*", "*.security.*memory*"],  # Memory/String
    "V1.5": ["*.security.*deserializ*"],  # Safe Deserialization
    # V2 chapters
    "V2.1": ["*.security.*validation*"],  # Input Validation
    "V2.2": ["*.security.*sanitiz*"],  # Sanitization (validation-side)
    "V2.3": ["*.security.*regex*", "*.security.*redos*"],  # Regex / ReDoS
    "V2.4": ["*.security.*upload*", "*.security.*file*"],  # File Upload
    "V2.5": ["*.security.*business*logic*", "*.security.*race*"],  # Business Logic
}

# Fallback mappings for scanners without static catalogs. One glob per
# scanner, broad enough to catch any relevant finding.
UNCATALOGUED_FALLBACKS: dict[str, list[tuple[str, str]]] = {
    # scanner: [(glob_pattern, reasoning)]
    "semgrep": [],  # Per-section heuristics, see SEMGREP_HEURISTIC_PATTERNS
    "grype": [("CVE-*", "Grype matches CVEs from NVD/GHSA. Globbed here pending per-CVE mapping."),
              ("GHSA-*", "Grype also surfaces GitHub Security Advisories.")],
    "osv-scanner": [("CVE-*", "osv-scanner queries OSV.dev which aggregates CVEs."),
                    ("GHSA-*", "osv-scanner also surfaces GitHub Security Advisories.")],
    "trivy-secret": [],  # Deferred — catalog not yet built
    "syft": [],  # SBOM-only scanner, no findings to map
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_asvs_requirements(chapters: list[str], levels: list[int]) -> dict[str, list[dict]]:
    """Return {chapter: [requirement_dicts]} filtered by chapter and level."""
    path = SOURCES_DIR / "asvs_requirements.json"
    data = json.loads(path.read_text())
    out: dict[str, list[dict]] = {c: [] for c in chapters}
    for req in data.get("requirements", []):
        chapter = req.get("chapter", "")
        if chapter not in out:
            continue
        if req.get("level") not in levels:
            continue
        out[chapter].append(req)
    return out


def load_csv_hints(csv_path: Path | None) -> dict[str, str]:
    """Return {asvs_id: hint_text} from the project CSV's 'Automated Scan Tool' column."""
    if csv_path is None or not csv_path.exists():
        return {}
    hints: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        # Skip preamble rows until the header row containing "ASVS ID".
        reader = csv.reader(fh)
        header_idx: dict[str, int] = {}
        for row in reader:
            if not row:
                continue
            if any(cell.strip() == "ASVS ID" for cell in row):
                header_idx = {cell.strip(): i for i, cell in enumerate(row) if cell.strip()}
                break
        if not header_idx:
            return {}
        id_col = header_idx.get("ASVS ID")
        hint_col = header_idx.get("Automated Scan Tool")
        if id_col is None:
            return {}
        for row in reader:
            if not row or len(row) <= max(id_col, hint_col or 0):
                continue
            asvs_id = row[id_col].strip()
            hint = row[hint_col].strip() if hint_col is not None else ""
            if asvs_id and asvs_id.startswith(f"v{ASVS_VERSION}-"):
                hints[asvs_id] = hint
    return hints


def load_scanner_rules(scanner: str) -> list[dict]:
    """Load rule entries for a scanner from data/sources/<scanner>_rules.json.

    Returns empty list if the snapshot doesn't exist.
    """
    path = SOURCES_DIR / f"{scanner.replace('-', '_')}_rules.json"
    if not path.exists():
        # Try the unconverted name.
        path = SOURCES_DIR / f"{scanner}_rules.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data.get("entries", []) or data.get("requirements", []) or []


# ---------------------------------------------------------------------------
# Hash + ID helpers
# ---------------------------------------------------------------------------

def rule_hash(rule: dict) -> str:
    """SHA-256 of the canonical {title, description, severity} JSON tuple."""
    canon = json.dumps(
        {
            "title": str(rule.get("title", "")),
            "description": str(rule.get("description", "")),
            "severity": str(rule.get("severity", "")),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _scanner_rules_by_id(scanner: str) -> dict[str, dict]:
    """Return {rule_id: rule_dict} for fast lookup."""
    out: dict[str, dict] = {}
    for rule in load_scanner_rules(scanner):
        rid = rule.get("id")
        if rid:
            out[rid] = rule
    return out


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You map OWASP ASVS requirements to scanner rules. You receive one ASVS chapter and one scanner's rule catalog at a time. For each ASVS requirement in the chapter, decide which scanner rules verify it (if any) and emit a mapping entry.

Rules of thumb:
- Be CONSERVATIVE. Only mark a mapping as confidence "high" when the rule clearly and directly verifies the requirement. When in doubt, use "medium" or "low" — never "high".
- A rule that finds related-but-different problems is "medium" or "low", not "high". Example: a Semgrep XSS rule is "medium" for an output-encoding requirement (related but not the same), "high" only for an XSS-specific requirement.
- Rules that find generic vulnerabilities (e.g. CVE-* for dependency scanning) are "low" — they signal possible issues but don't directly verify a specific ASVS requirement.
- It's fine to emit zero mappings for a requirement if no rule clearly applies. The requirement will fall back to "manual evidence" in the dashboard.
- rule_id may be an exact ID or a glob pattern (e.g. "DS-0002" or "python.security.injection.*"). Globs match via fnmatch at scan time.
- For each mapping, include a one-sentence "reasoning" explaining why the rule covers the requirement. Reviewers rely on this.

The output is strict JSON, no markdown fences, schema:
{
  "mappings": [
    {
      "asvs_id": "v5.0.0-1.2.4",
      "rule_id": "python.django.security.injection.sql.*",
      "confidence": "high" | "medium" | "low",
      "reasoning": "...",
      "csv_hint_agreement": "agree" | "modified" | "rejected" | "no_hint"
    }
  ]
}

"csv_hint_agreement" captures your relationship to the project CSV's "Automated Scan Tool" hint (when provided):
- "agree"   — you endorse the CSV's claim that this scanner covers this row
- "modified" — CSV suggested this scanner, you mapped it but with caveats
- "rejected" — CSV suggested this scanner, you disagree (still emit reasoning)
- "no_hint" — CSV had no hint for this row
"""


def build_user_prompt(chapter: str, scanner: str, reqs: list[dict], rules: list[dict], csv_hints: dict[str, str]) -> str:
    """Build the user message for one (chapter, scanner) pair."""
    chapter_title = _chapter_title(chapter)
    lines: list[str] = [
        f"ASVS chapter: {chapter} {chapter_title}",
        f"Scanner: {scanner}",
        "",
        f"ASVS requirements in scope ({len(reqs)} total):",
        "",
    ]
    for req in reqs:
        rid = req["id"]
        level = req.get("level", "?")
        desc = req.get("description", "").strip().replace("\n", " ")
        hint = csv_hints.get(rid, "")
        hint_str = f'\n  CSV hint: "{hint}"' if hint else '\n  CSV hint: (none)'
        lines.append(f"- {rid} [L{level}]: {desc[:300]}{hint_str}")
    lines.append("")
    lines.append(f"Scanner rule catalog ({len(rules)} rules total):")
    lines.append("")
    # Show every rule when there are <=200; otherwise cap to 200 with a note.
    show_rules = rules if len(rules) <= 200 else rules[:200]
    if len(rules) > 200:
        lines.append(f"(showing first 200 of {len(rules)} rules; the rest are in the catalog but omitted here for brevity)")
        lines.append("")
    for rule in show_rules:
        rid = rule.get("id", "?")
        title = rule.get("title", "")
        desc = (rule.get("description", "") or "").strip().replace("\n", " ")
        sev = rule.get("severity", "UNKNOWN")
        title_str = f" — {title}" if title and title != rid else ""
        lines.append(f"- id: {rid}{title_str}")
        lines.append(f"  description: {desc[:250]}")
        lines.append(f"  severity: {sev}")
        lines.append("")
    lines.append("Map each requirement above to zero or more rules from this catalog. Respond with the JSON schema only.")
    return "\n".join(lines)


def _chapter_title(chapter: str) -> str:
    titles = {
        "V1": "Encoding and Sanitization",
        "V2": "Validation and Business Logic",
        "V3": "Web Frontend Security",
        "V4": "API and Web Service",
        "V5": "File Handling",
        "V6": "Authentication",
        "V7": "Session Management",
        "V8": "Authorization",
        "V9": "Self-contained Tokens",
        "V10": "OAuth and OAuth/OpenID Connect",
        "V11": "Cryptography",
        "V12": "Secure Communication",
        "V13": "Configuration",
        "V14": "Data Protection",
        "V15": "Secure Coding and Architecture",
        "V16": "Security Logging and Error Handling",
        "V17": "WebRTC",
    }
    return titles.get(chapter, "")


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def call_claude(system: str, user: str, model: str, dry_run: bool) -> dict:
    """Call Claude with the given prompts and return the parsed JSON response.

    In dry-run mode, prints the prompts and returns an empty response without
    making an API call.
    """
    if dry_run:
        print("\n--- SYSTEM PROMPT ---\n")
        print(system)
        print("\n--- USER PROMPT (first 2000 chars) ---\n")
        print(user[:2000])
        if len(user) > 2000:
            print(f"\n... ({len(user) - 2000} more chars truncated)")
        return {"mappings": []}

    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "anthropic is not installed. Run: pip install -r requirements-mapping.txt"
        ) from exc

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before running the generator."
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Extract text from response
    text = "".join(
        block.text  # type: ignore[attr-defined]
        for block in message.content
        if hasattr(block, "text")
    )
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```\s*$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude response was not valid JSON: {exc}\nRaw:\n{text[:500]}") from exc


# ---------------------------------------------------------------------------
# Fallback mappings for uncatalogued scanners
# ---------------------------------------------------------------------------

def _fallback_mappings_for_uncatalogued(
    chapter: str, scanner: str, reqs: list[dict], csv_hints: dict[str, str]
) -> list[dict]:
    """Produce non-LLM mappings for scanners without a static catalog."""
    mappings: list[dict] = []
    fallbacks = UNCATALOGUED_FALLBACKS.get(scanner, [])

    if scanner == "semgrep":
        # Per-section heuristic patterns.
        for req in reqs:
            section = req.get("section", "")
            patterns = SEMGREP_HEURISTIC_PATTERNS.get(section, [])
            hint = csv_hints.get(req["id"], "")
            agree = "agree" if "semgrep" in hint.lower() else ("no_hint" if not hint else "modified")
            for pattern in patterns:
                mappings.append({
                    "asvs_id": req["id"],
                    "rule_id": pattern,
                    "confidence": "low",
                    "reasoning": f"Heuristic pattern for {section} (Semgrep catalog pending). Replace with specific rule IDs after Semgrep catalog build.",
                    "csv_hint_agreement": agree,
                    "_source": "heuristic",
                })
        return mappings

    # Generic per-scanner fallbacks (grype, osv-scanner, trivy-secret)
    for req in reqs:
        hint = csv_hints.get(req["id"], "")
        scanner_lower = scanner.lower()
        agree = "agree" if scanner_lower in hint.lower() else ("no_hint" if not hint else "modified")
        for pattern, reasoning in fallbacks:
            mappings.append({
                "asvs_id": req["id"],
                "rule_id": pattern,
                "confidence": "low",
                "reasoning": reasoning,
                "csv_hint_agreement": agree,
                "_source": "fallback",
            })
    return mappings


# ---------------------------------------------------------------------------
# Merge into existing YAML
# ---------------------------------------------------------------------------

def _load_existing_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyyaml is required. Run: pip install -r requirements-mapping.txt") from exc
    return yaml.safe_load(path.read_text()) or {}


def _write_yaml(payload: dict, path: Path) -> None:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyyaml is required. Run: pip install -r requirements-mapping.txt") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=120))


def _merge_entries(
    existing: dict[str, Any],
    new_entries_by_asvs: dict[str, dict[str, list[dict]]],
    scanner_rules_cache: dict[str, dict[str, dict]],
) -> dict[str, Any]:
    """Merge new entries into existing requirements structure.

    Preserve existing reviewed entries unless rule_hash mismatches the source.
    """
    existing_reqs = (existing.get("requirements") or {})
    merged_reqs: dict[str, Any] = {}

    # All ASVS IDs we know about (from existing YAML + new entries)
    all_ids = set(existing_reqs.keys()) | set(new_entries_by_asvs.keys())

    for asvs_id in sorted(all_ids):
        existing_entry = existing_reqs.get(asvs_id) or {}
        new_scanners = new_entries_by_asvs.get(asvs_id, {})
        existing_scanners = existing_entry.get("scanners") or {}

        # Combine scanner keys
        all_scanners = sorted(set(existing_scanners.keys()) | set(new_scanners.keys()))
        merged_scanners: dict[str, list[dict]] = {}
        for scanner in all_scanners:
            existing_maps = existing_scanners.get(scanner) or []
            new_maps = new_scanners.get(scanner) or []
            # Index existing by rule_id for fast lookup
            by_rule: dict[str, dict] = {m.get("rule_id", ""): m for m in existing_maps}
            # Add/update from new
            rules_catalog = scanner_rules_cache.get(scanner, {})
            for new_map in new_maps:
                rule_id = new_map["rule_id"]
                catalog_rule = rules_catalog.get(rule_id)
                if catalog_rule is None:
                    # Glob or wildcard — hash is empty
                    new_map["review"] = new_map.get("review") or {
                        "status": "unreviewed",
                    }
                else:
                    new_hash = rule_hash(catalog_rule)
                    new_map["review"] = new_map.get("review") or {
                        "status": "unreviewed",
                    }
                    # If existing entry's hash differs, mark stale
                    existing_map = by_rule.get(rule_id)
                    if existing_map and existing_map.get("review", {}).get("rule_hash") and existing_map["review"]["rule_hash"] != new_hash:
                        new_map["review"] = {**existing_map["review"], "status": "stale", "rule_hash": new_hash}
                    elif existing_map and existing_map.get("review", {}).get("rule_hash"):
                        # Hash matches — preserve existing review state
                        new_map["review"] = existing_map["review"]
                    else:
                        new_map["review"]["rule_hash"] = new_hash
                by_rule[rule_id] = new_map

            # Preserve existing entries that weren't in new (orphan-detection happens in validator)
            merged_scanners[scanner] = list(by_rule.values())

        # Preserve metadata for the requirement
        merged_reqs[asvs_id] = {
            "chapter": existing_entry.get("chapter"),
            "level": existing_entry.get("level"),
            "scanners": merged_scanners,
        }
        # Drop None values
        if merged_reqs[asvs_id]["chapter"] is None:
            merged_reqs[asvs_id].pop("chapter")
        if merged_reqs[asvs_id]["level"] is None:
            merged_reqs[asvs_id].pop("level")

    return {
        "version": existing.get("version", 1),
        "asvs_version": existing.get("asvs_version", ASVS_VERSION),
        "generated_at": _utc_now_iso(),
        "requirements": merged_reqs,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _augment_with_metadata(new_entries: dict[str, dict[str, list[dict]]], reqs_by_chapter: dict[str, list[dict]]) -> None:
    """Add chapter + level metadata to each asvs_id key in new_entries."""
    req_lookup: dict[str, dict] = {}
    for reqs in reqs_by_chapter.values():
        for r in reqs:
            req_lookup[r["id"]] = r
    for asvs_id, scanners in new_entries.items():
        req = req_lookup.get(asvs_id, {})
        # We can't add metadata to the asvs_id key directly (it's the key);
        # metadata is added in _merge_entries from the existing YAML or the reqs lookup.
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chapters", default=",".join(DEFAULT_CHAPTERS),
                    help=f"Comma-separated ASVS chapters (default: {','.join(DEFAULT_CHAPTERS)})")
    ap.add_argument("--levels", default="1,2",
                    help="Comma-separated ASVS levels to include (default: 1,2)")
    ap.add_argument("--compliance-csv", type=Path, default=None,
                    help="Path to project compliance CSV (for the 'Automated Scan Tool' hint column)")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Output YAML path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})")
    ap.add_argument("--merge", action="store_true", default=None,
                    help="Preserve existing reviewed entries (default if output exists)")
    ap.add_argument("--no-merge", dest="merge", action="store_false",
                    help="Overwrite the output instead of merging")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print prompts that would be sent without making LLM calls")
    ap.add_argument("--model", default="claude-sonnet-4-6",
                    help="Anthropic model to use (default: claude-sonnet-4-6)")
    args = ap.parse_args()

    chapters = [c.strip().upper() for c in args.chapters.split(",") if c.strip()]
    levels = [int(l.strip()) for l in args.levels.split(",") if l.strip()]
    if args.merge is None:
        args.merge = args.output.exists()

    # Loaders
    reqs_by_chapter = load_asvs_requirements(chapters, levels)
    csv_hints = load_csv_hints(args.compliance_csv)
    print(f"Loaded {sum(len(r) for r in reqs_by_chapter.values())} ASVS requirements across {len(reqs_by_chapter)} chapters", file=sys.stderr)
    print(f"Loaded {len(csv_hints)} CSV hints", file=sys.stderr)

    # Pre-load scanner rule catalogs and build lookup caches
    scanner_rules_cache: dict[str, dict[str, dict]] = {}
    for scanners in CHAPTER_SCANNERS.values():
        for scanner in scanners:
            if scanner not in scanner_rules_cache:
                scanner_rules_cache[scanner] = _scanner_rules_by_id(scanner)
                count = len(scanner_rules_cache[scanner])
                print(f"  scanner {scanner}: {count} rules in catalog", file=sys.stderr)

    # Generate mappings per (chapter × scanner)
    new_entries_by_asvs: dict[str, dict[str, list[dict]]] = {}
    for chapter in chapters:
        reqs = reqs_by_chapter.get(chapter, [])
        if not reqs:
            print(f"\n-- {chapter}: no requirements in scope, skipping --", file=sys.stderr)
            continue
        for scanner in CHAPTER_SCANNERS.get(chapter, []):
            print(f"\n== {chapter} × {scanner} ==", file=sys.stderr)
            if scanner in CATALOGUED_SCANNERS and scanner_rules_cache.get(scanner):
                rules = list(scanner_rules_cache[scanner].values())
                # Skip LLM call if no API key (unless --dry-run, which already skips).
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key and not args.dry_run:
                    print(f"  no ANTHROPIC_API_KEY — skipping LLM call, emitting zero mappings for {scanner}", file=sys.stderr)
                    mappings = []
                else:
                    system = SYSTEM_PROMPT
                    user = build_user_prompt(chapter, scanner, reqs, rules, csv_hints)
                    response = call_claude(system, user, args.model, args.dry_run)
                    mappings = response.get("mappings", [])
                    print(f"  LLM returned {len(mappings)} mappings", file=sys.stderr)
            else:
                mappings = _fallback_mappings_for_uncatalogued(chapter, scanner, reqs, csv_hints)
                source = "heuristic" if mappings and mappings[0].get("_source") == "heuristic" else "fallback"
                print(f"  no LLM call — emitted {len(mappings)} {source} mappings", file=sys.stderr)

            for m in mappings:
                m.pop("_source", None)
                asvs_id = m["asvs_id"]
                new_entries_by_asvs.setdefault(asvs_id, {}).setdefault(scanner, []).append(m)

    # Merge and write
    if args.dry_run:
        print("\n--dry-run: skipping merge + write", file=sys.stderr)
        return 0

    existing = _load_existing_yaml(args.output) if args.merge else {}
    merged = _merge_entries(existing, new_entries_by_asvs, scanner_rules_cache)

    # Carry chapter + level metadata from the loaded ASVS requirements
    req_lookup: dict[str, dict] = {}
    for reqs in reqs_by_chapter.values():
        for r in reqs:
            req_lookup[r["id"]] = r
    for asvs_id, entry in merged["requirements"].items():
        req = req_lookup.get(asvs_id)
        if req:
            entry.setdefault("chapter", req.get("chapter", ""))
            entry.setdefault("section", req.get("section", ""))
            entry["level"] = f"L{req.get('level', '')}"

    _write_yaml(merged, args.output)
    total_mappings = sum(
        len(maps)
        for entry in merged["requirements"].values()
        for maps in (entry.get("scanners") or {}).values()
    )
    print(f"\nWrote {args.output.relative_to(REPO_ROOT)}: {len(merged['requirements'])} requirements, {total_mappings} total mappings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
