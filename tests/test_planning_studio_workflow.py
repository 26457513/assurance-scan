from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "data" / "fixtures" / "target-schemas"
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
                gates=[{"id": "GATE-001", "name": "Assurance scan", "command": "asvs-scanner scan ."}],
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
        blueprint = REPO_ROOT / "data" / "blueprints" / "security-core" / "asvs-5.0.0" / "fr-catalog.blueprint.json"
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
                        "path": "data/rulesets/asvs/5.0.0.json",
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
                    "--config-selection",
                    str(config_path),
                    "--output",
                    str(proposal_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            proposal = json.loads(proposal_path.read_text())
            self.assertEqual([], validate_artifact(proposal_path, "blueprint_selection_proposal"))
            self.assertEqual(["FR-BP-ASVS-SESSION-MANAGEMENT-001"], [item["blueprint_fr"] for item in proposal["candidates"]])

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
                            {"target": "fr", "source_id": "FR-BP-ASVS-SESSION-MANAGEMENT-001", "field": "id", "to": "FR-016"},
                            {
                                "target": "tbt",
                                "source_id": "TBT-BP-ASVS-SESSION-MANAGEMENT-001-A",
                                "field": "id",
                                "to": "TBT-016-ASVS-A",
                            },
                        ],
                    }
                ],
            }
            decisions_path = write_artifact(root, "blueprint_decision_log", decisions)
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
                    str(proposal_path),
                    "--decisions",
                    str(decisions_path),
                    "--blueprint",
                    str(blueprint),
                    "--output",
                    str(config_update_path),
                ],
                cwd=REPO_ROOT,
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
            self.assertNotIn("evidence", added_tbt)


if __name__ == "__main__":
    unittest.main()
