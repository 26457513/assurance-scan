#!/usr/bin/env python3
"""One-off enrichment script — adds curated LLM-style mappings for the three
catalogued scanner pairs (V13×trivy-config, V14×trivy-vuln, V14×gitleaks)
plus V13×gitleaks (added based on security analysis — gitleaks detects
source-side hardcoded secrets, which is squarely V13.3 secrets management).

Mappings were produced by direct analysis (Path B from conversation) instead
of an external LLM call. Each entry includes reasoning + rule_hash per the
schema in scripts/prompts/asvs-mapping.md.

Run once to enrich the baseline YAML::

    python3 scripts/enrich-mapping-llm.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = REPO_ROOT / "data" / "sources"
YAML_PATH = REPO_ROOT / "data" / "asvs_mapping.yaml"


def rule_hash(rule: dict) -> str:
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
    return f"sha256:{hashlib.sha256(canon.encode('utf-8')).hexdigest()}"


def load_rules(scanner: str) -> dict[str, dict]:
    path = SOURCES_DIR / f"{scanner.replace('-', '_')}_rules.json"
    data = json.loads(path.read_text())
    entries = data.get("entries") or data.get("requirements") or []
    return {r.get("id", ""): r for r in entries if r.get("id")}


def load_yaml() -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyyaml required") from exc
    return yaml.safe_load(YAML_PATH.read_text()) or {}


def write_yaml(payload: dict) -> None:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyyaml required") from exc
    YAML_PATH.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=120))


# ---------------------------------------------------------------------------
# Curated mappings (Path B — direct LLM analysis)
# ---------------------------------------------------------------------------

# Each mapping: (asvs_id, scanner, rule_id, confidence, reasoning, csv_hint_agreement)
# confidence follows system prompt: high = direct verification, medium = related,
# low = signal only. csv_hint_agreement values: agree/modified/rejected/no_hint.

CURATED: list[tuple[str, str, str, str, str, str]] = [
    # === V13 × trivy-config (Docker misconfigurations) ===
    # DS-0031 is a HIGH-confidence match for 13.3.1 — directly checks for
    # hardcoded secrets in Dockerfile build-args/envs/files.
    ("v5.0.0-13.3.1", "trivy-config", "DS-0031", "high",
     "DS-0031 directly detects secrets passed via Dockerfile build-args, envs, or copied secret files — exactly what V13.3.1 requires a secrets management solution to prevent.",
     "agree"),
    # DS-0002 (non-root) is MEDIUM for 13.3.2 — least privilege is broader than
    # just user identity, but non-root container execution is one piece of it.
    ("v5.0.0-13.3.2", "trivy-config", "DS-0002", "medium",
     "DS-0002 (Image user should not be 'root') is one concrete implementation of least-privilege operation, which V13.3.2 requires for secret access. Containers running as non-root reduce the blast radius if a secret is leaked.",
     "modified"),
    # DS-0004 (Port 22 exposed) is LOW for 13.4.5 — SSH exposure is one form
    # of unintended monitoring/admin endpoint exposure, but the rule is narrow.
    ("v5.0.0-13.4.5", "trivy-config", "DS-0004", "low",
     "DS-0004 (Port 22 exposed) flags one specific case of unintended endpoint exposure — SSH access into a container. V13.4.5 is broader (any documentation/monitoring endpoints), so this is a partial signal only.",
     "no_hint"),
    # DS-0026 (No HEALTHCHECK) is LOW for 13.4.2 (debug modes disabled) —
    # weak connection: healthcheck isn't strictly about debug mode, but a
    # missing healthcheck suggests insufficient production hardening.
    ("v5.0.0-13.4.2", "trivy-config", "DS-0026", "low",
     "DS-0026 (No HEALTHCHECK defined) is a weak proxy for V13.4.2 production hardening — HEALTHCHECK presence indicates production-ready configuration, but doesn't directly verify debug modes are disabled.",
     "no_hint"),

    # === V13 × gitleaks (added — secrets management) ===
    # Gitleaks is the canonical tool for V13.3.1 (secrets management solution).
    # Use a broad glob to catch all secret-detection rule IDs.
    ("v5.0.0-13.3.1", "gitleaks", "*api-key*", "high",
     "Gitleaks API-key rules directly detect hardcoded API keys in source — a primary form of secret that V13.3.1 requires a secrets management solution to handle.",
     "agree"),
    ("v5.0.0-13.3.1", "gitleaks", "*token*", "high",
     "Gitleaks token rules detect hardcoded OAuth tokens, JWTs, service-account tokens, etc. — all categories V13.3.1 requires be stored in a secrets manager rather than source.",
     "agree"),
    ("v5.0.0-13.3.1", "gitleaks", "*secret*", "high",
     "Gitleaks generic secret rules catch a long tail of hardcoded secret patterns (Stripe, Twilio, Mailgun, etc.) that V13.3.1 requires be managed externally.",
     "agree"),
    ("v5.0.0-13.3.1", "gitleaks", "*private-key*", "high",
     "Gitleaks private-key rules detect hardcoded RSA/EC/PGP private keys — high-sensitivity secrets that must never appear in source per V13.3.1.",
     "agree"),
    ("v5.0.0-13.3.1", "gitleaks", "*password*", "high",
     "Gitleaks password rules detect hardcoded passwords — basic secret-management hygiene required by V13.3.1.",
     "agree"),

    # === V14 × trivy-vuln (CVE wildcards — dependency vulnerabilities) ===
    # Compromised dependencies can undermine ANY data protection control,
    # so CVE-* is a low-confidence signal across all V14 reqs. The dashboard
    # will treat these as "scanner ran with related findings" — not a
    # direct verification.
    ("v5.0.0-14.1.1", "trivy-vuln", "CVE-*", "low",
     "Compromised dependencies can exfiltrate or alter sensitive data identified per V14.1.1. CVE-* is a weak signal — presence of CVEs doesn't directly verify classification, but absence reduces one risk class.",
     "no_hint"),
    ("v5.0.0-14.1.2", "trivy-vuln", "CVE-*", "low",
     "V14.1.2 requires documented protection requirements per data class. Dependency CVEs don't verify documentation, but unpatched high-severity CVEs undermine any protection requirement.",
     "no_hint"),
    ("v5.0.0-14.2.1", "trivy-vuln", "CVE-*", "low",
     "V14.2.1 requires sensitive data only in HTTP body/headers. CVEs in HTTP libraries (e.g. request smuggling) can leak URL params; presence of CVEs is weak signal.",
     "no_hint"),
    ("v5.0.0-14.2.2", "trivy-vuln", "CVE-*", "low",
     "V14.2.2 requires no caching of sensitive data. CVEs in caching layers can leak cached data; weak signal.",
     "no_hint"),
    ("v5.0.0-14.2.3", "trivy-vuln", "CVE-*", "low",
     "V14.2.3 requires no sensitive data to untrusted parties. CVEs in analytics/tracking SDKs could exfiltrate; weak signal.",
     "no_hint"),
    ("v5.0.0-14.2.4", "trivy-vuln", "CVE-*", "low",
     "V14.2.4 requires encryption/integrity controls. Crypto library CVEs directly undermine these; weak-to-medium signal but conservatively marked low.",
     "no_hint"),
    ("v5.0.0-14.3.1", "trivy-vuln", "CVE-*", "low",
     "V14.3.1 requires clearing authenticated data from client storage. Browser/storage library CVEs could leave residue; weak signal.",
     "no_hint"),
    ("v5.0.0-14.3.2", "trivy-vuln", "CVE-*", "low",
     "V14.3.2 requires anti-caching headers. CVEs don't directly verify header presence; weak signal.",
     "no_hint"),
    ("v5.0.0-14.3.3", "trivy-vuln", "CVE-*", "low",
     "V14.3.3 requires no sensitive data in browser storage. CVEs in storage libraries could leak; weak signal.",
     "no_hint"),

    # === V14 × gitleaks (selective — most V14 reqs are about runtime/client-side) ===
    # Only V14.1.1 (sensitive data identification) has a defensible mapping to
    # gitleaks, since gitleaks finds SOME sensitive data (API keys, etc.) but
    # doesn't classify or document it.
    ("v5.0.0-14.1.1", "gitleaks", "*api-key*", "low",
     "Gitleaks API-key rules detect one category of sensitive data (API keys). V14.1.1 requires identification/classification of ALL sensitive data — gitleaks is a partial signal.",
     "no_hint"),
    ("v5.0.0-14.1.1", "gitleaks", "*private-key*", "low",
     "Gitleaks private-key rules detect one category of sensitive data. Partial signal for V14.1.1 classification.",
     "no_hint"),
]


def main() -> int:
    yaml_data = load_yaml()
    requirements = yaml_data.setdefault("requirements", {})

    # Load rule catalogs to compute rule_hash for catalog-matching rules
    trivy_rules = load_rules("trivy-config")
    gitleaks_rules = load_rules("gitleaks")
    trivy_vuln_rules = load_rules("trivy-vuln")
    catalog_cache = {
        "trivy-config": trivy_rules,
        "gitleaks": gitleaks_rules,
        "trivy-vuln": trivy_vuln_rules,
    }

    added = 0
    updated = 0
    for asvs_id, scanner, rule_id, confidence, reasoning, agreement in CURATED:
        req_entry = requirements.setdefault(asvs_id, {"scanners": {}})
        scanners = req_entry.setdefault("scanners", {})
        rule_list = scanners.setdefault(scanner, [])

        # Skip if entry already reviewed-and-matching (preserve human review)
        existing = next((m for m in rule_list if m.get("rule_id") == rule_id), None)
        if existing and existing.get("review", {}).get("status") in ("reviewed", "rejected"):
            continue

        # Compute rule_hash for catalog rules (skip for globs)
        catalog = catalog_cache.get(scanner, {})
        exact_rule = catalog.get(rule_id)
        rhash = rule_hash(exact_rule) if exact_rule else None

        new_entry = {
            "asvs_id": asvs_id,
            "rule_id": rule_id,
            "confidence": confidence,
            "reasoning": reasoning,
            "csv_hint_agreement": agreement,
            "review": {
                "status": "unreviewed",
                **({"rule_hash": rhash} if rhash else {}),
            },
        }

        if existing:
            # Preserve any existing review fields, update the rest
            existing.update(new_entry)
            existing["review"] = {**existing.get("review", {}), **new_entry["review"]}
            if "rule_hash" not in existing["review"] and rhash:
                existing["review"]["rule_hash"] = rhash
            updated += 1
        else:
            rule_list.append(new_entry)
            added += 1

    # Update top-level metadata
    import datetime as _dt
    yaml_data["generated_at"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    yaml_data["enrichment_source"] = "Path B (direct LLM analysis in conversation) for catalogued scanners; heuristic/fallback for uncatalogued"

    write_yaml(yaml_data)
    print(f"Enriched {YAML_PATH.relative_to(REPO_ROOT)}: {added} new mappings, {updated} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
