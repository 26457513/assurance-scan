#!/usr/bin/env python3
"""Generate a polished, tabbed HTML dashboard for a scan bundle.

Output: <report_dir>/dashboard.html

Tabs:
  - Overview  : hero scorecard, KPI gauges/donuts, headline charts
  - Scanners  : one card per scanner with description, health, raw-output link
  - Findings  : top CVEs, top secrets, most-vulnerable packages, ignored files
  - Fix Plan  : embedded agent prompt with copy button
"""
from __future__ import annotations

import argparse
import fnmatch
import html
import json
import re
import subprocess
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from artifact_hashing import (
    canonical_json_sha256,
    ensure_sha256_prefix,
    file_sha256,
    write_hash_sidecar,
)
from assurance_claims import build_claim
from assurance_proof_bundles import build_proof_bundle
from dashboard.assets import load_asset, load_dashboard_asset
from graph_projection import graph_projections
from graph_vocabulary import (
    GRAPH_RESPONSIBILITIES,
    normalise_graph_edge_type,
    normalise_graph_node_type,
    graph_edge_responsibility,
)
from scanner_parsers import *  # noqa: F401,F403 — constants, parsers, chart helpers

CSS = load_asset("dashboard.css")
REPO_ROOT = Path(__file__).resolve().parent.parent



# ===========================================================================
# Palette
# ===========================================================================



# ===========================================================================
# Scanner catalogue (descriptions for the Scanners tab)
# ===========================================================================


# ===========================================================================
# Loaders / extractors
# ===========================================================================

def record_report_artifact(report_dir: Path, artifact: Path) -> None:
    manifest_path = report_dir / "evidence-manifest.json"
    if not manifest_path.exists() or not artifact.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
        rel = artifact.relative_to(report_dir)
        digest = file_sha256(artifact)
        write_hash_sidecar(report_dir, artifact)
        files = [item for item in manifest.get("evidence_files", []) if item.get("file") != str(rel)]
        files.append({"file": str(rel), "bytes": artifact.stat().st_size, "sha256": digest})
        manifest["evidence_files"] = sorted(files, key=lambda item: item.get("file", ""))
        manifest_path.write_text(json.dumps(manifest, indent=2))
    except Exception:
        return


def record_core_report_artifacts(report_dir: Path) -> None:
    for rel in (
        "evidence-bundle.json",
        "agent-prompt-plan.json",
        "fr-config-update-proposal.template.json",
        "dashboard-payload.json",
        "dashboard.html",
    ):
        record_report_artifact(report_dir, report_dir / rel)


def report_artifact_entry(report_dir: Path, rel: str) -> dict[str, Any]:
    path = report_dir / rel
    return {
        "path": rel,
        "sha256": file_sha256(path, prefixed=True),
        "bytes": path.stat().st_size if path.exists() else 0,
    }


def write_report_hash_file(report_dir: Path, artifact: Path) -> None:
    write_hash_sidecar(report_dir, artifact)


def remove_report_artifact_manifest_entry(report_dir: Path, rel: str) -> None:
    manifest_path = report_dir / "evidence-manifest.json"
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text())
        manifest["evidence_files"] = [
            item for item in manifest.get("evidence_files", [])
            if item.get("file") != rel
        ]
        manifest_path.write_text(json.dumps(manifest, indent=2))
    except Exception:
        return


def refresh_existing_assurance_claims_and_proofs(report_dir: Path) -> None:
    """Refresh existing claim/proof artifacts after graph commitments change.

    Dashboard regeneration rewrites dashboard-payload.json and graph-manifest.json.
    Existing claims/proof bundles are therefore stale unless they are rebuilt
    against the new commitments. This function intentionally refreshes only
    artifacts already present in the report; it does not invent new claims.
    """
    for claim_path in sorted((report_dir / "claims").glob("*.json")):
        try:
            previous = json.loads(claim_path.read_text())
            claim_type = str(previous.get("claim_type") or "")
            target = str(previous.get("target") or "")
            if not claim_type or not target:
                continue
            claim = build_claim(report_dir, claim_type, target)
            claim_path.write_text(json.dumps(claim, indent=2) + "\n")
            write_hash_sidecar(report_dir, claim_path)
        except Exception:
            continue

    for bundle_path in sorted((report_dir / "proof-bundles").glob("*.json")):
        try:
            previous = json.loads(bundle_path.read_text())
            embedded_claim = previous.get("claim") or {}
            claim_type = str(embedded_claim.get("claim_type") or "")
            target = str(embedded_claim.get("target") or "")
            if not claim_type or not target:
                continue
            claim_path = None
            for candidate in sorted((report_dir / "claims").glob("*.json")):
                try:
                    candidate_claim = json.loads(candidate.read_text())
                except Exception:
                    continue
                if candidate_claim.get("claim_type") == claim_type and candidate_claim.get("target") == target:
                    claim_path = candidate
                    break
            if claim_path is None:
                claim_path = report_dir / "claims" / f"{claim_type}.{target}.json"
                claim = build_claim(report_dir, claim_type, target)
                claim_path.parent.mkdir(parents=True, exist_ok=True)
                claim_path.write_text(json.dumps(claim, indent=2) + "\n")
                write_hash_sidecar(report_dir, claim_path)
            openings = [
                str(opening.get("path"))
                for opening in previous.get("openings") or []
                if opening.get("path")
            ]
            bundle = build_proof_bundle(report_dir, claim_path, openings=openings)
            bundle_path.write_text(json.dumps(bundle, indent=2) + "\n")
            write_hash_sidecar(report_dir, bundle_path)
        except Exception:
            continue


CONFIG_SCHEMA_BY_ROLE = {
    "fr_catalog": "data/schemas/fr-catalog.schema.json",
    "compliance_regime": "data/schemas/compliance-regime.schema.json",
    "compliance_mapping_pack": "data/schemas/compliance-mapping-pack.schema.json",
    "scanner_compliance_mapping_pack": "data/schemas/scanner-compliance-mapping-pack.schema.json",
    "assurance_framework": "data/schemas/assurance-framework.schema.json",
    "assurance_instance": "data/schemas/assurance-instance.schema.json",
}

PLANNING_SCHEMA_BY_ROLE = {
    "project_intake": "data/schemas/project-intake.schema.json",
    "project_config_selection": "data/schemas/project-config-selection.schema.json",
    "blueprint_selection_proposal": "data/schemas/blueprint-selection-proposal.schema.json",
    "blueprint_decision_log": "data/schemas/blueprint-decision-log.schema.json",
    "config_update_proposal": "data/schemas/config-update-proposal.schema.json",
    "resolved_project_planning_contract": "data/schemas/resolved-project-planning-contract.schema.json",
    "project_assurance_contract": "data/schemas/project-assurance-contract.schema.json",
    "project_design_document_manifest": "data/schemas/project-design-document-manifest.schema.json",
    "code_studio_handoff_pack": "data/schemas/code-studio-handoff-pack.schema.json",
    "code_generator_handoff_pack": "data/schemas/code-generator-handoff-pack.schema.json",
}

PLANNING_ARTIFACT_NAME_ROLES = {
    "intake.json": "project_intake",
    "config-selection.json": "project_config_selection",
    "blueprint-proposal.json": "blueprint_selection_proposal",
    "blueprint-decisions.json": "blueprint_decision_log",
    "config-update-proposal.json": "config_update_proposal",
    "resolved-planning-contract.json": "resolved_project_planning_contract",
    "project-assurance-contract.json": "project_assurance_contract",
    "design-document-manifest.json": "project_design_document_manifest",
    "code-studio-handoff.json": "code_studio_handoff_pack",
    "code-generator-handoff.json": "code_generator_handoff_pack",
}


