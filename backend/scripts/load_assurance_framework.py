#!/usr/bin/env python3
"""Load and validate an assurance framework gate catalog JSON file.

The assurance framework catalog models approval gates, roles, criteria, and
required evidence for frameworks such as MOD JSP-453. It is intentionally
separate from the FR catalog: gates can reference FRs through an assurance
instance, but a gate is a workflow checkpoint rather than a Functional
Requirement.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "resources" / "schemas" / "assurance-framework.schema.json"


class AssuranceFrameworkError(Exception):
    """Raised when the catalog fails schema or strict semantic validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(self._format())

    def _format(self) -> str:
        return "Assurance framework validation failed (%d error(s)):\n%s" % (
            len(self.errors),
            "\n".join(f"  - {e}" for e in self.errors),
        )

    def __str__(self) -> str:
        return self._format()


class AssuranceFrameworkWarning:
    """Recoverable semantic issue."""

    def __init__(self, severity: str, code: str, message: str) -> None:
        self.severity = severity
        self.code = code
        self.message = message


class AssuranceFramework:
    """Validated assurance framework with helper accessors."""

    def __init__(
        self,
        raw: dict[str, Any],
        assurance_framework: str,
        title: str,
        version: int,
        roles: list[dict[str, Any]],
        processes: list[dict[str, Any]],
        warnings: list[AssuranceFrameworkWarning] | None = None,
    ) -> None:
        self.raw = raw
        self.assurance_framework = assurance_framework
        self.title = title
        self.version = version
        self.roles = roles
        self.processes = processes
        self.warnings = warnings or []

    @property
    def role_ids(self) -> set[str]:
        return {r["id"] for r in self.roles}

    @property
    def process_ids(self) -> set[str]:
        return {p["id"] for p in self.processes}

    def role_by_id(self, role_id: str) -> dict[str, Any] | None:
        for role in self.roles:
            if role["id"] == role_id:
                return role
        return None


def _validate_schema(catalog: dict[str, Any]) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []

    if not SCHEMA_PATH.exists():
        return [f"Schema file not found: {SCHEMA_PATH}"]

    schema = json.loads(SCHEMA_PATH.read_text())
    validator_kwargs: dict[str, Any] = {}
    try:
        from referencing import Registry, Resource  # type: ignore

        resources = []
        for path in SCHEMA_PATH.parent.glob("*.schema.json"):
            loaded = json.loads(path.read_text())
            schema_id = loaded.get("$id")
            if schema_id:
                resources.append((schema_id, Resource.from_contents(loaded)))
        validator_kwargs["registry"] = Registry().with_resources(resources)
    except Exception:
        validator_kwargs = {}
    validator = jsonschema.Draft202012Validator(schema, **validator_kwargs)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(catalog), key=lambda e: list(e.absolute_path))
    ]


def _adapt_target_assurance_framework(raw: dict[str, Any]) -> dict[str, Any]:
    """Project target assurance-framework JSON into the current gate UI shape."""
    adapted = copy.deepcopy(raw)
    adapted["version"] = raw.get("schema_version", raw.get("version", 1))

    for process in adapted.get("processes") or []:
        for gate in process.get("gates") or []:
            if "continuation_rule" not in gate and gate.get("continuation_policy"):
                gate["continuation_rule"] = gate.get("continuation_policy")
            for criterion in gate.get("criteria") or []:
                if "evidence" in criterion:
                    continue
                evidence_items = []
                for requirement in criterion.get("requirements") or []:
                    rtype = requirement.get("type", "")
                    ref = requirement.get("ref", "")
                    if rtype == "fr_placeholder":
                        evidence_items.append({
                            "type": "fr",
                            "ref": ref,
                            "label": ref,
                            "required": requirement.get("required", True),
                        })
                    elif rtype == "ruleset_row":
                        ruleset = requirement.get("ruleset", "")
                        row = requirement.get("row") or ref
                        evidence_items.append({
                            "type": "ruleset_row",
                            "ref": f"{ruleset}:{row}" if ruleset else row,
                            "label": f"{ruleset} {row}".strip(),
                            "required": requirement.get("required", True),
                        })
                    elif rtype in {"manual_artifact", "approval", "waiver"}:
                        evidence_items.append({
                            "type": "approval" if rtype == "approval" else "manual",
                            "ref": ref,
                            "label": ref,
                            "required": requirement.get("required", True),
                        })
                    else:
                        evidence_items.append({
                            "type": rtype or "manual",
                            "ref": ref,
                            "label": ref,
                            "required": requirement.get("required", True),
                        })
                criterion["evidence"] = evidence_items
    return adapted


