from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "resources" / "fixtures" / "target-schemas"
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from planning_studio.atomic.handoff_pack_builder import (  # noqa: E402
    build_code_studio_handoff,
    build_code_generator_handoff,
)
from planning_studio.atomic.assurance_contract_builder import build_project_assurance_contract  # noqa: E402
from planning_studio.atomic.planning_contract_resolver import (  # noqa: E402
    build_resolved_project_planning_contract,
)
from planning_studio.storage import read_artifact, write_artifact  # noqa: E402
from planning_studio.validators import validate_artifact  # noqa: E402
from planning_studio.workflows.handoff_workflow import (  # noqa: E402
    publish_code_studio_handoff,
    publish_code_generator_handoff,
)
from planning_studio.workflows.planning_approval_workflow import approve_resolved_contract  # noqa: E402


class PlanningStudioWorkflowTest(unittest.TestCase):
    def test_healthcare_assurance_framework_is_rich_process_config(self) -> None:
        framework_path = REPO_ROOT / "resources" / "assurance-frameworks" / "healthcare-digital-assurance" / "1.0.0-draft.json"
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "load_target_artifacts.py"),
                "assurance_framework",
                str(framework_path),
                "--strict",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("10 roles, 9 gates, 16 criteria", result.stdout)

        framework = json.loads(framework_path.read_text())
        process_ids = {process["id"] for process in framework["processes"]}
        self.assertEqual({"HDA-PROC-ASSURANCE-PATH", "HDA-PROC-URGENT-SAFETY-CHANGE"}, process_ids)
        role_ids = {role["id"] for role in framework["roles"]}
        self.assertIn("ROLE-CLINICAL-SAFETY-OFFICER", role_ids)
        self.assertIn("ROLE-CALDICOTT-GUARDIAN", role_ids)
        self.assertIn("ROLE-HEALTHCARE-CAB", role_ids)

        gate_ids = {
            gate["id"]
            for process in framework["processes"]
            for gate in process["gates"]
        }
        self.assertIn("GATE-HDA-CLINICAL-VALIDATION", gate_ids)
        self.assertIn("GATE-HDA-URGENT-POST-CHANGE", gate_ids)
        linked_processes = {(link["from_process"], link["to_process"]) for link in framework.get("process_links", [])}
        self.assertIn(("HDA-PROC-ASSURANCE-PATH", "HDA-PROC-URGENT-SAFETY-CHANGE"), linked_processes)

    def test_dashboard_framework_options_include_healthcare_and_preserve_active_snapshot(self) -> None:
        import generate_dashboard  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "assurance-framework.snapshot.json"
            snapshot.write_text(json.dumps({
                "schema_version": 1,
                "assurance_framework": "JSP-453",
                "version": "1.0.0-draft",
                "title": "JSP 453 Digital Services Assurance Gate Process",
                "processes": [],
                "roles": [],
            }))
            options = generate_dashboard._load_assurance_framework_options(snapshot)

        by_id = {item["id"]: item for item in options}
        self.assertIn("JSP-453", by_id)
        self.assertIn("HEALTHCARE-DIGITAL-ASSURANCE", by_id)
        self.assertTrue(by_id["JSP-453"]["selected"])
        self.assertFalse(by_id["HEALTHCARE-DIGITAL-ASSURANCE"]["selected"])
        self.assertGreaterEqual(len(by_id["HEALTHCARE-DIGITAL-ASSURANCE"]["processes"]), 2)
        self.assertEqual(
            "/opt/assurance-scan/backend/resources/assurance-frameworks/healthcare-digital-assurance/1.0.0-draft.json",
            by_id["HEALTHCARE-DIGITAL-ASSURANCE"]["image_path"],
        )

    def test_resolved_contract_requires_approval_before_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = build_resolved_project_planning_contract(
                "demo-project",
                source_artifacts=[
                    {"kind": "project_intake", "path": "intake.json"},
                    {"kind": "project_config_selection", "path": "config-selection.json"},
                ],
                sections={
                    "intent": {"summary": "Build an assurance-ready service."},
                    "assurance": {"regimes": ["ASVS"]},
                    "governance": {"approval": "required"},
                },
            )
            contract_path = write_artifact(root, "resolved_project_planning_contract", contract)
            self.assertEqual([], validate_artifact(contract_path, "resolved_project_planning_contract"))

            with self.assertRaisesRegex(ValueError, "approved resolved project planning contract"):
                build_code_studio_handoff("demo-project", contract, {"summary": "draft"})

            approved_path = approve_resolved_contract(root, contract)
            approved_contract = read_artifact(root, "resolved_project_planning_contract")
            self.assertEqual("approved", approved_contract["status"])
            self.assertEqual([], validate_artifact(approved_path, "resolved_project_planning_contract"))

            tampered_contract = dict(approved_contract)
            tampered_contract["sections"] = dict(tampered_contract["sections"])
            tampered_contract["sections"]["intent"] = {"summary": "Tampered after approval."}
            tampered_path = root / "tampered-contract.json"
            tampered_path.write_text(json.dumps(tampered_contract))
            self.assertIn(
                "Resolved planning contract section_hashes.intent must match sections.intent",
                validate_artifact(tampered_path, "resolved_project_planning_contract"),
            )

            designer = build_code_studio_handoff(
                "demo-project",
                approved_contract,
                {"summary": "approved planning contract"},
            )
            designer_path = publish_code_studio_handoff(root, approved_contract, designer)
            self.assertEqual([], validate_artifact(designer_path, "code_studio_handoff_pack"))

            tampered_designer = json.loads(designer_path.read_text())
            tampered_designer["context"] = {"summary": "Changed after hashing."}
            tampered_designer_path = root / "tampered-designer.json"
            tampered_designer_path.write_text(json.dumps(tampered_designer))
            self.assertIn(
                "code_studio_handoff_pack: content_hash must match canonical artifact content",
                validate_artifact(tampered_designer_path, "code_studio_handoff_pack"),
            )

            engineer = build_code_generator_handoff(
                "demo-project",
                approved_contract,
                tasks=[{"id": "TASK-001", "title": "Implement approved design", "acceptance": ["Tests pass"]}],
                gates=[{"id": "GATE-001", "name": "Assurance scan", "command": "assurance-scan scan ."}],
            )
            engineer_path = publish_code_generator_handoff(root, approved_contract, engineer)
            self.assertEqual([], validate_artifact(engineer_path, "code_generator_handoff_pack"))
            self.assertNotIn("source_design", json.loads(engineer_path.read_text()))

            assurance_contract = build_project_assurance_contract(
                "demo-project",
                approved_contract,
                artifacts=[
                    {"kind": "fr_catalog", "path": "fr-catalog.json", "sha256": "sha256:" + "a" * 64},
                    {"kind": "graph_manifest", "path": "graph-manifest.json", "sha256": "sha256:" + "b" * 64},
                ],
            )
            assurance_path = write_artifact(root, "project_assurance_contract", assurance_contract)
            self.assertEqual([], validate_artifact(assurance_path, "project_assurance_contract"))

    def test_blueprint_decisions_emit_review_gated_config_update_without_evidence(self) -> None:
        blueprint = REPO_ROOT / "resources" / "blueprints" / "security-core" / "asvs-5.0.0" / "fr-catalog.blueprint.json"
        mapping_pack = REPO_ROOT / "resources" / "blueprint-mappings" / "security-core" / "asvs" / "5.0.0.json"
        nist_mapping_pack = REPO_ROOT / "resources" / "blueprint-mappings" / "security-core" / "nist-800-53" / "5.2.0.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_selection = {
                "schema_version": 1,
                "id": "CONFIG-demo-project",
                "status": "draft",
                "project": "demo-project",
                "selections": [
                    {
                        "package_type": "compliance_ruleset",
                        "id": "ASVS",
                        "version": "5.0.0",
                        "path": "resources/rulesets/asvs/5.0.0.json",
                        "source": "user",
                    }
                ],
                "unknowns": [],
                "not_applicable": [],
            }
            config_path = write_artifact(root, "project_config_selection", config_selection)
            proposal_path = root / "blueprint-proposal.json"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "propose-blueprint-frs.py"),
                    "--project",
                    "demo-project",
                    "--blueprint",
                    str(blueprint),
                    "--blueprint-compliance-mapping-pack",
                    str(mapping_pack),
                    "--blueprint-compliance-mapping-pack",
                    str(nist_mapping_pack),
                    "--config-selection",
                    str(config_path),
                    "--output",
                    str(proposal_path),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            proposal = json.loads(proposal_path.read_text())
            self.assertEqual([], validate_artifact(proposal_path, "blueprint_selection_proposal"))
            source_mapping_pack_ids = {pack["id"] for pack in proposal["source_mapping_packs"]}
            self.assertEqual({
                "security-core-blueprint-to-asvs-5.0.0",
                "security-core-blueprint-to-nist-800-53-5.2.0",
            }, source_mapping_pack_ids)
            proposed_blueprints = [item["blueprint_fr"] for item in proposal["candidates"]]
            self.assertIn("FR-BP-SEC-SESSION-MANAGEMENT-001", proposed_blueprints)
            self.assertIn("FR-BP-SEC-AUTHORIZATION-001", proposed_blueprints)
            self.assertIn("FR-BP-SEC-DATA-PROTECTION-001", proposed_blueprints)
            self.assertIn("FR-BP-SEC-GOVERNED-OPERATIONS-001", proposed_blueprints)
            self.assertEqual(11, len(proposed_blueprints))
            session_candidate = next(
                item for item in proposal["candidates"]
                if item["blueprint_fr"] == "FR-BP-SEC-SESSION-MANAGEMENT-001"
            )
            mappings_by_ruleset = {mapping["ruleset"]: mapping for mapping in session_candidate["compliance_mappings"]}
            session_asvs_mapping = mappings_by_ruleset["ASVS"]
            self.assertEqual("ASVS", session_asvs_mapping["ruleset"])
            self.assertEqual("5.0.0", session_asvs_mapping["version"])
            self.assertEqual(5, len(session_asvs_mapping["rows"]))
            self.assertIn(
                {"ruleset": "ASVS", "row": "v5.0.0-7.1.1"},
                session_asvs_mapping["rows"],
            )
            self.assertIn("BCM-ASVS-5-FR-SESSION-MANAGEMENT-001", session_asvs_mapping["mapping_ids"])
            session_nist_mapping = mappings_by_ruleset["NIST-800-53"]
            self.assertEqual("5.2.0", session_nist_mapping["version"])
            self.assertIn({"ruleset": "NIST-800-53", "row": "ac-12"}, session_nist_mapping["rows"])
            self.assertIn({"ruleset": "NIST-800-53", "row": "ia-13.2"}, session_nist_mapping["rows"])

            decisions = {
                "schema_version": 1,
                "id": "BLUEPRINT-DECISIONS-demo-project",
                "project": "demo-project",
                "proposal": proposal["id"],
                "decisions": [
                    {
                        "candidate": proposal["candidates"][0]["id"],
                        "decision": "tailored",
                        "reviewed_by": "security-architect",
                        "reason": "Project has authenticated sessions and accepts the ASVS session-management blueprint.",
                        "tailoring": [
                            {"target": "fr", "source_id": "FR-BP-SEC-SESSION-MANAGEMENT-001", "field": "id", "to": "FR-016"},
                            {
                                "target": "tbt",
                                "source_id": "TBT-BP-SEC-SESSION-MANAGEMENT-001-A",
                                "field": "id",
                                "to": "TBT-016-ASVS-A",
                            },
                        ],
                    }
                ],
            }
            write_artifact(root, "blueprint_decision_log", decisions)
            config_update_path = root / "config-update-proposal.json"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "blueprint-decisions-to-config-update.py"),
                    "--project",
                    "demo-project",
                    "--run-id",
                    "planning-run-1",
                    "--proposal",
                    "blueprint-proposal.json",
                    "--decisions",
                    "blueprint-decisions.json",
                    "--blueprint",
                    str(blueprint),
                    "--output",
                    str(config_update_path),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            config_update = json.loads(config_update_path.read_text())
            self.assertEqual([], validate_artifact(config_update_path, "config_update_proposal"))
            self.assertEqual(6, len(config_update["fr_catalog_updates"]))
            self.assertEqual([], config_update["manual_evidence_updates"])
            self.assertEqual([], config_update["native_test_mapping_updates"])

            base_catalog = root / "fr-catalog.base.json"
            base_catalog.write_text(json.dumps({
                "schema_version": 1,
                "project": "demo-project",
                "frs": [
                    {
                        "id": "FR-BASE",
                        "title": "Baseline project requirement",
                        "lifecycle_status": "in_scope",
                    }
                ],
                "tbts": [],
            }))
            output_catalog = root / "fr-catalog.updated.json"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "apply-config-update-proposal.py"),
                    str(config_update_path),
                    "--select",
                    "fr_catalog_updates:*",
                    "--reviewed-by",
                    "security-architect",
                    "--fr-catalog",
                    str(base_catalog),
                    "--fr-catalog-out",
                    str(output_catalog),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            updated = json.loads(output_catalog.read_text())
            self.assertIn("FR-016", {fr["id"] for fr in updated["frs"]})
            self.assertIn("TBT-016-ASVS-A", {tbt["id"] for tbt in updated["tbts"]})
            added_tbt = next(tbt for tbt in updated["tbts"] if tbt["id"] == "TBT-016-ASVS-A")
            self.assertEqual(["FR-016"], added_tbt["proves"])
            self.assertEqual("blueprint_tbt", added_tbt["derived_from"]["source_type"])
            self.assertEqual(
                {
                    "field": "id",
                    "from": "TBT-BP-SEC-SESSION-MANAGEMENT-001-A",
                    "to": "TBT-016-ASVS-A",
                    "rationale": decisions["decisions"][0]["reason"],
                },
                added_tbt["derived_from"]["tailoring"][0],
            )
            self.assertNotIn("evidence", added_tbt)

    def test_security_core_blueprint_has_asvs_and_nist_coverage(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "validate-blueprint-compliance-coverage.py"),
                "--blueprint",
                str(REPO_ROOT / "resources" / "blueprints" / "security-core" / "asvs-5.0.0" / "fr-catalog.blueprint.json"),
                "--mapping-pack",
                str(REPO_ROOT / "resources" / "blueprint-mappings" / "security-core" / "asvs" / "5.0.0.json"),
                "--mapping-pack",
                str(REPO_ROOT / "resources" / "blueprint-mappings" / "security-core" / "nist-800-53" / "5.2.0.json"),
                "--expect-relationship",
                "ASVS=satisfies/direct",
                "--expect-relationship",
                "NIST-800-53=supports/partial",
                "--expect-mapping-relationship",
                "BCM-ASVS-5-FR-GOVERNED-OPERATIONS-001=supports/partial",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertIn("FR-BP-SEC-SESSION-MANAGEMENT-001 | ASVS 5.0.0", result.stdout)
        self.assertIn("FR-BP-SEC-SESSION-MANAGEMENT-001 | NIST-800-53 5.2.0", result.stdout)
        self.assertIn("v5.0.0-7.1.1", result.stdout)
        self.assertIn("ia-13.2", result.stdout)

    def test_apply_reviewed_scope_wraps_blueprint_decision_pipeline(self) -> None:
        blueprint = REPO_ROOT / "resources" / "blueprints" / "security-core" / "asvs-5.0.0" / "fr-catalog.blueprint.json"
        mapping_pack = REPO_ROOT / "resources" / "blueprint-mappings" / "security-core" / "asvs" / "5.0.0.json"
        nist_mapping_pack = REPO_ROOT / "resources" / "blueprint-mappings" / "security-core" / "nist-800-53" / "5.2.0.json"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposal_path = root / "blueprint-proposal.json"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "propose-blueprint-frs.py"),
                    "--project",
                    "demo-project",
                    "--blueprint",
                    str(blueprint),
                    "--blueprint-compliance-mapping-pack",
                    str(mapping_pack),
                    "--blueprint-compliance-mapping-pack",
                    str(nist_mapping_pack),
                    "--include-all",
                    "--output",
                    str(proposal_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            base_catalog = root / "fr-catalog.base.json"
            base_catalog.write_text(json.dumps({
                "schema_version": 1,
                "project": "demo-project",
                "frs": [],
                "tbts": [],
            }))
            output_catalog = root / "fr-catalog.reviewed.json"
            decisions_path = root / "blueprint-decisions.json"
            config_update_path = root / "proposal.json"
            review_path = root / "proposal-review.md"
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "apply-reviewed-scope.py"),
                    "--run-id",
                    "planning-run-2",
                    "--proposal",
                    "blueprint-proposal.json",
                    "--decisions",
                    "blueprint-decisions.json",
                    "--blueprint",
                    str(blueprint),
                    "--proposal-out",
                    "proposal.json",
                    "--review-out",
                    "proposal-review.md",
                    "--fr-catalog",
                    "fr-catalog.base.json",
                    "--fr-catalog-out",
                    "fr-catalog.reviewed.json",
                    "--reviewed-by",
                    "security-architect",
                    "--accept-all-blueprints",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual([], validate_artifact(decisions_path, "blueprint_decision_log"))
            self.assertEqual([], validate_artifact(config_update_path, "config_update_proposal"))
            self.assertTrue(review_path.exists())
            updated = json.loads(output_catalog.read_text())
            fr_ids = {fr["id"] for fr in updated["frs"]}
            tbt_ids = {tbt["id"] for tbt in updated["tbts"]}
            self.assertIn("FR-SEC-SESSION-MANAGEMENT-001", fr_ids)
            self.assertIn("TBT-SEC-SESSION-MANAGEMENT-001-A", tbt_ids)
            added_fr = next(fr for fr in updated["frs"] if fr["id"] == "FR-SEC-SESSION-MANAGEMENT-001")
            self.assertEqual("blueprint_fr", added_fr["derived_from"]["source_type"])



if __name__ == "__main__":
    unittest.main()