def _as_nonempty_string(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _add_unique_string(target: set[str], value: Any) -> None:
    text = _as_nonempty_string(value)
    if text:
        target.add(text)


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def config_review_summary(raw: Any) -> dict[str, Any]:
    """Summarise review/approval provenance without replacing the raw config hash."""
    review_status_counts: Counter[str] = Counter()
    approval_status_counts: Counter[str] = Counter()
    reviewers: set[str] = set()
    approvers: set[str] = set()
    deciders: set[str] = set()
    signature_refs: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        status = _as_nonempty_string(value.get("review_status"))
        if status:
            review_status_counts[status] += 1
        approval_status = _as_nonempty_string(value.get("approval_status"))
        if approval_status:
            approval_status_counts[approval_status] += 1

        _add_unique_string(reviewers, value.get("reviewed_by"))
        _add_unique_string(approvers, value.get("approved_by"))
        _add_unique_string(deciders, value.get("decided_by"))
        _add_unique_string(signature_refs, value.get("signature_ref"))
        _add_unique_string(signature_refs, value.get("review_signature"))

        for item in value.values():
            visit(item)

    visit(raw)

    summary: dict[str, Any] = {}
    if review_status_counts:
        summary["review_status_counts"] = _counter_dict(review_status_counts)
        summary["reviewed_item_count"] = sum(review_status_counts.values())
    if approval_status_counts:
        summary["approval_status_counts"] = _counter_dict(approval_status_counts)
        summary["approval_item_count"] = sum(approval_status_counts.values())
    if reviewers:
        summary["reviewers"] = sorted(reviewers)
    if approvers:
        summary["approvers"] = sorted(approvers)
    if deciders:
        summary["deciders"] = sorted(deciders)
    if signature_refs:
        summary["signature_refs"] = sorted(signature_refs)
        summary["signed_item_count"] = len(signature_refs)
    return summary


def config_artifact_commitment(path: Path, *, role: str, label: str | None = None) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    digest = file_sha256(path, prefixed=True)
    if not digest:
        return None
    raw = load_json(path) if path.suffix == ".json" else {}
    schema_version = raw.get("schema_version") if isinstance(raw, dict) else None
    commitment = {
        "id": f"config:{role}:{path.stem}:{digest.split(':', 1)[-1][:16]}",
        "role": role,
        "label": label or role,
        "path": str(path),
        "sha256": digest,
        "bytes": path.stat().st_size,
        "schema": CONFIG_SCHEMA_BY_ROLE.get(role, ""),
        "schema_version": schema_version,
        "freeze": {
            "mode": "content_addressed",
            "immutable": True,
        },
    }
    if isinstance(raw, dict):
        for key in ("review_status", "reviewed_by", "pack", "regime", "version", "ruleset", "ruleset_version", "assurance_framework", "project"):
            if raw.get(key):
                commitment[key] = raw[key]
        review_summary = config_review_summary(raw)
        if review_summary:
            commitment["review_summary"] = review_summary
    return commitment


def planning_artifact_commitment(path: Path, *, role: str, label: str | None = None) -> dict[str, Any] | None:
    commitment = config_artifact_commitment(path, role=role, label=label or role)
    if not commitment:
        return None
    commitment["id"] = commitment["id"].replace("config:", "planning:", 1)
    commitment["schema"] = PLANNING_SCHEMA_BY_ROLE.get(role, commitment.get("schema", ""))
    return commitment


def planning_artifact_commitments(
    report_dir: Path,
    *,
    planning_artifact_paths: list[str | Path] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[Path, str, str]] = []
    for raw_path in planning_artifact_paths or []:
        path = Path(raw_path)
        role = PLANNING_ARTIFACT_NAME_ROLES.get(path.name, path.stem.replace("-", "_"))
        candidates.append((path, role, role))
    planning_dir = report_dir / "planning"
    for name, role in PLANNING_ARTIFACT_NAME_ROLES.items():
        for path in (report_dir / name, planning_dir / name):
            if path.exists():
                candidates.append((path, role, role))

    commitments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path, role, label in candidates:
        commitment = planning_artifact_commitment(path, role=role, label=label)
        if not commitment:
            continue
        key = (commitment["role"], commitment["sha256"])
        if key in seen:
            continue
        seen.add(key)
        commitments.append(commitment)
    return sorted(commitments, key=lambda item: (item["role"], item["path"], item["sha256"]))


def accepted_config_commitments(
    *,
    fr_catalog_path: str | Path | None = None,
    compliance_regime_paths: list[str | Path] | None = None,
    compliance_mapping_pack_path: str | Path | None = None,
    scanner_compliance_mapping_paths: list[str] | None = None,
    assurance_framework_path: str | Path | None = None,
    assurance_instance_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[Path, str, str]] = []
    if fr_catalog_path:
        candidates.append((Path(fr_catalog_path), "fr_catalog", "fr_catalog"))
    for idx, raw_path in enumerate(compliance_regime_paths or [], start=1):
        candidates.append((Path(raw_path), "compliance_regime", f"compliance_regime:{idx}"))
    if compliance_mapping_pack_path:
        candidates.append((Path(compliance_mapping_pack_path), "compliance_mapping_pack", "compliance_mapping_pack"))
    if assurance_framework_path:
        candidates.append((Path(assurance_framework_path), "assurance_framework", "assurance_framework"))
    if assurance_instance_path:
        candidates.append((Path(assurance_instance_path), "assurance_instance", "assurance_instance"))
    for idx, raw_path in enumerate(scanner_compliance_mapping_paths or [], start=1):
        path = Path(raw_path)
        if path.is_dir():
            for candidate in sorted(path.rglob("*.json")):
                candidates.append((candidate, "scanner_compliance_mapping_pack", f"scanner_compliance_mapping_pack:{idx}"))
        else:
            candidates.append((path, "scanner_compliance_mapping_pack", f"scanner_compliance_mapping_pack:{idx}"))

    commitments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path, role, label in candidates:
        commitment = config_artifact_commitment(path, role=role, label=label)
        if not commitment:
            continue
        key = (commitment["role"], commitment["sha256"])
        if key in seen:
            continue
        seen.add(key)
        commitments.append(commitment)
    return sorted(commitments, key=lambda item: (item["role"], item["path"], item["sha256"]))


def _regime_slug(regime: str) -> str:
    return str(regime or "").strip().lower()


def _regime_metadata_candidates(regime: str) -> list[Path]:
    slug = _regime_slug(regime)
    if not slug:
        return []
    root = REPO_ROOT / "data" / "compliance-regimes" / slug
    if not root.exists():
        return []
    return sorted(root.glob("*.json"))


def _all_compliance_regime_paths() -> list[Path]:
    root = REPO_ROOT / "data" / "compliance-regimes"
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def _all_assurance_framework_paths() -> list[Path]:
    root = REPO_ROOT / "data" / "assurance-frameworks"
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def _image_data_path(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
        return f"/opt/assurance-scan/{relative.as_posix()}"
    except ValueError:
        return str(path)


def _framework_label(data: dict[str, Any]) -> str:
    framework_id = str(data.get("assurance_framework") or "").strip()
    title = str(data.get("title") or framework_id or "Assurance framework").strip()
    if framework_id == "JSP-453":
        return "JSP-453 Digital Services"
    if framework_id and title and title != framework_id:
        return f"{framework_id} - {re.sub(r'^' + re.escape(framework_id) + r'\s*[-:]?\s*', '', title, flags=re.I)}"
    return title or framework_id or "Assurance framework"


def _process_label(process: dict[str, Any]) -> str:
    title = str(process.get("title") or process.get("id") or "Gated flow").strip()
    return re.sub(r"^JSP\s*453\s+", "", title, flags=re.I)


def _load_assurance_framework_options(active_path: str | Path | None = None) -> list[dict[str, Any]]:
    active_resolved = Path(active_path).resolve() if active_path else None
    active_data = load_json(Path(active_path)) if active_path else {}
    active_framework_id = str(active_data.get("assurance_framework") or "") if isinstance(active_data, dict) else ""
    options: list[dict[str, Any]] = []
    for path in _all_assurance_framework_paths():
        data = load_json(path) or {}
        if not isinstance(data, dict) or not data.get("assurance_framework"):
            continue
        processes = [
            {
                "id": str(process.get("id") or ""),
                "label": _process_label(process),
            }
            for process in data.get("processes") or []
            if process.get("id")
        ]
        options.append({
            "id": str(data.get("assurance_framework") or ""),
            "label": _framework_label(data),
            "title": str(data.get("title") or ""),
            "version": str(data.get("version") or ""),
            "path": str(path),
            "image_path": _image_data_path(path),
            "processes": processes,
            "selected": bool(
                (active_resolved and path.resolve() == active_resolved)
                or (active_framework_id and str(data.get("assurance_framework") or "") == active_framework_id)
            ),
        })
    return sorted(options, key=lambda item: (item.get("label") or "").lower())


def discover_compliance_regime_paths(
    *,
    fr_catalog_path: str | Path | None = None,
    scanner_compliance_packs: list[dict[str, Any]] | None = None,
    include_all_installed: bool = True,
) -> list[Path]:
    used_rulesets: set[str] = set()
    catalog = load_json(Path(fr_catalog_path)) if fr_catalog_path else {}
    if isinstance(catalog, dict):
        for ruleset in (catalog.get("scope") or {}).keys():
            _add_unique_string(used_rulesets, ruleset)
        for fr in catalog.get("frs") or []:
            for row in fr.get("satisfies") or []:
                _add_unique_string(used_rulesets, row.get("ruleset"))
        for tbt in catalog.get("tbts") or []:
            for row in tbt.get("compliance") or []:
                _add_unique_string(used_rulesets, row.get("ruleset"))
        for row in catalog.get("na_rows") or []:
            _add_unique_string(used_rulesets, row.get("ruleset"))

    for pack in scanner_compliance_packs or []:
        compliance = pack.get("compliance") or {}
        _add_unique_string(used_rulesets, compliance.get("ruleset"))
        for mapping in pack.get("mappings") or []:
            for row in mapping.get("ruleset_rows") or []:
                _add_unique_string(used_rulesets, row.get("ruleset"))
            domain = mapping.get("domain")
            if isinstance(domain, dict):
                _add_unique_string(used_rulesets, domain.get("ruleset"))

    paths: list[Path] = _all_compliance_regime_paths() if include_all_installed else []
    for ruleset in sorted(used_rulesets):
        paths.extend(_regime_metadata_candidates(ruleset))
    seen: set[Path] = set()
    unique_paths: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_paths.append(path)
    return unique_paths


CLAIM_CONFIG_REQUIREMENTS = {
    "fr_satisfied": {"fr_catalog"},
    "tbt_satisfied": {"fr_catalog"},
    "compliance_row_satisfied": {"fr_catalog", "compliance_regime"},
    "no_blocking_scanner_evidence": {"scanner_compliance_mapping_pack"},
    "selected_scope_satisfied": {"fr_catalog", "assurance_framework"},
}


def graph_claim_readiness(config_commitments: list[dict[str, Any]]) -> dict[str, Any]:
    committed_roles = {str(item.get("role") or "") for item in config_commitments}
    supported: list[str] = []
    unsupported: list[dict[str, Any]] = []
    for claim, required_roles in CLAIM_CONFIG_REQUIREMENTS.items():
        missing = sorted(role for role in required_roles if role not in committed_roles)
        if missing:
            unsupported.append({
                "claim": claim,
                "missing_config_roles": missing,
            })
        else:
            supported.append(claim)
    return {
        "policy": "claims_require_committed_runtime_config",
        "supported": supported,
        "unsupported": unsupported,
    }


def graph_toolchain(evidence_manifest: dict[str, Any] | None) -> dict[str, Any]:
    evidence_manifest = evidence_manifest or {}
    scanners = []
    tools = evidence_manifest.get("tools") or {}
    health = evidence_manifest.get("scanner_health") or {}
    for name in sorted(set(tools) | set(health)):
        tool = tools.get(name) or {}
        scanner_health = health.get(name) or {}
        scanners.append({
            "name": name,
            "image": str(tool.get("image") or ""),
            "level": tool.get("level", ""),
            "status": str(scanner_health.get("status") or ""),
            "reason": str(scanner_health.get("reason") or ""),
        })
    test_evidence = evidence_manifest.get("test_evidence") or {}
    junit = test_evidence.get("junit") or {}
    test_runners = []
    if junit:
        test_runners.append({
            "name": "junit",
            "format": "junit",
            "status": "observed" if junit.get("present") or junit.get("tests") else "missing",
            "summary": junit,
        })
    return {
        "scanners": scanners,
        "test_runners": test_runners,
    }


def write_graph_manifest(
    report_dir: Path,
    dashboard_payload: dict[str, Any],
    *,
    fr_catalog_path: str | Path | None = None,
    compliance_regime_paths: list[str | Path] | None = None,
    compliance_mapping_pack_path: str | Path | None = None,
    scanner_compliance_mapping_paths: list[str] | None = None,
    assurance_framework_path: str | Path | None = None,
    assurance_instance_path: str | Path | None = None,
    planning_artifact_paths: list[str | Path] | None = None,
    evidence_manifest: dict[str, Any] | None = None,
) -> Path:
    remove_report_artifact_manifest_entry(report_dir, "graph-manifest.json")
    graph = dashboard_payload.get("graph") or {"nodes": [], "edges": []}
    config_commitments = accepted_config_commitments(
        fr_catalog_path=fr_catalog_path,
        compliance_regime_paths=compliance_regime_paths or [],
        compliance_mapping_pack_path=compliance_mapping_pack_path,
        scanner_compliance_mapping_paths=scanner_compliance_mapping_paths or [],
        assurance_framework_path=assurance_framework_path,
        assurance_instance_path=assurance_instance_path,
    )
    accepted_config = {
        "policy": "runtime_config_is_frozen_by_content_hash",
        "commitment_count": len(config_commitments),
        "commitments": config_commitments,
    }
    planning_commitments = planning_artifact_commitments(
        report_dir,
        planning_artifact_paths=planning_artifact_paths,
    )
    planning_artifacts = {
        "policy": "planning_artifacts_are_frozen_by_content_hash",
        "commitment_count": len(planning_commitments),
        "commitments": planning_commitments,
    }
    claim_readiness = graph_claim_readiness(config_commitments)
    toolchain = graph_toolchain(evidence_manifest)
    artifacts = {
        "report": [
            report_artifact_entry(report_dir, "dashboard-payload.json"),
            report_artifact_entry(report_dir, "evidence-bundle.json"),
            report_artifact_entry(report_dir, "evidence-manifest.json"),
            *(
                [report_artifact_entry(report_dir, "project-fr-board-state.json")]
                if (report_dir / "project-fr-board-state.json").exists()
                else []
            ),
        ],
        "config": [
            {
                "path": item["path"],
                "label": item["label"],
                "sha256": item["sha256"],
                "bytes": item["bytes"],
            }
            for item in config_commitments
        ],
        "planning": [
            {
                "path": item["path"],
                "label": item["label"],
                "sha256": item["sha256"],
                "bytes": item["bytes"],
            }
            for item in planning_commitments
        ],
    }
    evidence_files = [
        {
            "path": item.get("file", ""),
            "sha256": ensure_sha256_prefix(str(item.get("sha256", ""))),
            "bytes": item.get("bytes", 0),
        }
        for item in (evidence_manifest or {}).get("evidence_files", [])
        if item.get("file") and item.get("file") != "graph-manifest.json"
    ]
    manifest = {
        "schema_version": 1,
        "mode": "graph_proof_manifest",
        "project": dashboard_payload.get("project", ""),
        "run_id": (dashboard_payload.get("summary") or {}).get("run_id") or (evidence_manifest or {}).get("run_id") or "",
        "generated_at": dashboard_payload.get("generated_at", ""),
        "source_commit": (evidence_manifest or {}).get("git_commit", ""),
        "graph_builder": {
            "name": "assurance-scan.dashboard.graph",
            "version": 1,
            "vocabulary": "data/schemas/defs.schema.json",
        },
        "toolchain": toolchain,
        "graph": {
            "node_count": len(graph.get("nodes") or []),
            "edge_count": len(graph.get("edges") or []),
            "root_hash": canonical_json_sha256(graph),
        },
        "artifacts": artifacts,
        "accepted_config": accepted_config,
        "planning_artifacts": planning_artifacts,
        "evidence_artifacts": evidence_files,
        "claim_readiness": claim_readiness,
        "supported_claims": claim_readiness["supported"],
        "commitments": {
            "dashboard_payload_hash": file_sha256(report_dir / "dashboard-payload.json", prefixed=True),
            "evidence_bundle_hash": file_sha256(report_dir / "evidence-bundle.json", prefixed=True),
            "evidence_manifest_hash": file_sha256(report_dir / "evidence-manifest.json", prefixed=True),
            "accepted_config_hash": canonical_json_sha256(accepted_config),
            "planning_artifacts_hash": canonical_json_sha256(planning_artifacts),
            "graph_root_hash": canonical_json_sha256(graph),
        },
    }
    path = report_dir / "graph-manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    write_report_hash_file(report_dir, path)
    remove_report_artifact_manifest_entry(report_dir, "graph-manifest.json")
    return path


def render_matrix(evidence: dict, ignored: dict, *, include_skipped: bool = True) -> str:
    scanner_health = evidence.get('scanner_health', {})
    findings = evidence.get('findings_summary', {})
    rows = []
    used = set()

    def scanner_row(name: str) -> str:
        health = scanner_health.get(name, {}) or {}
        status = health.get('status', 'SKIPPED')
        info = SCANNERS.get(name, {'title': name, 'level': '-', 'category': '', 'output': ''})
        reason = health.get('reason', 'Not requested')
        fv = scanner_finding_value(name, findings)
        ignored_note = ''
        if name in ignored:
            ii = ignored[name]
            ignored_note = f' <span title="filtered by .scannerignore">-{ii["removed"]}</span>'
        return (
            '<tr>'
            f'<td class="scanner">{html.escape(info.get("title", name))}</td>'
            f'<td class="level">L{html.escape(str(info.get("level", "-")))}</td>'
            f'<td class="status-col">{status_pill(status)}</td>'
            f'<td class="findings-col">{finding_markup(fv)}{ignored_note}</td>'
            f'<td><div class="reason" title="{html.escape(reason)}">{html.escape(reason)}</div></td>'
            f'<td class="evidence-col">{evidence_markup(evidence, name)}</td>'
            '</tr>'
        )



    for label, meta, names in scan_surface_groups():
        present = []
        for name in names:
            if name not in scanner_health:
                continue
            status = (scanner_health.get(name) or {}).get('status', 'SKIPPED')
            if status == 'SKIPPED' and not include_skipped:
                continue
            present.append(name)
        if not present:
            continue
        rows.append(f'<tr class="category-row"><td colspan="6">{html.escape(label)}<span class="category-meta"> · {html.escape(meta)}</span></td></tr>')
        for name in present:
            used.add(name)
            rows.append(scanner_row(name))

    remaining = []
    for name in scanner_health:
        if name in used:
            continue
        status = (scanner_health.get(name) or {}).get('status', 'SKIPPED')
        if status == 'SKIPPED' and not include_skipped:
            continue
        remaining.append(name)
    if remaining:
        rows.append('<tr class="category-row"><td colspan="6">Other<span class="category-meta"> · additional scanner outputs</span></td></tr>')
        for name in remaining:
            rows.append(scanner_row(name))

    if not rows:
        rows.append('<tr><td colspan="6" class="empty-state">No scanner data.</td></tr>')
    return (
        '<table class="matrix"><thead><tr>'
        f'{th("Scanner")}{th("Tier")}{th("Status")}{th("Findings")}{th("Signal")}{th("Evidence")}'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )


def render_severity_panel(sev: dict, assurance: dict) -> str:
    total = sum(sev.values()) or 1
    rows = []
    for label in SEVERITY_ORDER:
        n = sev.get(label, 0)
        w = 0 if not n else max(3, (n / total) * 100)
        rows.append(
            f'<div class="sev-row"><label>{label}</label><div class="track">'
            f'<div class="fill" style="--w:{w:.1f}%;--bar:{SEVERITY_COLORS[label]}"></div></div><strong>{n}</strong></div>'
        )
    return f'<div class="risk-rail"><div class="severity-stack">{"".join(rows)}</div></div>'

def short_text(value, limit: int = 150) -> str:
    text = str(value or '-').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + '…'


def location_label(path: str, line=None) -> str:
    loc = str(path or '-')
    if line:
        loc += f':{line}'
    return loc


def remediation_text(value, *, kind: str = "generic") -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        if kind == "secret":
            return "Remove or rotate the secret, then rerun the scanner."
        return "No scanner-provided remediation."
    if kind == "fixed_version":
        if "," in text:
            return f"Upgrade to one of the fixed versions: {text}."
        return f"Upgrade to {text} or later."
    if kind == "secret":
        return f"Review and remove or rotate the reported secret: {text}."
    return text


COLUMN_TOOLTIPS = {
    'Scanner': 'Scanner\n\nThe tool that produced this row, such as Semgrep, Gitleaks, Trivy, Grype, Syft, ZAP, or another configured scanner.',
    'Tier': 'Tier\n\nThe scanner priority or assurance level used by this dashboard. Higher-tier scanners tend to provide stronger or more direct assurance signals.',
    'Status': 'Status\n\nWhether the scanner ran, skipped, failed, or produced usable output in this scan.',
    'Findings': 'Findings\n\nThe number and severity mix of findings reported by this scanner.',
    'Signal': 'Signal\n\nA short explanation of what the scanner result means for assurance triage.',
    'Evidence': 'Evidence\n\nThe scanner output artifact or evidence file captured for this report.',
    'Breakdown': 'Breakdown\n\nSeverity or category counts reported by the scanner.',
    'Total': 'Total\n\nThe total number of findings represented by this row.',
    'Severity': 'Severity\n\nThe scanner-reported impact level for the finding.',
    'ID': 'ID\n\nThe scanner rule, CVE, vulnerability, secret, or misconfiguration identifier.',
    'CVE': 'CVE\n\nThe public vulnerability identifier reported for a dependency finding.',
    'Rule': 'Rule\n\nThe scanner rule identifier that produced the finding.',
    'Location': 'Location\n\nThe file, line, artifact, package, image, or configuration location where the scanner reported the finding.',
    'Message': 'Message\n\nThe scanner message describing what was detected.',
    'Description': 'Description\n\nThe scanner-provided description of the detected issue.',
    'Target': 'Target\n\nThe affected asset the scanner checked, such as a package, image layer, file path, container image, configuration target, or scan surface.',
    'Finding': 'Finding\n\nThe package, secret, misconfiguration, or issue summary reported by the scanner.',
    'Remediation': 'Remediation\n\nThe action the scanner recommends, such as an upgrade version, configuration change, or secret cleanup step.',
    'Assurance trace': 'Assurance trace\n\nShows whether this scanner finding maps to a compliance row and whether that row links onward to project FRs and TBTs. Compliance-only findings are useful signals even when they do not yet prove a project FR/TBT.',
    'Package': 'Package\n\nThe dependency or package affected by the finding.',
    'Installed': 'Installed\n\nThe installed package version observed by the scanner.',
    'Fixed in': 'Fixed in\n\nThe version or versions that contain a fix, when the scanner knows one.',
    'Before': 'Before\n\nThe finding count before ignore filters were applied.',
    'After': 'After\n\nThe finding count after ignore filters were applied.',
    'Removed': 'Removed\n\nFindings suppressed by ignore filters.',
    'Patterns': 'Patterns\n\nIgnore patterns that affected this scanner output.',
}


def th(label: str, *, class_name: str = '') -> str:
    tooltip = COLUMN_TOOLTIPS.get(label, f'{label}\n\nColumn value for {label.lower()}.')
    cls = f' class="{html.escape(class_name)}"' if class_name else ''
    return f'<th{cls} data-tooltip="{html.escape(tooltip)}">{html.escape(label)}</th>'


def detail_block(items: list[tuple[str, str]]) -> str:
    rows = []
    for label, value in items:
        if value in (None, ""):
            continue
        rows.append(f'<div><span>{html.escape(label)}</span><strong>{value}</strong></div>')
    return '<div class="finding-row-detail-grid">' + ''.join(rows) + '</div>'


def chain_markup(chains: list[dict]) -> str:
    if not chains:
        return '<span class="finding-chain finding-chain-empty">No assurance trace</span>'
    rendered = []
    seen: set[str] = set()
    for chain in chains[:3]:
        row = chain.get("row", "")
        frs = ", ".join(chain.get("frs") or []) or "No FR"
        tbts = ", ".join(chain.get("tbts") or []) or "No TBT"
        key = f"{row}:{frs}:{tbts}"
        if key in seen:
            continue
        seen.add(key)
        label = f'{row} -> {frs} / {tbts}' if row else f'{frs} / {tbts}'
        rendered.append(f'<span class="finding-chain" title="{html.escape(label)}">{html.escape(short_text(label, 54))}</span>')
    if len(chains) > 3:
        rendered.append(f'<span class="finding-chain finding-chain-more">+{len(chains) - 3}</span>')
    return '<div class="finding-chain-list">' + ''.join(rendered) + '</div>'


def compliance_trace_markup(chains: list[dict]) -> str:
    if not chains:
        return '<span class="finding-chain finding-chain-empty">No mapped compliance row</span>'
    rendered = []
    seen: set[str] = set()
    for chain in chains:
        label = f'{chain.get("ruleset") or "Compliance"} {chain.get("row") or "-"}'
        if label in seen:
            continue
        seen.add(label)
        rendered.append(f'<span class="finding-chain" title="{html.escape(label)}">{html.escape(short_text(label, 64))}</span>')
    return '<div class="finding-chain-list">' + ''.join(rendered) + '</div>'


def project_trace_markup(chains: list[dict]) -> str:
    if not chains:
        return '<span class="finding-chain finding-chain-empty">No project FR/TBT trace</span>'
    rendered = []
    seen: set[str] = set()
    for chain in chains:
        frs = ", ".join(chain.get("frs") or [])
        tbts = ", ".join(chain.get("tbts") or [])
        if not frs and not tbts:
            continue
        label = f'{frs or "No FR"} / {tbts or "No TBT"}'
        if label in seen:
            continue
        seen.add(label)
        rendered.append(f'<span class="finding-chain" title="{html.escape(label)}">{html.escape(short_text(label, 72))}</span>')
    if not rendered:
        return '<span class="finding-chain finding-chain-empty">No project FR/TBT mapped yet</span>'
    return '<div class="finding-chain-list">' + ''.join(rendered) + '</div>'


def trace_detail_items(chains: list[dict]) -> list[tuple[str, str]]:
    return [
        ("Compliance trace", compliance_trace_markup(chains)),
        ("Project trace", project_trace_markup(chains)),
    ]


def _field_value(finding: dict, field: str) -> str:
    aliases = {
        "ruleId": ["ruleId", "RuleID", "rule_id", "id"],
        "RuleID": ["RuleID", "ruleId", "rule_id", "id"],
        "ID": ["ID", "id", "rule_id", "RuleID", "VulnerabilityID"],
        "VulnerabilityID": ["VulnerabilityID", "id", "ID"],
    }
    for candidate in aliases.get(field, [field]):
        if candidate in finding and finding.get(candidate) not in (None, ""):
            return str(finding.get(candidate))
    folded = {str(k).lower(): v for k, v in finding.items()}
    value = folded.get(field.lower(), "")
    return "" if value in (None, "") else str(value)


def _selector_matches(selector: dict, finding: dict) -> bool:
    field = selector.get("output_field") or "rule_id"
    expected = str(selector.get("value") or "")
    actual = _field_value(finding, field)
    if not expected or not actual:
        return False
    selector_type = selector.get("type", "exact")
    if selector_type == "exact":
        return actual == expected
    if selector_type == "glob":
        return fnmatch.fnmatchcase(actual.lower(), expected.lower())
    if selector_type == "contains":
        return expected.lower() in actual.lower()
    return False


@lru_cache(maxsize=12)
def _row_to_tbt_chains_cached(report_dir_value: str) -> dict[tuple[str, str], dict[str, set[str]]]:
    report_dir = Path(report_dir_value)
    catalog = load_json(report_dir / "fr-catalog.snapshot.json") or {}
    chains: dict[tuple[str, str], dict[str, set[str]]] = {}
    for tbt in catalog.get("tbts") or catalog.get("test_basis") or []:
        tbt_id = str(tbt.get("id") or "")
        frs = [str(fr) for fr in tbt.get("proves") or [] if fr]
        compliance = tbt.get("compliance") or []
        meta_row = ((tbt.get("metadata") or {}).get("ruleset_row") or {})
        if meta_row:
            compliance = [*compliance, meta_row]
        for row in compliance:
            key = (str(row.get("ruleset") or ""), str(row.get("row") or ""))
            if not all(key):
                continue
            entry = chains.setdefault(key, {"frs": set(), "tbts": set()})
            if tbt_id:
                entry["tbts"].add(tbt_id)
            entry["frs"].update(frs)
    return chains


@lru_cache(maxsize=12)
def _scanner_packs_for_report(report_dir_value: str) -> tuple[dict, ...]:
    report_dir = Path(report_dir_value)
    return tuple(_load_scanner_compliance_packs(_default_scanner_compliance_mapping_paths(report_dir)) or [])


def scanner_relationships_for_finding(report_dir: Path, scanner: str, finding: dict) -> list[dict]:
    packs = _scanner_packs_for_report(str(report_dir))
    row_chains = _row_to_tbt_chains_cached(str(report_dir))
    chains: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for pack in packs:
        if str(pack.get("scanner") or "") != scanner:
            continue
        for mapping in pack.get("mappings") or []:
            if mapping.get("review_status") != "accepted" or mapping.get("mapping_level") != "compliance_row":
                continue
            if not any(_selector_matches(selector, finding) for selector in mapping.get("rule_selectors") or []):
                continue
            for target in (mapping.get("targets") or {}).get("compliance_rows") or []:
                key = (str(target.get("ruleset") or ""), str(target.get("row") or ""))
                linked = row_chains.get(key, {"frs": set(), "tbts": set()})
                chain = {
                    "ruleset": key[0],
                    "row": key[1],
                    "frs": sorted(linked.get("frs") or []),
                    "tbts": sorted(linked.get("tbts") or []),
                    "mapping": mapping.get("id", ""),
                    "effect": mapping.get("assurance_effect", ""),
                }
                dedupe = (chain["row"], ",".join(chain["frs"]), ",".join(chain["tbts"]))
                if dedupe not in seen:
                    seen.add(dedupe)
                    chains.append(chain)
    return chains


def render_detail_table(headers: list[str], rows: list[list[str] | dict], *, limit: int = 100) -> str:
    if not rows:
        return '<div class="empty-state">No row-level findings available for this scanner.</div>'
    headers = [h for h in headers if h != "Details"]
    head = ''.join(th(h) for h in headers)
    body = []
    shown_rows = rows[:limit]
    for idx, row in enumerate(shown_rows):
        if isinstance(row, dict):
            visible = row.get("visible") or []
            detail = row.get("detail", "")
            detail_id = row.get("detail_id") or f"finding-row-detail-{idx}"
        else:
            visible = row
            detail = ""
            detail_id = ""
        cells = []
        for cell in visible:
            cells.append(f'<td>{cell}</td>')
        if detail:
            safe_id = html.escape(detail_id)
            body.append(
                f'<tr class="finding-click-row" data-finding-toggle="{safe_id}" '
                f'aria-controls="{safe_id}" aria-expanded="false" tabindex="0">'
                + ''.join(cells)
                + '</tr>'
            )
        else:
            body.append('<tr>' + ''.join(cells) + '</tr>')
        if detail:
            body.append(f'<tr class="finding-row-detail" id="{html.escape(detail_id)}" hidden><td colspan="{len(headers)}">{detail}</td></tr>')
    note = ''
    if len(rows) > limit:
        note = (
            f'<div class="evidence-purpose">Showing the first {limit} of {len(rows):,} row-level findings to keep the dashboard responsive. '
            'Use the Evidence Files page for the complete raw scanner output.</div>'
        )
    return note + '<table class="finding-detail"><thead><tr>' + head + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table>'


def output_candidates(report_dir: Path, rel: str, include_suffixed: bool = False) -> list[Path]:
    base = report_dir / rel
    parent = base.parent
    name = base.name
    if name.endswith('.cyclonedx.json'):
        prefix = name[: -len('.cyclonedx.json')]
        suffix = '.cyclonedx.json'
    else:
        suffix = ''.join(base.suffixes) or base.suffix
        prefix = name[: -len(suffix)] if suffix else name
    candidates: list[Path] = []
    if base.exists() and base.stat().st_size > 0:
        candidates.append(base)
    if include_suffixed and parent.is_dir():
        for path in sorted(parent.glob(f'{prefix}-*{suffix}')):
            if path.is_file() and path.stat().st_size > 0 and path not in candidates:
                candidates.append(path)
    return candidates


def target_from_output_path(path: Path, prefix: str, suffix: str) -> str:
    name = path.name
    if name == f'{prefix}{suffix}':
        return '-'
    if name.startswith(f'{prefix}-') and name.endswith(suffix):
        return name[len(prefix) + 1 : -len(suffix)]
    return '-'


def semgrep_detail_rows(report_dir: Path) -> tuple[list[str], list[list[str]]]:
    data = load_json(report_dir / 'reports' / 'semgrep.sarif') or {}
    results = ((data.get('runs') or [{}])[0].get('results') or []) if isinstance(data, dict) else []
    rows = []
    for item in results:
        loc = (((item.get('locations') or [{}])[0].get('physicalLocation') or {}))
        artifact = (loc.get('artifactLocation') or {}).get('uri', '-')
        region = loc.get('region') or {}
        line = region.get('startLine')
        rule = item.get('ruleId', '-')
        msg = (item.get('message') or {}).get('text', '-')
        finding = {
            "scanner": "semgrep",
            "rule_id": rule,
            "ruleId": rule,
            "id": rule,
            "location": location_label(artifact, line),
            "path": artifact,
            "message": msg,
        }
        chains = scanner_relationships_for_finding(report_dir, "semgrep", finding)
        detail_id = "finding-semgrep-" + str(len(rows))
        rows.append({
            "detail_id": detail_id,
            "visible": [
            f'<code title="{html.escape(rule)}">{html.escape(short_text(rule, 70))}</code>',
            f'<div class="finding-message" title="{html.escape(msg)}">{html.escape(short_text(msg, 170))}</div>',
            chain_markup(chains),
            ],
            "detail": detail_block([
                ("Location", f'<code>{html.escape(location_label(artifact, line))}</code>'),
                ("Message", html.escape(msg or "-")),
                *trace_detail_items(chains),
            ]),
        })
    return ['Rule', 'Message', 'Assurance trace'], rows


def gitleaks_detail_rows(report_dir: Path) -> tuple[list[str], list[list[str]]]:
    data = load_json(report_dir / 'reports' / 'gitleaks.json') or []
    rows = []
    if not isinstance(data, list):
        return ['Rule', 'Location', 'Description'], rows
    for item in data:
        rule = item.get('RuleID', '-')
        path = item.get('File', '-')
        line = item.get('StartLine')
        desc = item.get('Description', '-')
        finding = {
            "scanner": "gitleaks",
            "rule_id": rule,
            "RuleID": rule,
            "id": rule,
            "location": location_label(path, line),
            "path": path,
            "message": desc,
        }
        chains = scanner_relationships_for_finding(report_dir, "gitleaks", finding)
        detail_id = "finding-gitleaks-" + str(len(rows))
        rows.append({
            "detail_id": detail_id,
            "visible": [
            f'<code>{html.escape(short_text(rule, 44))}</code>',
            f'<div class="finding-message" title="{html.escape(desc)}">{html.escape(short_text(desc, 160))}</div>',
            chain_markup(chains),
            ],
            "detail": detail_block([
                ("Location", f'<code>{html.escape(location_label(path, line))}</code>'),
                ("Description", html.escape(desc or "-")),
                *trace_detail_items(chains),
            ]),
        })
    return ['Rule', 'Description', 'Assurance trace'], rows


def scanner_finding_records(report_dir: Path) -> list[dict]:
    records: list[dict] = []
    semgrep = load_json(report_dir / 'reports' / 'semgrep.sarif') or {}
    semgrep_results = ((semgrep.get('runs') or [{}])[0].get('results') or []) if isinstance(semgrep, dict) else []
    for item in semgrep_results:
        loc = (((item.get('locations') or [{}])[0].get('physicalLocation') or {}))
        artifact = (loc.get('artifactLocation') or {}).get('uri', '')
        region = loc.get('region') or {}
        line = region.get('startLine')
        rule = item.get('ruleId', '')
        msg = (item.get('message') or {}).get('text', '')
        location = location_label(artifact, line) if artifact or line else ''
        records.append({
            'scanner': 'semgrep',
            'rule_id': rule,
            'ruleId': rule,
            'id': rule,
            'message': msg,
            'location': location,
            'path': artifact,
        })

    gitleaks = load_json(report_dir / 'reports' / 'gitleaks.json') or []
    if isinstance(gitleaks, list):
        for item in gitleaks:
            rule = item.get('RuleID', '')
            path = item.get('File', '')
            line = item.get('StartLine')
            desc = item.get('Description', '')
            records.append({
                'scanner': 'gitleaks',
                'rule_id': rule,
                'RuleID': rule,
                'id': rule,
                'message': desc,
                'location': location_label(path, line) if path or line else '',
                'path': path,
            })
    return records


def trivy_detail_rows(report_dir: Path, rel: str, include_suffixed: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    scanner_name = 'trivy-image' if 'trivy-image' in rel else ('trivy-config' if 'trivy-config' in rel else 'trivy-fs')
    for path in output_candidates(report_dir, rel, include_suffixed):
        data = load_json(path) or {}
        image_target = target_from_output_path(path, 'trivy-image', '.json')
        for result in data.get('Results', []) or []:
            target = result.get('Target', '-')
            display_target = target if image_target == '-' else f'{image_target} / {target}'
            for vuln in result.get('Vulnerabilities') or []:
                fixed = ', '.join(vuln.get('FixedVersion') or []) if isinstance(vuln.get('FixedVersion'), list) else (vuln.get('FixedVersion') or '-')
                vuln_id = vuln.get("VulnerabilityID", "-")
                finding = {
                    "scanner": scanner_name,
                    "rule_id": vuln_id,
                    "VulnerabilityID": vuln_id,
                    "ID": vuln_id,
                    "id": vuln_id,
                    "Target": display_target,
                    "location": display_target,
                    "message": vuln.get("Title") or vuln.get("Description") or vuln.get("PkgName", ""),
                }
                chains = scanner_relationships_for_finding(report_dir, scanner_name, finding)
                detail_id = "finding-" + scanner_name + "-" + str(len(rows))
                rows.append({
                    "detail_id": detail_id,
                    "visible": [
                    sev_badge(str(vuln.get('Severity', 'UNKNOWN')).upper()),
                    f'<code>{html.escape(vuln_id)}</code>',
                    f'<div class="finding-message">{html.escape(short_text(vuln.get("PkgName", "-"), 80))} {html.escape(short_text(vuln.get("InstalledVersion", ""), 40))}</div>',
                    chain_markup(chains),
                    ],
                    "detail": detail_block([
                        ("Target", f'<code>{html.escape(display_target)}</code>'),
                        ("Finding", html.escape(short_text(vuln.get("Title") or vuln.get("Description") or vuln.get("PkgName", "-"), 220))),
                        ("Remediation", html.escape(remediation_text(fixed, kind="fixed_version"))),
                        *trace_detail_items(chains),
                    ]),
                })
            for secret in result.get('Secrets') or []:
                rule_id = secret.get("RuleID", "-")
                location = location_label(display_target, secret.get("StartLine"))
                finding = {
                    "scanner": scanner_name,
                    "rule_id": rule_id,
                    "RuleID": rule_id,
                    "ID": rule_id,
                    "id": rule_id,
                    "Target": display_target,
                    "location": location,
                    "message": secret.get("Title", secret.get("Category", "Secret")),
                }
                chains = scanner_relationships_for_finding(report_dir, scanner_name, finding)
                detail_id = "finding-" + scanner_name + "-" + str(len(rows))
                rows.append({
                    "detail_id": detail_id,
                    "visible": [
                    sev_badge(str(secret.get('Severity', 'UNKNOWN')).upper()),
                    f'<code>{html.escape(rule_id)}</code>',
                    f'<div class="finding-message">{html.escape(short_text(secret.get("Title", secret.get("Category", "Secret")), 100))}</div>',
                    chain_markup(chains),
                    ],
                    "detail": detail_block([
                        ("Target", f'<code>{html.escape(location)}</code>'),
                        ("Finding", html.escape(secret.get("Title", secret.get("Category", "Secret")) or "-")),
                        ("Remediation", html.escape(remediation_text(secret.get("Title", secret.get("Category", "Secret")), kind="secret"))),
                        *trace_detail_items(chains),
                    ]),
                })
            for misconf in result.get('Misconfigurations') or []:
                if misconf.get('Status') and misconf.get('Status') != 'FAIL':
                    continue
                rule_id = misconf.get("ID", "-")
                finding = {
                    "scanner": scanner_name,
                    "rule_id": rule_id,
                    "ID": rule_id,
                    "id": rule_id,
                    "Target": display_target,
                    "location": display_target,
                    "message": misconf.get("Message", misconf.get("Title", "")),
                }
                chains = scanner_relationships_for_finding(report_dir, scanner_name, finding)
                detail_id = "finding-" + scanner_name + "-" + str(len(rows))
                rows.append({
                    "detail_id": detail_id,
                    "visible": [
                    sev_badge(str(misconf.get('Severity', 'UNKNOWN')).upper()),
                    f'<code>{html.escape(rule_id)}</code>',
                    f'<div class="finding-message" title="{html.escape(misconf.get("Message", ""))}">{html.escape(short_text(misconf.get("Title", misconf.get("Message", "-")), 110))}</div>',
                    chain_markup(chains),
                    ],
                    "detail": detail_block([
                        ("Target", f'<code>{html.escape(display_target)}</code>'),
                        ("Finding", html.escape(misconf.get("Message", misconf.get("Title", "-")) or "-")),
                        ("Remediation", html.escape(remediation_text(misconf.get('Resolution', '-') or "-", kind="resolution"))),
                        *trace_detail_items(chains),
                    ]),
                })
    return ['Severity', 'ID', 'Finding', 'Assurance trace'], rows


def grype_detail_rows(report_dir: Path, rel: str = 'reports/grype.json', include_suffixed: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    scanner_name = 'grype-image' if 'grype-image' in rel else 'grype'
    rank = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'UNKNOWN': 4}
    def key(match):
        sev = str(((match.get('vulnerability') or {}).get('severity') or 'UNKNOWN')).upper()
        return (rank.get(sev, 9), (match.get('vulnerability') or {}).get('id', ''))
    for path in output_candidates(report_dir, rel, include_suffixed):
        data = load_json(path) or {}
        image_target = target_from_output_path(path, 'grype-image', '.json')
        for match in sorted(data.get('matches', []) or [], key=key):
            vuln = match.get('vulnerability') or {}
            artifact = match.get('artifact') or {}
            fix = ', '.join((vuln.get('fix') or {}).get('versions') or []) or '-'
            package = artifact.get('name', '-')
            if image_target != '-':
                package = f'{image_target} / {package}'
            vuln_id = vuln.get("id", "-")
            finding = {
                "scanner": scanner_name,
                "rule_id": vuln_id,
                "VulnerabilityID": vuln_id,
                "ID": vuln_id,
                "id": vuln_id,
                "Package": package,
                "location": package,
                "message": vuln.get("description") or vuln.get("namespace") or "",
            }
            chains = scanner_relationships_for_finding(report_dir, scanner_name, finding)
            detail_id = "finding-" + scanner_name + "-" + str(len(rows))
            rows.append({
                "detail_id": detail_id,
                "visible": [
                sev_badge(str(vuln.get('severity', 'UNKNOWN')).upper()),
                f'<code>{html.escape(vuln_id)}</code>',
                f'<div class="finding-message">{html.escape(short_text(artifact.get("name", package), 94))} {html.escape(short_text(artifact.get("version", ""), 32))}</div>',
                chain_markup(chains),
                ],
                "detail": detail_block([
                    ("Package target", f'<code>{html.escape(package)}</code>'),
                    ("Installed", html.escape(artifact.get('version', '-') or "-")),
                    ("Remediation", html.escape(remediation_text(fix, kind="fixed_version"))),
                    *trace_detail_items(chains),
                ]),
            })
    return ['Severity', 'ID', 'Package', 'Assurance trace'], rows


def syft_detail_rows(report_dir: Path, rel: str = 'sbom/sbom.cyclonedx.json', include_suffixed: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    for path in output_candidates(report_dir, rel, include_suffixed):
        data = load_json(path) or {}
        image_target = target_from_output_path(path, 'image-sbom', '.cyclonedx.json')
        for comp in data.get('components', []) or []:
            props = {p.get('name'): p.get('value') for p in comp.get('properties', []) or [] if isinstance(p, dict)}
            ptype = props.get('syft:package:type') or comp.get('type', '-')
            component = comp.get('name', '-')
            if image_target != '-':
                component = f'{image_target} / {component}'
            rows.append([
                f'<code>{html.escape(short_text(ptype, 38))}</code>',
                f'<code title="{html.escape(component)}">{html.escape(short_text(component, 100))}</code>',
                html.escape(short_text(comp.get('version', '-'), 48)),
                f'<code title="{html.escape(comp.get("purl", comp.get("bom-ref", "-")))}">{html.escape(short_text(comp.get("purl", comp.get("bom-ref", "-")), 110))}</code>',
            ])
    return ['Type', 'Component', 'Version', 'Locator'], rows


def manual_evidence_items(report_dir: Path) -> list[dict]:
    manual_path = report_dir / 'manual-evidence-required.md'
    if not manual_path.exists():
        return []
    items = []
    current = None
    heading_re = re.compile(r'^##\s+(\d+)\.\s+(.+?)\s*$')
    field_re = re.compile(r'^-\s+\*\*(Description|Why required|Evidence expected|Status):\*\*\s*(.*)$')
    for line in manual_path.read_text(errors='replace').splitlines():
        heading = heading_re.match(line)
        if heading:
            if current:
                items.append(current)
            current = {
                'id': heading.group(1),
                'title': heading.group(2),
                'description': '',
                'why': '',
                'evidence': '',
                'status': 'PENDING',
            }
            continue
        if not current:
            continue
        field = field_re.match(line)
        if field:
            key = field.group(1).lower().replace(' ', '_')
            current[key] = field.group(2).strip()
    if current:
        items.append(current)
    return items


def severity_issues(report_dir: Path, wanted: set[str]) -> list[dict]:
    issues: list[dict] = []
    rank = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'UNKNOWN': 4}

    for path in output_candidates(report_dir, 'reports/grype.json', include_suffixed=True):
        image_target = target_from_output_path(path, 'grype-image', '.json')
        source = 'Grype Image' if image_target != '-' else 'Grype'
        scanner_id = 'grype-image' if image_target != '-' else 'grype'
        data = load_json(path) or {}
        for match in data.get('matches', []) or []:
            vuln = match.get('vulnerability') or {}
            artifact = match.get('artifact') or {}
            severity = str(vuln.get('severity') or 'UNKNOWN').upper()
            if severity not in wanted:
                continue
            fix = ', '.join((vuln.get('fix') or {}).get('versions') or []) or '-'
            pkg = artifact.get('name', '-')
            version = artifact.get('version', '-')
            if image_target != '-':
                pkg = f'{image_target} / {pkg}'
            issues.append({
                'severity': severity,
                'source': source,
                'scanner': scanner_id,
                'id': vuln.get('id', '-'),
                'target': f'{pkg} {version}'.strip(),
                'detail': fix,
                'remediation_kind': 'fixed_version',
                'finding': f'{artifact.get("name", pkg)} {version}'.strip(),
            })

    trivy_sources = [
        ('reports/trivy-fs.json', 'Trivy FS', False),
        ('reports/trivy-config.json', 'Trivy Config', False),
        ('reports/trivy-image.json', 'Trivy Image', True),
    ]
    for rel, base_source, include_suffixed in trivy_sources:
        candidates = output_candidates(report_dir, rel, include_suffixed=include_suffixed)
        for path in candidates:
            image_target = target_from_output_path(path, 'trivy-image', '.json')
            source = 'Trivy Image' if image_target != '-' else base_source
            scanner_id = 'trivy-image' if image_target != '-' else base_source.lower().replace(' ', '-')
            data = load_json(path) or {}
            for result in data.get('Results', []) or []:
                target = result.get('Target', '-')
                if image_target != '-':
                    target = f'{image_target} / {target}' if target != '-' else image_target
                for vuln in result.get('Vulnerabilities') or []:
                    severity = str(vuln.get('Severity') or 'UNKNOWN').upper()
                    if severity not in wanted:
                        continue
                    fixed = vuln.get('FixedVersion') or '-'
                    issues.append({
                        'severity': severity,
                        'source': source,
                        'scanner': scanner_id,
                        'id': vuln.get('VulnerabilityID', '-'),
                        'target': f'{vuln.get("PkgName", target)} {vuln.get("InstalledVersion", "")}'.strip(),
                        'detail': fixed if isinstance(fixed, str) else ', '.join(fixed),
                        'remediation_kind': 'fixed_version',
                        'finding': f'{vuln.get("PkgName", target)} {vuln.get("InstalledVersion", "")}'.strip(),
                    })
                for secret in result.get('Secrets') or []:
                    severity = str(secret.get('Severity') or 'UNKNOWN').upper()
                    if severity not in wanted:
                        continue
                    issues.append({
                        'severity': severity,
                        'source': source,
                        'scanner': scanner_id,
                        'id': secret.get('RuleID', '-'),
                        'target': location_label(target, secret.get('StartLine')),
                        'detail': secret.get('Title') or secret.get('Category') or 'Secret',
                        'remediation_kind': 'secret',
                        'finding': secret.get('Title') or secret.get('Category') or 'Secret',
                    })
                for misconf in result.get('Misconfigurations') or []:
                    if misconf.get('Status') and misconf.get('Status') != 'FAIL':
                        continue
                    severity = str(misconf.get('Severity') or 'UNKNOWN').upper()
                    if severity not in wanted:
                        continue
                    issues.append({
                        'severity': severity,
                        'source': source,
                        'scanner': scanner_id,
                        'id': misconf.get('ID', '-'),
                        'target': target,
                        'detail': misconf.get('Resolution') or misconf.get('Title') or misconf.get('Message') or '-',
                        'remediation_kind': 'resolution',
                        'finding': misconf.get('Title') or misconf.get('Message') or target,
                    })

    issues.sort(key=lambda x: (rank.get(x['severity'], 9), x['source'], x['id'], x['target']))
    return issues


def critical_high_issues(report_dir: Path) -> list[dict]:
    return severity_issues(report_dir, {'CRITICAL', 'HIGH'})


def medium_low_issues(report_dir: Path) -> list[dict]:
    return severity_issues(report_dir, {'MEDIUM', 'LOW'})


def issue_chain(report_dir: Path, issue: dict) -> list[dict]:
    finding = {
        "scanner": issue.get("scanner", ""),
        "rule_id": issue.get("id", ""),
        "id": issue.get("id", ""),
        "ID": issue.get("id", ""),
        "VulnerabilityID": issue.get("id", ""),
        "RuleID": issue.get("id", ""),
        "Target": issue.get("target", ""),
        "Package": issue.get("target", ""),
        "location": issue.get("target", ""),
        "message": issue.get("detail") or issue.get("finding") or "",
    }
    return scanner_relationships_for_finding(report_dir, str(issue.get("scanner", "")), finding)


def issue_trace_category(chains: list[dict]) -> str:
    if any((chain.get("frs") or chain.get("tbts")) for chain in chains):
        return "formal-assurance"
    if chains:
        return "compliance-only"
    return "security-hygiene"


def issue_trace_label(category: str) -> str:
    return {
        "formal-assurance": "Formal assurance impact",
        "compliance-only": "Compliance-only signal",
        "security-hygiene": "Security hygiene",
    }.get(category, "Security hygiene")


def trace_category_counts(report_dir: Path, issues: list[dict]) -> dict[str, int]:
    counts = {"formal-assurance": 0, "compliance-only": 0, "security-hygiene": 0}
    for issue in issues:
        category = issue_trace_category(issue_chain(report_dir, issue))
        counts[category] = counts.get(category, 0) + 1
    return counts


def render_issue_triage_kpis(report_dir: Path, issues: list[dict]) -> str:
    if not issues:
        return ""
    counts = trace_category_counts(report_dir, issues)
    cards = [
        (
            "formal-assurance",
            "Formal assurance",
            counts["formal-assurance"],
            "Formal assurance findings\n\nThese scanner findings trace to a project FR/TBT assurance chain. Treat failures as direct assurance blockers until fixed, waived, or otherwise resolved.",
            "#ff8a3d",
        ),
        (
            "compliance-only",
            "Compliance only",
            counts["compliance-only"],
            "Compliance-only findings\n\nThese scanner findings map to selected compliance rows, but not yet to a project FR/TBT. They still matter for compliance triage and may need a project FR/TBT mapping.",
            "#ffd166",
        ),
        (
            "security-hygiene",
            "Security hygiene",
            counts["security-hygiene"],
            "Security hygiene findings\n\nThese scanner findings do not currently trace to the selected compliance regime or a project FR/TBT. Review them as general security risk, then map, fix, accept, or document why they are out of scope.",
            "#8fcbe8",
        ),
    ]
    out = [
        '<div class="issue-triage-card" data-overview-persistent="true">'
        '<div class="issue-triage-grid">'
    ]
    for key, label, count, tooltip, color in cards:
        out.append(
            f'<button type="button" class="metric issue-trace-filter" style="--metric-color:{color}" '
            f'data-issue-trace-filter="{html.escape(key)}" data-tooltip="{html.escape(tooltip)}" aria-pressed="false">'
            f'<b>{count:,}</b><span>{html.escape(label)}</span>'
            '</button>'
        )
    out.append(
        '<button type="button" class="metric issue-trace-filter is-clear" data-issue-trace-filter="all" '
        'data-tooltip="Triage issue rows&#10;&#10;Normalized scanner issue rows used by the assurance-impact filters. This is smaller than raw scanner-finding volume because raw tool output may include repeated findings, dependency rows, locations, or scanner-specific records." aria-pressed="true">'
        f'<b>{len(issues):,}</b><span>Triage issue rows</span></button>'
        '</div></div>'
    )
    return ''.join(out)


def render_issue_table(section: str, title: str, meta: str, issues: list[dict], report_dir: Path) -> str:
    out = [
        f'<section class="card" data-overview-section="{html.escape(section)}" data-issue-table-section="true"><div class="card-head"><h2>{title}</h2><span class="meta">{html.escape(meta)}</span></div>'
        f'<table class="matrix issue-summary-table"><thead><tr>{th("Severity")}{th("Scanner")}{th("ID")}{th("Finding")}{th("Assurance trace")}</tr></thead><tbody>'
    ]
    for idx, issue in enumerate(issues):
        chains = issue_chain(report_dir, issue)
        category = issue_trace_category(chains)
        detail_id = f'issue-detail-{section}-{idx}'
        safe_id = html.escape(detail_id)
        out.append(
            f'<tr class="finding-click-row" data-finding-toggle="{safe_id}" data-issue-trace-category="{html.escape(category)}" '
            f'aria-controls="{safe_id}" aria-expanded="false" tabindex="0">'
            f'<td>{sev_badge(issue["severity"])}</td>'
            f'<td>{html.escape(issue["source"])}</td>'
            f'<td><code>{html.escape(short_text(issue["id"], 44))}</code></td>'
            f'<td><div class="finding-message" title="{html.escape(issue.get("finding") or issue.get("target") or "")}">{html.escape(short_text(issue.get("finding") or issue.get("target") or "-", 92))}</div></td>'
            f'<td>{chain_markup(chains)}</td></tr>'
        )
        out.append(
            f'<tr class="finding-row-detail" id="{safe_id}" data-issue-trace-detail="{html.escape(category)}" hidden><td colspan="5">'
            + detail_block([
                ("Target", f'<code>{html.escape(issue.get("target", "-"))}</code>'),
                ("Triage category", html.escape(issue_trace_label(category))),
                ("Remediation", html.escape(remediation_text(issue.get("detail", "-"), kind=issue.get("remediation_kind", "generic")))),
                *trace_detail_items(chains),
            ])
            + '</td></tr>'
        )
    out.append('</tbody></table></section>')
    return ''.join(out)


def scanner_detail_table(name: str, report_dir: Path) -> str:
    normalized = name.replace('_', '-')
    if normalized == 'semgrep':
        headers, rows = semgrep_detail_rows(report_dir)
    elif normalized == 'gitleaks':
        headers, rows = gitleaks_detail_rows(report_dir)
    elif normalized == 'trivy-fs':
        headers, rows = trivy_detail_rows(report_dir, 'reports/trivy-fs.json')
    elif normalized == 'trivy-config':
        headers, rows = trivy_detail_rows(report_dir, 'reports/trivy-config.json')
    elif normalized == 'trivy-image':
        headers, rows = trivy_detail_rows(report_dir, 'reports/trivy-image.json', include_suffixed=True)
    elif normalized == 'grype':
        headers, rows = grype_detail_rows(report_dir)
    elif normalized == 'grype-image':
        headers, rows = grype_detail_rows(report_dir, 'reports/grype-image.json', include_suffixed=True)
    elif normalized == 'syft':
        headers, rows = syft_detail_rows(report_dir)
    elif normalized == 'syft-image':
        headers, rows = syft_detail_rows(report_dir, 'sbom/image-sbom.cyclonedx.json', include_suffixed=True)
    else:
        return '<div class="empty-state">No row-level finding details available for this scanner.</div>'
    return render_detail_table(headers, rows)


def render_all_findings(evidence: dict, report_dir: Path) -> str:
    findings = evidence.get('findings_summary', {})
    rows = []
    ordered = [name for name in SCANNERS if scanner_finding_value(name, findings) is not None]
    ordered += [name for name in findings if name.replace('_', '-') not in ordered and name not in ordered]
    for name in ordered:
        value = scanner_finding_value(name, findings)
        total = finding_total(value)
        if total <= 0:
            continue
        title = SCANNERS.get(name, SCANNERS.get(name.replace('_', '-'), {})).get('title', name.replace('_', '-'))
        detail_id = 'finding-detail-' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        safe_id = html.escape(detail_id)
        rows.append(
            f'<tr class="finding-parent finding-click-row" data-finding-toggle="{safe_id}" aria-controls="{safe_id}" aria-expanded="false" tabindex="0">'
            f'<td class="scanner">{html.escape(title)}</td>'
            f'<td>{finding_markup(value)}</td>'
            f'<td class="plain-count">{total:,}</td>'
            '</tr>'
        )
        rows.append(
            f'<tr class="finding-detail-row" id="{safe_id}" hidden>'
            f'<td colspan="3">{scanner_detail_table(name, report_dir)}</td>'
            '</tr>'
        )
    if not rows:
        rows.append('<tr><td colspan="4" class="empty-state">No findings.</td></tr>')
    return (
        '<section class="card" data-overview-section="all-findings"><div class="card-head">'
        '<h2>All Findings</h2><span class="meta">scanner summaries with row-level findings</span></div>'
        f'<table class="matrix"><thead><tr>{th("Scanner")}{th("Breakdown")}{th("Total")}</tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></section>'
    )

def render_scanner_health(evidence: dict) -> str:
    scanner_health = evidence.get('scanner_health', {})
    findings = evidence.get('findings_summary', {})
    scanner_groups = [
        ('Code', 'SAST, secrets, filesystem and config analysis', ['semgrep', 'gitleaks', 'trivy-fs', 'trivy-config']),
        ('Supply Chain', 'SBOM generation and vulnerability matching', ['syft', 'grype', 'osv-scanner']),
        ('Container Image', 'built image SBOM and vulnerability checks', ['trivy-image', 'syft-image', 'grype-image']),
        ('Runtime Surface', 'web app, headers and TLS checks', ['zap-baseline', 'security-headers', 'testssl']),
        ('Uploads & Malware', 'uploaded content scanning', ['clamav']),
    ]
    used: set[str] = set()
    rows = []

    def scanner_row(name: str) -> str:
        info = SCANNERS.get(name, {'title': name, 'level': '-', 'output': '-'})
        health = scanner_health.get(name, {}) or {}
        status = health.get('status', 'SKIPPED')
        reason = health.get('reason', 'Not requested')
        fv = scanner_finding_value(name, findings)
        return (
            '<tr>'
            f'<td class="scanner">{html.escape(info.get("title", name))}</td>'
            f'<td class="level">L{html.escape(str(info.get("level", "-")))}</td>'
            f'<td class="status-col">{status_pill(status)}</td>'
            f'<td class="findings-col">{finding_markup(fv)}</td>'
            f'<td><div class="reason" title="{html.escape(reason)}">{html.escape(reason)}</div></td>'
            f'<td class="evidence-col">{evidence_markup(evidence, name)}</td>'
            '</tr>'
        )

    for label, meta, names in scanner_groups:
        present = [name for name in names if name in scanner_health]
        if not present:
            continue
        rows.append(
            f'<tr class="category-row"><td colspan="6">{html.escape(label)}'
            f'<span class="category-meta"> · {html.escape(meta)}</span></td></tr>'
        )
        for name in present:
            used.add(name)
            rows.append(scanner_row(name))

    remaining = [name for name in scanner_health if name not in used]
    if remaining:
        rows.append('<tr class="category-row"><td colspan="6">Other<span class="category-meta"> · additional scanner outputs</span></td></tr>')
        for name in remaining:
            rows.append(scanner_row(name))

    return (
        '<section class="card" data-overview-section="scanner-health"><div class="card-head">'
        '<h2>Scanners</h2><span class="meta">grouped by scan surface</span></div>'
        f'<table class="matrix"><thead><tr>{th("Scanner")}{th("Tier")}{th("Status")}{th("Findings")}{th("Signal")}{th("Evidence")}</tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></section>'
    )


def evidence_inventory_meta(rel_file: str) -> dict[str, str]:
    lower = rel_file.lower()
    name = Path(rel_file).name.lower()
    if rel_file.startswith('generated-tests/VG_TEST_FRAMEWORK/manifest.json'):
        return {'type': 'Generated test pack', 'producer': 'VG_TEST_FRAMEWORK', 'status': 'generated', 'supports': 'FR/TBT gaps'}
    if rel_file.startswith('generated-tests/VG_TEST_FRAMEWORK/imported/'):
        return {'type': 'Copied native test', 'producer': 'VG_TEST_FRAMEWORK', 'status': 'review input', 'supports': 'TBT candidate'}
    if rel_file.startswith('generated-tests/VG_TEST_FRAMEWORK/'):
        return {'type': 'Assurance test artifact', 'producer': 'VG_TEST_FRAMEWORK', 'status': 'generated', 'supports': 'TBT candidate'}
    if name == 'fr-config-update-proposal.template.json':
        return {'type': 'Config proposal template', 'producer': 'VibeGuide', 'status': 'generated', 'supports': 'config review workflow'}
    if name in {'evidence-bundle.json', 'dashboard-payload.json', 'agent-prompt-plan.json'}:
        return {'type': 'Report artifact', 'producer': 'VibeGuide', 'status': 'generated', 'supports': 'audit trail'}
    if 'prompt' in lower:
        return {'type': 'Agent prompt', 'producer': 'VibeGuide', 'status': 'generated', 'supports': 'remediation workflow'}
    if lower.endswith(('.xml', '.junit')):
        return {'type': 'Test result', 'producer': 'project tests', 'status': 'observed', 'supports': 'test evidence'}
    if lower.endswith(('.md', '.txt', '.pdf', '.docx')):
        return {'type': 'Manual/document evidence', 'producer': 'project or assessor', 'status': 'review input', 'supports': 'manual assurance'}
    if rel_file.startswith('reports/'):
        if 'sbom' in lower:
            return {'type': 'SBOM artifact', 'producer': 'scanner run', 'status': 'observed', 'supports': 'supply-chain evidence'}
        if 'test' in lower or 'junit' in lower:
            return {'type': 'Test result', 'producer': 'scanner run', 'status': 'observed', 'supports': 'test evidence'}
        return {'type': 'Scanner output', 'producer': 'scanner run', 'status': 'observed', 'supports': 'security finding evidence'}
    return {'type': 'Evidence artifact', 'producer': 'scanner run', 'status': 'present', 'supports': 'run evidence'}


def evidence_support_label(item: dict[str, Any]) -> str:
    ruleset = str(item.get("ruleset") or "").strip()
    row_ref = str(item.get("row") or "").strip()
    domain = str(item.get("domain") or "").strip()
    mapping_level = str(item.get("mapping_level") or "").strip()
    node_id = str(item.get("node_id") or "").strip()

    if ruleset and row_ref:
        if mapping_level == "compliance_domain" or not re.match(r"^(?:v?\d+(?:\.\d+)*-)?\d+(?:\.\d+)+$", row_ref, re.I):
            return f"{ruleset} domain: {row_ref}"
        return f"{ruleset} {row_ref}"
    if ruleset and domain:
        return f"{ruleset} domain: {domain}"
    if node_id.startswith("evidence:scanner-domain:"):
        parts = node_id.split(":", 5)
        if len(parts) == 6:
            return f"{parts[4]} domain: {parts[5]}"
        return "Scanner domain signal"
    return node_id or "run evidence"


def evidence_artifact_label(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        label = str(item.get("path") or item.get("locator") or item.get("source") or item.get("id") or "")
        schema_ref = str(item.get("schema_ref") or "")
        return f"{label} · schema: {schema_ref}" if label and schema_ref else label
    return str(item) if item is not None else ""


def evidence_side_effect_label(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        parts = [
            str(item.get("type") or "side_effect").replace("_", " "),
            str(item.get("target") or ""),
            str(item.get("mode") or "").replace("_", " "),
        ]
        return " · ".join(part for part in parts if part)
    return str(item) if item is not None else ""


def evidence_io_detail_html(item: dict[str, Any]) -> str:
    def list_block(label: str, values: list[Any], formatter) -> str:
        rows = [formatter(value) for value in values if formatter(value)]
        if not rows:
            return ""
        return (
            f'<div class="evidence-io-block"><span>{html.escape(label)}</span><ul>'
            + ''.join(f'<li><code>{html.escape(row)}</code></li>' for row in rows[:6])
            + (f'<li><em>and {len(rows) - 6} more</em></li>' if len(rows) > 6 else '')
            + '</ul></div>'
        )

    blocks = [
        list_block("Inputs", item.get("inputs") or [], evidence_artifact_label),
        list_block("Outputs", item.get("outputs") or [], evidence_artifact_label),
        list_block("Side effects", item.get("side_effects") or [], evidence_side_effect_label),
        list_block(
            "Test actions",
            item.get("test_actions") or [],
            lambda action: (
                " · ".join(
                    part for part in [
                        str(action.get("type") or "").replace("_", " "),
                        str(action.get("name") or ""),
                        str(action.get("status") or ""),
                        str(action.get("target") or ""),
                        str(action.get("description") or ""),
                    ]
                    if part
                )
                if isinstance(action, dict)
                else str(action)
            ),
        ),
    ]
    blocks = [block for block in blocks if block]
    if not blocks:
        return '<div class="muted">No input/output or side-effect metadata was recorded for this evidence node.</div>'
    return '<div class="evidence-io-grid">' + ''.join(blocks) + '</div>'


def evidence_fact_table(rows: list[tuple[str, str]]) -> str:
    body = ''.join(
        '<tr>'
        f'<th>{html.escape(label)}</th>'
        f'<td>{value}</td>'
        '</tr>'
        for label, value in rows
        if value
    )
    return f'<table class="evidence-fact-table"><tbody>{body}</tbody></table>' if body else ""


def _manifest_path_label(path_text: str, report_dir: Path) -> str:
    if not path_text:
        return "-"
    repo_root = Path(__file__).resolve().parents[1]
    legacy_root = Path("/Users/jd/Development/asvs-scanner")
    try:
        raw_path = Path(path_text)
        if raw_path.is_absolute() and raw_path.is_relative_to(legacy_root):
            path_text = str(repo_root / raw_path.relative_to(legacy_root))
    except (TypeError, ValueError):
        pass
    path = Path(path_text)
    try:
        if path.is_absolute():
            return str(path.relative_to(report_dir))
    except ValueError:
        pass
    try:
        if path.is_absolute():
            return str(path.relative_to(repo_root))
    except ValueError:
        pass
    return path_text


def _config_group_label(role: str) -> str:
    if role in {"fr_catalog", "compliance_mapping_pack"}:
        return "Project assurance contract"
    if role in {"assurance_framework", "assurance_instance"}:
        return "Assurance framework"
    if role == "scanner_compliance_mapping_pack":
        return "Scanner-to-compliance mappings"
    if role in PLANNING_SCHEMA_BY_ROLE:
        return "Planning artifacts"
    return "Other runtime config"


def _config_role_label(role: str) -> str:
    labels = {
        "fr_catalog": "Project FR/TBT catalog",
        "compliance_mapping_pack": "Compliance mapping pack",
        "assurance_framework": "Assurance framework",
        "assurance_instance": "Assurance instance",
        "scanner_compliance_mapping_pack": "Scanner mapping pack",
    }
    return labels.get(role, role.replace("_", " "))


def render_config_artifacts(report_dir: Path) -> str:
    manifest = load_json(report_dir / "graph-manifest.json") or {}
    commitments = list(((manifest.get("accepted_config") or {}).get("commitments") or []))
    commitments.extend(((manifest.get("planning_artifacts") or {}).get("commitments") or []))
    if not commitments:
        return ""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in commitments:
        role = str(item.get("role") or "")
        grouped.setdefault(_config_group_label(role), []).append(item)

    rows: list[str] = []
    group_order = [
        "Project assurance contract",
        "Assurance framework",
        "Scanner-to-compliance mappings",
        "Planning artifacts",
        "Other runtime config",
    ]
    for group in group_order:
        items = grouped.get(group) or []
        if not items:
            continue
        rows.append(
            f'<tr class="config-group-row"><td colspan="4">{html.escape(group)}'
            f'<span>{len(items)} file{"s" if len(items) != 1 else ""}</span></td></tr>'
        )
        for idx, item in enumerate(sorted(items, key=lambda value: (str(value.get("role") or ""), str(value.get("path") or "")))):
            role = str(item.get("role") or "")
            path_label = _manifest_path_label(str(item.get("path") or ""), report_dir)
            schema_label = _manifest_path_label(str(item.get("schema") or ""), report_dir)
            review = item.get("review_summary") or {}
            review_bits = []
            if review.get("review_status_counts"):
                review_bits.append(
                    ", ".join(f"{k}: {v}" for k, v in sorted((review.get("review_status_counts") or {}).items()))
                )
            if review.get("reviewers"):
                review_bits.append("reviewed by " + ", ".join(str(v) for v in review.get("reviewers") or []))
            review_label = "; ".join(review_bits) or str(item.get("review_status") or item.get("freeze", {}).get("mode") or "-")
            scope_label = str(item.get("ruleset") or item.get("assurance_framework") or item.get("project") or item.get("pack") or "-")
            detail_id = "config-detail-" + re.sub(r"[^a-z0-9]+", "-", f"{group}-{role}-{idx}".lower()).strip("-")
            detail_rows = [
                ("Role", html.escape(_config_role_label(role))),
                ("File", f'<code>{html.escape(path_label)}</code>'),
                ("Scope", html.escape(scope_label)),
                ("Schema", f'<code>{html.escape(schema_label or "-")}</code>'),
                ("Schema version", html.escape(str(item.get("schema_version") or "-"))),
                ("Review / freeze", html.escape(review_label)),
                ("Freeze mode", html.escape(str((item.get("freeze") or {}).get("mode") or "-"))),
                ("Immutable", html.escape(str((item.get("freeze") or {}).get("immutable") if item.get("freeze") else "-").lower())),
                ("Size", html.escape(fmt_bytes(item.get("bytes", 0)))),
                ("Hash", f'<code>{html.escape(str(item.get("sha256") or "-"))}</code>'),
            ]
            if review.get("review_status_counts"):
                detail_rows.append(("Review statuses", html.escape(", ".join(f"{k}: {v}" for k, v in sorted((review.get("review_status_counts") or {}).items())))))
            if review.get("reviewers"):
                detail_rows.append(("Reviewers", html.escape(", ".join(str(v) for v in review.get("reviewers") or []))))
            rows.append(
                f'<tr class="config-artifact-row" tabindex="0" data-config-detail="{html.escape(detail_id)}" aria-controls="{html.escape(detail_id)}" aria-expanded="false">'
                f'<td>{html.escape(_config_role_label(role))}</td>'
                f'<td><code title="{html.escape(path_label)}">{html.escape(short_text(path_label, 88))}</code></td>'
                f'<td><code title="{html.escape(schema_label)}">{html.escape(short_text(schema_label or "-", 58))}</code></td>'
                f'<td class="mono-cell">{fmt_bytes(item.get("bytes", 0))}</td>'
                '</tr>'
                f'<tr class="config-detail-row" id="{html.escape(detail_id)}" hidden><td colspan="4">'
                '<div class="config-inline-detail">'
                + evidence_fact_table(detail_rows)
                + '</div></td></tr>'
            )

    return (
        '<section class="evidence-config-section" data-file-tab-panel="config">'
        '<div class="evidence-section-head"><h3>Runtime Config Files</h3>'
        '<span>content-addressed inputs that power this report, graph and assurance claims</span></div>'
        '<table class="matrix config-artifact-table"><thead><tr>'
        '<th>Role</th><th>File</th><th>Schema</th><th>Size</th>'
        '</tr></thead><tbody>'
        + ''.join(rows)
        + '</tbody></table></section>'
    )


def manifest_artifact_for_evidence_ref(
    manifest_by_file: dict[str, dict],
    ref: str,
    scanner: str = "",
) -> tuple[str, dict]:
    if ref in manifest_by_file:
        return ref, manifest_by_file[ref]
    output = scanner_output_link(scanner) if scanner else ""
    if output and output in manifest_by_file:
        return output, manifest_by_file[output]
    if output:
        output_path = Path(output)
        prefix, suffix = output_family(output_path.name)
        candidates = []
        for file_name, item in manifest_by_file.items():
            path = Path(file_name)
            if path.parent.as_posix() != output_path.parent.as_posix():
                continue
            if path.name == output_path.name or (suffix and path.name.startswith(prefix) and path.name.endswith(suffix)):
                candidates.append((file_name, item))
        if candidates:
            return sorted(candidates, key=lambda pair: pair[0])[0]
        return output, {}
    return ref, {}


def render_coverage(evidence: dict, report_dir: Path, evidence_view: dict[str, Any] | None = None) -> str:
    evidence_files = evidence.get('evidence_files', [])
    evidence_view = evidence_view or {}
    manifest_by_file = {
        str(item.get("file", "")): item
        for item in evidence_files
        if item.get("file")
    }
    out = [
        '<section class="card evidence-inventory-card">'
        '<div class="page-intro files-page-intro"><div><h2>Files</h2><ul>'
        '<li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg><span>Runtime config files are the frozen inputs used to build this report and graph.</span></li>'
        '<li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg><span>Evidence files are observed scanner, test, generated and manual artifacts cited by graph nodes.</span></li>'
        '<li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg><span>Expand a row to inspect provenance, hashes, schemas, inputs, outputs and side effects.</span></li>'
        '</ul></div></div>',
    ]
    if evidence_view:
        metrics = [
            (
                "Evidence nodes",
                evidence_view.get("evidence_count", 0),
                "Evidence nodes\n\nGraph nodes that represent observed or expected evidence, including scanner results, test results, documents, approvals and manual notes.",
            ),
            (
                "Scanner evidence",
                evidence_view.get("scanner_evidence_count", 0),
                "Scanner evidence\n\nEvidence nodes produced from scanner mappings. These may be passing, failing, missing or skipped depending on whether the scanner ran and produced a matching artifact.",
            ),
            (
                "Test results",
                evidence_view.get("test_result_count", 0),
                "Test results\n\nObserved test-result evidence imported from JUnit or approved assurance test runs. These can satisfy TBT evidence when linked to the expected FR/TBT chain.",
            ),
            (
                "Artifact refs",
                evidence_view.get("artifact_ref_count", 0),
                "Artifact refs\n\nReport files referenced by graph evidence nodes. Expand rows to see the exact artifact, source locator, hash and provenance metadata where available.",
            ),
        ]
        out.append(
            '<div class="metric-grid" style="grid-template-columns:repeat(4,minmax(120px,1fr));margin-bottom:12px">'
            + ''.join(
                f'<div class="metric" data-tooltip="{html.escape(tooltip)}"><b>{html.escape(str(value))}</b><span>{html.escape(label)}</span></div>'
                for label, value, tooltip in metrics
            )
            + '</div>'
        )

    config_html = render_config_artifacts(report_dir)
    out.append(
        '<div class="file-page-tabs" role="tablist" aria-label="File views">'
        f'<button type="button" class="file-page-tab active" data-file-tab="config" role="tab" aria-selected="true">Runtime config files</button>'
        f'<button type="button" class="file-page-tab" data-file-tab="evidence" role="tab" aria-selected="false">Evidence</button>'
        '</div>'
    )
    if config_html:
        out.append(config_html)
    else:
        out.append('<section class="evidence-config-section" data-file-tab-panel="config"><div class="empty-state">No runtime config manifest was recorded for this run.</div></section>')

    artifact_refs = evidence_view.get("artifact_refs") or []
    evidence_table_html = ""
    if artifact_refs:
        rows = []
        for idx, item in enumerate(artifact_refs):
            rel_file = str(item.get("ref") or item.get("source_locator") or item.get("source") or "-")
            evidence_type = str(item.get("evidence_type") or "evidence")
            scanner = str(item.get("scanner") or "")
            artifact_file, manifest_item = manifest_artifact_for_evidence_ref(manifest_by_file, rel_file, scanner)
            sha = str(manifest_item.get('sha256', ''))
            status = str(item.get("status") or "unknown")
            scanner_health = str(item.get("scanner_health") or "")
            scanner_reason = str(item.get("scanner_reason") or "")
            ruleset = str(item.get("ruleset") or "")
            meta = evidence_inventory_meta(artifact_file)
            if evidence_type != "unknown":
                meta["type"] = evidence_type.replace("_", " ")
            if scanner:
                meta["producer"] = scanner
            if status:
                meta["status"] = status.replace("_", " ")
            if ruleset or item.get("node_id"):
                meta["supports"] = evidence_support_label(item)
            size = fmt_bytes(manifest_item.get('bytes', 0)) if manifest_item else ("not produced" if scanner else "-")
            hash_label = sha or ("no output captured" if scanner else "not in manifest")
            summary = (
                f"Graph evidence {item.get('node_id') or item.get('label') or rel_file} "
                f"cites {rel_file}. Artifact: {artifact_file}. Produced by {meta['producer']}; status {meta['status']}."
            )
            fact_rows = [
                ("Producer", html.escape(meta["producer"])),
                ("Status", html.escape(meta["status"])),
                ("Supports", html.escape(meta["supports"])),
                ("Artifact", f'<code>{html.escape(artifact_file)}</code>'),
                ("Size", html.escape(size)),
                ("Hash", f'<code>{html.escape(hash_label)}</code>'),
                ("Graph node", f'<code>{html.escape(str(item.get("node_id") or "-"))}</code>'),
            ]
            if artifact_file != rel_file:
                fact_rows.insert(4, ("Source locator", f'<code>{html.escape(rel_file)}</code>'))
            if scanner_health:
                fact_rows.insert(2, ("Scanner health", html.escape(scanner_health)))
            if scanner_reason:
                fact_rows.insert(3, ("Scanner reason", html.escape(scanner_reason)))
            facts = evidence_fact_table(fact_rows)
            detail_id = f'evidence-detail-{idx}'
            rows.append(
                '<tr class="evidence-row" tabindex="0"'
                f' data-evidence-detail="{detail_id}" aria-controls="{detail_id}" aria-expanded="false">'
                f'<td><span class="evidence-type-chip">{html.escape(meta["type"])}</span></td>'
                f'<td><code title="{html.escape(artifact_file)}">{html.escape(short_text(artifact_file, 78))}</code></td>'
                f'<td>{html.escape(meta["producer"])}</td>'
                f'<td><span class="evidence-status-chip">{html.escape(meta["status"])}</span></td>'
                f'<td title="{html.escape(meta["supports"])}">{html.escape(short_text(meta["supports"], 54))}</td>'
                f'<td class="mono-cell">{size}</td>'
                '</tr>'
                f'<tr class="evidence-detail-row" id="{detail_id}" hidden><td colspan="6">'
                '<div class="evidence-inline-detail">'
                f'<div class="evidence-inline-title"><strong>{html.escape(meta["type"])}</strong><code>{html.escape(rel_file)}</code></div>'
                f'<div class="evidence-inline-summary">{html.escape(summary)}</div>'
                + facts
                + evidence_io_detail_html(item) +
                '</div>'
                '</td></tr>'
            )
        evidence_table_html = (
            '<section data-file-tab-panel="evidence" hidden><table class="matrix evidence-table"><thead><tr>'
            '<th>Type</th><th>Artifact</th><th>Producer</th><th>Status</th><th>Supports</th><th>Size</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></section>'
        )
    elif evidence_files:
        rows = []
        for idx, item in enumerate(evidence_files):
            rel_file = str(item.get("file", "-"))
            sha = str(item.get('sha256', ''))
            meta = evidence_inventory_meta(rel_file)
            size = fmt_bytes(item.get('bytes', 0))
            summary = (
                f"{meta['type']} produced by {meta['producer']}. "
                f"Status: {meta['status']}. Supports: {meta['supports']}."
            )
            facts = evidence_fact_table([
                ("Producer", html.escape(meta["producer"])),
                ("Status", html.escape(meta["status"])),
                ("Supports", html.escape(meta["supports"])),
                ("Size", html.escape(size)),
                ("Hash", f'<code>{html.escape(sha or "-")}</code>'),
            ])
            detail_id = f'evidence-detail-{idx}'
            rows.append(
                '<tr class="evidence-row" tabindex="0"'
                f' data-evidence-detail="{detail_id}" aria-controls="{detail_id}" aria-expanded="false">'
                f'<td><span class="evidence-type-chip">{html.escape(meta["type"])}</span></td>'
                f'<td><code title="{html.escape(rel_file)}">{html.escape(short_text(rel_file, 78))}</code></td>'
                f'<td>{html.escape(meta["producer"])}</td>'
                f'<td><span class="evidence-status-chip">{html.escape(meta["status"])}</span></td>'
                f'<td>{html.escape(meta["supports"])}</td>'
                f'<td class="mono-cell">{size}</td>'
                '</tr>'
                f'<tr class="evidence-detail-row" id="{detail_id}" hidden><td colspan="6">'
                '<div class="evidence-inline-detail">'
                f'<div class="evidence-inline-title"><strong>{html.escape(meta["type"])}</strong><code>{html.escape(rel_file)}</code></div>'
                f'<div class="evidence-inline-summary">{html.escape(summary)}</div>'
                + facts
                + '</div>'
                '</td></tr>'
            )
        evidence_table_html = (
            '<section data-file-tab-panel="evidence" hidden><table class="matrix evidence-table"><thead><tr>'
            '<th>Type</th><th>Artifact</th><th>Producer</th><th>Status</th><th>Supports</th><th>Size</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></section>'
        )
    else:
        evidence_table_html = '<section data-file-tab-panel="evidence" hidden><div class="empty-state">No evidence files were recorded for this run.</div></section>'
    out.append(evidence_table_html)
    out.append('</section>')
    return ''.join(out)


def _index_fr_catalog_for_tests(report_dir: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    catalog = load_json(report_dir / "fr-catalog.snapshot.json") or {}
    fr_by_id = {fr.get("id"): fr for fr in catalog.get("frs", []) or [] if fr.get("id")}
    tbt_by_id = {tbt.get("id"): tbt for tbt in catalog.get("tbts", []) or [] if tbt.get("id")}
    return fr_by_id, tbt_by_id


def _native_mapping_proposals(report_dir: Path) -> dict[str, dict]:
    proposals: dict[str, dict] = {}
    for rel in (
        "native-test-mapping-proposal.json",
        "config-update-proposal.json",
        "proposal.json",
    ):
        proposal = load_json(report_dir / rel) or {}
        for update in proposal.get("native_test_mapping_updates") or []:
            native = update.get("native_test") or {}
            for key in (native.get("native_path"), native.get("pack_id")):
                if key and key not in proposals:
                    proposals[str(key)] = update
    return proposals


def _native_mapping_recommendation_html(update: dict | None) -> str:
    if not update:
        return ""
    native = update.get("native_test") or {}
    target = update.get("target") or {}
    operation = str(update.get("operation") or "review")
    status = str(update.get("review_status") or "proposed")
    confidence = str(update.get("confidence") or "unknown")
    target_label = " / ".join(part for part in (target.get("fr"), target.get("tbt")) if part) or "No FR/TBT target"
    rationale = str(update.get("rationale") or "No rationale provided.")
    source_refs = [
        str(source.get("ref") or source.get("type") or "")
        for source in update.get("source_basis") or []
        if source.get("ref") or source.get("type")
    ]
    source_text = ", ".join(source_refs[:3]) or native.get("native_path") or native.get("pack_id") or "proposal"
    return (
        '<div class="assurance-map-recommendation">'
        '<div class="assurance-map-recommendation-head">'
        '<span>Agent review recommendation</span>'
        f'<b>{html.escape(operation.replace("_", " "))}</b>'
        f'<em>{html.escape(status.replace("_", " "))} · {html.escape(confidence)}</em>'
        '</div>'
        '<div class="assurance-map-recommendation-grid">'
        f'<div><span>Target</span><strong>{html.escape(target_label)}</strong></div>'
        f'<div><span>Source</span><strong>{html.escape(source_text)}</strong></div>'
        '</div>'
        f'<p>{html.escape(rationale)}</p>'
        '</div>'
    )


def _assurance_workflow_state(item: dict) -> str:
    assessment = str(item.get("assessment") or "")
    review_disposition = str(item.get("review_disposition") or "")
    if assessment == "not_assurance_relevant" or review_disposition == "reviewed_not_evidence":
        return "reviewed_not_evidence"
    if assessment == "bespoke_project_only" or review_disposition == "bespoke_project_only":
        return "bespoke_project_only"
    if review_disposition in {"needs_mapping_review", "left_unmapped"}:
        return "recommended"
    if not item.get("tbt") and item.get("native_path"):
        return "map"
    if item.get("source") == "planned_tbt":
        return "specify"
    if (
        item.get("safety") == "review_required"
        and item.get("tbt")
        and item.get("source") in {"generated", "existing_asvs"}
    ):
        return "review"
    if item.get("status") in {"ready_to_run", "executed"}:
        return "import"
    return "review"


def _review_board_cards(report_dir: Path) -> list[dict[str, Any]]:
    pack = load_json(report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json") or {}
    fr_by_id, tbt_by_id = _index_fr_catalog_for_tests(report_dir)
    mapping_proposals = _native_mapping_proposals(report_dir)
    cards: list[dict[str, Any]] = []

    def fr_summary(fr_id: str) -> str:
        fr = fr_by_id.get(fr_id) or {}
        if not fr:
            return ""
        title = str(fr.get("title") or fr_id)
        desc = str(fr.get("description") or "")
        return f"{fr_id}: {title}" + (f" - {short_text(desc, 150)}" if desc else "")

    def tbt_summary(tbt_id: str) -> str:
        tbt = tbt_by_id.get(tbt_id) or {}
        if not tbt:
            return ""
        title = str(tbt.get("title") or tbt_id)
        kind = str(tbt.get("type") or "test")
        proves = ", ".join(str(fr) for fr in tbt.get("proves") or [])
        compliance = ", ".join(
            f"{row.get('ruleset', '')} {row.get('row', '')}".strip()
            for row in tbt.get("compliance") or []
            if row.get("ruleset") or row.get("row")
        )
        suffix = f"{kind}"
        if proves:
            suffix += f" for {proves}"
        if compliance:
            suffix += f"; maps to {compliance}"
        return f"{tbt_id}: {title} ({suffix})"

    for index, item in enumerate(pack.get("tests") or []):
        if not (
            item.get("source") in {"generated", "planned_tbt", "wrapper_needed", "existing_asvs"}
            or item.get("safety") == "review_required"
            or item.get("assessment") in {"needs_design", "useful_with_wrapper", "candidate_inspiration", "not_assurance_relevant", "bespoke_project_only"}
        ):
            continue
        tbt_id = str(item.get("tbt") or "")
        tbt = tbt_by_id.get(tbt_id, {})
        fr_ids = item.get("frs") or tbt.get("proves") or []
        proposal = mapping_proposals.get(str(item.get("native_path") or "")) or mapping_proposals.get(str(item.get("pack_id") or ""))
        mapping_review = item.get("mapping_review") or {}
        target = (proposal or {}).get("target") or {}
        target_fr = str(target.get("fr") or "")
        target_tbt = str(target.get("tbt") or "")
        summary_fr_ids = list(dict.fromkeys([str(fr) for fr in (fr_ids or []) if fr] + ([target_fr] if target_fr else [])))
        summary_tbt_ids = list(dict.fromkeys([tbt_id] if tbt_id else [] + ([target_tbt] if target_tbt else [])))
        if target_tbt and target_tbt not in summary_tbt_ids:
            summary_tbt_ids.append(target_tbt)
        cards.append({
            "id": str(item.get("pack_id") or item.get("native_path") or tbt_id or f"card-{index}"),
            "selector_index": index + 1,
            "proposal_selector": "",
            "lane": _assurance_workflow_state(item),
            "title": item.get("title") or item.get("native_path") or tbt.get("title") or tbt_id or "Assurance item",
            "native_path": item.get("native_path") or "",
            "pack_path": item.get("pack_path") or "",
            "source": item.get("source") or "",
            "safety": item.get("safety") or "",
            "assessment": item.get("assessment") or "",
            "type": item.get("type") or tbt.get("type") or "test",
            "status": item.get("status") or "",
            "tbt": tbt_id,
            "frs": fr_ids,
            "recommendation": str((proposal or {}).get("operation") or mapping_review.get("operation") or ""),
            "confidence": str((proposal or {}).get("confidence") or mapping_review.get("confidence") or ""),
            "target": " / ".join(part for part in (target.get("fr"), target.get("tbt")) if part),
            "agentic_rationale": str((proposal or {}).get("rationale") or mapping_review.get("rationale") or ""),
            "discovery_rationale": str(item.get("rationale") or ""),
            "test_names": [str(name) for name in item.get("test_names") or [] if name],
            "review_status": str(mapping_review.get("review_status") or ""),
            "reviewed_by": str(mapping_review.get("reviewed_by") or ""),
            "source_basis": [source for source in mapping_review.get("source_basis") or [] if isinstance(source, dict)],
            "fr_summary": " | ".join(summary for summary in (fr_summary(fr_id) for fr_id in summary_fr_ids) if summary),
            "tbt_summary": " | ".join(summary for summary in (tbt_summary(tbt_id) for tbt_id in summary_tbt_ids) if summary),
        })
    proposal = load_json(report_dir / "native-test-mapping-proposal.json") or load_json(report_dir / "config-update-proposal.json") or load_json(report_dir / "proposal.json") or {}
    selector_by_key: dict[str, str] = {}
    for idx, update in enumerate(proposal.get("native_test_mapping_updates") or [], start=1):
        native = update.get("native_test") or {}
        selector = f"native_test_mapping_updates:{idx}"
        for key in (native.get("native_path"), native.get("pack_id")):
            if key:
                selector_by_key[str(key)] = selector
    for card in cards:
        card["proposal_selector"] = selector_by_key.get(card["native_path"]) or selector_by_key.get(card["id"]) or ""
        has_agentic_mapping = bool(
            card["proposal_selector"]
            and card.get("recommendation")
            and card.get("agentic_rationale")
        )
        if has_agentic_mapping and card["lane"] == "map":
            card["lane"] = "recommended"
    return cards


REVIEW_BOARD_LANES = {"map", "recommended", "reviewed_not_evidence", "bespoke_project_only", "specify", "review", "import", "blocked"}
REVIEW_BOARD_DECISIONS = {
    "",
    "accept_recommendation",
    "remap_as_orphan",
    "leave_unmapped",
    "mark_not_assurance_relevant",
    "mark_project_specific_only",
    "needs_new_tbt_fr",
    "approve_for_implementation",
    "approve_to_run",
    "send_back_to_review",
    "blocked",
}


def _board_card_state(card: dict[str, Any], *, generated_at: str = "") -> dict[str, Any]:
    lane = str(card.get("lane") or "blocked")
    decision = str(card.get("decision") or "")
    return {
        "id": str(card.get("id") or ""),
        "lane": lane if lane in REVIEW_BOARD_LANES else "blocked",
        "source": str(card.get("source") or ""),
        "title": str(card.get("title") or ""),
        "native_path": str(card.get("native_path") or ""),
        "pack_path": str(card.get("pack_path") or ""),
        "tbt": str(card.get("tbt") or ""),
        "frs": [str(fr) for fr in card.get("frs") or [] if fr],
        "target": str(card.get("target") or ""),
        "recommendation": str(card.get("recommendation") or ""),
        "decision": decision if decision in REVIEW_BOARD_DECISIONS else "",
        "reviewer_note": str(card.get("reviewer_note") or ""),
        "manual_test_path": str(card.get("manual_test_path") or ""),
        "agentic_rationale": str(card.get("agentic_rationale") or ""),
        "discovery_rationale": str(card.get("discovery_rationale") or ""),
        "confidence": str(card.get("confidence") or ""),
        "type": str(card.get("type") or ""),
        "status": str(card.get("status") or ""),
        "assessment": str(card.get("assessment") or ""),
        "safety": str(card.get("safety") or ""),
        "test_names": [str(name) for name in card.get("test_names") or [] if name],
        "review_status": str(card.get("review_status") or ""),
        "reviewed_by": str(card.get("reviewed_by") or ""),
        "source_basis": [source for source in card.get("source_basis") or [] if isinstance(source, dict)],
        "updated_at": generated_at,
    }


def _load_project_fr_board_state(report_dir: Path) -> dict[str, dict[str, Any]]:
    state = load_json(report_dir / "project-fr-board-state.json") or {}
    cards = state.get("cards") if isinstance(state, dict) else []
    out: dict[str, dict[str, Any]] = {}
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        card_id = str(card.get("id") or "")
        if card_id:
            out[card_id] = card
        tbt = str(card.get("tbt") or "")
        if tbt:
            out.setdefault(f"tbt:{tbt}", card)
        native_path = str(card.get("native_path") or "")
        if native_path:
            out.setdefault(f"native:{native_path}", card)
    return out


def _load_blueprint_proposal(report_dir: Path, source_repo: str = "") -> tuple[dict[str, Any] | None, Path | None]:
    candidates: list[Path] = []
    if source_repo:
        candidates.append(Path(source_repo) / "blueprint-proposal.json")
    candidates.extend([
        report_dir / "blueprint-proposal.json",
        report_dir.parent.parent / "blueprint-proposal.json",
    ])
    for candidate in candidates:
        if not candidate.exists():
            continue
        data = load_json(candidate) or {}
        if isinstance(data, dict) and data.get("candidates"):
            return data, candidate
    return None, None


def _blueprint_mapping_summary(candidate: dict[str, Any]) -> str:
    parts: list[str] = []
    for mapping in candidate.get("compliance_mappings") or []:
        ruleset = str(mapping.get("ruleset") or "")
        version = str(mapping.get("version") or "")
        rows = mapping.get("rows") or []
        domains = mapping.get("domains") or []
        count = len(rows) + len(domains)
        label = f"{ruleset} {version}".strip()
        if label:
            parts.append(f"{label}: {count}")
    return "; ".join(parts) or "No mapped rows"


def _blueprint_mapping_detail(candidate: dict[str, Any]) -> str:
    rows: list[str] = []
    for mapping in candidate.get("compliance_mappings") or []:
        ruleset = str(mapping.get("ruleset") or "")
        version = str(mapping.get("version") or "")
        relationship = str(mapping.get("relationship") or "")
        strength = str(mapping.get("traceability_strength") or "")
        refs = [str(row.get("row") or row.get("domain") or "") for row in (mapping.get("rows") or mapping.get("domains") or [])]
        refs = [ref for ref in refs if ref]
        rows.append(
            "<tr>"
            f"<td>{html.escape(ruleset)}</td>"
            f"<td>{html.escape(version)}</td>"
            f"<td>{html.escape(relationship)}</td>"
            f"<td>{html.escape(strength)}</td>"
            f"<td>{html.escape(', '.join(refs[:12]) + (' +' + str(len(refs) - 12) if len(refs) > 12 else ''))}</td>"
            "</tr>"
        )
    if not rows:
        return '<p class="muted">No compliance mappings were attached to this candidate.</p>'
    return (
        '<table class="matrix blueprint-proposal-detail-table"><thead><tr>'
        '<th>Regime</th><th>Version</th><th>Relationship</th><th>Strength</th><th>Rows / controls</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )


def render_blueprint_proposals_tab(report_dir: Path, source_repo: str = "") -> str:
    proposal, proposal_path = _load_blueprint_proposal(report_dir, source_repo)
    if not proposal:
        return (
            '<section class="card blueprint-proposal-card" data-blueprint-proposal-page>'
            '<div class="empty-state">No blueprint-proposal.json was found for this run. Run Step 2 to compare the supplied project FR catalog with reusable blueprint FR/TBT candidates.</div>'
            '</section>'
        )
    candidates = proposal.get("candidates") or []
    rows: list[str] = []
    for idx, candidate in enumerate(candidates, start=1):
        cid = str(candidate.get("id") or f"candidate-{idx}")
        detail_id = f"blueprint-proposal-detail-{idx}"
        tbts = candidate.get("blueprint_tbts") or []
        assumptions = candidate.get("assumptions") or []
        detail = (
            f'<tr class="blueprint-proposal-detail-row" id="{html.escape(detail_id)}" hidden><td colspan="8">'
            '<div class="blueprint-proposal-detail">'
            f'<p>{html.escape(str(candidate.get("rationale") or ""))}</p>'
            f'<div class="blueprint-proposal-detail-grid"><div><strong>Blueprint TBTs</strong><span>{html.escape(", ".join(tbts) or "-")}</span></div>'
            f'<div><strong>Assumptions</strong><span>{html.escape("; ".join(assumptions) or "-")}</span></div></div>'
            f'{_blueprint_mapping_detail(candidate)}'
            '</div></td></tr>'
        )
        rows.append(
            '<tr class="blueprint-proposal-row" tabindex="0" role="button" aria-expanded="false" '
            f'data-blueprint-candidate="{html.escape(cid)}" data-blueprint-detail="{html.escape(detail_id)}">'
            '<td><input type="checkbox" class="blueprint-proposal-check" data-blueprint-check checked aria-label="Select blueprint candidate"></td>'
            f'<td><code>{html.escape(str(candidate.get("blueprint_fr") or cid))}</code></td>'
            f'<td>{html.escape(str(candidate.get("confidence") or "medium"))}</td>'
            f'<td>{html.escape(str(len(tbts)))}</td>'
            f'<td>{html.escape(_blueprint_mapping_summary(candidate))}</td>'
            '<td><select class="blueprint-proposal-decision" data-blueprint-decision>'
            '<option value="accepted_as_is" selected>Accept</option>'
            '<option value="tailored">Tailor</option>'
            '<option value="rejected">Reject</option>'
            '<option value="not_applicable">Not applicable</option>'
            '</select></td>'
            f'<td><input class="blueprint-proposal-reason" data-blueprint-reason value="Accepted." aria-label="Decision reason"></td>'
            '<td><span class="instruction-expand">Open</span></td>'
            '</tr>' + detail
        )
    proposal_json = html.escape(json.dumps(proposal), quote=False)
    return (
        '<section class="card blueprint-proposal-card" data-blueprint-proposal-page '
        f'data-blueprint-proposal-path="{html.escape(str(proposal_path or "blueprint-proposal.json"))}">'
        f'<script type="application/json" data-blueprint-proposal-json>{proposal_json}</script>'
        '<div class="blueprint-proposal-toolbar">'
        '<div><strong>Blueprint Proposals</strong><span>Review reusable blueprint alignment against the supplied project catalog before anything becomes accepted scope.</span></div>'
        '<div class="blueprint-proposal-actions">'
        '<button type="button" class="mini-btn" data-blueprint-select-all>Select all</button>'
        '<button type="button" class="mini-btn" data-blueprint-clear-all>Clear all</button>'
        '</div></div>'
        '<table class="matrix blueprint-proposal-table"><colgroup><col style="width:5%"><col style="width:16%"><col style="width:8%"><col style="width:6%"><col style="width:18%"><col style="width:12%"><col style="width:25%"><col style="width:10%"></colgroup><thead><tr>'
        '<th>Select</th><th>Blueprint FR</th><th>Confidence</th><th>TBTs</th><th>Compliance mappings</th><th>Decision</th><th>Reason</th><th>Details</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
        '</section>'
    )



def _load_project_specific_fr_proposal(report_dir: Path, source_repo: str = "") -> tuple[dict[str, Any] | None, Path | None]:
    candidates: list[Path] = []
    if source_repo:
        candidates.append(Path(source_repo) / "project-specific-fr-proposal.json")
    candidates.extend([
        report_dir / "project-specific-fr-proposal.json",
        report_dir.parent.parent / "project-specific-fr-proposal.json",
        report_dir / "config-update-proposal.json",
        report_dir / "proposal.json",
    ])
    for candidate in candidates:
        if not candidate.exists():
            continue
        data = load_json(candidate) or {}
        if isinstance(data, dict) and data.get("mode") == "config_update_proposal":
            return data, candidate
    return None, None


def _project_specific_update_target(update: dict[str, Any]) -> str:
    parts = []
    for key in ("fr_id", "tbt_id", "row_id"):
        value = update.get(key)
        if value:
            parts.append(str(value))
    target = update.get("target")
    if isinstance(target, dict):
        kind = str(target.get("kind") or "target")
        ident = str(target.get("id") or "")
        if ident:
            parts.append(f"{kind}:{ident}")
    return " / ".join(parts) or "scope item"


def _project_specific_source_basis(update: dict[str, Any]) -> str:
    refs = []
    for item in update.get("source_basis") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("type") or "source")
        ref = str(item.get("ref") or item.get("path") or "")
        refs.append(f"{label}: {ref}" if ref else label)
    return "; ".join(refs) or "-"


def render_project_specific_frs_tab(report_dir: Path, source_repo: str = "") -> str:
    proposal, proposal_path = _load_project_specific_fr_proposal(report_dir, source_repo)
    if not proposal:
        return (
            '<section class="card project-specific-fr-card" data-project-specific-fr-page>'
            '<div class="blueprint-proposal-toolbar">'
            '<div><strong>Project-Specific FRs</strong><span>Review proposed bespoke FR/TBT gaps after supplied catalog and blueprint alignment have been considered.</span></div>'
            '<div class="blueprint-proposal-actions">'
            '<button type="button" class="mini-btn" data-project-specific-fr-prompt>Generate project-specific FR prompt</button>'
            '</div></div>'
            '<div class="empty-state">No project-specific FR proposal has been generated yet. This does not mean the project has no FR catalog; it means no additional bespoke FR/TBT gap proposal has been produced after blueprint review. Generate the prompt after reviewing Blueprint Proposals, then ask the agent to create a review-gated config update proposal.</div>'
            '</section>'
        )
    updates = proposal.get("fr_catalog_updates") or []
    review_required = proposal.get("review_required") or []
    rows: list[str] = []
    for idx, update in enumerate(updates, start=1):
        if not isinstance(update, dict):
            continue
        detail_id = f"project-specific-fr-detail-{idx}"
        operation = str(update.get("operation") or "update")
        target = _project_specific_update_target(update)
        confidence = str(update.get("confidence") or "")
        status = str(update.get("review_status") or "proposed")
        rationale = str(update.get("rationale") or "")
        source_basis = _project_specific_source_basis(update)
        proposed_fields = update.get("proposed_fields") or {}
        detail_json = html.escape(json.dumps(proposed_fields, indent=2), quote=False) if proposed_fields else "-"
        rows.append(
            '<tr class="project-specific-fr-row" tabindex="0" role="button" aria-expanded="false" '
            f'data-project-specific-fr-detail="{html.escape(detail_id)}">'
            f'<td><code>{html.escape(operation)}</code></td>'
            f'<td>{html.escape(target)}</td>'
            f'<td>{html.escape(status)}</td>'
            f'<td>{html.escape(confidence or "-")}</td>'
            f'<td>{html.escape(short_text(rationale, 180) or "-")}</td>'
            '<td><span class="instruction-expand">Open</span></td>'
            '</tr>'
            f'<tr class="project-specific-fr-detail-row" id="{html.escape(detail_id)}" hidden><td colspan="6">'
            '<div class="blueprint-proposal-detail">'
            '<div class="blueprint-proposal-detail-grid">'
            f'<div><strong>Source basis</strong><span>{html.escape(source_basis)}</span></div>'
            f'<div><strong>Proposed fields</strong><span><pre>{detail_json}</pre></span></div>'
            '</div>'
            '</div></td></tr>'
        )
    review_rows: list[str] = []
    for idx, item in enumerate(review_required, start=1):
        if not isinstance(item, dict):
            continue
        review_rows.append(
            '<tr>'
            f'<td>{html.escape(str(item.get("item") or f"review-{idx}"))}</td>'
            f'<td>{html.escape(str(item.get("question") or ""))}</td>'
            f'<td>{html.escape(str(item.get("why") or ""))}</td>'
            '</tr>'
        )
    update_table = (
        '<table class="matrix project-specific-fr-table"><thead><tr>'
        '<th>Operation</th><th>Target</th><th>Status</th><th>Confidence</th><th>Rationale</th><th>Details</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
        if rows else '<div class="empty-state">This proposal has no FR/TBT updates yet.</div>'
    )
    review_table = (
        '<table class="matrix project-specific-review-table"><thead><tr><th>Item</th><th>Question</th><th>Why</th></tr></thead><tbody>'
        + ''.join(review_rows) + '</tbody></table>'
        if review_rows else '<p class="muted">No open review questions were recorded.</p>'
    )
    return (
        '<section class="card project-specific-fr-card" data-project-specific-fr-page '
        f'data-project-specific-fr-proposal-path="{html.escape(str(proposal_path or "project-specific-fr-proposal.json"))}">'
        '<div class="blueprint-proposal-toolbar">'
        f'<div><strong>Project-Specific FRs</strong><span>{html.escape(str(proposal_path or "project-specific-fr-proposal.json"))}</span></div>'
        '<div class="blueprint-proposal-actions">'
        '<button type="button" class="mini-btn" data-project-specific-fr-prompt>Regenerate prompt</button>'
        '</div></div>'
        '<div class="project-specific-fr-summary">'
        f'<span><b>{len(updates)}</b> proposed FR/TBT update(s)</span>'
        f'<span><b>{len(review_required)}</b> review question(s)</span>'
        '</div>'
        '<div class="project-specific-fr-section"><h3>Proposed scope updates</h3>' + update_table + '</div>'
        '<div class="project-specific-fr-section"><h3>Review required</h3>' + review_table + '</div>'
        '</section>'
    )

def _merge_project_fr_board_state(cards: list[dict[str, Any]], persisted: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    mutable_fields = {
        "lane",
        "target",
        "decision",
        "reviewer_note",
        "manual_test_path",
    }
    merged: list[dict[str, Any]] = []
    for card in cards:
        next_card = dict(card)
        saved = (
            persisted.get(str(card.get("id") or ""))
            or persisted.get(f"tbt:{str(card.get('tbt') or '')}")
            or persisted.get(f"native:{str(card.get('native_path') or '')}")
            or {}
        )
        derived_lane = str(card.get("lane") or "")
        manifest_ready = (
            str(card.get("status") or "") in {"ready_to_run", "executed"}
            and str(card.get("safety") or "") == "non_destructive"
        )
        for field in mutable_fields:
            value = saved.get(field)
            if value is None:
                continue
            if field == "lane" and value not in REVIEW_BOARD_LANES:
                continue
            if field == "lane" and manifest_ready:
                value = derived_lane
            if field == "lane" and derived_lane == "recommended" and value == "map":
                value = derived_lane
            if field == "decision" and value not in REVIEW_BOARD_DECISIONS:
                continue
            next_card[field] = value
        merged.append(next_card)
    return merged


def write_project_fr_board_state(
    report_dir: Path,
    cards: list[dict[str, Any]],
    *,
    project: str = "",
    run_id: str = "",
    generated_at: str = "",
) -> dict[str, Any]:
    """Write the current report-local Project FR board state artifact."""
    state = {
        "schema_version": 1,
        "mode": "project_fr_board_state",
        "project": project,
        "run_id": run_id,
        "generated_at": generated_at or "1970-01-01T00:00:00Z",
        "cards": [_board_card_state(card, generated_at=generated_at or "1970-01-01T00:00:00Z") for card in cards],
    }
    path = report_dir / "project-fr-board-state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")
    record_report_artifact(report_dir, path)
    return state


def render_native_review_board_page(
    report_dir: Path,
    fr_catalog_html: str = "",
    *,
    project: str = "",
    run_id: str = "",
    generated_at: str = "",
    source_repo: str = "",
) -> str:
    cards = _review_board_cards(report_dir)
    cards = _merge_project_fr_board_state(cards, _load_project_fr_board_state(report_dir))
    board_state = write_project_fr_board_state(
        report_dir,
        cards,
        project=project,
        run_id=run_id,
        generated_at=generated_at,
    )
    lanes = [
        ("map", "Map Orphan Tests", "Discovered tests with no FR/TBT mapping"),
        ("recommended", "Review Agentic Mapping", "Agent mapping recommendation needs approval"),
        ("reviewed_not_evidence", "Reviewed: Not Evidence", "Inspected native tests intentionally excluded from assurance evidence"),
        ("bespoke_project_only", "Project Only", "May justify bespoke project FR/TBT; not reusable blueprint scope"),
        ("specify", "Draft Tests for FR", "Generate review-required test drafts for mapped FR/TBT coverage"),
        ("review", "Review Agentic Tests", "Agent draft or wrapper needs approval"),
        ("import", "Run Approved Tests", "Execute approved tests and scan results"),
        ("blocked", "Blocked", "Needs more input"),
    ]
    cards_by_lane: dict[str, list[dict[str, Any]]] = {lane: [] for lane, _, _ in lanes}
    for card in cards:
        cards_by_lane.setdefault(card["lane"], []).append(card)

    def card_display_title(card: dict[str, Any]) -> str:
        title = str(card.get("title") or "")
        lane = str(card.get("lane") or "")
        tbt_id = str(card.get("tbt") or "")
        fr_ids = [str(fr) for fr in card.get("frs") or [] if fr]
        if lane != "map" and tbt_id and fr_ids:
            return f"{fr_ids[0]} -> {tbt_id}"
        replacements = {
            "unit": "Unit test for",
            "integration": "Integration test for",
            "e2e": "E2E test for",
            "load": "Load test for",
            "test": "Test for",
        }
        for kind, label in replacements.items():
            pattern = re.compile(rf"^{re.escape(kind)}\s+test\s+basis\s+for\s+", re.IGNORECASE)
            if pattern.search(title):
                return pattern.sub(label + " ", title)
        return re.sub(r"^test\s+basis\s+for\s+", "Test for ", title, flags=re.IGNORECASE)

    def card_html(card: dict[str, Any]) -> str:
        display_title = card_display_title(card)
        return (
            '<article class="review-board-card" draggable="true"'
            f' data-review-card="{html.escape(card["id"])}"'
            f' data-origin-lane="{html.escape(card.get("lane") or "")}"'
            f' data-selector="{html.escape(card.get("proposal_selector") or "")}"'
            f' data-title="{html.escape(display_title)}"'
            f' data-native-path="{html.escape(card.get("native_path") or "")}"'
            f' data-tbt="{html.escape(card.get("tbt") or "")}"'
            f' data-frs="{html.escape(", ".join(card.get("frs") or []))}"'
            f' data-fr-summary="{html.escape(card.get("fr_summary") or "")}"'
            f' data-tbt-summary="{html.escape(card.get("tbt_summary") or "")}"'
            f' data-target="{html.escape(card.get("target") or "")}"'
            f' data-recommendation="{html.escape(card.get("recommendation") or "")}"'
            f' data-type="{html.escape(card.get("type") or "")}"'
            f' data-status="{html.escape(card.get("status") or "")}"'
            f' data-pack-path="{html.escape(card.get("pack_path") or "")}"'
            f' data-source="{html.escape(card.get("source") or "")}"'
            f' data-safety="{html.escape(card.get("safety") or "")}"'
            f' data-assessment="{html.escape(card.get("assessment") or "")}"'
            f' data-confidence="{html.escape(card.get("confidence") or "")}"'
            f' data-test-names="{html.escape(json.dumps(card.get("test_names") or []))}"'
            f' data-review-status="{html.escape(card.get("review_status") or "")}"'
            f' data-reviewed-by="{html.escape(card.get("reviewed_by") or "")}"'
            f' data-source-basis="{html.escape(json.dumps(card.get("source_basis") or []))}"'
            f' data-review-decision="{html.escape(card.get("decision") or "")}"'
            f' data-reviewer-note="{html.escape(card.get("reviewer_note") or "")}"'
            f' data-manual-test-path="{html.escape(card.get("manual_test_path") or "")}"'
            f' data-agentic-rationale="{html.escape(short_text(card.get("agentic_rationale") or "", 500))}"'
            f' data-discovery-rationale="{html.escape(short_text(card.get("discovery_rationale") or "", 500))}">'
            '<button type="button" class="review-card-pick" data-review-card-pick aria-label="Select card for prompt"></button>'
            '<div class="review-board-card-head">'
            f'<strong>{html.escape(short_text(display_title, 74))}</strong>'
            '</div>'
            '</article>'
        )

    lane_html = []
    for lane_id, title, hint in lanes:
        lane_cards = cards_by_lane.get(lane_id, [])
        prompt_label = "Review" if lane_id == "recommended" else "Implement" if lane_id == "review" else "Prompt"
        if lane_id == "import":
            lane_action_html = (
                '<div class="review-lane-action-grid">'
                '<button type="button" class="review-lane-prompt-btn" data-review-lane-prompt="import" data-review-lane-action="run-only">Tests only</button>'
                '<button type="button" class="review-lane-prompt-btn" data-review-lane-prompt="import" data-review-lane-action="fresh-scan">Full scan</button>'
                '</div>'
            )
        else:
            lane_action_html = (
                f'<button type="button" class="review-lane-prompt-btn" data-review-lane-prompt="{html.escape(lane_id)}">{prompt_label}</button>'
            )
        agent_icon = (
            '<svg class="review-lane-agent-icon" viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M12 3v3"/><path d="M7 6h10"/><rect x="5" y="8" width="14" height="10" rx="3"/>'
            '<path d="M9 12h.01"/><path d="M15 12h.01"/><path d="M10 15h4"/>'
            '</svg>'
            if lane_id in {"recommended", "review"} else ""
        )
        lane_html.append(
            '<section class="review-board-lane" data-review-lane="' + html.escape(lane_id) + '">'
            '<div class="review-board-lane-head">'
            f'<strong>{agent_icon}{html.escape(title)}</strong><b>{len(lane_cards)}</b>'
            f'<span>{html.escape(hint)}</span>'
            f'{lane_action_html}'
            '</div>'
            '<div class="review-board-dropzone">'
            + ''.join(card_html(card) for card in lane_cards)
            + '</div></section>'
        )

    cards_json = html.escape(json.dumps(cards), quote=False)
    board_state_json = html.escape(json.dumps(board_state), quote=False)
    blueprint_proposals_html = render_blueprint_proposals_tab(report_dir, source_repo)
    project_specific_frs_html = render_project_specific_frs_tab(report_dir, source_repo)
    report_dir_s = html.escape(str(report_dir))
    manifest_path = html.escape(str(report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json"))
    proposal_path = html.escape(str(report_dir / "native-test-mapping-proposal.json"))
    fr_tab_html = (
        '<button type="button" class="review-board-tab active" data-review-board-tab="project-frs">Supplied Catalog</button>'
        if fr_catalog_html else ""
    )
    blueprint_tab_active = "" if fr_catalog_html else " active"
    board_tab_active = ""
    fr_pane_html = (
        '<div class="review-board-pane active" data-review-board-pane="project-frs">'
        + fr_catalog_html +
        '</div>'
        if fr_catalog_html else ""
    )
    blueprint_pane_active = "" if fr_catalog_html else " active"
    board_pane_active = ""
    catalog_badge = ""
    if (report_dir / "fr-catalog.snapshot.json").exists():
        catalog_badge = f'<code>{html.escape((report_dir / "fr-catalog.snapshot.json").name)}</code>'
    return (
        '<section class="card review-board-card-shell">'
        '<div class="page-intro review-board-intro"><div><h2>Project FRs</h2>'
        '<ul class="review-board-intro-list">'
        '<li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg><span>Functional Requirements (FR) have one or more tests (TBT) that provide evidence for Assurance; the supplied catalog is the project-declared baseline scope until reviewed updates change it.</span></li>'
        '<li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg><span>Blueprint alignment: reusable security/compliance blueprints can confirm, standardise, extend, or reject mappings through review-gated proposals.</span></li>'
        '<li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg><span>Project-specific discovery: bespoke FR/TBT gaps found in the codebase are proposed separately before the Board creates, reviews, or runs tests.</span></li>'
        '</ul>'
        '</div>'
        f'{catalog_badge}'
        '</div>'
        f'<div class="review-board" data-review-board data-report-dir="{report_dir_s}" data-manifest="{manifest_path}" data-proposal="{proposal_path}">'
        f'<script type="application/json" data-review-board-cards>{cards_json}</script>'
        f'<script type="application/json" data-review-board-state>{board_state_json}</script>'
        '<div class="review-board-tabs" role="tablist" aria-label="Native review board views">'
        + fr_tab_html +
        f'<button type="button" class="review-board-tab{blueprint_tab_active}" data-review-board-tab="blueprints">Blueprint Proposals</button>'
        '<button type="button" class="review-board-tab" data-review-board-tab="project-specific">Project-Specific FRs</button>'
        f'<button type="button" class="review-board-tab{board_tab_active}" data-review-board-tab="board">Board</button>'
        '</div>'
        + fr_pane_html +
        f'<div class="review-board-pane{blueprint_pane_active}" data-review-board-pane="blueprints">'
        + blueprint_proposals_html +
        '</div>'
        '<div class="review-board-pane" data-review-board-pane="project-specific">'
        + project_specific_frs_html +
        '</div>'
        f'<div class="review-board-pane{board_pane_active}" data-review-board-pane="board">'
        '<div class="review-board-toolbar"><span>Move cards or select a subset, then use the lane action to generate the right prompt, review brief, or command.</span>'
        '<div class="review-board-toolbar-actions">'
        '<button type="button" class="review-board-save-btn" data-review-board-save>Persist board state</button>'
        '</div></div>'
        '<div class="review-board-workspace">'
        '<div class="review-board-lanes">' + ''.join(lane_html) + '</div>'
        '<aside class="review-board-context" data-review-context>'
        '<div class="review-context-body" hidden>'
        '<div class="review-context-head"><button type="button" class="review-context-close" data-review-context-close aria-label="Close context">×</button><span>Selected card</span><strong data-review-context-title></strong><em data-review-context-meta></em></div>'
        '<div class="review-context-grid">'
        '<div><span data-review-context-source-label>Native path</span><strong data-review-context-native></strong></div>'
        '<div><span data-review-context-test-path-label>Test file path</span><strong data-review-context-test-path></strong></div>'
        '<div><span>Current TBT</span><strong data-review-context-tbt></strong></div>'
        '<div><span>Current FRs</span><strong data-review-context-frs></strong></div>'
        '<div><span data-review-context-target-label>Recommendation</span><strong data-review-context-target></strong></div>'
        '</div>'
        '<div class="review-context-proof">'
        '<div><span>FR context</span><p data-review-context-fr-summary></p></div>'
        '<div><span>TBT context</span><p data-review-context-tbt-summary></p></div>'
        '</div>'
        '<div class="review-context-rationale"><span data-review-context-rationale-label>Rationale</span><p data-review-context-rationale></p></div>'
        '<div class="review-context-controls" data-review-context-map-controls>'
        '<label><span data-review-operation-label>Mapping decision</span><select data-review-map-operation><option value="accept_recommendation">Accept recommendation</option><option value="remap_as_orphan">Clear mapping / remap as orphan</option><option value="leave_unmapped">Leave unmapped</option><option value="mark_not_assurance_relevant">Mark not assurance relevant</option><option value="mark_project_specific_only">Project only / bespoke FR</option><option value="needs_new_tbt_fr">Needs new TBT/FR</option><option value="blocked">Blocked</option></select></label>'
        '<label><span data-review-fr-label>Suggested FR</span><input data-review-map-fr placeholder="FR-xxx"></label>'
        '<label><span data-review-tbt-label>Suggested TBT</span><input data-review-map-tbt placeholder="TBT-xxx"></label>'
        '<label class="review-context-wide"><span data-review-test-path-input-label>Manual test path</span><input data-review-test-path placeholder="tests/asvs/unit/TBT-xxx.assurance.test.js"></label>'
        '<label class="review-context-wide"><span>Reviewer note</span><textarea data-review-map-note rows="3" placeholder="Why this decision is acceptable or what is still missing"></textarea></label>'
        '<button type="button" class="mini-btn" data-review-apply-context>Update card decision</button>'
        '</div>'
        '</div>'
        '</aside>'
        '</div>'
        '</div>'
        '<aside class="review-prompt-drawer" data-review-prompt-drawer hidden>'
        '<div class="review-prompt-drawer-head">'
        '<div><span data-review-prompt-kicker>Prompt</span><strong data-review-prompt-title></strong><em data-review-prompt-scope></em></div>'
        '<div class="review-prompt-head-actions"><button type="button" class="mini-btn" data-review-prompt-copy>Copy prompt</button><button type="button" class="review-context-close" data-review-prompt-close aria-label="Close prompt">×</button></div>'
        '</div>'
        '<div class="review-prompt-warning" data-review-prompt-warning hidden></div>'
        '<pre><code data-review-prompt-body></code></pre>'
        '</aside>'
        '</div></section>'
    )


def render_assurance_tests_page(report_dir: Path) -> str:
    pack = load_json(report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json") or {}
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    fr_by_id, tbt_by_id = _index_fr_catalog_for_tests(report_dir)
    mapping_proposals = _native_mapping_proposals(report_dir)
    tests = pack.get("tests") or []
    specs = {
        item.get("tbt"): item
        for item in pack.get("generated_specifications", []) or []
        if item.get("tbt")
    }
    queue = [
        item for item in tests
        if item.get("source") in {"generated", "planned_tbt", "wrapper_needed"}
        or item.get("safety") == "review_required"
        or item.get("assessment") in {"needs_design", "useful_with_wrapper", "candidate_inspiration"}
    ]
    queue.sort(key=lambda item: (str(item.get("tbt") or item.get("pack_id") or ""), str(item.get("pack_id") or "")))
    generated = len([item for item in queue if item.get("source") == "generated"])
    planned = len([item for item in queue if item.get("source") == "planned_tbt"])
    need_mapping = len([item for item in queue if not item.get("tbt") and item.get("native_path")])
    review_required = len([item for item in queue if item.get("safety") == "review_required"])
    need_design = len([item for item in queue if item.get("source") == "planned_tbt"])
    source_repo = str(evidence.get("source_repo") or evidence.get("target_dir") or "")
    source_mount = str(Path(source_repo).parent) if source_repo else ""
    project_name = str(evidence.get("repository") or evidence.get("project") or "target-project")
    run_id = str(evidence.get("run_id") or report_dir.name)
    fr_catalog_arg = str(report_dir / "fr-catalog.snapshot.json")
    junit_output_arg = str(report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "results" / "approved-tbt-junit.xml")
    report_dir_arg = str(report_dir)

    def workflow_state(item: dict) -> str:
        if not item.get("tbt") and item.get("native_path"):
            return "map"
        if item.get("source") == "planned_tbt":
            return "design"
        if item.get("safety") == "review_required" and item.get("tbt") and item.get("source") == "generated":
            return "approve"
        if item.get("status") in {"ready_to_run", "executed"}:
            return "import"
        return "review"

    state_counts = Counter(workflow_state(item) for item in queue)
    fr_options_html = ''.join(
        f'<option value="{html.escape(fr_id)}">{html.escape(fr_id)} - {html.escape(short_text(fr.get("title", fr_id), 80))}</option>'
        for fr_id, fr in sorted(fr_by_id.items())
    )
    tbt_options_html = ''.join(
        f'<option value="{html.escape(tbt_id)}" data-fr="{html.escape(str((tbt.get("proves") or [""])[0]))}">'
        f'{html.escape(tbt_id)} - {html.escape(short_text(tbt.get("title", tbt_id), 80))}</option>'
        for tbt_id, tbt in sorted(tbt_by_id.items())
    )
    next_prompt_panel = (
        '<div class="assurance-next-step"'
        f' data-project="{html.escape(project_name)}"'
        f' data-run-id="{html.escape(run_id)}"'
        f' data-report-dir="{html.escape(report_dir_arg)}"'
        f' data-source-repo="{html.escape(source_repo)}"'
        f' data-source-mount="{html.escape(source_mount)}"'
        f' data-fr-catalog="{html.escape(fr_catalog_arg)}"'
        f' data-junit-output="{html.escape(junit_output_arg)}">'
        '<div class="assurance-next-step-head"><div><strong id="assurance-next-title">TBT Prompts</strong>'
        '<span id="assurance-next-subtitle">Agent handoff generated from selected workflow rows</span></div>'
        '<div class="assurance-next-tools">'
        '<label><span>Prompt type</span><select id="assurance-next-mode">'
        '<option value="auto">Auto from selection</option>'
        '<option value="map">Map Test to FR/TBT</option>'
        '<option value="design">Draft Tests for FR</option>'
        '<option value="approve">Review Agentic Tests</option>'
        '<option value="import">Run Approved Tests</option>'
        '</select></label>'
        '<button type="button" class="mini-btn" id="copy-assurance-command">Copy prompt</button>'
        '</div></div>'
        '<pre><code id="assurance-next-command">Choose rows in the Workflow tab, then open TBT Prompts for the generated agent handoff.</code></pre>'
        '</div>'
    )

    out = [
        '<section class="card assurance-tests-card">'
        '<div class="page-intro assurance-tests-intro"><div><h2>Assurance Tests</h2>'
        '<p>Turn missing assurance into evidence without blurring the line between a draft test and a proven control.</p>'
        '<div class="assurance-intro-facts">'
        '<span><b>Start here</b> Map native tests or create the tests needed for an FR.</span>'
        '<span><b>Human gate</b> Review generated drafts before implementation.</span>'
        '<span><b>Evidence rule</b> Only imported execution results can satisfy assurance.</span>'
        '</div></div></div>'
        '<div class="assurance-page-tabs" role="tablist" aria-label="Assurance Tests views">'
        '<button type="button" class="assurance-page-tab active" data-assurance-page-tab="workflow">Workflow</button>'
        '<button type="button" class="assurance-page-tab" data-assurance-page-tab="next">TBT Prompts</button>'
        '</div>'
        '<div class="assurance-page-pane active" data-assurance-page-pane="workflow">'
        '<div class="assurance-workflow-explainer">'
        '<div><strong>Current workflow</strong>'
        '<span>Select the stage that matches the row state, choose the rows, then open TBT Prompts for the exact handoff.</span></div>'
        '<div class="assurance-workflow-rule"><b>No shortcut:</b> draft or planned tests stay review-required until approved, run, and imported as observed evidence.</div>'
        '</div>'
        '<div class="assurance-workflow-tabs" role="tablist" aria-label="Assurance test workflow">'
        f'<button type="button" class="assurance-workflow-tab active" data-assurance-state-tab="map" data-tooltip="Map native tests&#10;&#10;Assign discovered project tests to an existing FR/TBT, or propose a new FR/TBT when none fits."><span class="workflow-step-num">1</span><span><strong>Map Test to FR/TBT</strong><em>Classify native tests</em></span><b>{state_counts.get("map", 0)}</b></button>'
        f'<button type="button" class="assurance-workflow-tab" data-assurance-state-tab="design" data-tooltip="Draft tests for FR&#10;&#10;Define the TBT or draft test needed for a project FR. This creates or updates a review-required draft, not evidence."><span class="workflow-step-num">2</span><span><strong>Draft Tests for FR</strong><em>Draft missing coverage</em></span><b>{state_counts.get("design", 0)}</b></button>'
        f'<button type="button" class="assurance-workflow-tab" data-assurance-state-tab="approve" data-tooltip="Review agentic tests&#10;&#10;Check generated drafts for relevance, safety, and traceability before implementation."><span class="workflow-step-num">3</span><span><strong>Review Agentic Tests</strong><em>Approve safe tests</em></span><b>{state_counts.get("approve", 0)}</b></button>'
        f'<button type="button" class="assurance-workflow-tab" data-assurance-state-tab="import" data-tooltip="Run approved tests&#10;&#10;Execute approved tests and import observed results, such as JUnit XML, into the next scan."><span class="workflow-step-num">4</span><span><strong>Run Approved Tests</strong><em>Record real results</em></span><b>{state_counts.get("import", 0)}</b></button>'
        '</div>'
    ]
    if not queue:
        out.append(
            '<div class="empty-state">No generated or planned assurance tests are waiting for review.</div>'
            '</div><div class="assurance-page-pane" data-assurance-page-pane="next">'
            f'{next_prompt_panel}</div></section>'
        )
        return ''.join(out)

    rows = []
    for idx, item in enumerate(queue):
        tbt_id = str(item.get("tbt") or "")
        spec = specs.get(tbt_id) or {}
        tbt = tbt_by_id.get(tbt_id, {})
        fr_ids = item.get("frs") or tbt.get("proves") or spec.get("frs") or []
        fr_titles = [fr_by_id.get(fr_id, {}).get("title", fr_id) for fr_id in fr_ids]
        is_unmapped_native = not tbt_id and item.get("native_path")
        mapping_proposal = mapping_proposals.get(str(item.get("native_path") or "")) or mapping_proposals.get(str(item.get("pack_id") or ""))
        is_planned_tbt = item.get("source") == "planned_tbt"
        is_approvable = item.get("safety") == "review_required" and bool(tbt_id) and item.get("source") == "generated"
        state = workflow_state(item)
        title = item.get("title") or tbt.get("title") or tbt_id or item.get("native_path") or item.get("pack_id", "Assurance test")
        source = str(item.get("source", "-")).replace("_", " ")
        status = str(item.get("status", "-")).replace("_", " ")
        safety = str(item.get("safety", "-")).replace("_", " ")
        assessment = str(item.get("assessment", "-")).replace("_", " ")
        test_type = str(item.get("type") or spec.get("type") or "test")
        pack_path = str(item.get("pack_path") or spec.get("spec_path") or "-")
        runner = str(item.get("runner") or spec.get("runner") or "-")
        case_names = [
            str(case.get("name") or case.get("ref") or "")
            for case in item.get("cases") or []
            if case.get("name") or case.get("ref")
        ]
        evidence_state = str(spec.get("evidence_state") or "not observed").replace("_", " ")
        rows_for_item = item.get("ruleset_rows") or spec.get("ruleset_rows") or []
        rules = ", ".join(
            f"{row.get('ruleset', '')} {row.get('row', '')}".strip()
            for row in rows_for_item[:6]
            if row.get("ruleset") or row.get("row")
        ) or "-"
        decision_id = f"assurance-test-{idx}"
        approval_key = html.escape(str(item.get("pack_id") or tbt_id or decision_id))
        type_notes = {
            "unit": "Unit-level test. Useful when the assertion proves a focused control decision without needing the full app.",
            "integration": "Integration test. Use this when the proof depends on several app components working together.",
            "e2e": "End-to-end test. Use this when the user-visible workflow is the assurance proof.",
            "load": "Load or resilience test. Use bounded fixtures and explicit thresholds.",
            "scanner": "Scanner evidence. Usually supporting evidence unless the TBT is scanner-specific.",
            "manual_review": "Manual review evidence. A human artifact or approval is expected.",
            "document_review": "Document review evidence. The proof is an inspected document or policy artifact.",
            "approval": "Approval evidence. The proof is a recorded role or gate decision.",
            "test": "Generic test basis. Refine the test type during review if the proof path is clearer.",
        }
        status_notes = {
            "copied": "Found in the native project tests and copied into the report for assessment. Not accepted as assurance yet.",
            "planned": "Declared as needed coverage, but no executable assurance test has been approved yet.",
            "generated": "Draft scaffold exists. It still needs review, implementation, and observed execution evidence.",
            "executed": "Execution evidence has been imported and can be evaluated against the mapped TBT.",
            "deprecated": "No longer intended to be used as current assurance evidence.",
        }
        if mapping_proposal:
            target = mapping_proposal.get("target") or {}
            recommendation_value = str(mapping_proposal.get("operation") or "review").replace("_", " ")
            recommendation_note = "Agent review is available in this row. Expand the recommendation panel before accepting any mapping."
            if target.get("fr") or target.get("tbt"):
                recommendation_note = f"Suggested target: {' / '.join(part for part in (target.get('fr'), target.get('tbt')) if part)}. Review before applying."
        elif is_unmapped_native:
            recommendation_value = "Needs review"
            recommendation_note = "No agent recommendation is available yet. Run the Map prompt to inspect this native test."
        else:
            recommendation_value = "Not required"
            recommendation_note = "This row is not waiting on native-test mapping."
        tbt_value = tbt_id or "Unmapped"
        tbt_note = (
            f"Mapped to {tbt_id}; JUnit evidence must carry this identifier."
            if tbt_id
            else "Awaiting map review. This native test does not yet prove a specific TBT."
        )
        fr_value = ", ".join(fr_ids) or "Awaiting map review"
        fr_note = (
            "These FRs would receive evidence if the mapped TBT is later executed and imported."
            if fr_ids
            else "No FR is claimed yet. The reviewer must map the test to a TBT/FR or leave it unmapped."
        )
        review_value = "Select row" if is_unmapped_native else "Review draft" if is_approvable else "Draft Tests for FR" if is_planned_tbt else "Inspect"
        review_note = (
            "Select this row, open TBT Prompts, and run the Map workflow."
            if is_unmapped_native
            else "Approve only after the draft is safe, relevant, and traceable."
            if is_approvable
            else "Generate a review-required specification for this missing TBT."
            if is_planned_tbt
            else "Inspect the row details and evidence provenance."
        )
        detail_bits = [
            ("TBT", tbt_value, tbt_note),
            ("Type", test_type, type_notes.get(test_type, "Test execution type. Review whether this is the right proof shape.")),
            ("Test basis", title, f"Source path: {pack_path}. This is the item being assessed for assurance use."),
            ("FRs", fr_value, fr_note),
            ("Status", status, status_notes.get(status, "Current lifecycle state in the assurance test pack.")),
            ("Recommendation", recommendation_value, recommendation_note),
            ("Review action", review_value, review_note),
            ("Evidence", evidence_state, "Only observed execution or accepted manual evidence can satisfy assurance."),
            ("Rules", rules, "Compliance rows this test may help satisfy after mapping and evidence import."),
            ("Runner", runner, "Expected runner or toolchain for producing importable evidence."),
        ]
        detail_html = ''.join(
            '<div class="assurance-detail-item">'
            f'<span>{html.escape(label)}</span>'
            f'<strong>{html.escape(value)}</strong>'
            f'<p>{html.escape(note)}</p>'
            '</div>'
            for label, value, note in detail_bits
        )
        map_controls_html = ""
        if is_unmapped_native:
            recommendation_html = _native_mapping_recommendation_html(mapping_proposal)
            map_controls_html = (
                recommendation_html +
                '<div class="assurance-map-controls" data-map-controls>'
                '<label><span>Mapping decision</span><select data-map-operation>'
                '<option value="leave_unmapped">Leave unmapped until inspected</option>'
                '<option value="map_native_test_to_existing_tbt">Map to existing FR/TBT</option>'
                '<option value="create_tbt_under_existing_fr">Create TBT under existing FR</option>'
                '<option value="create_new_fr_and_tbt">Create new FR and TBT</option>'
                '<option value="mark_not_assurance_relevant">Mark not assurance relevant</option><option value="mark_project_specific_only">Project only / bespoke FR</option>'
                '</select></label>'
                f'<label><span>Suggested FR</span><select data-map-fr><option value="">No FR selected</option>{fr_options_html}</select></label>'
                f'<label><span>Suggested TBT</span><select data-map-tbt><option value="">No TBT selected</option>{tbt_options_html}</select></label>'
                '<label><span>New FR id</span><input data-map-new-fr placeholder="FR-xxx"></label>'
                '<label><span>New TBT id</span><input data-map-new-tbt placeholder="TBT-xxx"></label>'
                '<label class="assurance-map-wide"><span>Assessor hypothesis / rationale</span><textarea data-map-rationale rows="2" placeholder="Why this native test may prove, or may not prove, the suggested FR/TBT"></textarea></label>'
                '<label><span>Confidence</span><select data-map-confidence><option value="medium">medium</option><option value="high">high</option><option value="low">low</option></select></label>'
                '</div>'
            )
        guidance_title = "Mapping checklist" if is_unmapped_native else "Specification checklist" if is_planned_tbt else "Draft review checklist"
        if is_unmapped_native:
            checklist_html = (
                '<li>Treat any selected FR/TBT as an assessor hypothesis until the native test source is inspected.</li>'
                '<li>Accept the mapping only when the test behaviour actually proves that FR/TBT.</li>'
                '<li>If no existing TBT fits, propose a better config update or leave the test unmapped.</li>'
                '<li>Only promote it after the JUnit testcase name/classname can carry the TBT identifier.</li>'
                '<li>Do not count the native test as assurance evidence while it remains unmapped.</li>'
            )
        elif is_planned_tbt:
            checklist_html = (
                '<li>Decide whether this TBT needs a unit, integration, e2e, load, scanner, document, or manual test.</li>'
                '<li>Generate a draft test only after the required product behaviour and safe fixtures are clear.</li>'
                '<li>Keep the TBT identifier in the file name, test title, and future JUnit testcase name.</li>'
                '<li>Do not approve until there is a concrete draft test or existing mapped native test to review.</li>'
            )
        else:
            checklist_html = (
                '<li>The test proves the stated TBT/FR rather than merely touching related code.</li>'
                '<li>The test uses disposable data, mocks, or a safe test environment.</li>'
                '<li>The implementation will not invent endpoints or product behaviour.</li>'
                '<li>The JUnit testcase name/classname will include the TBT identifier.</li>'
            )
        action_key = html.escape(str(item.get("pack_id") or tbt_id or decision_id))
        action_attrs = (
            f'data-assurance-action="{action_key}" '
            f'data-state="{html.escape(state)}" '
            f'data-tbt="{html.escape(tbt_id)}" '
            f'data-pack-id="{html.escape(str(item.get("pack_id") or ""))}" '
            f'data-native-path="{html.escape(str(item.get("native_path") or ""))}" '
            f'data-pack-path="{html.escape(pack_path if pack_path != "-" else "")}" '
            f'data-test-names="{html.escape(json.dumps(case_names[:20]))}" '
            f'data-assessment="{html.escape(assessment)}" '
            f'data-source="{html.escape(source)}" '
            f'data-status="{html.escape(status)}" '
            f'data-test-type="{html.escape(test_type)}" '
            f'data-title="{html.escape(title)}"'
        )
        if is_approvable:
            review_cell = (
                f'<label><input type="checkbox" {action_attrs}> Review</label>'
            )
        elif is_unmapped_native:
            review_cell = f'<label><input type="checkbox" {action_attrs}> Map</label>'
        elif is_planned_tbt:
            review_cell = f'<label><input type="checkbox" {action_attrs}> Specify TBT</label>'
        else:
            review_cell = '<span class="assurance-review-action">Review</span>'
        if mapping_proposal:
            target = mapping_proposal.get("target") or {}
            rec_target = " / ".join(part for part in (target.get("fr"), target.get("tbt")) if part) or "No target"
            rec_title = f"Agent review: {str(mapping_proposal.get('operation') or 'review').replace('_', ' ')} · {rec_target} · {mapping_proposal.get('confidence', 'unknown')}"
            recommendation_cell = (
                '<span class="assurance-review-icon is-reviewed"'
                f' title="{html.escape(rec_title)}" aria-label="{html.escape(rec_title)}">'
                '<span aria-hidden="true">✓</span><b>Reviewed</b>'
                '</span>'
            )
        elif is_unmapped_native:
            recommendation_cell = (
                '<span class="assurance-review-icon" title="No agent review recommendation yet" aria-label="No agent review recommendation yet">'
                '<span aria-hidden="true">?</span><b>Needs review</b>'
                '</span>'
            )
        else:
            recommendation_cell = '<span class="assurance-muted">-</span>'
        rows.append(
            '<tr class="assurance-test-row" tabindex="0"'
            f' data-assurance-state="{html.escape(state)}" data-assurance-test-detail="{decision_id}" aria-controls="{decision_id}" aria-expanded="false"'
            f'{" hidden" if state != "map" else ""}>'
            f'<td><code>{html.escape(tbt_id or "Unmapped")}</code></td>'
            f'<td><span class="evidence-type-chip">{html.escape(test_type)}</span></td>'
            f'<td>{html.escape(short_text(title, 64))}</td>'
            f'<td>{html.escape(", ".join(fr_ids) or "-")}</td>'
            f'<td><span class="evidence-status-chip">{html.escape(status)}</span></td>'
            f'<td>{recommendation_cell}</td>'
            f'<td class="assurance-approve-cell">{review_cell}</td>'
            '</tr>'
            f'<tr class="assurance-test-detail-row" id="{decision_id}" hidden><td colspan="7">'
            '<div class="assurance-test-detail">'
            '<div class="assurance-test-detail-head">'
            f'<strong>{html.escape(title)}</strong>'
            f'<span>{html.escape(assessment)} · {html.escape(evidence_state)}</span>'
            '</div>'
            f'<div class="assurance-test-detail-grid">{detail_html}</div>'
            f'{map_controls_html}'
            '<div class="assurance-approval-guidance">'
            f'<b>{html.escape(guidance_title)}</b>'
            f'<ul>{checklist_html}</ul>'
            '</div>'
            '</div>'
            '</td></tr>'
        )
    out.append(
        '<table class="matrix assurance-tests-table"><thead><tr>'
        '<th>TBT</th><th>Type</th><th>Test basis</th><th>FRs</th><th>Status</th><th>Recommendation</th><th>Review</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )
    out.append(
        '</div><div class="assurance-page-pane" data-assurance-page-pane="next">'
        f'{next_prompt_panel}</div></section>'
    )
    return ''.join(out)


def render_manual_checklist(evidence: dict, report_dir: Path) -> str:
    assurance = evidence.get('assurance', {})
    manual_items = manual_evidence_items(report_dir)
    manual_total = assurance.get('manual_items_total', len(manual_items))
    manual_done = assurance.get('manual_items_completed', 0)
    out = [
        '<section class="card" data-overview-section="manual"><div class="card-head">'
        '<h2>Manual ASVS Checklist</h2><span class="meta">evidence that requires human review</span></div>'
    ]
    if not manual_items:
        out.append('<div class="empty-state">No manual evidence checklist was generated.</div></section>')
        return ''.join(out)

    out.append(
        f'<div class="manual-checklist" data-manual-total="{manual_total}" data-manual-initial="{manual_done}">'
        '<div class="manual-tools">'
        f'<strong>Manual completion <span id="manual-progress">{manual_done}/{manual_total}</span></strong>'
        '<div class="manual-actions"><button type="button" class="mini-btn" data-manual-select="all">Select all</button>'
        '<button type="button" class="mini-btn" data-manual-select="none">Clear</button></div>'
        '</div>'
        '<table class="manual-table"><thead><tr><th class="check-col">Done</th><th class="item-col">Manual step</th><th>What to verify</th><th>Evidence to collect</th></tr></thead><tbody>'
    )
    for item in manual_items:
        checked = item.get('status') not in ('', 'PENDING')
        desc = item.get('description') or ''
        why = item.get('why_required') or item.get('why') or ''
        evidence_required = item.get('evidence_expected') or item.get('evidence') or ''
        item_id = f'manual-{html.escape(str(item.get("id", "")))}'
        out.append(
            '<tr>'
            f'<td class="check-col"><input type="checkbox" data-manual-check="{html.escape(str(item.get("id", "")))}" id="{item_id}"{" checked" if checked else ""}></td>'
            f'<td class="item-col"><label for="{item_id}">{html.escape(str(item.get("id", "")))}. {html.escape(str(item.get("title", "")))}</label></td>'
            f'<td><div class="manual-desc">{html.escape(desc)}</div><div class="manual-evidence">{html.escape(why)}</div></td>'
            f'<td><div class="manual-desc">{html.escape(evidence_required)}</div></td>'
            '</tr>'
        )
    out.append('</tbody></table></div></section>')
    return ''.join(out)


def render_secret_detail(report_dir: Path, overview_section: bool = False) -> str:
    secret_rules, secret_files, secret_total = secret_breakdowns(report_dir / 'reports' / 'gitleaks.json')
    if not secret_total:
        return ''
    section_attr = ' data-overview-section="secrets"' if overview_section else ''
    out = [f'<div class="stack"{section_attr}>']
    out.append(
        f'<section class="card"><div class="card-head"><h2>Secrets</h2><span class="meta">{secret_total} exposed</span></div>'
        f'<div class="callout">{ICONS["alert"]}<div><strong>Rotate before code fixes.</strong> '
        f'Gitleaks found {secret_total} secrets; assume exposure until revoked.</div></div></section>'
    )
    out.append('<div class="two-col">')
    out.append(f'<section class="card"><div class="card-head"><h2>Secret Types</h2><span class="meta">{secret_total} total</span></div><div class="dense-list">')
    for rule, n in secret_rules:
        out.append(f'<div class="kv"><code>{html.escape(rule)}</code><strong>{n}</strong></div>')
    out.append('</div></section>')
    out.append('<section class="card"><div class="card-head"><h2>Secret Files</h2><span class="meta">top paths</span></div><div class="dense-list">')
    for path, n in secret_files:
        out.append(f'<div class="kv"><code title="{html.escape(path)}">{html.escape(path)}</code><strong>{n}</strong></div>')
    out.append('</div></section></div></div>')
    return ''.join(out)


def render_overview(evidence: dict, report_dir: Path, ignored: dict) -> str:
    findings = evidence.get('findings_summary', {})
    priority_issues = critical_high_issues(report_dir)
    medium_low = medium_low_issues(report_dir)
    secret_detail = render_secret_detail(report_dir, overview_section=True)
    top_pkgs = top_packages(report_dir / 'reports' / 'grype.json', limit=8)
    out = ['<div class="overview-grid">']
    out.append('<section class="card" data-overview-section="matrix"><div class="card-head"><h2>Evidence Matrix</h2><span class="meta">full scanner coverage and raw evidence paths</span></div>')
    out.append(render_matrix(evidence, ignored, include_skipped=True))
    out.append('</section>')
    out.append(render_all_findings(evidence, report_dir))
    out.append(render_scanner_health(evidence))
    out.append(render_test_evidence(evidence))

    if secret_detail:
        out.append(secret_detail)

    lower_cards = []
    if top_pkgs:
        hot = ['<section class="card" data-overview-section="hot-packages"><div class="card-head"><h2>Hot Packages</h2><span class="meta">by vuln count</span></div><div class="dense-list">']
        for pkg, n in top_pkgs:
            hot.append(f'<div class="kv"><code>{html.escape(pkg)}</code><strong>{n}</strong></div>')
        hot.append('</div></section>')
        lower_cards.append(''.join(hot))

    if lower_cards:
        out.append('<div class="two-col below-matrix" data-overview-group>' + ''.join(lower_cards) + '</div>')

    if priority_issues:
        out.append(render_issue_table("cves", "Critical &amp; High Issues", f"{len(priority_issues)} critical/high rows", priority_issues, report_dir))

    if medium_low:
        out.append(render_issue_table("medium-low", "Medium &amp; Low Issues", f"{len(medium_low)} medium/low rows", medium_low, report_dir))

    out.append('</div>')
    return ''.join(out)


def render_scanners(evidence: dict, report_dir: Path, ignored: dict) -> str:
    return '<section class="card"><div class="card-head"><h2>Scanner Detail</h2><span class="meta">status, signal, and raw evidence path</span></div>' + render_matrix(evidence, ignored, include_skipped=True) + '</section>'


def render_findings(evidence: dict, report_dir: Path, ignored: dict) -> str:
    out = ['<div class="stack">']
    top_vulns = top_grype(report_dir / 'reports' / 'grype.json', limit=20)
    if top_vulns:
        out.append(f'<section class="card"><div class="card-head"><h2>Vulnerability Queue</h2><span class="meta">first pass triage list</span></div><table class="matrix"><thead><tr>{th("Severity")}{th("CVE")}{th("Package")}{th("Installed")}{th("Remediation")}</tr></thead><tbody>')
        for v in top_vulns:
            remediation = html.escape(remediation_text(v['fixed_in'], kind="fixed_version"))
            out.append(f'<tr><td>{sev_badge(v["severity"])}</td><td><code>{html.escape(v["id"])}</code></td><td><code>{html.escape(v["pkg"])}</code></td><td>{html.escape(v["version"])}</td><td>{remediation}</td></tr>')
        out.append('</tbody></table></section>')

    secret_detail = render_secret_detail(report_dir)
    if secret_detail:
        out.append(secret_detail)

    if ignored:
        out.append(f'<section class="card"><div class="card-head"><h2>.scannerignore Impact</h2><span class="meta">filtered source/config findings</span></div><table class="matrix"><thead><tr>{th("Scanner")}{th("Before")}{th("After")}{th("Removed")}{th("Patterns")}</tr></thead><tbody>')
        for name, info in ignored.items():
            out.append(f'<tr><td class="scanner">{html.escape(name)}</td><td>{info["before"]}</td><td>{info["after"]}</td><td><strong>{info["removed"]}</strong></td><td>{info["patterns_count"]}</td></tr>')
        out.append('</tbody></table></section>')

    out.append('</div>')
    return ''.join(out)


def render_prompt_panel(
    report_dir: Path,
    *,
    filename: str,
    heading: str,
    meta: str,
    body_id: str,
    button_label: str,
) -> str:
    prompt_path = report_dir / filename
    prompt_md = prompt_path.read_text(errors="replace") if prompt_path.exists() else f"{heading} is not available for this run. The scan may have stopped before report generation completed."
    prompt_md = prompt_md.replace("/Users/jd/Development/asvs-scanner", str(REPO_ROOT))
    prompt_html = md_to_html(prompt_md)
    return f'''
<section class="section">
  <div class="prompt-shell">
    <div class="prompt-bar">
      <div>
        <h2>{html.escape(heading)}</h2>
        <div class="meta">{html.escape(meta)}</div>
      </div>
      <button class="copy-btn" onclick="copyPrompt('{body_id}', this)">{ICONS["copy"]}<span class="btn-label">{html.escape(button_label)}</span></button>
    </div>
    <div class="prompt-body" id="{body_id}">{prompt_html}</div>
  </div>
</section>
'''


def render_fixplan(report_dir: Path) -> str:
    return render_prompt_panel(
        report_dir,
        filename="agent-investigation-prompt.md",
        heading="Agent Investigation & Fix Plan",
        meta="Copy this prompt into Codex manually for focused vulnerability remediation.",
        body_id="fix-prompt-body",
        button_label="Copy fix prompt",
    )


def render_assurance_prompt_tab(report_dir: Path) -> str:
    return render_prompt_panel(
        report_dir,
        filename="assurance-assessment-prompt.md",
        heading="Assurance Assessment Prompt",
        meta="Copy this prompt into Codex manually to assess FR/TBT/ASVS/JSP-453 coverage without generating broad new tests by default.",
        body_id="assurance-prompt-body",
        button_label="Copy assurance prompt",
    )


def render_config_update_template_panel(report_dir: Path) -> str:
    template_path = report_dir / "fr-config-update-proposal.template.json"
    if template_path.exists():
        template_text = template_path.read_text(errors="replace")
    else:
        template_text = json.dumps(
            {
                "schema_version": 1,
                "mode": "config_update_proposal",
                "project": "project-name",
                "run_id": "scan-run-id",
                "source_inputs": [
                    {"path": "dashboard-payload.json", "used_for": "traceability context"}
                ],
                "fr_catalog_updates": [],
                "compliance_mapping_pack_updates": [],
                "assurance_framework_or_instance_updates": [],
                "manual_evidence_updates": [],
                "uncertain_mappings": [],
                "review_required": [
                    {
                        "item": "config-authoring",
                        "question": "Replace this template item with proposal content.",
                        "why": "Older report did not include a generated template artifact.",
                    }
                ],
            },
            indent=2,
        )
    return f'''
<section class="section">
  <div class="prompt-shell config-template-panel">
    <div class="prompt-bar">
      <div>
        <h2>Proposal JSON Template</h2>
        <div class="meta">Start from <code>fr-config-update-proposal.template.json</code>, then validate and review before applying.</div>
      </div>
      <button class="copy-btn" onclick="copyPrompt('config-update-template-body', this)">{ICONS["copy"]}<span class="btn-label">Copy template</span></button>
    </div>
    <pre class="json-template" id="config-update-template-body"><code>{html.escape(template_text)}</code></pre>
  </div>
</section>
'''


def render_config_update_prompt_tab(report_dir: Path) -> str:
    workflow = '''
<section class="section">
  <div class="prompt-shell config-workflow">
    <div class="prompt-bar">
      <div>
        <h2>Config Update Workflow</h2>
        <div class="meta">Use this after Codex returns proposal JSON from the prompt below.</div>
      </div>
    </div>
    <div class="workflow-note">
      Auto-apply currently supports FR catalog, compliance mapping pack, project assurance-instance mappings, gate decisions, waivers, native test mappings, and manual evidence targeted at FRs, TBTs, criteria, and sufficiently specified gate/role instance records. Reusable framework-structure edits and scanner-compliance mapping pack curation remain review-only.
    </div>
    <div class="workflow-steps">
      <div class="workflow-step">
        <strong>1. Validate</strong>
        <p>Check schema and cross-references before review.</p>
        <pre><code>assurance-scan validate-config-update proposal.json \
  --fr-catalog /path/to/project.fr-catalog.enriched.json \
  --ruleset /path/to/ruleset.json \
  --scanner-rules /path/to/scanner-rules.json \
  --assurance-framework /path/to/assurance-framework.json</code></pre>
      </div>
      <div class="workflow-step">
        <strong>2. Review</strong>
        <p>Render a human decision brief with confidence, provenance and review questions.</p>
        <pre><code>assurance-scan review-config-update proposal.json \
  --output proposal-review.md</code></pre>
      </div>
      <div class="workflow-step">
        <strong>3. Apply Selected</strong>
        <p>Write accepted entries to explicit output files. Originals are not changed in place.</p>
        <pre><code>assurance-scan apply-config-update proposal.json --list
assurance-scan apply-config-update proposal.json \
  --select fr_catalog_updates:1 \
  --reviewed-by "assessor-name" \
  --fr-catalog /path/to/current.fr-catalog.json \
  --fr-catalog-out /path/to/reviewed.fr-catalog.json
assurance-scan apply-config-update proposal.json \
  --select assurance_framework_or_instance_updates:1 \
  --reviewed-by "assessor-name" \
  --assurance-instance /path/to/current.assurance-instance.json \
  --assurance-instance-out /path/to/reviewed.assurance-instance.json \
  --assurance-framework /path/to/assurance-framework.json</code></pre>
      </div>
    </div>
  </div>
</section>
'''
    return workflow + render_config_update_template_panel(report_dir) + render_prompt_panel(
        report_dir,
        filename="fr-config-update-prompt.md",
        heading="FR Config Update Prompt",
        meta="Copy this prompt into Codex to propose FR/TBT/compliance/gate config deltas without editing product code or inventing evidence.",
        body_id="config-update-prompt-body",
        button_label="Copy config prompt",
    )


def render_agent_prompts(report_dir: Path) -> str:
    return (
        '<div class="prompt-hub fw-regime-tabs">'
        '<section class="card">'
        '<div class="page-intro"><div><h2>Agent Prompts</h2><ul>'
        '<li>Use controlled handoff prompts after review</li>'
        '<li>Separate config authoring, assurance assessment, and remediation</li>'
        '<li>Keep generated work focused and auditable</li>'
        '</ul></div></div>'
        '<div class="fw-regime-tabbar" role="tablist" aria-label="Agent prompt types">'
        '<button type="button" class="fw-regime-tab-btn active" data-fw-tab-target="agent-prompt-remediation" aria-selected="true">Remediation</button>'
        '<button type="button" class="fw-regime-tab-btn" data-fw-tab-target="agent-prompt-config" aria-selected="false">Config Updates</button>'
        '<button type="button" class="fw-regime-tab-btn" data-fw-tab-target="agent-prompt-assurance" aria-selected="false">Assurance Tests</button>'
        '</div>'
        '</section>'
        f'<div class="fw-regime-pane active" id="agent-prompt-remediation">{render_fixplan(report_dir)}</div>'
        f'<div class="fw-regime-pane" id="agent-prompt-config">{render_config_update_prompt_tab(report_dir)}</div>'
        f'<div class="fw-regime-pane" id="agent-prompt-assurance">{render_assurance_prompt_tab(report_dir)}</div>'
        '</div>'
    )


def shell_quote(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


def docker_mount_root(source_repo: str, report_dir: Path) -> str:
    candidates = [Path(source_repo).expanduser(), report_dir]
    for path in candidates:
        parts = path.parts
        if len(parts) >= 5 and parts[:4] == ("/", "Users", "jd", "Development"):
            return str(Path(*parts[:5]))
    if source_repo:
        return str(Path(source_repo).expanduser().parent)
    return str(report_dir.parent)


def render_instruction_command(command_id: str, title: str, body: str, note: str = "") -> str:
    return (
        '<div class="instruction-command">'
        '<div class="instruction-command-head">'
        f'<div><strong>{html.escape(title)}</strong>'
        f'{f"<span>{html.escape(note)}</span>" if note else ""}</div>'
        f'<button class="copy-btn" onclick="copyPrompt(\'{html.escape(command_id)}\', this)">{ICONS["copy"]}<span class="btn-label">Copy</span></button>'
        '</div>'
        f'<pre class="instruction-code" id="{html.escape(command_id)}"><code>{html.escape(body)}</code></pre>'
        '</div>'
    )


def render_instruction_detail(row_id: str, command_id: str, command_title: str, command: str, notes: list[str]) -> str:
    note_items = "".join(f"<li>{html.escape(str(note))}</li>" for note in notes)
    return (
        f'<tr class="instruction-detail-row" id="{html.escape(row_id)}" hidden>'
        '<td colspan="6">'
        '<div class="instruction-detail">'
        f'{render_instruction_command(command_id, command_title, command)}'
        '<div class="instruction-detail-notes"><strong>Review notes</strong>'
        f'<ul>{note_items}</ul>'
        '</div>'
        '</div>'
        '</td>'
        '</tr>'
    )


def render_instructions_page(report_dir: Path, evidence: dict) -> str:
    source_repo = str(evidence.get("source_repo") or evidence.get("target_dir") or "")
    report_path = str(report_dir)
    runtime_dir = report_dir.parent.parent
    runtime_fr_catalog = runtime_dir / f"{str(evidence.get('repository') or 'target-project')}.fr-catalog.enriched.json"
    report_fr_catalog = report_dir / "fr-catalog.snapshot.json"
    fr_catalog = str(runtime_fr_catalog if runtime_fr_catalog.exists() else report_fr_catalog)
    junit_path = str(report_dir / "reports" / "junit.xml")
    framework_snapshot = report_dir / "assurance-framework.snapshot.json"
    compliance_mapping_snapshot = report_dir / "compliance-mapping-pack.snapshot.json"
    scanner_mapping_snapshot = report_dir / "scanner-compliance-mapping-packs"
    docker_image = "__ASSURANCE_SCAN_IMAGE__"
    mount_flags = "__MOUNT_FLAGS__"
    workdir_expr = "__WORKDIR_EXPR__"
    source_expr = "__SOURCE_REPO_EXPR__"
    run_preamble = "__RUN_PREAMBLE__"
    assurance_context_comment = "__ASSURANCE_CONTEXT_COMMENT__"
    report_q = shell_quote(report_path)
    fr_catalog_q = shell_quote(fr_catalog)
    junit_q = shell_quote(junit_path)
    project_id = str(evidence.get("repository") or "target-project")
    default_project_fr_catalog = str(runtime_fr_catalog)
    default_reviewed_fr_catalog = str(runtime_dir / f"{project_id}.fr-catalog.reviewed.json")
    scan_config_flags = [
        "__ASSURANCE_FRAMEWORK_FLAG__",
        "  --scanner-compliance-mapping-pack '/opt/assurance-scan/data/scanner-mappings'",
    ]
    scan_config_suffix = "__SCAN_FR_CATALOG_FLAG__" + (" " + chr(92) + "\n").join(scan_config_flags)

    fresh_scan_command = "\n".join([
        assurance_context_comment,
        run_preamble,
        "docker run --rm -it \\",
        "  -e ASSURANCE_SCAN_IMAGE_BUILD_PARALLELISM=2 \\",
        "  -e ASSURANCE_SCAN_PARALLELISM=4 \\",
        "  -v /var/run/docker.sock:/var/run/docker.sock \\",
        mount_flags,
        f"  -w {workdir_expr} \\",
        f"  {docker_image} scan {source_expr} \\",
        scan_config_suffix + " && " + chr(92),
    ])
    refresh_dashboard_command = (
        f"python3 {shell_quote(str(REPO_ROOT / 'scripts' / 'generate_dashboard.py'))} "
        f"--report-dir {report_q}"
    )
    sync_authority_command = "\n".join([
        f"python3 {shell_quote(str(REPO_ROOT / 'scripts' / 'sync-authority-rulesets.py'))} --download",
        f"python3 {shell_quote(str(REPO_ROOT / 'scripts' / 'load_target_artifacts.py'))} authority_source_registry "
        f"{shell_quote(str(REPO_ROOT / 'data' / 'authority-sources' / 'rulesets.json'))} --strict",
    ])
    validate_report_command = "\n".join([
        f"python3 {shell_quote(str(REPO_ROOT / 'scripts' / 'load_target_artifacts.py'))} graph_manifest {shell_quote(str(report_dir / 'graph-manifest.json'))} --strict",
        f"python3 {shell_quote(str(REPO_ROOT / 'scripts' / 'load_target_artifacts.py'))} dashboard_payload {shell_quote(str(report_dir / 'dashboard-payload.json'))} --strict",
    ])
    reviewed_catalog_scan_command = "__REVIEWED_CATALOG_SCAN_COMMAND__"
    approved_test_command = "__KANBAN_EVIDENCE_COMMAND__"
    config_review_command = "\n".join([
        "# Writes blueprint-decisions.json from the Blueprint Proposals tab selection, then applies reviewed scope.",
        "# Review the Blueprint Proposals tab first if you need to reject or tailor anything.",
        "__BLUEPRINT_DECISION_PRELUDE__",
        "__DOCKER_CLI_BASE__ apply-reviewed-scope " + chr(92),
        f"  --run-id {shell_quote(str(evidence.get('run_id') or 'scan-run-id'))} " + chr(92),
        "  --proposal blueprint-proposal.json " + chr(92),
        "  --decisions blueprint-decisions.json " + chr(92),
        "  --blueprint '/opt/assurance-scan/data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json' " + chr(92),
        "  --fr-catalog __FR_CATALOG_INPUT_PATH__ " + chr(92),
        "  --fr-catalog-out __FR_CATALOG_OUTPUT_PATH__ " + chr(92),
        '  --reviewed-by "${USER:-reviewer}"',
    ])
    project_specific_review_command = "\n".join([
        "# Generate project-specific-fr-proposal.json from the Project-Specific FRs tab prompt first.",
        "# This validates, reviews and applies only explicitly proposed bespoke FR/TBT catalog updates.",
        "__DOCKER_CLI_BASE__ validate-config-update project-specific-fr-proposal.json " + chr(92),
        "  --fr-catalog __FR_CATALOG_OUTPUT_PATH__ && " + chr(92),
        "__DOCKER_CLI_BASE__ review-config-update project-specific-fr-proposal.json " + chr(92),
        "  --output project-specific-fr-review.md && " + chr(92),
        "__DOCKER_CLI_BASE__ apply-config-update project-specific-fr-proposal.json " + chr(92),
        "  --select fr_catalog_updates:* " + chr(92),
        '  --reviewed-by "${USER:-reviewer}" ' + chr(92),
        "  --fr-catalog __FR_CATALOG_OUTPUT_PATH__ " + chr(92),
        "  --fr-catalog-out __FR_CATALOG_OUTPUT_PATH__",
    ])
    blueprint_catalog_q = shell_quote("/opt/assurance-scan/data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json")
    blueprint_mapping_pack_q = shell_quote("/opt/assurance-scan/data/blueprint-mappings/security-core/asvs/5.0.0.json")
    blueprint_nist_mapping_pack_q = shell_quote("/opt/assurance-scan/data/blueprint-mappings/security-core/nist-800-53/5.2.0.json")
    docker_cli_base = "\n".join([
        "docker run --rm -it \\",
        mount_flags,
        f"  -w {workdir_expr} \\",
        f"  {docker_image}",
    ])
    blueprint_command = "\n".join([
        docker_cli_base + " propose-blueprint-frs " + chr(92),
        f"  --project {shell_quote(project_id)} " + chr(92),
        f"  --blueprint {blueprint_catalog_q} " + chr(92),
        f"  --blueprint-compliance-mapping-pack {blueprint_mapping_pack_q} " + chr(92),
        f"  --blueprint-compliance-mapping-pack {blueprint_nist_mapping_pack_q} " + chr(92),
        "  --include-all " + chr(92),
        "  --output blueprint-proposal.json",
    ])
    export_bundle_command = "\n".join([
        assurance_context_comment,
        run_preamble,
        "docker run --rm -it \\",
        mount_flags,
        f"  -w {workdir_expr} \\",
        f"  {docker_image} export-assurance-claim {report_q} \\",
        "  --claim-type selected_scope_satisfied \\",
        "  --target selected-scope \\",
        f"  --out {shell_quote(str(report_dir / 'claims' / 'selected-scope.json'))} && \\",
        "docker run --rm -it \\",
        mount_flags,
        f"  -w {workdir_expr} \\",
        f"  {docker_image} export-assurance-proof-bundle {shell_quote(str(report_dir / 'claims' / 'selected-scope.json'))} \\",
        f"  --report-dir {report_q} \\",
        f"  --out {shell_quote(str(report_dir / 'proof-bundles' / 'selected-scope.proof-bundle.json'))} && \\",
        f"cd {report_q} && zip -r compliance-bundle.zip graph-manifest.json dashboard-payload.json evidence-manifest.json evidence-bundle.json claims proof-bundles hashes",
    ])

    steps = [
        {
            "step": "1",
            "title": "Update compliance and framework standards",
            "input": "Official online standards, licensed user-supplied standards, assurance framework configs and scanner mapping packs.",
            "output": "Canonical rulesets/framework configs with raw artifact hashes and transform hashes.",
            "handoff": "Standards/config ball.",
            "command_title": "Refresh authority standards",
            "command": sync_authority_command,
            "notes": [
                "This is run when standards or framework sources change, not before every scan.",
                "NIST and ASVS are transformed from official public artifacts. ISO detailed content must be supplied by a license holder.",
                "Agentic help is useful for reviewing parser output and mapping gaps, but the final artifact is strict schema-validated config.",
            ],
        },
        {
            "step": "2",
            "title": "Discovery scan and blueprint proposal",
            "input": "Source repository, selected standards, assurance framework, scanner mapping packs and reusable blueprint FR/TBT templates.",
            "output": "Discovery report plus blueprint-proposal.json. These candidates are not accepted project FRs yet.",
            "handoff": "Candidate assurance-scope ball.",
            "command_title": "Run discovery scan, then propose blueprint FRs",
            "command": fresh_scan_command + "\n" + blueprint_command,
            "notes": [
                "Discovery may ingest an existing FR catalog if you select one, but proposed blueprint FRs remain separate until reviewed.",
                "The scan writes the dashboard before blueprint-proposal.json is created. Refresh this report dashboard after Step 2 so the Blueprint Proposals tab can load the new proposal file.",
                "The scan loads installed compliance regime metadata and scanner mapping packs by default; the dashboard dropdowns filter the resulting graph rather than requiring a new scanner run.",
                "The selected assurance framework and gated flow remain the active governance context for this report.",
                "Blueprints accelerate common security/compliance obligations; project-specific FRs still need explicit authoring and review.",
                "For greenfield SOW work this same proposal step starts from planning answers rather than existing code discovery.",
            ],
        },
        {
            "step": "3",
            "title": "Review reusable blueprint scope",
            "input": "Supplied/discovered project FR catalog, blueprint-proposal.json and human decisions from the Blueprint Proposals tab.",
            "output": "Reviewed project FR/TBT catalog with accepted blueprint lineage where applicable.",
            "handoff": "Blueprint-reviewed scope ball.",
            "command_title": "Apply reviewed blueprint decisions",
            "command": config_review_command,
            "notes": [
                "Do not silently combine blueprint candidates with accepted FRs. This step is the review gate between recommendation and project obligation.",
                "Accepted candidates become config-update proposals, then reviewed FR/TBT catalog entries with blueprint lineage.",
                "Reject, mark not applicable or tailor candidates when the blueprint does not match observable project intent.",
            ],
        },
        {
            "step": "4A",
            "title": "Optional: review project-specific FR gaps",
            "input": "Blueprint-reviewed FR catalog plus an agent-authored project-specific-fr-proposal.json, if one has been created.",
            "output": "The same reviewed FR/TBT catalog, amended only by validated and explicitly reviewed bespoke FR/TBT updates.",
            "handoff": "Bespoke scope ball, only when needed.",
            "command_title": "Optional: validate, review and apply bespoke FR/TBT proposals",
            "command": project_specific_review_command,
            "notes": [
                "Run this only after using the Project-Specific FRs tab prompt and receiving project-specific-fr-proposal.json.",
                "Skip this step when you are happy to start with the accepted blueprint scope from Step 3.",
                "This is where project FRs not covered by supplied catalog entries or reusable blueprints are proposed and review-gated.",
            ],
        },
        {
            "step": "4B",
            "title": "Required: rescan with reviewed FR catalog",
            "input": "Reviewed FR/TBT catalog from Step 3, optionally amended by Step 4A.",
            "output": "Fresh report whose supplied catalog, graph, board and compliance views are driven by the reviewed catalog.",
            "handoff": "Accepted scope scan ball.",
            "command_title": "Rescan with reviewed FR catalog",
            "command": reviewed_catalog_scan_command,
            "notes": [
                "This is the normal next step after accepting blueprint scope.",
                "It creates a new report directory and makes the accepted FR/TBT scope visible in the Supplied Catalog, Board, Compliance Regime and Traceability Graph views.",
                "If you ran Step 4A, this command uses the amended reviewed catalog at the same path.",
            ],
        },
        {
            "step": "5",
            "title": "Generate, approve and run assurance tests",
            "input": "Accepted FR/TBT catalog, Kanban review decisions, ready-to-run tests, scanner outputs and optional JUnit XML.",
            "output": "Observed test evidence, refreshed assurance graph, resolved FR/TBT/compliance status and dashboard.",
            "handoff": "Observed evidence ball.",
            "command_title": "Run approved tests or refresh evidence",
            "command": approved_test_command,
            "notes": [
                "Use the Project FRs Board to draft tests, review agentic tests, approve them, then run approved tests.",
                "Tests-only refreshes the current report evidence without creating a new scan directory.",
                "Tests then full scan records JUnit evidence and creates a clean report against the accepted FR catalog.",
            ],
        },
        {
            "step": "6",
            "title": "Export compliance zip bundle",
            "input": "Graph manifest, evidence bundle, config commitments and optional openings.",
            "output": "Compliance bundle containing graph commitments, evidence manifest, evidence bundle, claims and proof bundles.",
            "handoff": "Audit/proof ball.",
            "command_title": "Export selected-scope claim, proof bundle and zip",
            "command": export_bundle_command,
            "notes": [
                "Your wording of a zip bundle is right, but it should include the claim/proof artifacts, not just raw reports.",
                "A selected-scope claim may be unsatisfied if any FR/compliance row is still missing, failed, partial or blocked.",
                "Future ZK packaging can use the same graph/config/evidence commitments with selective openings.",
            ],
        },
    ]
    def report_snapshot_has_reviewed_scope() -> bool:
        snapshot_path = report_dir / "fr-catalog.snapshot.json"
        if not snapshot_path.exists():
            return False
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        frs = snapshot.get("frs") or snapshot.get("functional_requirements") or []
        tbts = snapshot.get("tbts") or []
        for item in list(frs) + list(tbts):
            derived = item.get("derived_from") or item.get("derived_from_template") or item.get("blueprint_lineage")
            metadata = item.get("metadata") or {}
            review = metadata.get("config_update_review") if isinstance(metadata, dict) else None
            if isinstance(derived, dict) and derived.get("review_status") == "accepted":
                return True
            if isinstance(review, dict) and review.get("review_status") == "accepted":
                return True
        return False

    def workflow_stage_state() -> str:
        if (report_dir / "proof-bundles").exists() or (report_dir / "claims").exists():
            return "6"
        if (report_dir / "reports" / "junit.xml").exists():
            return "5"
        if report_snapshot_has_reviewed_scope():
            return "5"
        if Path(default_reviewed_fr_catalog).exists():
            return "4B"
        if (Path(source_repo) / "project-specific-fr-proposal.json").exists():
            return "4A"
        if (Path(source_repo) / "blueprint-decisions.json").exists():
            return "3"
        if (Path(source_repo) / "blueprint-proposal.json").exists() or (report_dir / "blueprint-proposal.json").exists():
            return "2"
        return "1"

    def approved_tbt_ids_for_instruction_step() -> list[str]:
        state_path = report_dir / "project-fr-board-state.json"
        state = load_json(state_path) or {}
        ids: list[str] = []
        for card in state.get("cards") or []:
            if str(card.get("lane") or "") != "import":
                continue
            tbt_id = str(card.get("tbt") or "").strip()
            if tbt_id and tbt_id not in ids:
                ids.append(tbt_id)
        return ids

    approved_tbt_ids = approved_tbt_ids_for_instruction_step()
    active_workflow_step = workflow_stage_state()
    active_step_index = next((idx for idx, candidate in enumerate(steps) if str(candidate["step"]) == active_workflow_step), 0)
    workflow_flow_json = json.dumps([
        {
            "id": str(item["step"]),
            "title": str(item["title"]),
            "input": str(item["input"]),
            "output": str(item["output"]),
            "handoff": str(item["handoff"]),
            "command_title": str(item["command_title"]),
            "command": str(item["command"]),
            "notes": [str(note) for note in item["notes"]],
            "active": str(item["step"]) == active_workflow_step,
            "done": idx < active_step_index,
        }
        for idx, item in enumerate(steps)
    ]).replace("</", "<\\/")

    rows: list[str] = []
    for item in steps:
        detail_id = f"instruction-detail-{item['step']}"
        command_id = f"instruction-command-{item['step']}"
        rows.append(
            '<tr class="instruction-row" tabindex="0" role="button" '
            f'aria-expanded="false" data-instruction-detail="{html.escape(detail_id)}">'
            f'<td><span class="instruction-step-pill">{html.escape(item["step"])}</span></td>'
            f'<td><strong>{html.escape(item["title"])}</strong></td>'
            f'<td>{html.escape(item["input"])}</td>'
            f'<td>{html.escape(item["output"])}</td>'
            f'<td>{html.escape(item["handoff"])}</td>'
            '<td><span class="instruction-expand">Open</span></td>'
            '</tr>'
        )
        rows.append(render_instruction_detail(
            detail_id,
            command_id,
            str(item["command_title"]),
            str(item["command"]),
            list(item["notes"]),
        ))
    table_html = (
        '<table class="matrix instruction-table"><thead><tr>'
        f'{th("Step")}{th("Workflow step")}{th("Input")}{th("Output")}{th("Passes on")}{th("Commands")}'
        '</tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table>'
    )
    tool_root = REPO_ROOT
    if ".assurance-scan/runtime" in str(tool_root) or ".asvs-scanner/runtime" in str(tool_root):
        tool_root = Path("/Users/jd/Development/assurance-scan")
    return (
        '<div class="instructions-page stack" '
        f'data-report-dir="{html.escape(report_path)}" '
        f'data-fr-catalog="{html.escape(fr_catalog)}" '
        f'data-default-fr-catalog="{html.escape(default_project_fr_catalog)}" '
        f'data-reviewed-fr-catalog="{html.escape(default_reviewed_fr_catalog)}" '
        f'data-tool-root="{html.escape(str(tool_root))}" '
        f'data-junit-path="{html.escape(junit_path)}" '
        f'data-approved-tbts="{html.escape(json.dumps(approved_tbt_ids))}" '
        f'data-source-repo="{html.escape(source_repo)}">'
        '<section class="card instruction-hero-card">'
        '<div class="instruction-hero">'
        '<div><span class="instruction-eyebrow">Assurance workflow cockpit</span><h2>Instructions</h2>'
        '<p>Follow the artifact handoff from standards and discovery through reviewed FR/TBT scope, evidence generation and exportable assurance proof. The commands and prompts below update from the selected framework, compliance regime, mount strategy and test execution choices.</p></div>'
        '<div class="instruction-hero-facts">'
        '<span><b>Current stage</b><strong>' + html.escape(active_workflow_step) + '</strong></span>'
        '<span><b>Artifact model</b><strong>typed + review gated</strong></span>'
        '<span><b>Execution</b><strong>copyable commands</strong></span>'
        '</div>'
        '</div>'
        '<div class="instruction-flow-workspace">'
        '<div class="instruction-flow-stage"><div class="instruction-flow-stage-head"><strong>Process routes</strong><span>Click a box to inspect commands and prompts. Diamonds are choices; dashed lines are optional paths; purple paths loop evidence back into a scan.</span></div>'
        '<div class="instruction-flow-map" id="instruction-flow-map" aria-label="Assurance workflow map"></div></div>'
        '<aside class="instruction-flow-detail" id="instruction-flow-detail" aria-live="polite"></aside>'
        '</div>'
        '<div class="instruction-flow-menu" id="instruction-flow-menu" hidden></div>'
        f'<script type="application/json" id="instruction-workflow-data">{workflow_flow_json}</script>'
        '<div class="instruction-context">'
        f'<span><b>Source repo</b><code>{html.escape(source_repo or "not recorded")}</code></span>'
        f'<span><b>Report dir</b><code>{html.escape(report_path)}</code></span>'
        '</div>'
        '<div class="instruction-options" aria-label="Instruction command options">'
        '<label data-instruction-control="source" data-tooltip="Run from&#10;&#10;Choose how the command identifies the target code project.&#10;&#10;Target project folder means you first cd into the project and the command uses $PWD.&#10;&#10;Recorded source repo uses the source path captured in this report, so the command can be copied from another folder."><span>Run from</span><select id="instruction-source-mode-select">'
        '<option value="pwd" selected>Target project folder ($PWD)</option>'
        f'<option value="recorded">Recorded source repo ({html.escape(Path(source_repo).name if source_repo else "not recorded")})</option>'
        '</select></label>'
        '<label data-instruction-control="image" data-tooltip="Docker image&#10;&#10;The assurance-scan container image used to run the command.&#10;&#10;Use local after rebuilding on this machine. Use latest only when you intentionally want a published image tag."><span>Docker image</span><select id="instruction-image-select">'
        '<option value="assurance-scan:local" selected>assurance-scan:local</option>'
        '<option value="assurance-scan:latest">assurance-scan:latest</option>'
        '</select></label>'
        '<label data-instruction-control="mount" data-tooltip="Mount scope&#10;&#10;Controls which host folder is visible inside Docker. The path must include both the target project and any report/config files referenced by the command.&#10;&#10;Parent of current folder is the usual choice when you run from the project folder. Current project only is tighter but fails if the report directory lives outside the project. /Users/jd/Development is broader and useful when project and report folders are siblings. Custom lets you provide an explicit absolute host path."><span>Mount scope</span><select id="instruction-mount-select">'
        '<option value="parent" selected>Parent of current folder</option>'
        '<option value="project">Current project only</option>'
        '<option value="development">/Users/jd/Development</option>'
        '<option value="custom">Custom absolute path</option>'
        '</select></label>'
        '<label data-instruction-control="custom-mount" data-tooltip="Custom mount path&#10;&#10;Used only when Mount scope is Custom. Enter an absolute folder that contains every host path used by the generated Docker command."><span>Custom mount path</span><input id="instruction-custom-mount-input" value="/Users/jd/Development" /></label>'
        '<label data-instruction-control="fr-catalog" data-tooltip="FR catalog for Step 2&#10;&#10;Controls whether the initial scan starts from no prior project FR catalog or intentionally reuses one.&#10;&#10;Discovery scan is the default for a new target project. Use this report snapshot only when you deliberately want to rescan against the current report catalog. Custom/project path is for a reviewed FR catalog you keep with the code project."><span>FR catalog</span><select id="instruction-fr-catalog-mode-select">'
        '<option value="none" selected>Discovery scan, no prior FR catalog</option>'
        '<option value="snapshot">Use this report snapshot</option>'
        '<option value="custom">Custom/project FR catalog</option>'
        '</select></label>'
        '<label data-instruction-control="custom-fr-catalog" data-tooltip="Custom FR catalog path&#10;&#10;Used only when FR catalog is Custom/project FR catalog. Enter a path visible inside Docker, usually a file under the target project or mounted workspace."><span>Custom FR catalog</span><input id="instruction-custom-fr-catalog-input" value="./.assurance-scan/runtime/{project_id}.fr-catalog.enriched.json" /></label>'
        '<label data-instruction-control="test-execution" data-tooltip="Test execution&#10;&#10;Controls how approved project tests are run.&#10;&#10;Docker test container runs the tests inside a separate Node container, which is more repeatable and isolated.&#10;&#10;Host runner inside scan container runs from inside the assurance-scan container environment and is useful only when that image already has the project test runtime available."><span>Test execution</span><select id="instruction-test-mode-select">'
        '<option value="docker" selected>Docker test container</option>'
        '<option value="host">Host runner inside scan container</option>'
        '</select></label>'
        '<label data-instruction-control="evidence-outcome" data-tooltip="Evidence step outcome&#10;&#10;Full scan creates a fresh scan using the accepted FR catalog from Steps 3, 4A and 4B. This is the normal next step after accepting blueprint scope.&#10;&#10;Tests only writes JUnit XML and refreshes the current report evidence without creating a new scan directory. Use it only when approved tests already exist.&#10;&#10;Tests then full scan does both in sequence."><span>Evidence step outcome</span><select id="instruction-step4-outcome-select">'
        '<option value="full-scan" selected>Full scan with reviewed FR catalog</option>'
        '<option value="tests-only">Tests only, refresh current report</option>'
        '<option value="tests-then-full-scan">Tests, then full scan</option>'
        '</select></label>'
        '</div>'
        '</section>'
        '<details class="card instruction-prompt-library fw-regime-tabs"><summary><span>Reference prompts</span><em>fallback prompts for cases not covered by the selected workflow node</em></summary>'
        '<div class="fw-regime-tabbar" role="tablist" aria-label="Workflow prompt types">'
        '<button type="button" class="fw-regime-tab-btn active" data-fw-tab-target="instruction-prompt-remediation" aria-selected="true">Remediation</button>'
        '<button type="button" class="fw-regime-tab-btn" data-fw-tab-target="instruction-prompt-config" aria-selected="false">Config Updates</button>'
        '<button type="button" class="fw-regime-tab-btn" data-fw-tab-target="instruction-prompt-assurance" aria-selected="false">Assurance Tests</button>'
        '</div>'
        f'<div class="fw-regime-pane active" id="instruction-prompt-remediation">{render_fixplan(report_dir)}</div>'
        f'<div class="fw-regime-pane" id="instruction-prompt-config">{render_config_update_prompt_tab(report_dir)}</div>'
        f'<div class="fw-regime-pane" id="instruction-prompt-assurance">{render_assurance_prompt_tab(report_dir)}</div>'
        '</details>'
        '<section class="card"><div class="card-head"><h2>Report Checks</h2><span class="meta">use after refresh or export</span></div>'
        '<div class="instruction-command-grid">'
        f'{render_instruction_command("cmd-validate-report", "Validate report graph artifacts", validate_report_command, "Checks dashboard payload and graph manifest.")}'
        f'{render_instruction_command("cmd-refresh-dashboard", "Refresh this dashboard only", refresh_dashboard_command, "Keeps the same report directory.")}'
        '</div></section>'
        '</div>'
    )


def render_assurance_deficiencies(deficiencies: list[dict]) -> str:
    if not deficiencies:
        return ""
    rows = []
    for item in deficiencies[:20]:
        related = ", ".join(str(v) for v in item.get("related", [])[:4]) or "-"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(item.get('fr_id', ''))}</code><div class=\"manual-desc\">{html.escape(item.get('title', ''))}</div></td>"
            f"<td><span class=\"pill\" style=\"--c:#ffd166\">{html.escape(item.get('test_type', 'test'))}</span></td>"
            f"<td>{html.escape(item.get('gap', '').replace('_', ' '))}</td>"
            f"<td>{html.escape(item.get('suggestion', ''))}<div class=\"manual-evidence\">{html.escape(related)}</div></td>"
            "</tr>"
        )
    more = ""
    if len(deficiencies) > 20:
        more = f'<div class="callout">Showing 20 of {len(deficiencies)} assurance deficiencies. See Agent Prompts for the full list.</div>'
    return (
        '<section class="card" data-overview-section="assurance-deficiencies">'
        '<div class="card-head"><h2>Assurance Deficiencies</h2>'
        '<span class="meta">mapped FRs that need stronger project evidence</span></div>'
        f'{more}'
        '<table class="matrix"><thead><tr><th>FR</th><th>Suggested test</th><th>Gap</th><th>Agent action</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></section>'
    )


def render_test_evidence(evidence: dict) -> str:
    test_evidence = evidence.get("test_evidence") or {}
    pack = evidence.get("assurance_test_pack") or {}
    inventory = test_evidence.get("inventory") or {}
    junit = test_evidence.get("junit") or {}
    pack_summary = pack.get("summary") or {}
    by_type = inventory.get("by_type") or {}
    rows = [
        ("Discovered test files", inventory.get("files", 0), "source inventory"),
        ("Discovered test cases", inventory.get("cases", 0), "source inventory"),
        ("Assurance tests copied", pack_summary.get("copied_native", 0), pack.get("path") or "VG_TEST_FRAMEWORK not generated"),
        ("TBT tests needing design", pack_summary.get("planned_tbt", 0), pack.get("path") or "VG_TEST_FRAMEWORK not generated"),
        ("JUnit passed", junit.get("passed", 0), junit.get("path") or "no junit.xml supplied"),
        ("JUnit failed", junit.get("failed", 0), junit.get("path") or "no junit.xml supplied"),
        ("JUnit execution errors", junit.get("execution_error", 0), junit.get("path") or "no junit.xml supplied"),
        ("JUnit skipped", junit.get("skipped", 0), junit.get("path") or "no junit.xml supplied"),
    ]
    type_bits = " · ".join(f"{html.escape(str(k))}: {html.escape(str(v))}" for k, v in sorted(by_type.items()))
    body = "".join(
        f"<div class=\"kv\"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"
        f"<div class=\"manual-evidence\">{html.escape(str(note))}</div>"
        for label, value, note in rows
    )
    if type_bits:
        body += f'<div class="callout">Native test types discovered: {type_bits}</div>'
    return (
        '<section class="card" data-overview-section="test-evidence">'
        '<div class="card-head"><h2>Project Test Evidence</h2>'
        '<span class="meta">native tests and exported execution proof</span></div>'
        f'<div class="dense-list">{body}</div></section>'
    )


def kpi(label: str, value: str, accent: str, icon: str, sub: str = "") -> str:
    return (
        f'<div class="kpi" style="--accent:{accent}">'
        f'<div class="kpi-icon">{ICONS.get(icon, ICONS["shield"])}</div>'
        f'<div class="kpi-value">{html.escape(value)}</div>'
        f'<div class="kpi-label">{html.escape(label)}</div>'
        f'{f"<div class=\"kpi-sub\">{html.escape(sub)}</div>" if sub else ""}'
        f'</div>'
    )


# ===========================================================================
# Top-level
# ===========================================================================

GRAPH_JS = load_dashboard_asset("10-graph-runtime.js")
DASHBOARD_INTERACTIONS_JS = load_dashboard_asset("20-dashboard-interactions.js")


def _normalise_dashboard_payload_graph(graph: dict) -> dict:
    status_map = {
        "satisfied": "passed",
        "unaddressed": "missing",
        "discovered": "in_scope",
        "auto": "passed",
        "manual": "manual_review",
        "met": "ready",
    }
    allowed_statuses = {
        "draft", "in_scope", "deferred", "not_applicable", "retired", "planned", "implemented",
        "passed", "failed", "execution_error", "missing", "manual_review", "waived", "ready",
        "blocked", "partial", "pending", "approved", "rejected",
    }

    nodes = []
    for node in graph.get("nodes") or []:
        node_type = normalise_graph_node_type(node.get("type"))
        status = node.get("status") or node.get("evidence_status")
        payload_node = {
            "id": str(node.get("id", "")),
            "type": node_type,
            "label": str(node.get("label") or node.get("id") or ""),
            "lane": str(node.get("lane") or ""),
            "source": {},
            "metadata": {
                key: value
                for key, value in node.items()
                if key not in {"id", "type", "label", "lane", "source"}
            },
        }
        if status:
            mapped_status = status_map.get(str(status), str(status))
            if mapped_status in allowed_statuses:
                payload_node["status"] = mapped_status
        nodes.append(payload_node)

    edges = []
    for edge in graph.get("edges") or []:
        raw_edge_type = edge.get("type")
        responsibility = graph_edge_responsibility(raw_edge_type, edge.get("responsibility"))
        payload_edge = {
            "source": str(edge.get("source", "")),
            "target": str(edge.get("target", "")),
            "type": normalise_graph_edge_type(raw_edge_type),
            "label": str(raw_edge_type or ""),
            "metadata": {
                key: value
                for key, value in edge.items()
                if key not in {"source", "target", "type", "label", "responsibility"}
            },
        }
        if responsibility in GRAPH_RESPONSIBILITIES:
            payload_edge["responsibility"] = responsibility
        edges.append(payload_edge)
    return {"nodes": nodes, "edges": edges}


def _framework_gate_count(path: Path) -> tuple[int, int, int]:
    data = load_json(path) or {}
    processes = data.get("processes") or []
    gates = sum(len(process.get("gates") or []) for process in processes)
    criteria = sum(
        len(gate.get("criteria") or [])
        for process in processes
        for gate in process.get("gates") or []
    )
    versioned = 1 if data.get("version") else 0
    return gates, criteria, versioned


def _richest_framework_path(report_dir: Path) -> str | None:
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        report_dir / "assurance-framework.snapshot.json",
        repo_root / "data" / "assurance-frameworks" / "jsp-453" / "1.0.0-draft.json",
    ]
    for parent in [report_dir, *report_dir.parents]:
        if parent.name == "runtime":
            candidates.extend([
                parent / "data" / "assurance-frameworks" / "jsp-453" / "1.0.0-draft.json",
                parent / "jsp-453.assurance-framework.draft.json",
                parent / "data" / "fixtures" / "target-schemas" / "assurance-framework.example.json",
            ])
            break
    candidates.append(repo_root / "data" / "fixtures" / "target-schemas" / "assurance-framework.example.json")
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None
    return str(max(existing, key=_framework_gate_count))


def _load_scanner_compliance_packs(paths: list[str] | None) -> list[dict] | None:
    if not paths:
        return None
    packs: list[dict] = []
    for raw_path in paths:
        path = Path(raw_path)
        candidates = sorted(path.rglob("*.json")) if path.is_dir() else [path]
        for candidate in candidates:
            data = load_json(candidate)
            if isinstance(data, dict) and data.get("schema_version") == 1 and data.get("mappings"):
                packs.append(data)
    return packs


def _assurance_instance_load_errors(instance: dict, framework: dict, project: str) -> list[str]:
    errors: list[str] = []
    instance_project = str(instance.get("project") or "")
    if project and instance_project and instance_project != project:
        errors.append(f"project mismatch: instance={instance_project} report={project}")

    role_ids = {role.get("id") for role in framework.get("roles") or [] if role.get("id")}
    gate_ids: set[str] = set()
    criterion_ids: set[str] = set()
    for process in framework.get("processes") or []:
        for gate in process.get("gates") or []:
            if gate.get("id"):
                gate_ids.add(gate["id"])
            for criterion in gate.get("criteria") or []:
                if criterion.get("id"):
                    criterion_ids.add(criterion["id"])

    for mapping in instance.get("criterion_mappings") or []:
        criterion = mapping.get("criterion")
        if criterion and criterion not in criterion_ids:
            errors.append(f"unknown criterion: {criterion}")
    for assignment in instance.get("role_assignments") or []:
        gate = assignment.get("gate")
        role = assignment.get("role")
        if gate and gate not in gate_ids:
            errors.append(f"unknown gate: {gate}")
        if role and role not in role_ids:
            errors.append(f"unknown role: {role}")
    for decision in instance.get("decisions") or []:
        gate = decision.get("gate")
        criterion = decision.get("criterion")
        if gate and gate not in gate_ids:
            errors.append(f"unknown decision gate: {gate}")
        if criterion and criterion not in criterion_ids:
            errors.append(f"unknown decision criterion: {criterion}")
    return errors


def _usable_assurance_instance_path(report_dir: Path, explicit_path: str | None, framework_path: str | None, project: str) -> str | None:
    candidate = explicit_path
    if not candidate and (report_dir / "assurance-instance.snapshot.json").exists():
        candidate = str(report_dir / "assurance-instance.snapshot.json")
    if not candidate:
        return None
    instance = load_json(Path(candidate))
    framework = load_json(Path(framework_path)) if framework_path else {}
    errors = _assurance_instance_load_errors(instance, framework, project) if instance and framework else []
    if errors:
        warning = f"WARN: Ignoring assurance instance {candidate}: {'; '.join(errors)}\n"
        try:
            with (report_dir / "run.log").open("a") as fh:
                fh.write(warning)
        except Exception:
            pass
        return None
    return candidate


def _default_scanner_compliance_mapping_paths(report_dir: Path) -> list[str]:
    paths: list[str] = []
    for candidate in (
        report_dir / "scanner-compliance-mapping-packs",
        Path(__file__).resolve().parent.parent / "data" / "scanner-mappings",
    ):
        if candidate.exists():
            paths.append(str(candidate))
    return paths




def _project_id_for_report(report_dir: Path) -> str:
    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    project_id = str(
        evidence.get("repository")
        or evidence.get("repo_name")
        or git_repo_name(str(evidence.get("source_repo") or evidence.get("target_dir") or ""))
        or ""
    ).strip()
    return project_id


def _discover_project_fr_catalog_path(report_dir: Path) -> str | None:
    report_snapshot = report_dir / "fr-catalog.snapshot.json"
    if report_snapshot.exists():
        return str(report_snapshot)

    project_id = _project_id_for_report(report_dir)
    if not project_id:
        return None

    runtime_dir = report_dir.parent.parent if report_dir.parent.name == "reports" else report_dir.parent
    for suffix in ("reviewed", "enriched", "draft"):
        candidate = runtime_dir / f"{project_id}.fr-catalog.{suffix}.json"
        if candidate.exists():
            return str(candidate)
    return None

def render(*, report_dir: Path, fr_catalog_path: str | None = None,
           assurance_framework_path: str | None = None,
           assurance_instance_path: str | None = None,
           junit_xml_path: str | None = None,
           compliance_mapping_pack_path: str | None = None,
           scanner_compliance_mapping_paths: list[str] | None = None) -> str:
    if not fr_catalog_path:
        fr_catalog_path = _discover_project_fr_catalog_path(report_dir)
    if not assurance_framework_path:
        assurance_framework_path = _richest_framework_path(report_dir)

    # Lazy imports for FR-driven tabs — loaded at call time to avoid circular imports
    if fr_catalog_path:
        from fr.catalog_tab import render_fr_catalog
        from fr.framework_tab import (
            render_framework_tab, RULESET_SNAPSHOTS,
            _compute_fr_evidence_status, _load_junit_index,
            _load_test_inventory, _tbts_by_fr,
        )

    evidence = load_json(report_dir / "evidence-manifest.json") or {}
    project_name = str(evidence.get("repository") or evidence.get("repo_name") or git_repo_name(str(evidence.get("target_dir", ""))) or "")
    assurance_instance_path = _usable_assurance_instance_path(
        report_dir,
        assurance_instance_path,
        assurance_framework_path,
        project_name,
    )
    if not scanner_compliance_mapping_paths:
        scanner_compliance_mapping_paths = _default_scanner_compliance_mapping_paths(report_dir)
    scanner_health = evidence.get("scanner_health", {})
    findings = evidence.get("findings_summary", {})
    assurance = evidence.get("assurance", {})
    ignored = parse_ignored_from_log(report_dir / "run.log")

    sev = aggregate_severity_strict(findings)
    total_findings = actionable_finding_total(findings)
    critical_count = sev.get('CRITICAL', 0)
    high_count = sev.get('HIGH', 0)
    medium_count = sev.get('MEDIUM', 0)
    low_count = sev.get('LOW', 0)
    rec = str(assurance.get("release_recommendation", "UNKNOWN"))
    rec_color = C["pass"] if rec == "READY" else C["fail"]
    failed = assurance.get("failed", sum(1 for info in scanner_health.values() if info.get("status") == "FAIL"))
    warned = assurance.get("warned", sum(1 for info in scanner_health.values() if info.get("status") == "WARN"))
    skipped = assurance.get("skipped", sum(1 for info in scanner_health.values() if info.get("status") == "SKIPPED"))
    secrets = findings.get("gitleaks", 0) if isinstance(findings.get("gitleaks"), int) else 0
    secret_rules, secret_files, _secret_total = secret_breakdowns(report_dir / 'reports' / 'gitleaks.json')
    secret_type_count = len(secret_rules)
    secret_file_count = len(secret_files)
    auto_pct = assurance.get("automated_assurance_pct", 0)
    asvs_pct = assurance.get("asvs_traceability_pct", 0)
    scanner_issues = critical_high_issues(report_dir) + medium_low_issues(report_dir)
    issue_triage_html = render_issue_triage_kpis(report_dir, scanner_issues)

    overview_html = render_overview(evidence, report_dir, ignored)
    evidence_html = render_coverage(evidence, report_dir)
    instructions_html = render_instructions_page(report_dir, evidence)

    assurance_status_payload: dict[str, Any] = {}
    fr_catalog_html = ""

    # Framework tabs — one per framework in the project's scope
    framework_tabs_html: list[tuple[str, str]] = []  # (tab_id, fw_name, html)
    assurance_framework_label = "Assurance Gates"
    process_flow_json = '{"processes":[]}'
    reverse_lookup_json = "[]"
    graph_json = '{"nodes":[],"edges":[]}'
    catalog = None
    assurance_framework = None
    assurance_instance_payload = load_json(Path(assurance_instance_path)) if assurance_instance_path else {}
    fr_evidence_status: dict[str, tuple[str, list[dict]]] = {}
    assurance_deficiencies: list[dict] = []
    target_evidence_bundle = (
        load_json(report_dir / "evidence-bundle.json")
        or load_json(report_dir / "reports" / "evidence-bundle.json")
        or {}
    )
    scanner_findings_for_graph = scanner_finding_records(report_dir)
    scanner_compliance_packs_payload = _load_scanner_compliance_packs(scanner_compliance_mapping_paths)
    compliance_regime_paths = discover_compliance_regime_paths(
        fr_catalog_path=fr_catalog_path,
        scanner_compliance_packs=scanner_compliance_packs_payload,
    )
    if fr_catalog_path and target_evidence_bundle:
        try:
            import importlib.util
            resolver_path = Path(__file__).resolve().parent / "resolve-assurance-status.py"
            spec = importlib.util.spec_from_file_location("resolve_assurance_status_runtime", resolver_path)
            if spec and spec.loader:
                resolver_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(resolver_mod)
                from argparse import Namespace
                with tempfile.NamedTemporaryFile("w", suffix=".evidence-bundle.json", delete=True) as temp_bundle:
                    temp_bundle.write(json.dumps(target_evidence_bundle))
                    temp_bundle.flush()
                    resolve_args = {
                        "fr_catalog": Path(fr_catalog_path),
                        "evidence_bundle": Path(temp_bundle.name),
                    }
                    if assurance_instance_path:
                        resolve_args["assurance_instance"] = Path(assurance_instance_path)
                    resolve_args["scanner_findings"] = scanner_findings_for_graph
                    if scanner_compliance_packs_payload is not None:
                        resolve_args["scanner_compliance_packs"] = scanner_compliance_packs_payload
                    assurance_status_payload = resolver_mod.resolve(Namespace(**resolve_args))
        except Exception:
            assurance_status_payload = {}
    if fr_catalog_path:
        import importlib.util
        loader_path = Path(__file__).resolve().parent / "load_fr_catalog.py"
        spec = importlib.util.spec_from_file_location("load_fr_catalog_runtime", loader_path)
        if spec and spec.loader:
            loader_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loader_mod)
            try:
                catalog = loader_mod.load_fr_catalog(Path(fr_catalog_path))
                rulesets_to_render: list[str] = []
                for fw in catalog.scope:
                    if fw in RULESET_SNAPSHOTS and fw not in rulesets_to_render:
                        rulesets_to_render.append(fw)
                for pack in scanner_compliance_packs_payload or []:
                    compliance = pack.get("compliance") or {}
                    fw = str(compliance.get("ruleset") or "").strip()
                    if fw in RULESET_SNAPSHOTS and fw not in rulesets_to_render:
                        rulesets_to_render.append(fw)
                    for mapping in pack.get("mappings") or []:
                        for target in (mapping.get("targets") or {}).get("compliance_rows") or []:
                            fw = str(target.get("ruleset") or "").strip()
                            if fw in RULESET_SNAPSHOTS and fw not in rulesets_to_render:
                                rulesets_to_render.append(fw)
                for path in compliance_regime_paths or []:
                    parts = Path(path).parts
                    slug = parts[-2] if len(parts) >= 2 else ""
                    slug_map = {"asvs": "ASVS", "nist-800-53": "NIST-800-53"}
                    fw = slug_map.get(slug, "")
                    if fw in RULESET_SNAPSHOTS and fw not in rulesets_to_render:
                        rulesets_to_render.append(fw)
                for fw in rulesets_to_render:
                    tab_html = render_framework_tab(fw, catalog, report_dir, junit_xml_path, assurance_status_payload)
                    tab_id = f"fw-{fw.lower().replace('-', '').replace('_', '')}"
                    framework_tabs_html.append((tab_id, fw, tab_html))

                # Build reverse lookup index for "Find ASVS impact" feature.
                # Maps scanner TBT refs to the FR IDs + compliance rows they inform.
                reverse_lookup: dict[str, dict] = {}
                tbts_for_fr = _tbts_by_fr(catalog)
                for fr in getattr(catalog, "frs", []) or []:
                    for tbt in tbts_for_fr.get(fr.get("id", ""), []):
                        if tbt.get("type") == "scanner":
                            ref = tbt.get("ref") or tbt.get("id", "")
                            entry = reverse_lookup.setdefault(ref, {"fr_ids": [], "compliance_rows": []})
                            if fr["id"] not in entry["fr_ids"]:
                                entry["fr_ids"].append(fr["id"])
                            for row in tbt.get("compliance") or []:
                                row_ref = {"ruleset": row.get("ruleset", ""), "row": row.get("row", "")}
                                if row_ref not in entry["compliance_rows"]:
                                    entry["compliance_rows"].append(row_ref)
                reverse_lookup_json = json.dumps(list(reverse_lookup.items()))

                test_index = _load_junit_index(report_dir, junit_xml_path)
                inventory_index = _load_test_inventory(report_dir)
                for fr in getattr(catalog, "frs", []) or []:
                    fr_evidence_status[fr["id"]] = _compute_fr_evidence_status(
                        fr,
                        tbts_for_fr.get(fr["id"], []),
                        report_dir,
                        test_index,
                        inventory_index,
                    )
                if target_evidence_bundle.get("evidence") and getattr(catalog, "tbts", None):
                    evidence_by_tbt: dict[str, list[dict]] = {}
                    for ev in target_evidence_bundle.get("evidence") or []:
                        produced_by = ev.get("produced_by")
                        if produced_by:
                            evidence_by_tbt.setdefault(produced_by, []).append(ev)
                    for fr in getattr(catalog, "frs", []) or []:
                        fr_id = fr.get("id")
                        if not fr_id:
                            continue
                        fr_tbts = [
                            tbt for tbt in getattr(catalog, "tbts", []) or []
                            if fr_id in (tbt.get("proves") or [])
                        ]
                        if not fr_tbts:
                            continue
                        statuses: list[str] = []
                        evidence_notes: list[dict] = []
                        for tbt in fr_tbts:
                            tbt_id = tbt.get("id", "")
                            records = evidence_by_tbt.get(tbt.get("id", "")) or []
                            if not records:
                                statuses.append("missing")
                                evidence_notes.append({
                                    "scanner": tbt.get("type", "evidence"),
                                    "rule_id": tbt_id,
                                    "location": "evidence-bundle.json",
                                    "message": f"{tbt_id} has no observed evidence record.",
                                })
                                continue
                            record_statuses = {record.get("result_status", "missing") for record in records}
                            if "failed" in record_statuses:
                                statuses.append("failed")
                                evidence_notes.extend({
                                    "scanner": record.get("tool") or tbt.get("type", "evidence"),
                                    "rule_id": tbt_id,
                                    "location": record.get("source_locator") or record.get("source", ""),
                                    "message": record.get("source_excerpt") or f"{tbt_id} evidence failed",
                                } for record in records if record.get("result_status") == "failed")
                            elif "execution_error" in record_statuses:
                                statuses.append("execution_error")
                                evidence_notes.extend({
                                    "scanner": record.get("tool") or tbt.get("type", "evidence"),
                                    "rule_id": tbt_id,
                                    "location": record.get("source_locator") or record.get("source", ""),
                                    "message": (record.get("metadata") or {}).get("message") or f"{tbt_id} test execution had a harness/runtime error",
                                } for record in records if record.get("result_status") == "execution_error")
                            elif "passed" in record_statuses and "missing" in record_statuses:
                                statuses.append("partial")
                                evidence_notes.append({
                                    "scanner": tbt.get("type", "evidence"),
                                    "rule_id": tbt_id,
                                    "location": "evidence-bundle.json",
                                    "message": f"{tbt_id} has passing evidence and missing expected evidence.",
                                })
                            elif "missing" in record_statuses:
                                statuses.append("missing")
                                evidence_notes.append({
                                    "scanner": tbt.get("type", "evidence"),
                                    "rule_id": tbt_id,
                                    "location": "evidence-bundle.json",
                                    "message": f"{tbt_id} evidence is recorded as missing.",
                                })
                            elif "passed" in record_statuses:
                                statuses.append("passed")
                            else:
                                statuses.append("partial")
                                evidence_notes.append({
                                    "scanner": tbt.get("type", "evidence"),
                                    "rule_id": tbt_id,
                                    "location": "evidence-bundle.json",
                                    "message": f"{tbt_id} evidence is present but inconclusive.",
                                })
                        if "failed" in statuses:
                            fr_evidence_status[fr_id] = ("failed", evidence_notes)
                        elif "execution_error" in statuses:
                            fr_evidence_status[fr_id] = ("execution_error", evidence_notes)
                        elif statuses and all(status == "passed" for status in statuses):
                            fr_evidence_status[fr_id] = ("passed", [])
                        elif any(status in ("passed", "partial") for status in statuses):
                            fr_evidence_status[fr_id] = ("partial", evidence_notes)
                        elif "missing" in statuses:
                            fr_evidence_status[fr_id] = ("missing", evidence_notes)
                        else:
                            fr_evidence_status[fr_id] = ("partial", evidence_notes)
                try:
                    from fr.deficiencies import collect_assurance_deficiencies
                    assurance_deficiencies = collect_assurance_deficiencies(catalog, fr_evidence_status)
                except Exception:
                    assurance_deficiencies = []


            except loader_mod.FrCatalogError:
                pass  # error already shown in FR Catalog tab
        if catalog and not assurance_status_payload.get("frs"):
            tbts_for_fr = _tbts_by_fr(catalog)
            tbt_statuses: list[dict[str, Any]] = []
            for tbt in getattr(catalog, "tbts", []) or []:
                tbt_id = tbt.get("id", "")
                if not tbt_id:
                    continue
                linked_frs = list(tbt.get("proves") or [])
                linked_statuses = [
                    fr_evidence_status.get(fr_id, ("missing", []))[0]
                    for fr_id in linked_frs
                ]
                if "failed" in linked_statuses:
                    tbt_state = "failed"
                elif "execution_error" in linked_statuses:
                    tbt_state = "execution_error"
                elif "partial" in linked_statuses:
                    tbt_state = "partial"
                elif linked_statuses and all(state == "passed" for state in linked_statuses):
                    tbt_state = "passed"
                else:
                    tbt_state = "missing"
                tbt_statuses.append({
                    "id": tbt_id,
                    "title": tbt.get("title", tbt_id),
                    "type": tbt.get("type"),
                    "status": tbt_state,
                    "evidence_policy": tbt.get("evidence_policy"),
                    "requirements": tbt.get("expected_evidence", []),
                    "observed_evidence": [],
                    "proves": linked_frs,
                    "reasons": [f"{tbt_id}: {tbt_state}"],
                })
            tbt_status_by_id = {item["id"]: item for item in tbt_statuses}
            assurance_status_payload = {
                **assurance_status_payload,
                "frs": [
                    {
                        "id": fr.get("id"),
                        "title": fr.get("title", fr.get("id", "")),
                        "status": fr_evidence_status.get(fr.get("id", ""), ("missing", []))[0],
                        "tbts": [tbt.get("id") for tbt in tbts_for_fr.get(fr.get("id", ""), []) if tbt.get("id")],
                        "tbt_statuses": [
                            tbt_status_by_id[tbt.get("id")]
                            for tbt in tbts_for_fr.get(fr.get("id", ""), [])
                            if tbt.get("id") in tbt_status_by_id
                        ],
                        "reasons": [
                            note.get("message", "")
                            for note in fr_evidence_status.get(fr.get("id", ""), ("missing", []))[1][:8]
                            if note.get("message")
                        ],
                    }
                    for fr in getattr(catalog, "frs", []) or []
                    if fr.get("id")
                ],
                "tbts": tbt_statuses,
            }
        fr_catalog_html = render_fr_catalog(fr_catalog_path, assurance_status_payload, report_dir=report_dir)

    dashboard_project = str(evidence.get("repository") or evidence.get("repo_name") or git_repo_name(str(evidence.get("target_dir", ""))) or "target-project")
    dashboard_generated_at = str(evidence.get("generated_at") or "1970-01-01T00:00:00Z")
    native_review_board_html = render_native_review_board_page(
        report_dir,
        fr_catalog_html,
        project=dashboard_project,
        run_id=str(evidence.get("run_id") or ""),
        generated_at=dashboard_generated_at,
        source_repo=str(evidence.get("source_repo") or evidence.get("target_dir") or ""),
    )

    framework_options_payload = _load_assurance_framework_options(assurance_framework_path)

    import importlib.util
    from process.process_tab import build_process_flow_data
    loader_path = Path(__file__).resolve().parent / "load_assurance_framework.py"
    spec = importlib.util.spec_from_file_location("load_assurance_framework_runtime", loader_path)
    loader_mod = None
    if spec and spec.loader:
        loader_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader_mod)

    active_framework_resolved = Path(assurance_framework_path).resolve() if assurance_framework_path else None
    if assurance_framework_path and loader_mod:
        try:
            assurance_framework = loader_mod.load_assurance_framework(
                Path(assurance_framework_path),
                assurance_instance_path=Path(assurance_instance_path) if assurance_instance_path else None,
            )
            assurance_framework_label = assurance_framework.title or assurance_framework.assurance_framework or assurance_framework_label
        except loader_mod.AssuranceFrameworkError:
            pass

    for option in framework_options_payload:
        option_path = Path(str(option.get("path") or ""))
        option_framework = None
        option_instance = None
        if loader_mod and option_path.exists():
            try:
                use_instance = bool(active_framework_resolved and option_path.resolve() == active_framework_resolved)
                option_instance = assurance_instance_payload if use_instance else None
                option_framework = assurance_framework if use_instance and assurance_framework else loader_mod.load_assurance_framework(
                    option_path,
                    assurance_instance_path=Path(assurance_instance_path) if use_instance and assurance_instance_path else None,
                )
            except loader_mod.AssuranceFrameworkError:
                option_framework = None
        if option_path.exists():
            option["process_flow"] = build_process_flow_data(
                str(option_path),
                report_dir=report_dir,
                fr_catalog=catalog,
                fr_evidence=fr_evidence_status,
                assurance_framework=option_framework,
                evidence_bundle=target_evidence_bundle,
                assurance_status=assurance_status_payload if option_framework else {},
                assurance_instance=option_instance,
            )

    if assurance_framework_path:
        selected_flow = next((item.get("process_flow") for item in framework_options_payload if item.get("selected") and item.get("process_flow")), None)
        if selected_flow is None:
            selected_flow = build_process_flow_data(
                assurance_framework_path,
                report_dir=report_dir,
                fr_catalog=catalog,
                fr_evidence=fr_evidence_status,
                assurance_framework=assurance_framework,
                evidence_bundle=target_evidence_bundle,
                assurance_status=assurance_status_payload,
                assurance_instance=assurance_instance_payload,
            )
        process_flow_json = json.dumps(selected_flow)

    if catalog or assurance_framework:
        try:
            from fr.graph import build_graph_data as _bgd
            graph_json = json.dumps(_bgd(
                catalog,
                fr_evidence_status,
                assurance_framework=assurance_framework,
                assurance_instance=assurance_instance_payload,
                test_inventory=load_json(report_dir / "reports" / "test-inventory.json") or {},
                assurance_pack=load_json(report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json") or {},
                evidence_bundle=target_evidence_bundle,
                assurance_status=assurance_status_payload,
                scanner_health=scanner_health,
                findings_summary=findings,
                scanner_findings=scanner_findings_for_graph,
                scanner_compliance_packs=scanner_compliance_packs_payload,
                graph_manifest=load_json(report_dir / "graph-manifest.json") or {},
            ))
        except Exception:
            graph_json = '{"nodes":[],"edges":[]}'

    if assurance_deficiencies:
        overview_html = render_assurance_deficiencies(assurance_deficiencies) + overview_html

    try:
        normalized_graph = _normalise_dashboard_payload_graph(json.loads(graph_json))
        projections = graph_projections(normalized_graph)
        evidence_html = render_coverage(evidence, report_dir, projections["evidence_files"])
        if catalog and framework_tabs_html:
            refreshed_framework_tabs: list[tuple[str, str, str]] = []
            ruleset_projections = projections.get("rulesets", {}).get("rulesets", {})
            for tab_id, fw, _html in framework_tabs_html:
                refreshed_framework_tabs.append((
                    tab_id,
                    fw,
                    render_framework_tab(
                        fw,
                        catalog,
                        report_dir,
                        junit_xml_path,
                        assurance_status_payload,
                        ruleset_projections.get(fw, {}),
                    ),
                ))
            framework_tabs_html = refreshed_framework_tabs
        dashboard_payload = {
            "schema_version": 1,
            "project": dashboard_project,
            "generated_at": dashboard_generated_at,
            "inputs": {
                "fr_catalog": str(fr_catalog_path or ""),
                "compliance_regimes": ",".join(str(path) for path in compliance_regime_paths),
                "compliance_mapping_pack": str(compliance_mapping_pack_path or ""),
                "scanner_compliance_mapping_packs": ",".join(scanner_compliance_mapping_paths or []),
                "assurance_framework": str(assurance_framework_path or ""),
                "assurance_frameworks": framework_options_payload,
                "assurance_instance": str(assurance_instance_path or ""),
                "evidence_manifest": "evidence-manifest.json",
                "evidence_bundle": "evidence-bundle.json" if target_evidence_bundle else "",
            },
            "summary": {
                "run_id": evidence.get("run_id"),
                "automated_assurance_pct": assurance.get("automated_assurance_pct", 0),
                "asvs_traceability_pct": assurance.get("asvs_traceability_pct", 0),
                "release_recommendation": assurance.get("release_recommendation", "UNKNOWN"),
                "critical_findings": assurance.get("critical_findings", 0),
                "manual_items_total": assurance.get("manual_items_total", 0),
                "manual_items_completed": assurance.get("manual_items_completed", 0),
            },
            "ruleset_views": {
                fw: {
                    "tab_id": tab_id,
                    "graph_projection": projections["rulesets"]["rulesets"].get(fw, {}),
                }
                for tab_id, fw, _html in framework_tabs_html
            },
            "fr_catalog_view": {
                **projections["project_frs"],
                "catalog_fr_count": len(getattr(catalog, "frs", []) or []) if catalog else 0,
                "catalog_tbt_count": len(getattr(catalog, "tbts", []) or []) if catalog else 0,
            },
            "evidence_view": projections["evidence_files"],
            "graph": normalized_graph,
            "graph_projections": projections,
            "assurance_views": {
                "process_flow": json.loads(process_flow_json),
                "resolved_status": assurance_status_payload,
                "graph_projection": projections["assurance"],
            },
            "deficiencies": [
                {
                    "id": f"DEF-DASH-{idx:03d}",
                    "severity": item.get("severity", "medium"),
                    "type": item.get("gap", "assurance_gap"),
                    "summary": f"{item.get('fr_id', '')} {item.get('title', '')}".strip(),
                }
                for idx, item in enumerate(assurance_deficiencies, start=1)
            ],
        }
        payload_path = report_dir / "dashboard-payload.json"
        payload_path.write_text(json.dumps(dashboard_payload, indent=2))
        record_report_artifact(report_dir, payload_path)
        write_graph_manifest(
            report_dir,
            dashboard_payload,
            fr_catalog_path=fr_catalog_path,
            compliance_regime_paths=compliance_regime_paths,
            compliance_mapping_pack_path=compliance_mapping_pack_path,
            scanner_compliance_mapping_paths=scanner_compliance_mapping_paths or [],
            assurance_framework_path=assurance_framework_path,
            assurance_instance_path=assurance_instance_path,
            evidence_manifest=evidence,
        )
        refresh_existing_assurance_claims_and_proofs(report_dir)
        evidence_html = render_coverage(evidence, report_dir, projections["evidence_files"])
    except Exception:
        pass

    run_id = html.escape(str(evidence.get("run_id", "-")))
    generated = html.escape(str(evidence.get("generated_at", "-"))[:19].replace("T", " "))
    target_raw = str(evidence.get("target_dir", "-"))
    source_repo_raw = str(evidence.get("source_repo") or "")
    repo_name = html.escape(str(evidence.get("repository") or evidence.get("repo_name") or git_repo_name(source_repo_raw) or git_repo_name(target_raw) or "-"))
    branch = html.escape(str(evidence.get("git_branch") or git_branch_name(source_repo_raw) or "-"))
    safe_branch = html.escape(str(evidence.get("safe_scan_branch") or git_branch_name(target_raw) or "-"))
    commit = html.escape(str(evidence.get("git_commit") or "-")[:12])

    def metric(label: str, value: str, color: str = "var(--ink)", overview_filter: str | None = None) -> str:
        attrs = ""
        classes = "metric"
        if overview_filter:
            classes += " summary-action"
            attrs = f' data-overview-filter="{html.escape(overview_filter)}" role="button" tabindex="0" aria-pressed="false" title="Show only {html.escape(label.lower())}"'
        return f'<div class="{classes}" style="--metric-color:{color}"{attrs}><b>{html.escape(value)}</b><span>{html.escape(label)}</span></div>'

    def split_metric(label: str, left_label: str, left_value: int, right_label: str, right_value: int, color: str, overview_filter: str, left_color: str | None = None, right_color: str | None = None) -> str:
        title = f'Show only {label.lower()}'
        left_style = f' style="--half-color:{left_color}"' if left_color else ''
        right_style = f' style="--half-color:{right_color}"' if right_color else ''
        return (
            f'<div class="metric split summary-action" style="--metric-color:{color}" data-overview-filter="{html.escape(overview_filter)}" '
            f'role="button" tabindex="0" aria-pressed="false" title="{html.escape(title)}">'
            f'<div class="metric-half"{left_style}><b>{left_value}</b><span>{html.escape(left_label)}</span></div>'
            f'<div class="metric-half"{right_style}><b>{right_value}</b><span>{html.escape(right_label)}</span></div>'
            '</div>'
        )

    compliance_page_html = "".join(
        '<div class="compliance-ruleset-view" data-compliance-ruleset="' + html.escape(fw) + '" id="compliance-' + html.escape(tab_id) + '">' + html_ + '</div>'
        for tab_id, fw, html_ in framework_tabs_html
    )
    compliance_nav_html = (
        f'<button class="tab-btn" data-tab="compliance">{ICONS["shield"]}<span>Compliance Regime</span></button>'
        if framework_tabs_html else ''
    )
    framework_options_json = json.dumps(framework_options_payload)
    industry_framework_label = 'Assurance Framework'
    gateflow_intro = (
        '<div class="page-intro"><div><h2>Industry Framework</h2><ul>'
        '<li>Shows gated process flow and readiness</li>'
        '<li>Links gates to roles, criteria and manual proof</li>'
        '<li>Highlights what blocks approval</li>'
        '</ul></div></div>'
    )
    graph_intro = (
        '<div class="page-intro"><div><h2>Traceability Graph</h2><ul>'
        '<li>Walk FRs, gates and compliance rows as chains</li>'
        '<li>Separate requirements, tests and evidence into lanes</li>'
        '<li>Click nodes for context and next actions</li>'
        '</ul></div></div>'
    )

    nav_html = f"""
      <button class="tab-btn" data-tab="overview">{ICONS['list']}<span>Scanner Results</span></button>
      <button class="tab-btn" data-tab="evidence">{ICONS['list']}<span>Files</span></button>
      <button class="tab-btn" data-tab="instructions">{ICONS['doc']}<span>Instructions</span></button>
      <button class="tab-btn" data-tab="nativereview">{ICONS['shield']}<span>Project FRs</span></button>
      {compliance_nav_html}
      {f'<button class="tab-btn" data-tab="gateflow">{ICONS["filter"]}<span>{industry_framework_label}</span></button>' if assurance_framework else ''}
      {'<button class="tab-btn" data-tab="graph">' + ICONS['filter'] + '<span>Traceability Graph</span></button>' if (fr_catalog_html or assurance_framework) else ''}
    """

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VibeGuide Assurance Engine - {run_id}</title>
<style>{CSS}</style>
</head><body data-active-tab="overview">
<div class="shell">
  <header class="topbar">
    <div class="brand">
      <h1 data-tooltip="VibeGuide Assurance Engine&#10;&#10;A traceable assurance workspace that links functional requirements, TBT tests, evidence, compliance regimes, industry frameworks, process gates, roles, and remediation prompts.">VibeGuide Assurance Engine</h1>
    </div>
    <div class="scan-meta">
      <table>
        <tbody>
          <tr><th>Repository</th><td>{repo_name}</td><th>Original branch</th><td>{branch}</td><th>Latest commit</th><td>{commit}</td></tr>
          <tr><th>Generated</th><td>{generated}</td><th>Safe scan branch</th><td>{safe_branch}</td><th>Report ID</th><td>{run_id}</td></tr>
        </tbody>
      </table>
    </div>
  </header>

  <section class="assurance-context" aria-label="Assurance context">
    <div class="assurance-context-title"><strong>Assurance context</strong><span>These choices drive the framework, compliance and graph views.</span></div>
    <label class="assurance-context-field assurance-context-framework"><span>Assurance Framework</span><select id="global-framework-select" class="graph-select"></select></label>
    <label class="assurance-context-field assurance-context-framework"><span>Gated flow</span><select id="global-process-select" class="graph-select"></select></label>
    <label class="assurance-context-field assurance-context-compliance"><span>Compliance regime</span><select id="global-ruleset-select" class="graph-select"></select></label>
    <label class="assurance-context-field assurance-context-wide assurance-context-compliance"><span>Chapter / family</span><select id="global-chapter-select" class="graph-select"></select></label>
  </section>

  <div class="dashboard-shell">
    <aside class="side-nav" aria-label="Dashboard sections">
      <div class="side-nav-title">Views</div>
      <nav class="nav">
        {nav_html}
      </nav>
    </aside>
    <div class="dashboard-workspace">
  <section class="command-strip">
    <div class="metric-stack">
      <div class="metric-grid">
        {metric('Raw scanner findings', str(total_findings), C['warn'] if total_findings else C['pass'], 'all-findings')}
        {split_metric('Critical load', 'Critical', critical_count, 'High', high_count, C['fail'] if critical_count or high_count else C['pass'], 'cves', left_color=C['critical'], right_color=C['high'])}
        {split_metric('Medium / Low', 'Medium', medium_count, 'Low', low_count, C['warn'] if medium_count or low_count else C['pass'], 'medium-low', left_color=C['medium'], right_color=C['low'])}
        {split_metric('Secrets', 'Secret Types', secret_type_count, 'Secret Files', secret_file_count, C['fail'] if secrets else C['pass'], 'secrets')}
      </div>
      {issue_triage_html}
    </div>
  </section>

  <main>
    <div class="panel active" id="tab-overview">{overview_html}</div>
    <div class="panel" id="tab-evidence">{evidence_html}</div>
    <div class="panel" id="tab-instructions">{instructions_html}</div>
    <div class="panel" id="tab-nativereview">{native_review_board_html}</div>
    {f'<div class="panel" id="tab-compliance">{compliance_page_html}</div>' if framework_tabs_html else ''}
    {f'<div class="panel" id="tab-gateflow"><section class="card process-flow-card">{gateflow_intro}<div id="process-profile-control" class="process-profile-control"></div><div class="process-flow-layout"><div id="process-flow-canvas" class="process-flow-canvas"></div><aside id="process-flow-detail" class="graph-detail-panel process-flow-detail"></aside></div></section></div>' if assurance_framework else ''}
    {f'<div class="panel" id="tab-graph"><section class="card graph-card">{graph_intro}<div id="graph-banner" class="graph-banner" hidden></div><div class="graph-layout"><div id="graph-summary" class="graph-summary-band" aria-live="polite"></div><div class="graph-control-deck"><div class="graph-control-section graph-focus-section"><div class="graph-control-heading"><strong>Focus view</strong><span>Choose the chain you want the graph to explain.</span></div><label class="graph-field"><span>View type</span><select id="graph-entry-type" class="graph-select"><option value="fr">FR evidence chain</option><option value="row">ASVS row proof</option><option value="scannerImpact">Scanner impact</option><option value="scannerUnmapped">Unmapped scanner findings</option><option value="gateProof">Gate proof</option><option value="process">Process review</option><option value="gate">Gate review</option><option value="criterion">Criterion review</option><option value="complete">Complete map overview</option></select></label><label class="graph-field graph-field-wide"><span>Starting point</span><select id="graph-entry-id" class="graph-select"></select></label><button id="graph-load-btn" class="mini-btn graph-action-btn">Apply</button></div><div class="graph-control-section graph-filter-section"><div class="graph-control-heading"><strong>Filters</strong><span>Page-specific filters. Regime and chapter are set in the assurance context bar.</span></div><select id="graph-ruleset-filter" class="graph-select graph-context-proxy" hidden></select><select id="graph-chapter-filter" class="graph-select graph-context-proxy" hidden></select><label class="graph-field"><span>Scanner</span><select id="graph-scanner-filter" class="graph-select"></select></label><label class="graph-field"><span>Evidence state</span><select id="graph-status-filter" class="graph-select"><option value="">All evidence states</option><option value="failed">Failing evidence</option><option value="execution_error">Execution errors</option><option value="partial">Partial evidence</option><option value="passed">Passing evidence</option><option value="missing">Missing evidence</option><option value="manual_review">Review required</option></select></label></div></div><div id="graph-legend" class="graph-legend-box" hidden></div><div id="graph-canvas" class="graph-canvas"></div><aside id="graph-detail" class="graph-detail-panel graph-detail-strip"></aside></div></section></div>' if (fr_catalog_html or assurance_framework) else ''}
  </main>
    </div>
  </div>
<script type="application/json" id="reverse-lookup-data">{reverse_lookup_json}</script>
<script type="application/json" id="graph-data">{graph_json}</script>
<script type="application/json" id="process-flow-data">{process_flow_json}</script>
<script type="application/json" id="framework-options-data">{framework_options_json}</script>
</div>
<script>{GRAPH_JS}</script>
<script>{DASHBOARD_INTERACTIONS_JS.replace("__RUN_ID__", run_id)}</script>
</body></html>
"""

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--fr-catalog", default=None,
                    help="Path to project FR catalog JSON (enables FR-driven view)")
    ap.add_argument("--assurance-framework", default=None,
                    help="Path to assurance-framework JSON (enables the framework gate view)")
    ap.add_argument("--assurance-instance", default=None,
                    help="Path to assurance-instance JSON applied to the selected assurance framework")
    ap.add_argument("--compliance-mapping-pack", default=None,
                    help="Path to compliance mapping pack JSON used for FR/TBT sufficiency rollup")
    ap.add_argument("--scanner-compliance-mapping-pack", action="append", default=[],
                    help="Path to scanner-to-compliance mapping pack JSON, or a directory of packs. May be repeated.")
    ap.add_argument("--junit-xml", default=None,
                    help="Path to JUnit XML test results (may be repeated for multi-runner)")
    args = ap.parse_args()
    report_dir = Path(args.report_dir)
    out = report_dir / "dashboard.html"
    out.write_text(render(report_dir=report_dir,
                          fr_catalog_path=args.fr_catalog,
                          assurance_framework_path=args.assurance_framework,
                          assurance_instance_path=args.assurance_instance,
                          compliance_mapping_pack_path=args.compliance_mapping_pack,
                          scanner_compliance_mapping_paths=args.scanner_compliance_mapping_pack,
                          junit_xml_path=args.junit_xml))
    record_report_artifact(report_dir, out)
    record_core_report_artifacts(report_dir)
    print(f"dashboard: written to {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