def _apply_target_assurance_instance(raw: dict[str, Any], instance: dict[str, Any]) -> dict[str, Any]:
    adapted = copy.deepcopy(raw)
    mappings_by_criterion = {
        mapping.get("criterion"): mapping.get("requirements") or []
        for mapping in instance.get("criterion_mappings") or []
        if mapping.get("criterion")
    }
    assignments_by_gate_role = {
        (assignment.get("gate"), assignment.get("role")): assignment
        for assignment in instance.get("role_assignments") or []
        if assignment.get("gate") and assignment.get("role")
    }

    for process in adapted.get("processes") or []:
        for gate in process.get("gates") or []:
            gate_id = gate.get("id")
            for role_req in gate.get("required_roles") or []:
                assignment = assignments_by_gate_role.get((gate_id, role_req.get("role")))
                if not assignment:
                    continue
                role_req["party"] = assignment.get("party", "")
                role_req["approval_ref"] = assignment.get("approval_ref", "")
                approval_status = assignment.get("approval_status", "")
                role_req["status"] = "approved" if approval_status in {"approved", "waived"} else "pending"
                role_req["approval_status"] = approval_status

            for criterion in gate.get("criteria") or []:
                mapped_requirements = mappings_by_criterion.get(criterion.get("id"))
                if not mapped_requirements:
                    continue
                evidence_items = []
                for requirement in mapped_requirements:
                    rtype = requirement.get("type", "")
                    ref = requirement.get("ref", "")
                    if rtype == "fr":
                        evidence_items.append({
                            "type": "fr",
                            "ref": ref,
                            "label": ref,
                            "required": True,
                        })
                    elif rtype == "tbt":
                        evidence_items.append({
                            "type": "test",
                            "ref": ref,
                            "label": ref,
                            "required": True,
                        })
                    elif rtype == "evidence":
                        evidence_items.append({
                            "type": "manual",
                            "ref": ref,
                            "label": ref,
                            "required": True,
                        })
                    elif rtype == "ruleset_row":
                        ruleset = requirement.get("ruleset", "")
                        row = requirement.get("row") or ref
                        evidence_items.append({
                            "type": "ruleset_row",
                            "ref": f"{ruleset}:{row}" if ruleset else row,
                            "label": f"{ruleset} {row}".strip(),
                            "required": True,
                        })
                    elif rtype == "manual_artifact":
                        evidence_items.append({
                            "type": "manual",
                            "ref": requirement.get("evidence") or ref,
                            "label": ref,
                            "required": True,
                        })
                if evidence_items:
                    criterion["evidence"] = evidence_items
                    criterion["instance_mapped"] = True
    return adapted


def _find_duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return dupes


def _semantic_checks(
    catalog: dict[str, Any],
    fr_ids: set[str] | None = None,
) -> list[AssuranceFrameworkWarning]:
    warnings: list[AssuranceFrameworkWarning] = []
    fr_ids = fr_ids or set()

    role_ids = [r.get("id", "") for r in catalog.get("roles") or [] if r.get("id")]
    for role_id in sorted(_find_duplicates(role_ids)):
        warnings.append(AssuranceFrameworkWarning(
            "warn", "assurance_framework.duplicate_role", f"Duplicate role id '{role_id}'",
        ))
    role_id_set = set(role_ids)

    process_ids = [p.get("id", "") for p in catalog.get("processes") or [] if p.get("id")]
    for process_id in sorted(_find_duplicates(process_ids)):
        warnings.append(AssuranceFrameworkWarning(
            "warn", "assurance_framework.duplicate_process", f"Duplicate process id '{process_id}'",
        ))

    gate_ids: list[str] = []
    criterion_ids: list[str] = []
    for process in catalog.get("processes") or []:
        pid = process.get("id", "?")
        process_gate_ids = {
            gate.get("id", "")
            for gate in process.get("gates") or []
            if gate.get("id")
        }
        process_outcome_ids = {
            outcome.get("id", "")
            for outcome in process.get("exit_outcomes") or []
            if outcome.get("id")
        }
        for transition in process.get("transitions") or []:
            for endpoint in ("from", "to"):
                ref = transition.get(endpoint)
                if ref and ref not in process_gate_ids and ref not in process_outcome_ids:
                    warnings.append(AssuranceFrameworkWarning(
                        "warn",
                        "assurance_framework.unknown_transition_ref",
                        f"Process {pid} transition '{transition.get('label', '?')}' {endpoint} references unknown gate/outcome '{ref}'",
                    ))
        for gate in process.get("gates") or []:
            gid = gate.get("id", "")
            if gid:
                gate_ids.append(gid)
            for req_role in gate.get("required_roles") or []:
                role = req_role.get("role")
                if role and role not in role_id_set:
                    warnings.append(AssuranceFrameworkWarning(
                        "warn",
                        "assurance_framework.unknown_role",
                        f"Process {pid} gate {gid or '?'} references unknown role '{role}'",
                    ))
            for criterion in gate.get("criteria") or []:
                cid = criterion.get("id", "")
                if cid:
                    criterion_ids.append(f"{gid}:{cid}")
                for evidence in criterion.get("evidence") or []:
                    etype = evidence.get("type")
                    ref = evidence.get("ref")
                    if etype == "fr" and fr_ids and ref not in fr_ids:
                        warnings.append(AssuranceFrameworkWarning(
                            "info",
                            "assurance_framework.unknown_fr",
                            f"Process {pid} gate {gid or '?'} criterion {cid or '?'} references unknown FR '{ref}'",
                        ))
                    if etype == "process" and ref not in process_ids:
                        warnings.append(AssuranceFrameworkWarning(
                            "warn",
                            "assurance_framework.unknown_process_ref",
                            f"Process {pid} gate {gid or '?'} criterion {cid or '?'} references unknown process '{ref}'",
                        ))

    for link in catalog.get("process_links") or []:
        for endpoint in ("from_process", "to_process"):
            process_id = link.get(endpoint)
            if process_id and process_id not in process_ids:
                warnings.append(AssuranceFrameworkWarning(
                    "warn",
                    "assurance_framework.unknown_process_link",
                    f"Process link '{link.get('label') or link.get('relationship') or '?'}' {endpoint} references unknown process '{process_id}'",
                ))

    for gate_id in sorted(_find_duplicates(gate_ids)):
        warnings.append(AssuranceFrameworkWarning(
            "warn", "assurance_framework.duplicate_gate", f"Duplicate gate id '{gate_id}'",
        ))
    for criterion_key in sorted(_find_duplicates(criterion_ids)):
        warnings.append(AssuranceFrameworkWarning(
            "warn", "assurance_framework.duplicate_criterion",
            f"Duplicate criterion id within gate '{criterion_key}'",
        ))

    return warnings


