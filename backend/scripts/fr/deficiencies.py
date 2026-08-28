#!/usr/bin/env python3
"""Assurance deficiency suggestions for FR/process evidence gaps."""
from __future__ import annotations

from typing import Any
import re


BEHAVIOURAL_TEST_TYPES = {"unit", "integration", "e2e", "load", "test"}


def infer_test_type(req: dict[str, Any]) -> str:
    text = " ".join(
        str(req.get(key, "")).lower()
        for key in ("id", "title", "category", "description")
    )
    words = set(re.findall(r"[a-z0-9]+", text))
    if any(term in text for term in ("tls", "https", "proxy", "caddy", "reverse proxy")):
        return "integration"
    if any(term in words for term in ("session", "auth", "authentication", "authorization", "role", "permission", "tenant", "lockout", "mfa")):
        return "integration"
    if any(term in text for term in ("capacity", "availability", "performance", "denial of service")):
        return "load"
    if any(term in text for term in ("workflow", "lifecycle", "supersession", "ingestion", "upload", "export", "download")):
        return "e2e"
    if any(term in text for term in ("audit", "logging", "metadata", "validation", "version")):
        return "integration"
    return "unit"


def suggested_test(req: dict[str, Any], test_type: str) -> str:
    title = str(req.get("title", req.get("id", "this FR")))
    text = " ".join(
        str(req.get(key, "")).lower()
        for key in ("title", "category", "description")
    )
    words = set(re.findall(r"[a-z0-9]+", text))
    if test_type == "load":
        return f"Add a load/resilience test proving {title} behaves within agreed limits under representative volume and failure conditions."
    if "session" in words:
        return f"Add an integration test proving expired or terminated sessions are rejected and re-authentication is required for {title}."
    if any(term in text for term in ("tls", "proxy", "caddy", "https")):
        return f"Add an integration or deployment smoke test proving HTTPS/proxy behaviour and access logging for {title}."
    if any(term in text for term in ("role", "permission", "tenant", "access control")):
        return f"Add an integration/e2e negative-path test proving unauthorized users cannot perform protected operations for {title}."
    if any(term in text for term in ("audit", "logging")):
        return f"Add an integration test proving the required audit/log event is emitted with correlation metadata for {title}."
    if any(term in text for term in ("ingestion", "upload", "metadata")):
        return f"Add an e2e or integration test proving uploaded/ingested documents preserve required metadata, validation and error handling for {title}."
    return f"Add a {test_type} test proving the core acceptance behaviour for {title}."


def _tbt_compliance_rows(req: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for tbt in req.get("tbts") or []:
        for row in tbt.get("compliance") or []:
            key = (row.get("ruleset", ""), row.get("row", ""))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _has_framework_mapping(req: dict[str, Any]) -> bool:
    return bool(_tbt_compliance_rows(req))


def _has_behavioural_test(req: dict[str, Any]) -> bool:
    for tbt in req.get("tbts") or []:
        if tbt.get("type") in BEHAVIOURAL_TEST_TYPES:
            return True
    return False


def _canonical_fr_rows(fr_catalog: Any) -> list[dict[str, Any]]:
    frs = getattr(fr_catalog, "frs", None)
    if frs is not None:
        tbts_by_fr: dict[str, list[dict[str, Any]]] = {}
        for tbt in getattr(fr_catalog, "tbts", []) or []:
            for fr_id in tbt.get("proves") or []:
                tbts_by_fr.setdefault(fr_id, []).append(tbt)
        rows: list[dict[str, Any]] = []
        for fr in frs:
            req = dict(fr)
            req["status"] = fr.get("lifecycle_status", fr.get("status", "in_scope"))
            req["tbts"] = tbts_by_fr.get(fr.get("id", ""), [])
            req["compliance"] = _tbt_compliance_rows(req)
            rows.append(req)
        return rows
    return []


def collect_assurance_deficiencies(
    fr_catalog: Any | None,
    fr_evidence: dict[str, tuple[str, list[dict]]] | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not fr_catalog:
        return []
    fr_evidence = fr_evidence or {}
    items: list[dict[str, Any]] = []
    for req in _canonical_fr_rows(fr_catalog):
        if req.get("status") not in (None, "in_scope"):
            continue
        fr_id = req.get("id")
        if not fr_id:
            continue
        compliance_mapped = _has_framework_mapping(req)
        if not compliance_mapped:
            continue
        evidence_status, culprits = fr_evidence.get(fr_id, ("missing", []))
        has_test = _has_behavioural_test(req)
        planned_tests = [
            tbt for tbt in (req.get("tbts") or [])
            if tbt.get("lifecycle_status") == "planned" and tbt.get("id")
        ]
        test_type = infer_test_type(req)
        related = []
        for sat in req.get("compliance") or []:
            ruleset = sat.get("ruleset")
            related.append(f"{ruleset} {sat.get('row')}")
        if planned_tests:
            tbt_ids = [tbt.get("id", "") for tbt in planned_tests if tbt.get("id")]
            tbts = ", ".join(tbt_ids[:3])
            items.append({
                "fr_id": fr_id,
                "title": req.get("title", fr_id),
                "category": req.get("category", ""),
                "gap": "test_result_missing",
                "severity": "medium",
                "test_type": planned_tests[0].get("type", test_type),
                "status": "missing",
                "related": related,
                "tbts": tbt_ids,
                "suggestion": (
                    f"Assess or design non-destructive assurance coverage for declared TBT(s) {tbts} "
                    f"covering {req.get('title', fr_id)}, then export observed JUnit/evidence only after the test is run."
                ),
            })
        elif not has_test:
            items.append({
                "fr_id": fr_id,
                "title": req.get("title", fr_id),
                "category": req.get("category", ""),
                "gap": "missing_behavioural_test",
                "severity": "medium",
                "test_type": test_type,
                "status": evidence_status,
                "related": related,
                "suggestion": suggested_test(req, test_type),
            })
        elif evidence_status == "missing":
            items.append({
                "fr_id": fr_id,
                "title": req.get("title", fr_id),
                "category": req.get("category", ""),
                "gap": "test_result_missing",
                "severity": "medium",
                "test_type": test_type,
                "status": evidence_status,
                "related": related,
                "tbts": [tbt.get("id", "") for tbt in req.get("tbts") or [] if tbt.get("id")],
                "suggestion": (
                    f"Run or export the declared {test_type} test evidence for {req.get('title', fr_id)} "
                    "as JUnit XML and pass it with --junit-xml."
                ),
            })
        elif evidence_status == "partial":
            items.append({
                "fr_id": fr_id,
                "title": req.get("title", fr_id),
                "category": req.get("category", ""),
                "gap": "partial_evidence",
                "severity": "medium",
                "test_type": test_type,
                "status": evidence_status,
                "related": related,
                "tbts": [tbt.get("id", "") for tbt in req.get("tbts") or [] if tbt.get("id")],
                "suggestion": (
                    f"Review the partial evidence for {req.get('title', fr_id)} and collect the missing "
                    "test result, manual artifact or approval required by the mapped TBT evidence policy."
                ),
                "culprits": culprits[:3],
            })
        elif evidence_status == "failed":
            items.append({
                "fr_id": fr_id,
                "title": req.get("title", fr_id),
                "category": req.get("category", ""),
                "gap": "evidence_failing",
                "severity": "high",
                "test_type": test_type,
                "status": evidence_status,
                "related": related,
                "tbts": [tbt.get("id", "") for tbt in req.get("tbts") or [] if tbt.get("id")],
                "suggestion": (
                    f"Fix the failing scanner/test evidence for {req.get('title', fr_id)} before treating related compliance rows as met."
                ),
                "culprits": culprits[:3],
            })

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (order.get(item["severity"], 9), item["fr_id"]))
    return items[:limit] if limit else items