def load_assurance_framework(
    path: Path,
    *,
    strict: bool = False,
    fr_ids: set[str] | None = None,
    assurance_instance_path: Path | None = None,
) -> AssuranceFramework:
    if not path.exists():
        raise AssuranceFrameworkError([f"Assurance framework file not found: {path}"])

    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise AssuranceFrameworkError([f"Invalid JSON: {exc}"]) from exc

    if not raw.get("assurance_framework"):
        raise AssuranceFrameworkError(["Expected target assurance-framework JSON with top-level 'assurance_framework'"])

    schema_errors = _validate_schema(raw)
    if schema_errors:
        raise AssuranceFrameworkError(schema_errors)

    raw = _adapt_target_assurance_framework(raw)
    if assurance_instance_path and assurance_instance_path.exists():
        try:
            instance = json.loads(assurance_instance_path.read_text())
            raw = _apply_target_assurance_instance(raw, instance)
        except Exception as exc:
            raise AssuranceFrameworkError([f"Invalid assurance instance: {exc}"]) from exc

    warnings = _semantic_checks(raw, fr_ids=fr_ids)
    if strict and any(w.severity == "warn" for w in warnings):
        raise AssuranceFrameworkError([w.message for w in warnings if w.severity == "warn"])

    return AssuranceFramework(
        raw=raw,
        assurance_framework=raw.get("assurance_framework", "(unknown)"),
        title=raw.get("title", "(untitled)"),
        version=raw.get("version", 1),
        roles=raw.get("roles") or [],
        processes=raw.get("processes") or [],
        warnings=warnings,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("catalog", type=Path, help="Path to assurance-framework JSON")
    ap.add_argument("--fr-catalog", type=Path, default=None,
                    help="Optional FR catalog used to validate fr evidence refs")
    ap.add_argument("--assurance-instance", type=Path, default=None,
                    help="Optional assurance-instance JSON applied to target assurance-framework catalogs")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as errors")
    args = ap.parse_args()

    fr_ids: set[str] | None = None
    fr_catalog = None
    if args.fr_catalog:
        try:
            import importlib.util
            loader_path = Path(__file__).resolve().parent / "load_fr_catalog.py"
            spec = importlib.util.spec_from_file_location("load_fr_catalog", loader_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                fr_catalog = mod.load_fr_catalog(args.fr_catalog)
                fr_ids = fr_catalog.fr_ids
        except Exception as exc:
            print(f"WARN: could not load FR catalog for cross-checks: {exc}", file=sys.stderr)

    try:
        catalog = load_assurance_framework(
            args.catalog,
            strict=args.strict,
            fr_ids=fr_ids,
            assurance_instance_path=args.assurance_instance,
        )
    except AssuranceFrameworkError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    gate_count = sum(len(p.get("gates") or []) for p in catalog.processes)
    criterion_count = sum(
        len(g.get("criteria") or [])
        for p in catalog.processes
        for g in p.get("gates") or []
    )
    print(
        f"OK: {args.catalog.name} — assurance framework '{catalog.assurance_framework}', "
        f"{len(catalog.processes)} processes, {gate_count} gates, "
        f"{criterion_count} criteria, {len(catalog.roles)} roles"
    )
    if catalog.warnings:
        print(f"\n{len(catalog.warnings)} warning(s):", file=sys.stderr)
        for w in catalog.warnings:
            print(f"  [{w.severity}] {w.code}: {w.message}", file=sys.stderr)
        return 0 if not args.strict else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
