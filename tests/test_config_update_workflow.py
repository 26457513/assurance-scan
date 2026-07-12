from __future__ import annotations

import argparse
import json
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "data" / "fixtures" / "target-schemas"
PROPOSAL = FIXTURES / "config-update-proposal.example.json"
FR_CATALOG = FIXTURES / "fr-catalog.example.json"
RULESET = FIXTURES / "ruleset.example.json"
SCANNER_RULES = FIXTURES / "scanner-rules.example.json"
ASSURANCE_FRAMEWORK = FIXTURES / "assurance-framework.example.json"
ASSURANCE_INSTANCE = FIXTURES / "assurance-instance.example.json"
ASSURANCE_TEST_PACK = FIXTURES / "assurance-test-pack.example.json"
EVIDENCE_BUNDLE = FIXTURES / "evidence-bundle.example.json"
SCANNER_COMPLIANCE_MAPPING_PACK = FIXTURES / "scanner-compliance-mapping-pack.example.json"


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def run_cli(*args: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ASVS_IMAGE_BUNDLE_DIR"] = str(REPO_ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        env["ASVS_WORKDIR"] = str(Path(tmp) / "runtime")
        return subprocess.run(
            [str(REPO_ROOT / "bin" / "asvs-scanner"), *args],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            input=input_text,
            capture_output=True,
            check=check,
        )


def add_manifest_artifact(report_dir: Path, rel: str) -> None:
    path = report_dir / rel
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    hash_path = report_dir / "hashes" / ("__".join(Path(rel).parts) + ".sha256")
    hash_path.parent.mkdir(parents=True, exist_ok=True)
    hash_path.write_text(f"{digest}  {rel}\n")
    manifest_path = report_dir / "evidence-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entries = [item for item in manifest.get("evidence_files", []) if item.get("file") != rel]
    entries.append({"file": rel, "bytes": path.stat().st_size, "sha256": digest})
    manifest["evidence_files"] = sorted(entries, key=lambda item: item["file"])
    manifest_path.write_text(json.dumps(manifest, indent=2))


def load_script_module(module_name: str, path: Path):
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_satisfied_tbt_report(report_dir: Path) -> None:
    (report_dir / "reports").mkdir(parents=True, exist_ok=True)
    junit_path = report_dir / "reports" / "junit.xml"
    junit_path.write_text(
        "<testsuite name=\"asvs\" tests=\"1\" failures=\"0\"><testcase classname=\"TBT-001\" name=\"TBT-001 passes\"/></testsuite>\n"
    )
    junit_sha = hashlib.sha256(junit_path.read_bytes()).hexdigest()
    (report_dir / "graph-manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "mode": "graph_proof_manifest",
        "project": "demo",
        "run_id": "run-1",
        "generated_at": "2026-07-09T00:00:00Z",
        "graph": {"node_count": 2, "edge_count": 1, "root_hash": "sha256:" + "a" * 64},
        "artifacts": {"report": [], "config": []},
        "accepted_config": {"policy": "runtime_config_is_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
        "planning_artifacts": {"policy": "planning_artifacts_are_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
        "claim_readiness": {"policy": "claims_require_committed_runtime_config", "supported": ["tbt_satisfied"], "unsupported": []},
        "supported_claims": ["tbt_satisfied"],
        "commitments": {
            "dashboard_payload_hash": "sha256:" + "b" * 64,
            "evidence_bundle_hash": "sha256:" + "c" * 64,
            "evidence_manifest_hash": "sha256:" + "d" * 64,
            "accepted_config_hash": "sha256:" + "e" * 64,
            "planning_artifacts_hash": "sha256:442730135fb2e63f1e4b4388deee1eeabe67127968ea3bc163b7db52130e3f44",
            "graph_root_hash": "sha256:" + "a" * 64,
        },
    }))
    (report_dir / "dashboard-payload.json").write_text(json.dumps({
        "schema_version": 1,
        "project": "demo",
        "generated_at": "2026-07-09T00:00:00Z",
        "inputs": {},
        "summary": {"run_id": "run-1"},
        "graph": {
            "nodes": [
                {
                    "id": "test:TBT-001",
                    "type": "tbt",
                    "label": "Test basis",
                    "status": "passed",
                    "metadata": {"reasons": ["TBT-001 has sufficient passing evidence."]},
                },
                {
                    "id": "evidence:EVD-TBT-001",
                    "type": "evidence",
                    "label": "Evidence",
                    "status": "passed",
                    "metadata": {"ref": "EVD-TBT-001"},
                },
            ],
            "edges": [
                {"source": "test:TBT-001", "target": "evidence:EVD-TBT-001", "type": "evidences"}
            ],
        },
    }))
    (report_dir / "evidence-bundle.json").write_text(json.dumps({
        "schema_version": 1,
        "project": "demo",
        "generated_at": "2026-07-09T00:00:00Z",
        "evidence": [
            {
                "id": "EVD-TBT-001",
                "type": "test_result",
                "result_status": "passed",
                "produced_by": "TBT-001",
                "source": "junit",
                "artifact": {
                    "path": "reports/junit.xml",
                    "format": "junit",
                    "bytes": junit_path.stat().st_size,
                    "sha256": junit_sha,
                    "media_type": "application/xml"
                },
            }
        ],
    }))
    (report_dir / "evidence-manifest.json").write_text(json.dumps({"evidence_files": []}))
    for rel in ("graph-manifest.json", "dashboard-payload.json", "evidence-bundle.json", "reports/junit.xml"):
        add_manifest_artifact(report_dir, rel)


def fixture_scanner_finding() -> dict:
    return {
        "scanner": "semgrep",
        "rule_id": "python.flask.security.injection",
        "ruleId": "python.flask.security.injection",
        "location": "src/app.py:12",
        "message": "SQL injection risk",
        "path": "src/app.py",
    }


class ConfigUpdateWorkflowTests(unittest.TestCase):
    def test_junit_tbt_match_builds_observed_strong_evidence(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "generate_evidence_bundle",
            REPO_ROOT / "scripts" / "generate-evidence-bundle.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            reports_dir = report_dir / "reports"
            reports_dir.mkdir()
            (reports_dir / "junit.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="1" failures="0" errors="0" skipped="0">
  <testsuite name="approved assurance">
    <testcase classname="TBT-016-ASVS-A.FR-016.expired-JWT-rejection" name="TBT-016-ASVS-A" />
  </testsuite>
</testsuites>
"""
            )

            sys.path.insert(0, str(REPO_ROOT / "scripts"))
            try:
                bundle = module.build_target_evidence_bundle(
                    project="template-app",
                    run_id="20260707T000000Z_test",
                    now="2026-07-07T00:00:00Z",
                    fr_catalog_path=str(FR_CATALOG),
                    report_dir=report_dir,
                    health_records=[],
                )
            finally:
                sys.path.remove(str(REPO_ROOT / "scripts"))

        self.assertIsNotNone(bundle)
        evidence = {
            record["produced_by"]: record
            for record in bundle["evidence"]
        }
        record = evidence["TBT-016-ASVS-A"]
        self.assertEqual("passed", record["result_status"])
        self.assertIs(True, record["observed"])
        self.assertEqual("strong", record["evidence_strength"])
        self.assertEqual(
            "TBT-016-ASVS-A.FR-016.expired-JWT-rejection::TBT-016-ASVS-A",
            record["source_locator"],
        )

    def test_cli_config_update_subcommands_are_wired(self) -> None:
        validate = run_cli(
            "validate-config-update",
            str(PROPOSAL),
            "--fr-catalog",
            str(FR_CATALOG),
            "--ruleset",
            str(RULESET),
            "--assurance-framework",
            str(ASSURANCE_FRAMEWORK),
        )
        listing = run_cli("apply-config-update", str(PROPOSAL), "--list")

        self.assertIn("OK config update proposal: 4 proposed updates", validate.stdout)
        self.assertIn("Selectable proposal entries:", listing.stdout)

    def test_cli_project_fr_board_state_subcommand_is_wired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "report"
            report_dir.mkdir()
            (report_dir / "evidence-manifest.json").write_text(json.dumps({
                "repository": "demo",
                "run_id": "run-board",
                "generated_at": "2026-07-08T00:00:00Z",
                "evidence_files": [],
            }))
            state_input = Path(tmp) / "board-state-input.json"
            state_input.write_text(json.dumps({
                "cards": [
                    {
                        "id": "GENERATED-TBT-001",
                        "lane": "import",
                        "source": "generated",
                        "decision": "approve_to_run",
                        "reviewer_note": "Approved by tester.",
                        "manual_test_path": "tests/asvs/integration/TBT-001.assurance.test.js",
                    }
                ]
            }))

            updated = run_cli(
                "update-project-fr-board-state",
                str(report_dir),
                "--state-json",
                "-",
                "--strict",
                input_text=state_input.read_text(),
            )
            validated = run_cli(
                "update-project-fr-board-state",
                str(report_dir),
                "--validate-only",
                "--strict",
            )
            state = json.loads((report_dir / "project-fr-board-state.json").read_text())
            hash_exists = (report_dir / "hashes" / "project-fr-board-state.json.sha256").exists()

        self.assertIn("project FR board state updated:", updated.stdout)
        self.assertIn("OK project FR board state:", validated.stdout)
        self.assertEqual(state["cards"][0]["decision"], "approve_to_run")
        self.assertTrue(hash_exists)

    def test_run_approved_tests_emits_junit_for_ready_tbt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "project"
            report_dir = root / "project-asvs-scan-20260707T000000Z_test" / ".asvs-scanner" / "runtime" / "reports" / "20260707T000000Z_test"
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            test_rel = Path("tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js")
            test_path = source_repo / test_rel
            test_path.parent.mkdir(parents=True)
            test_path.write_text("test('TBT-016-ASVS-A', () => expect(true).toBe(true));\n")
            pack_dir.mkdir(parents=True)
            (report_dir / "fr-catalog.snapshot.json").write_text(FR_CATALOG.read_text())
            (pack_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "VG_TEST_FRAMEWORK",
                "mode": "ephemeral",
                "generated_at": "2026-07-07T00:00:00Z",
                "tests": [{
                    "pack_id": "GENERATED-TBT-016-ASVS-A",
                    "tbt": "TBT-016-ASVS-A",
                    "frs": ["FR-016"],
                    "title": "Expired JWT rejection for FR-016 implemented assurance test",
                    "source": "generated",
                    "type": "integration",
                    "runner": "fake jest",
                    "status": "ready_to_run",
                    "assessment": "useful_as_is",
                    "safety": "non_destructive",
                    "pack_path": str(test_rel),
                }],
            }))
            fake_jest = root / "fake-jest"
            fake_jest.write_text("#!/bin/sh\nexit 0\n")
            fake_jest.chmod(0o755)
            junit_out = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "results" / "approved-tbt-junit.xml"

            result = run_cmd(
                "scripts/run-approved-tests.py",
                str(report_dir),
                "--source-repo",
                str(source_repo),
                "--tbt",
                "TBT-016-ASVS-A",
                "--jest-bin",
                str(fake_jest),
                "--execution-mode",
                "host",
                "--junit-out",
                str(junit_out),
            )
            xml = junit_out.read_text()

        self.assertIn("approved tests: passed=1 failed=0 skipped=0", result.stdout)
        self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn('classname="TBT-016-ASVS-A.FR-016.', xml)
        self.assertIn('name="TBT-016-ASVS-A"', xml)

    def test_run_approved_tests_allows_reviewed_existing_asvs_with_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "project"
            report_dir = root / "project-asvs-scan-20260707T000000Z_test" / ".asvs-scanner" / "runtime" / "reports" / "20260707T000000Z_test"
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            test_rel = Path("tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js")
            test_path = source_repo / test_rel
            test_path.parent.mkdir(parents=True)
            test_path.write_text("test('TBT-016-ASVS-A', () => expect(true).toBe(true));\n")
            pack_dir.mkdir(parents=True)
            (pack_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "VG_TEST_FRAMEWORK",
                "mode": "ephemeral",
                "generated_at": "2026-07-07T00:00:00Z",
                "tests": [{
                    "pack_id": "EXISTING-TBT-016-ASVS-A",
                    "tbt": "TBT-016-ASVS-A",
                    "frs": ["FR-016"],
                    "title": "Expired JWT rejection for FR-016",
                    "source": "existing_asvs",
                    "type": "integration",
                    "runner": "fake jest",
                    "status": "existing",
                    "assessment": "needs_review",
                    "safety": "review_required",
                    "pack_path": str(test_rel),
                }],
            }))
            fake_jest = root / "fake-jest"
            fake_jest.write_text("#!/bin/sh\nexit 0\n")
            fake_jest.chmod(0o755)
            junit_out = report_dir / "reports" / "junit.xml"

            refused = run_cmd(
                "scripts/run-approved-tests.py",
                str(report_dir),
                "--source-repo",
                str(source_repo),
                "--tbt",
                "TBT-016-ASVS-A",
                "--jest-bin",
                str(fake_jest),
                "--execution-mode",
                "host",
                "--junit-out",
                str(junit_out),
                check=False,
            )
            result = run_cmd(
                "scripts/run-approved-tests.py",
                str(report_dir),
                "--source-repo",
                str(source_repo),
                "--tbt",
                "TBT-016-ASVS-A",
                "--allow-reviewed-existing-asvs",
                "--jest-bin",
                str(fake_jest),
                "--execution-mode",
                "host",
                "--junit-out",
                str(junit_out),
            )

        self.assertNotEqual(0, refused.returncode)
        self.assertIn("not ready_to_run/non_destructive", refused.stderr)
        self.assertIn("approved tests: passed=1 failed=0 skipped=0", result.stdout)

    def test_assurance_pack_discovers_existing_asvs_test_for_planned_tbt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_repo = root / "project"
            report_dir = root / "report"
            test_rel = Path("tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js")
            test_path = source_repo / test_rel
            test_path.parent.mkdir(parents=True)
            test_path.write_text("test('TBT-016-ASVS-A', () => expect(true).toBe(true));\n")
            inventory = report_dir / "test-inventory.json"
            catalog = report_dir / "fr-catalog.snapshot.json"
            inventory.parent.mkdir(parents=True)
            inventory.write_text(json.dumps({"files": []}))
            catalog.write_text(json.dumps({
                "schema_version": 1,
                "frs": [{
                    "id": "FR-016",
                    "title": "Session timeout and re-authentication",
                    "lifecycle_status": "in_scope",
                }],
                "tbts": [{
                    "id": "TBT-016-ASVS-A",
                    "title": "Expired JWT rejection for FR-016",
                    "type": "integration",
                    "proves": ["FR-016"],
                    "compliance": [{"ruleset": "ASVS", "row": "v5.0.0-7.1.1"}],
                }],
            }))

            run_cmd(
                "scripts/generate-assurance-test-pack.py",
                "--target-dir",
                str(source_repo),
                "--report-dir",
                str(report_dir),
                "--test-inventory",
                str(inventory),
                "--fr-catalog",
                str(catalog),
            )
            pack = json.loads((report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json").read_text())

        self.assertEqual(1, pack["summary"]["existing_asvs"])
        self.assertEqual(0, pack["summary"]["planned_tbt"])
        self.assertEqual("existing_asvs", pack["tests"][0]["source"])
        self.assertEqual("existing", pack["tests"][0]["status"])
        self.assertEqual("review_required", pack["tests"][0]["safety"])
        self.assertEqual(str(test_rel), pack["tests"][0]["pack_path"])

    def test_cli_review_config_update_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "proposal-review.md"
            result = run_cli(
                "review-config-update",
                str(PROPOSAL),
                "--output",
                str(out_path),
            )
            review = out_path.read_text()

        self.assertIn("OK wrote proposal review", result.stdout)
        self.assertIn("# Config Update Proposal Review", review)
        self.assertIn("review recommended", review)
        self.assertIn("`fr_catalog_updates:1`", review)
        self.assertIn("Apply mode: `applyable`", review)

    def test_cli_apply_config_update_writes_reviewed_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "fr-catalog.cli-reviewed.json"
            result = run_cli(
                "apply-config-update",
                str(PROPOSAL),
                "--select",
                "fr_catalog_updates:1",
                "--reviewed-by",
                "cli-test-reviewer",
                "--fr-catalog",
                str(FR_CATALOG),
                "--fr-catalog-out",
                str(out_path),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote fr_catalog", result.stdout)
        tbt = next(item for item in reviewed["tbts"] if item["id"] == "TBT-016-ASVS-A")
        self.assertEqual(tbt["metadata"]["config_update_review"]["reviewed_by"], "cli-test-reviewer")

    def test_cli_apply_manual_evidence_update_for_tbt(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["manual_evidence_updates"] = [
            {
                "operation": "add_expected_manual_evidence",
                "target": {"kind": "tbt", "id": "TBT-016-ASVS-C"},
                "evidence_type": "document",
                "proposed_fields": {"paths": ["docs/cli-session-review.md"]},
                "review_status": "proposed",
                "source_basis": [{"type": "fr_catalog", "ref": "fixture"}],
                "rationale": "CLI manual evidence apply should update the TBT expected evidence.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "fr-catalog.cli-manual.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cli(
                "apply-config-update",
                str(proposal_path),
                "--select",
                "manual_evidence_updates:1",
                "--reviewed-by",
                "cli-manual-reviewer",
                "--fr-catalog",
                str(FR_CATALOG),
                "--fr-catalog-out",
                str(out_path),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote fr_catalog", result.stdout)
        tbt = next(item for item in reviewed["tbts"] if item["id"] == "TBT-016-ASVS-C")
        self.assertEqual(tbt["expected_evidence"][-1]["match"]["paths"], ["docs/cli-session-review.md"])
        self.assertEqual(tbt["metadata"]["config_update_review"]["reviewed_by"], "cli-manual-reviewer")

    def test_cli_apply_assurance_instance_mapping_writes_reviewed_output_file(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "update_instance_mapping",
                    "target": {"kind": "criterion", "id": "CRIT-GATE-03-04"},
                "proposed_fields": {
                    "append_requirements": [
                        {"type": "approval", "ref": "APP-ATT-SECURITY-REVIEW"}
                    ]
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/CRIT-GATE-03-04"}],
                "rationale": "The ATT gate criterion needs explicit approval evidence in the project instance.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cli(
                "apply-config-update",
                str(proposal_path),
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "cli-instance-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote assurance_instance", result.stdout)
        mapping = next(item for item in reviewed["criterion_mappings"] if item["criterion"] == "CRIT-GATE-03-04")
        self.assertIn({"type": "approval", "ref": "APP-ATT-SECURITY-REVIEW"}, mapping["requirements"])
        self.assertEqual(mapping["metadata"]["config_update_review"]["reviewed_by"], "cli-instance-reviewer")

    def test_apply_assurance_instance_role_assignment(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_instance_mapping",
                "target": {"kind": "role", "id": "ROLE-CAB"},
                "proposed_fields": {
                    "gate": "GATE-CAB-03-CAB-DECISION",
                    "role": "ROLE-CAB",
                    "party": "Change Advisory Board",
                    "approval_status": "pending",
                    "approval_ref": "approvals/cab-decision.md",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/ROLE-CAB"}],
                "rationale": "The CAB gate needs an explicit approver assignment in the project instance.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "role-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote assurance_instance", result.stdout)
        assignment = next(
            item
            for item in reviewed["role_assignments"]
            if item["gate"] == "GATE-CAB-03-CAB-DECISION" and item["role"] == "ROLE-CAB"
        )
        self.assertEqual(assignment["party"], "Change Advisory Board")
        self.assertEqual(assignment["metadata"]["config_update_review"]["reviewed_by"], "role-reviewer")

    def test_apply_assurance_instance_gate_decision(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_decision",
                "target": {"kind": "gate", "id": "GATE-CAB-03-CAB-DECISION"},
                "proposed_fields": {
                    "id": "DEC-GATE-CAB-03-CAB-DECISION",
                    "readiness_status": "manual_review",
                    "decided_by": "CAB Secretariat",
                    "notes": "CAB decision awaits manual approval evidence.",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/GATE-CAB-03-CAB-DECISION"}],
                "rationale": "The CAB gate needs an explicit project decision record.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "decision-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote assurance_instance", result.stdout)
        decision = next(item for item in reviewed["decisions"] if item["id"] == "DEC-GATE-CAB-03-CAB-DECISION")
        self.assertEqual(decision["gate"], "GATE-CAB-03-CAB-DECISION")
        self.assertEqual(decision["readiness_status"], "manual_review")
        self.assertEqual(decision["metadata"]["config_update_review"]["reviewed_by"], "decision-reviewer")

    def test_apply_assurance_instance_waiver(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_waiver",
                "target": {"kind": "tbt", "id": "TBT-016-ASVS-C"},
                "proposed_fields": {
                    "id": "WVR-TBT-016-ASVS-C",
                    "reason": "Manual document evidence is deferred to the next assurance review.",
                    "approval_status": "pending",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_instance", "ref": "fixture#/waivers"}],
                "rationale": "The missing manual evidence needs an explicit waiver rather than a silent gap.",
                "confidence": "medium",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "waiver-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote assurance_instance", result.stdout)
        waiver = next(item for item in reviewed["waivers"] if item["id"] == "WVR-TBT-016-ASVS-C")
        self.assertEqual(waiver["target"], "TBT-016-ASVS-C")
        self.assertEqual(waiver["approval_status"], "pending")
        self.assertEqual(waiver["metadata"]["config_update_review"]["reviewed_by"], "waiver-reviewer")

    def test_apply_assurance_instance_compensating_control(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_compensating_control",
                "target": {"kind": "ruleset_row", "id": "ASVS:v5.0.0-5.1.1", "ruleset": "ASVS", "row": "v5.0.0-5.1.1"},
                "proposed_fields": {
                    "id": "CMP-ASVS-5-1-1",
                    "reason": "The direct automated control is not currently available, so a reviewed compensating control is required.",
                    "control_description": "Security team performs manual session-management review before ATT gate approval.",
                    "approval_status": "pending",
                    "target_ref": {"type": "ruleset_row", "ref": "ASVS:v5.0.0-5.1.1", "ruleset": "ASVS", "row": "v5.0.0-5.1.1"},
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_instance", "ref": "fixture#/compensating_controls"}],
                "rationale": "The compliance row needs an explicit compensating-control record rather than a silent exception.",
                "confidence": "medium",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "control-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("OK wrote assurance_instance", result.stdout)
        control = next(item for item in reviewed["compensating_controls"] if item["id"] == "CMP-ASVS-5-1-1")
        self.assertEqual(control["target"], "ASVS:v5.0.0-5.1.1")
        self.assertEqual(control["target_ref"]["type"], "ruleset_row")
        self.assertEqual(control["approval_status"], "pending")
        self.assertEqual(control["metadata"]["config_update_review"]["reviewed_by"], "control-reviewer")

    def test_cli_validate_report_accepts_generated_config_template_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "dashboard-payload.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "inputs": {},
                    "summary": {},
                    "graph": {"nodes": [], "edges": []},
                })
            )
            (report_dir / "evidence-bundle.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "evidence": [],
                })
            )
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )
            add_manifest_artifact(report_dir, "dashboard-payload.json")
            add_manifest_artifact(report_dir, "evidence-bundle.json")
            run_cmd(
                "scripts/generate-agent-prompt.py",
                "--report-dir",
                str(report_dir),
                "--target-dir",
                str(REPO_ROOT),
                "--run-id",
                "template-run",
            )

            result = run_cli("validate-report", str(report_dir))

        self.assertIn("OK report artifacts:", result.stdout)
        self.assertIn("fr-config-update-proposal.template.json", result.stdout)

    def test_generated_report_artifacts_include_valid_config_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "dashboard-payload.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "inputs": {},
                    "summary": {},
                    "graph": {"nodes": [], "edges": []},
                })
            )
            (report_dir / "evidence-bundle.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "evidence": [],
                })
            )
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )
            add_manifest_artifact(report_dir, "dashboard-payload.json")
            add_manifest_artifact(report_dir, "evidence-bundle.json")

            run_cmd(
                "scripts/generate-agent-prompt.py",
                "--report-dir",
                str(report_dir),
                "--target-dir",
                str(REPO_ROOT),
                "--run-id",
                "template-run",
            )
            result = run_cmd("scripts/validate-report-artifacts.py", "--report-dir", str(report_dir))

        self.assertIn("OK report artifacts:", result.stdout)
        self.assertIn("fr-config-update-proposal.template.json", result.stdout)

    def test_report_validation_rejects_malformed_manifest_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "dashboard-payload.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "inputs": {},
                    "summary": {},
                    "graph": {"nodes": [], "edges": []},
                })
            )
            (report_dir / "evidence-bundle.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "evidence": [],
                })
            )
            (report_dir / "scanner-health.json").write_text(
                '{"scanners": [{name:zap-baseline,status:SKIPPED}]}'
            )
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )
            add_manifest_artifact(report_dir, "dashboard-payload.json")
            add_manifest_artifact(report_dir, "evidence-bundle.json")
            add_manifest_artifact(report_dir, "scanner-health.json")

            result = run_cmd(
                "scripts/validate-report-artifacts.py",
                "--report-dir",
                str(report_dir),
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scanner-health.json: listed JSON artifact is not readable JSON", result.stdout)

    def test_evidence_generator_rewrites_scanner_health_as_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "reports").mkdir()
            (report_dir / "sbom").mkdir()
            (report_dir / "manual-evidence-required.md").write_text("")
            (report_dir / "config-status.json").write_text(json.dumps({"checks": []}))
            (report_dir / "scanner-health.json").write_text(
                '{"scanners": [{name:zap-baseline,status:SKIPPED}]}'
            )

            run_cmd(
                "scripts/generate-evidence-bundle.py",
                "--report-dir",
                str(report_dir),
                "--target-dir",
                str(REPO_ROOT),
                "--run-id",
                "health-json-test",
            )

            scanner_health = json.loads((report_dir / "scanner-health.json").read_text())
            health_by_name = {item["name"]: item for item in scanner_health["scanners"]}

        self.assertEqual(health_by_name["zap-baseline"]["status"], "SKIPPED")
        self.assertIn("reason", health_by_name["zap-baseline"])

    def test_dashboard_regeneration_records_existing_core_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "evidence-bundle.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "evidence": [],
                })
            )
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )

            run_cmd("scripts/generate_dashboard.py", "--report-dir", str(report_dir))
            result = run_cmd("scripts/validate-report-artifacts.py", "--report-dir", str(report_dir))
            manifest = json.loads((report_dir / "evidence-manifest.json").read_text())
            manifest_files = {item["file"] for item in manifest["evidence_files"]}

        self.assertIn("OK report artifacts:", result.stdout)
        self.assertIn("evidence-bundle.json", manifest_files)
        self.assertIn("dashboard-payload.json", manifest_files)

    def test_project_fr_board_state_preserves_review_decisions(self) -> None:
        dashboard = load_script_module(
            "generate_dashboard_for_board_state_test",
            REPO_ROOT / "scripts" / "generate_dashboard.py",
        )
        loader = load_script_module(
            "load_target_artifacts_for_board_state_test",
            REPO_ROOT / "scripts" / "load_target_artifacts.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            pack_dir.mkdir(parents=True)
            (report_dir / "evidence-manifest.json").write_text(json.dumps({
                "repository": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-08T00:00:00Z",
                "evidence_files": [],
            }))
            (pack_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "VG_TEST_FRAMEWORK",
                "mode": "ephemeral",
                "generated_at": "2026-07-08T00:00:00Z",
                "tests": [
                    {
                        "pack_id": "GENERATED-TBT-001",
                        "source": "generated",
                        "type": "integration",
                        "status": "ready_to_run",
                        "assessment": "useful_as_is",
                        "safety": "non_destructive",
                        "title": "TBT-001 approved assurance test",
                        "tbt": "TBT-001",
                        "frs": ["FR-001"],
                        "pack_path": "tests/asvs/integration/TBT-001.assurance.test.js",
                    }
                ],
            }))
            add_manifest_artifact(report_dir, "generated-tests/VG_TEST_FRAMEWORK/manifest.json")
            (report_dir / "project-fr-board-state.json").write_text(json.dumps({
                "schema_version": 1,
                "mode": "project_fr_board_state",
                "project": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-08T00:00:00Z",
                "cards": [
                    {
                        "id": "GENERATED-TBT-001",
                        "lane": "import",
                        "source": "generated",
                        "decision": "approve_to_run",
                        "reviewer_note": "Reviewed safe to execute.",
                        "manual_test_path": "tests/asvs/integration/TBT-001.assurance.test.js",
                    }
                ],
            }))

            html_text = dashboard.render_native_review_board_page(
                report_dir,
                project="demo",
                run_id="run-1",
                generated_at="2026-07-08T00:00:00Z",
            )
            state = json.loads((report_dir / "project-fr-board-state.json").read_text())
            result = run_cmd("scripts/validate-report-artifacts.py", "--report-dir", str(report_dir))
            loaded = loader.load_target_artifact(report_dir / "project-fr-board-state.json", "project_fr_board_state", strict=True)

        card = state["cards"][0]
        self.assertEqual(card["lane"], "import")
        self.assertEqual(card["decision"], "approve_to_run")
        self.assertEqual(card["reviewer_note"], "Reviewed safe to execute.")
        self.assertIn('data-review-decision="approve_to_run"', html_text)
        self.assertIn('data-reviewer-note="Reviewed safe to execute."', html_text)
        self.assertIn("OK report artifacts:", result.stdout)
        self.assertEqual(loaded.kind, "project_fr_board_state")

    def test_project_fr_board_state_ready_manifest_overrides_stale_review_lane(self) -> None:
        dashboard = load_script_module(
            "generate_dashboard_for_ready_lane_test",
            REPO_ROOT / "scripts" / "generate_dashboard.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            pack_dir.mkdir(parents=True)
            (report_dir / "evidence-manifest.json").write_text(json.dumps({
                "repository": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-08T00:00:00Z",
                "evidence_files": [],
            }))
            (pack_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "VG_TEST_FRAMEWORK",
                "mode": "ephemeral",
                "generated_at": "2026-07-08T00:00:00Z",
                "tests": [
                    {
                        "pack_id": "GENERATED-TBT-016-ASVS-A",
                        "source": "generated",
                        "type": "integration",
                        "status": "ready_to_run",
                        "assessment": "useful_as_is",
                        "safety": "non_destructive",
                        "title": "Expired JWT rejection for FR-016",
                        "tbt": "TBT-016-ASVS-A",
                        "frs": ["FR-016"],
                        "pack_path": "tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js",
                    }
                ],
            }))
            add_manifest_artifact(report_dir, "generated-tests/VG_TEST_FRAMEWORK/manifest.json")
            (report_dir / "project-fr-board-state.json").write_text(json.dumps({
                "schema_version": 1,
                "mode": "project_fr_board_state",
                "project": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-08T00:00:00Z",
                "cards": [
                    {
                        "id": "GENERATED-TBT-016-ASVS-A",
                        "lane": "review",
                        "source": "generated",
                        "decision": "approve_to_run",
                        "reviewer_note": "Approved, but stale lane persisted from the review phase.",
                    }
                ],
            }))

            html_text = dashboard.render_native_review_board_page(
                report_dir,
                project="demo",
                run_id="run-1",
                generated_at="2026-07-08T00:00:00Z",
            )
            state = json.loads((report_dir / "project-fr-board-state.json").read_text())

        card = state["cards"][0]
        self.assertEqual(card["lane"], "import")
        self.assertEqual(card["status"], "ready_to_run")
        self.assertEqual(card["safety"], "non_destructive")
        self.assertIn('data-review-lane="import"', html_text)
        self.assertIn('data-review-card="GENERATED-TBT-016-ASVS-A"', html_text)

    def test_project_frs_page_shows_fallback_assurance_badges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)

            run_cmd(
                "scripts/generate_dashboard.py",
                "--report-dir",
                str(report_dir),
                "--fr-catalog",
                str(FR_CATALOG),
            )
            html_text = (report_dir / "dashboard.html").read_text()

        self.assertIn("Project Functional Requirements", html_text)
        self.assertIn("assurance-state-missing", html_text)
        self.assertIn("unproven", html_text)

    def test_generate_missing_assurance_specs_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            pack_dir.mkdir(parents=True)
            (report_dir / "fr-catalog.snapshot.json").write_text(FR_CATALOG.read_text())
            (report_dir / "evidence-bundle.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "evidence": [
                        {
                            "id": "EVD-TBT-016-ASVS-A",
                            "type": "test_result",
                            "result_status": "missing",
                            "produced_by": "TBT-016-ASVS-A",
                            "source": "reports/junit.xml",
                        }
                    ],
                })
            )
            (pack_dir / "manifest.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "name": "VG_TEST_FRAMEWORK",
                    "mode": "ephemeral",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "tests": [
                        {
                            "pack_id": "PLANNED-TBT-016-ASVS-A",
                            "tbt": "TBT-016-ASVS-A",
                            "frs": ["FR-016"],
                            "source": "planned_tbt",
                            "type": "integration",
                            "status": "planned",
                            "assessment": "needs_design",
                            "safety": "non_destructive",
                            "pack_path": "tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js",
                        }
                    ],
                    "summary": {},
                })
            )
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )
            add_manifest_artifact(report_dir, "evidence-bundle.json")
            add_manifest_artifact(report_dir, "generated-tests/VG_TEST_FRAMEWORK/manifest.json")

            run_cmd("scripts/generate-missing-assurance-tests.py", "--report-dir", str(report_dir))

            pack = json.loads((pack_dir / "manifest.json").read_text())
            manifest = json.loads((report_dir / "evidence-manifest.json").read_text())
            manifest_files = {item["file"] for item in manifest["evidence_files"]}

        self.assertEqual(3, len(pack.get("generated_specifications", [])))
        self.assertIn(
            "generated-tests/VG_TEST_FRAMEWORK/specifications/integration/TBT-016-ASVS-A.assurance-spec.md",
            manifest_files,
        )
        self.assertIn("generated-tests/VG_TEST_FRAMEWORK/RUNBOOK.md", manifest_files)

    def test_promote_assurance_specs_writes_review_required_scaffold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            pack_dir.mkdir(parents=True)
            (report_dir / "fr-catalog.snapshot.json").write_text(FR_CATALOG.read_text())
            (report_dir / "evidence-bundle.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "project": "template-app",
                    "evidence": [
                        {
                            "id": "EVD-TBT-016-ASVS-A",
                            "type": "test_result",
                            "result_status": "missing",
                            "produced_by": "TBT-016-ASVS-A",
                            "source": "reports/junit.xml",
                        }
                    ],
                })
            )
            (pack_dir / "manifest.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "name": "VG_TEST_FRAMEWORK",
                    "mode": "ephemeral",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "tests": [],
                    "summary": {},
                })
            )
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )
            add_manifest_artifact(report_dir, "evidence-bundle.json")
            add_manifest_artifact(report_dir, "generated-tests/VG_TEST_FRAMEWORK/manifest.json")

            run_cmd(
                "scripts/promote-assurance-specs.py",
                "--report-dir",
                str(report_dir),
                "--tbt",
                "TBT-016-ASVS-A",
            )

            pack = json.loads((pack_dir / "manifest.json").read_text())
            manifest = json.loads((report_dir / "evidence-manifest.json").read_text())
            scaffold = pack_dir / "tests" / "asvs" / "integration" / "TBT-016-ASVS-A.assurance.test.js"
            scaffold_text = scaffold.read_text()
            manifest_files = {item["file"] for item in manifest["evidence_files"]}

        self.assertEqual(1, len(pack.get("tests", [])))
        self.assertEqual("GENERATED-TBT-016-ASVS-A", pack["tests"][0]["pack_id"])
        self.assertEqual("review_required", pack["tests"][0]["safety"])
        self.assertIn('describe.skip("[TBT-016-ASVS-A]', scaffold_text)
        self.assertIn("generated-tests/VG_TEST_FRAMEWORK/tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js", manifest_files)

    def test_fr_catalog_prefers_generated_scaffold_over_planned_tbt_entry(self) -> None:
        catalog_tab = load_script_module(
            "catalog_tab_for_generated_scaffold_priority",
            REPO_ROOT / "scripts" / "fr" / "catalog_tab.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            pack_dir.mkdir(parents=True)
            (pack_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "VG_TEST_FRAMEWORK",
                "mode": "ephemeral",
                "generated_at": "2026-07-06T00:00:00Z",
                "tests": [
                    {
                        "pack_id": "TBT-016-ASVS-A",
                        "tbt": "TBT-016-ASVS-A",
                        "source": "planned_tbt",
                        "status": "planned",
                        "safety": "non_destructive",
                        "pack_path": "tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js",
                    },
                    {
                        "pack_id": "GENERATED-TBT-016-ASVS-A",
                        "tbt": "TBT-016-ASVS-A",
                        "source": "generated",
                        "status": "generated",
                        "safety": "review_required",
                        "pack_path": "tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js",
                    },
                ],
            }))

            by_tbt = catalog_tab._load_assurance_pack_by_tbt(report_dir)
            state = catalog_tab._test_existence_state(
                {"id": "TBT-016-ASVS-A", "ref": "tests/asvs/integration/TBT-016-ASVS-A.assurance.test.js"},
                {},
                by_tbt["TBT-016-ASVS-A"],
            )

        self.assertEqual("GENERATED-TBT-016-ASVS-A", by_tbt["TBT-016-ASVS-A"]["pack_id"])
        self.assertEqual("Awaiting approval", state["label"])

    def test_fr_catalog_renderer_reads_assurance_pack_from_report_dir(self) -> None:
        catalog_tab = load_script_module(
            "catalog_tab_for_report_dir_pack_lookup",
            REPO_ROOT / "scripts" / "fr" / "catalog_tab.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_dir = tmp_path / "report"
            report_dir.mkdir()
            catalog_path = tmp_path / "external.fr-catalog.json"
            catalog_path.write_text(json.dumps({
                "schema_version": 1,
                "project": "template-app",
                "frs": [
                    {
                        "id": "FR-001",
                        "title": "Session timeout",
                        "description": "Session timeout",
                        "lifecycle_status": "in_scope",
                    }
                ],
                "tbts": [
                    {
                        "id": "TBT-001",
                        "title": "Expired JWT rejection",
                        "type": "integration",
                        "proves": ["FR-001"],
                        "evidence_policy": "automated_required",
                        "expected_evidence": ["test_result"],
                    }
                ],
            }))
            pack_dir = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK"
            pack_dir.mkdir(parents=True)
            (pack_dir / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "VG_TEST_FRAMEWORK",
                "mode": "ephemeral",
                "tests": [
                    {
                        "pack_id": "GENERATED-TBT-001",
                        "tbt": "TBT-001",
                        "source": "generated",
                        "status": "generated",
                        "safety": "review_required",
                        "pack_path": "tests/asvs/integration/TBT-001.assurance.test.js",
                    }
                ],
            }))

            rendered = catalog_tab.render_fr_catalog(str(catalog_path), report_dir=report_dir)

        self.assertIn("Awaiting approval", rendered)
        self.assertIn("tests/asvs/integration/TBT-001.assurance.test.js", rendered)

    def test_generated_config_update_template_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "dashboard-payload.json").write_text("{}")
            (report_dir / "evidence-manifest.json").write_text(
                json.dumps({
                    "repository": "template-app",
                    "generated_at": "2026-07-06T00:00:00Z",
                    "evidence_files": [],
                })
            )
            result = run_cmd(
                "scripts/generate-agent-prompt.py",
                "--report-dir",
                str(report_dir),
                "--target-dir",
                str(REPO_ROOT),
                "--run-id",
                "template-run",
            )
            template_path = report_dir / "fr-config-update-proposal.template.json"
            self.assertIn("fr-config-update-proposal.template: written", result.stdout)
            self.assertTrue(template_path.exists())

            template = json.loads(template_path.read_text())
            self.assertEqual(template["mode"], "config_update_proposal")
            self.assertEqual(template["project"], "template-app")
            self.assertEqual(template["fr_catalog_updates"], [])
            self.assertEqual(template["review_required"][0]["item"], "config-authoring")

            validation = run_cmd("scripts/validate-config-update-proposal.py", str(template_path))
            self.assertIn("OK config update proposal: 0 proposed updates", validation.stdout)

    def test_validate_config_update_proposal_with_context(self) -> None:
        result = run_cmd(
            "scripts/validate-config-update-proposal.py",
            str(PROPOSAL),
            "--fr-catalog",
            str(FR_CATALOG),
            "--ruleset",
            str(RULESET),
            "--assurance-framework",
            str(ASSURANCE_FRAMEWORK),
        )

        self.assertIn("OK config update proposal: 4 proposed updates", result.stdout)

    def test_validate_config_update_rejects_unknown_native_test_mapping_target(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["native_test_mapping_updates"] = [
            {
                "operation": "map_native_test_to_existing_tbt",
                "native_test": {
                    "pack_id": "NATIVE-missing-target",
                    "native_path": "tests/missing-target.test.js",
                },
                "target": {"fr": "FR-404", "tbt": "TBT-404"},
                "review_status": "proposed",
                "source_basis": [{"type": "native_test", "ref": "tests/missing-target.test.js"}],
                "rationale": "This should be rejected because the target FR/TBT does not exist.",
                "confidence": "medium",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd(
                "scripts/validate-config-update-proposal.py",
                str(proposal_path),
                "--fr-catalog",
                str(FR_CATALOG),
                check=False,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unknown target FR FR-404", result.stdout)
        self.assertIn("unknown target TBT TBT-404", result.stdout)

    def test_validate_config_update_rejects_unknown_proposed_gate(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_instance_mapping",
                "target": {"kind": "role", "id": "ROLE-CAB"},
                "proposed_fields": {
                    "gate": "MISSING-GATE",
                    "role": "ROLE-CAB",
                    "approval_status": "pending",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/ROLE-CAB"}],
                "rationale": "This should be rejected because the gate does not exist in the framework.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd(
                "scripts/validate-config-update-proposal.py",
                str(proposal_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("proposed gate references unknown gate MISSING-GATE", result.stdout)

    def test_review_config_update_proposal_renders_decision_brief(self) -> None:
        result = run_cmd("scripts/review-config-update-proposal.py", str(PROPOSAL))

        self.assertIn("# Config Update Proposal Review", result.stdout)
        self.assertIn("review recommended", result.stdout)
        self.assertIn("Validate this proposal", result.stdout)
        self.assertIn("`fr_catalog_updates:1`", result.stdout)
        self.assertIn("asvs-scanner apply-config-update proposal.json --select fr_catalog_updates:1", result.stdout)

    def test_apply_without_selection_lists_entries_and_writes_nothing(self) -> None:
        result = run_cmd("scripts/apply-config-update-proposal.py", str(PROPOSAL))

        self.assertIn("Selectable proposal entries:", result.stdout)
        self.assertIn("fr_catalog_updates:1", result.stdout)
        self.assertIn("No changes written", result.stdout)

    def test_apply_manual_evidence_update_for_tbt_writes_expected_evidence(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["manual_evidence_updates"] = [
            {
                "operation": "add_expected_manual_evidence",
                "target": {"kind": "tbt", "id": "TBT-016-ASVS-C"},
                "evidence_type": "document",
                "proposed_fields": {
                    "paths": ["docs/session-review.md"],
                    "minimum_strength": "manual_review",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "fr_catalog", "ref": "fixture"}],
                "rationale": "Manual document review evidence should be expected for this TBT.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "fr-catalog.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            listing = run_cmd("scripts/apply-config-update-proposal.py", str(proposal_path))
            apply_result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "manual_evidence_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                "--fr-catalog",
                str(FR_CATALOG),
                "--fr-catalog-out",
                str(out_path),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("manual_evidence_updates:1", listing.stdout)
        self.assertIn("applyable", listing.stdout)
        self.assertIn("OK wrote fr_catalog", apply_result.stdout)
        tbt = next(item for item in reviewed["tbts"] if item["id"] == "TBT-016-ASVS-C")
        expected = tbt["expected_evidence"][-1]
        self.assertEqual(expected["type"], "document")
        self.assertEqual(expected["match"]["paths"], ["docs/session-review.md"])
        self.assertEqual(tbt["metadata"]["config_update_review"]["reviewed_by"], "unit-test-reviewer")

    def test_apply_native_test_mapping_writes_reviewed_test_pack(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["native_test_mapping_updates"] = [
            {
                "operation": "map_native_test_to_existing_tbt",
                "native_test": {
                    "pack_id": "NATIVE-tests-session-test-ts",
                    "native_path": "tests/session.test.ts",
                    "pack_path": "imported/tests/session.test.ts",
                },
                "target": {"fr": "FR-016", "tbt": "TBT-016-ASVS-A"},
                "review_status": "proposed",
                "source_basis": [{"type": "native_test", "ref": "tests/session.test.ts"}],
                "rationale": "Reviewed native session test proves the existing session timeout TBT.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-test-pack.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            listing = run_cmd("scripts/apply-config-update-proposal.py", str(proposal_path))
            apply_result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "native_test_mapping_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                "--assurance-test-pack",
                str(ASSURANCE_TEST_PACK),
                "--assurance-test-pack-out",
                str(out_path),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("native_test_mapping_updates:1", listing.stdout)
        self.assertIn("applyable", listing.stdout)
        self.assertIn("OK wrote assurance_test_pack", apply_result.stdout)
        native = next(item for item in reviewed["tests"] if item["pack_id"] == "NATIVE-tests-session-test-ts")
        self.assertEqual(native["tbt"], "TBT-016-ASVS-A")
        self.assertEqual(native["frs"], ["FR-016"])
        self.assertEqual(native["mapping_review"]["reviewed_by"], "unit-test-reviewer")
        self.assertEqual(reviewed["summary"]["mapped_native"], 1)

    def test_apply_manual_evidence_update_for_criterion_writes_instance_requirement(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["manual_evidence_updates"] = [
            {
                "operation": "add_expected_manual_evidence",
                "target": {"kind": "criterion", "id": "CRIT-GATE-03-04"},
                "evidence_type": "document",
                "proposed_fields": {
                    "ref": "ATT submission pack",
                    "evidence": "EVD-G3-ATT-PACK",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/CRIT-GATE-03-04"}],
                "rationale": "Criterion CRIT-GATE-03-04 requires a reviewed ATT submission pack.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            listing = run_cmd("scripts/apply-config-update-proposal.py", str(proposal_path))
            apply_result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "manual_evidence_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
            )
            reviewed = json.loads(out_path.read_text())

        self.assertIn("manual_evidence_updates:1", listing.stdout)
        self.assertIn("applyable", listing.stdout)
        self.assertIn("OK wrote assurance_instance", apply_result.stdout)
        mapping = next(item for item in reviewed["criterion_mappings"] if item["criterion"] == "CRIT-GATE-03-04")
        self.assertIn({"type": "manual_artifact", "ref": "ATT submission pack", "evidence": "EVD-G3-ATT-PACK"}, mapping["requirements"])
        self.assertEqual(mapping["metadata"]["config_update_review"]["reviewed_by"], "unit-test-reviewer")

    def test_apply_assurance_instance_rejects_unknown_gate_when_framework_supplied(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_instance_mapping",
                "target": {"kind": "role", "id": "ROLE-CAB"},
                "proposed_fields": {
                    "gate": "MISSING-GATE",
                    "role": "ROLE-CAB",
                    "party": "Change Advisory Board",
                    "approval_status": "pending",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/ROLE-CAB"}],
                "rationale": "This should be rejected because the gate does not exist in the framework.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            out_path = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            out_path.write_text(ASSURANCE_INSTANCE.read_text())
            original_out = out_path.read_text()
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(out_path),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
                check=False,
            )
            final_out = out_path.read_text()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown gate 'MISSING-GATE'", result.stderr)
        self.assertEqual(final_out, original_out)

    def test_apply_mixed_outputs_does_not_partially_commit_when_later_output_fails(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["assurance_framework_or_instance_updates"] = [
            {
                "operation": "add_instance_mapping",
                "target": {"kind": "role", "id": "ROLE-CAB"},
                "proposed_fields": {
                    "gate": "MISSING-GATE",
                    "role": "ROLE-CAB",
                    "approval_status": "pending",
                },
                "review_status": "proposed",
                "source_basis": [{"type": "assurance_framework", "ref": "fixture#/ROLE-CAB"}],
                "rationale": "The invalid gate should prevent all selected outputs from being committed.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            fr_out = Path(tmp) / "fr-catalog.reviewed.json"
            instance_out = Path(tmp) / "assurance-instance.reviewed.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            fr_out.write_text(FR_CATALOG.read_text())
            instance_out.write_text(ASSURANCE_INSTANCE.read_text())
            original_fr_out = fr_out.read_text()
            original_instance_out = instance_out.read_text()
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "fr_catalog_updates:1",
                "--select",
                "assurance_framework_or_instance_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                "--fr-catalog",
                str(FR_CATALOG),
                "--fr-catalog-out",
                str(fr_out),
                "--assurance-instance",
                str(ASSURANCE_INSTANCE),
                "--assurance-instance-out",
                str(instance_out),
                "--assurance-framework",
                str(ASSURANCE_FRAMEWORK),
                check=False,
            )
            final_fr_out = fr_out.read_text()
            final_instance_out = instance_out.read_text()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown gate 'MISSING-GATE'", result.stderr)
        self.assertEqual(final_fr_out, original_fr_out)
        self.assertEqual(final_instance_out, original_instance_out)

    def test_apply_lists_and_refuses_gate_manual_evidence_as_review_only(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["manual_evidence_updates"] = [
            {
                "operation": "add_expected_manual_evidence",
                "target": {"kind": "gate", "id": "GATE-1"},
                "evidence_type": "document",
                "review_status": "proposed",
                "source_basis": [{"type": "fr_catalog", "ref": "fixture"}],
                "rationale": "Gate evidence belongs in the assurance instance, not the FR catalog.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            listing = run_cmd("scripts/apply-config-update-proposal.py", str(proposal_path))
            apply_result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(proposal_path),
                "--select",
                "manual_evidence_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                check=False,
            )

        self.assertIn("manual_evidence_updates:1", listing.stdout)
        self.assertIn("review-only", listing.stdout)
        self.assertNotEqual(apply_result.returncode, 0)
        self.assertIn("review-only", apply_result.stderr)

    def test_review_brief_marks_gate_manual_evidence_as_review_only(self) -> None:
        proposal = json.loads(PROPOSAL.read_text())
        proposal["manual_evidence_updates"] = [
            {
                "operation": "add_expected_manual_evidence",
                "target": {"kind": "gate", "id": "GATE-1"},
                "evidence_type": "document",
                "review_status": "proposed",
                "source_basis": [{"type": "fr_catalog", "ref": "fixture"}],
                "rationale": "Gate evidence belongs in the assurance instance, not the FR catalog.",
                "confidence": "high",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proposal_path = Path(tmp) / "proposal.json"
            proposal_path.write_text(json.dumps(proposal, indent=2))
            result = run_cmd("scripts/review-config-update-proposal.py", str(proposal_path))

        self.assertIn("`manual_evidence_updates:1`", result.stdout)
        self.assertIn("Apply mode: `review-only`", result.stdout)
        self.assertIn("manual/review-only in this version", result.stdout)

    def test_apply_selected_fr_update_writes_reviewed_output_only(self) -> None:
        original = json.loads(FR_CATALOG.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "fr-catalog.reviewed.json"
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(PROPOSAL),
                "--select",
                "fr_catalog_updates:1",
                "--reviewed-by",
                "unit-test-reviewer",
                "--fr-catalog",
                str(FR_CATALOG),
                "--fr-catalog-out",
                str(out_path),
            )

            self.assertIn("OK wrote fr_catalog", result.stdout)
            reviewed = json.loads(out_path.read_text())

        self.assertEqual(original, json.loads(FR_CATALOG.read_text()))
        tbt = next(item for item in reviewed["tbts"] if item["id"] == "TBT-016-ASVS-A")
        review = tbt["metadata"]["config_update_review"]
        self.assertEqual(review["review_status"], "accepted")
        self.assertEqual(review["reviewed_by"], "unit-test-reviewer")
        self.assertEqual(tbt["expected_evidence"][0]["format"], "junit")

    def test_apply_requires_reviewer_for_selected_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "fr-catalog.reviewed.json"
            result = run_cmd(
                "scripts/apply-config-update-proposal.py",
                str(PROPOSAL),
                "--select",
                "fr_catalog_updates:1",
                "--fr-catalog",
                str(FR_CATALOG),
                "--fr-catalog-out",
                str(out_path),
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--reviewed-by is required", result.stderr)

    def test_direct_scanner_mapping_failure_blocks_compliance_row(self) -> None:
        resolver = load_script_module(
            "resolve_assurance_status",
            REPO_ROOT / "scripts" / "resolve-assurance-status.py",
        )
        mapping_pack = json.loads(SCANNER_COMPLIANCE_MAPPING_PACK.read_text())

        payload = resolver.resolve(
            argparse.Namespace(
                fr_catalog=FR_CATALOG,
                evidence_bundle=EVIDENCE_BUNDLE,
                assurance_instance=None,
                scanner_findings=[fixture_scanner_finding()],
                scanner_compliance_packs=[mapping_pack],
                scanner_compliance_mapping_pack=[],
            )
        )

        row = next(item for item in payload["compliance_rows"] if item["id"] == "ASVS:v5.0.0-5.1.1")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(len(row["scanner_blockers"]), 1)
        blocker = row["scanner_blockers"][0]
        self.assertEqual(blocker["tool"], "semgrep")
        self.assertEqual(blocker["mapping_id"], "SCM-SEMGREP-ASVS-5-INJECTION")
        self.assertEqual(blocker["source_locator"], "src/app.py:12")
        self.assertIn("Direct scanner evidence", " ".join(row["reasons"]))

    def test_graph_links_direct_scanner_blocker_to_compliance_row(self) -> None:
        resolver = load_script_module(
            "resolve_assurance_status_for_graph",
            REPO_ROOT / "scripts" / "resolve-assurance-status.py",
        )
        load_fr_catalog = load_script_module(
            "load_fr_catalog_for_graph",
            REPO_ROOT / "scripts" / "load_fr_catalog.py",
        )
        from fr.graph import build_graph_data

        mapping_pack = json.loads(SCANNER_COMPLIANCE_MAPPING_PACK.read_text())
        finding = fixture_scanner_finding()
        assurance_status = resolver.resolve(
            argparse.Namespace(
                fr_catalog=FR_CATALOG,
                evidence_bundle=EVIDENCE_BUNDLE,
                assurance_instance=None,
                scanner_findings=[finding],
                scanner_compliance_packs=[mapping_pack],
                scanner_compliance_mapping_pack=[],
            )
        )

        graph = build_graph_data(
            load_fr_catalog.load_fr_catalog(FR_CATALOG),
            evidence_bundle=json.loads(EVIDENCE_BUNDLE.read_text()),
            assurance_status=assurance_status,
            scanner_findings=[finding],
            scanner_compliance_packs=[mapping_pack],
        )

        scanner_nodes = [
            node for node in graph["nodes"]
            if node.get("evidence_type") == "scanner_result"
            and node.get("ref") == "SCM-SEMGREP-ASVS-5-INJECTION"
        ]
        self.assertEqual(len(scanner_nodes), 1)
        self.assertEqual(scanner_nodes[0]["status"], "failed")
        self.assertEqual(scanner_nodes[0]["mapping_level"], "compliance_row")
        self.assertEqual(scanner_nodes[0]["source_locator"], "src/app.py:12")

        scanner_node_id = scanner_nodes[0]["id"]
        self.assertIn(
            {
                "source": "ASVS:v5.0.0-5.1.1",
                "target": scanner_node_id,
                "type": "evidences",
                "key": f"ASVS:v5.0.0-5.1.1->{scanner_node_id}:evidences:",
            },
            graph["edges"],
        )

    def test_process_gate_rollup_blocks_on_direct_scanner_evidence(self) -> None:
        process_tab = load_script_module(
            "process_tab_for_scanner_rollup",
            REPO_ROOT / "scripts" / "process" / "process_tab.py",
        )

        state = process_tab._compute_gate_state(
            {
                "id": "GATE-TEST",
                "required_roles": [],
                "criteria": [
                    {
                        "id": "CRIT-SCANNER",
                        "title": "Scanner mapped row",
                        "required": True,
                        "evidence": [
                            {
                                "type": "ruleset_row",
                                "ref": "ASVS:v5.0.0-7.1.1",
                                "label": "ASVS v5.0.0-7.1.1",
                                "required": True,
                            }
                        ],
                    }
                ],
            },
            role_lookup={},
            target_dir=None,
            fr_catalog=None,
            fr_evidence={},
            target_evidence={},
            resolved_status={
                "row_by_id": {
                    "ASVS:v5.0.0-7.1.1": {
                        "id": "ASVS:v5.0.0-7.1.1",
                        "status": "failed",
                        "scanner_blockers": [
                            {
                                "tool": "semgrep",
                                "mapping_id": "SCM-SEMGREP-ASVS-7-JWT",
                                "source_locator": "src/auth.js:12",
                            }
                        ],
                    }
                },
                "fr_by_id": {},
                "tbt_by_id": {},
                "rows_by_fr": {},
                "rows_by_tbt": {},
            },
        )

        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["scanner_blocker_count"], 1)
        self.assertIn("blocking scanner evidence", state["blockers"][0])

    def test_process_gate_decision_can_resolve_scanner_blocked_criterion_to_partial(self) -> None:
        process_tab = load_script_module(
            "process_tab_for_gate_decision_rollup",
            REPO_ROOT / "scripts" / "process" / "process_tab.py",
        )

        state = process_tab._compute_gate_state(
            {
                "id": "GATE-TEST",
                "required_roles": [],
                "criteria": [
                    {
                        "id": "CRIT-SCANNER",
                        "title": "Scanner mapped row",
                        "required": True,
                        "evidence": [
                            {
                                "type": "ruleset_row",
                                "ref": "ASVS:v5.0.0-7.1.1",
                                "label": "ASVS v5.0.0-7.1.1",
                                "required": True,
                            }
                        ],
                    }
                ],
            },
            role_lookup={},
            target_dir=None,
            fr_catalog=None,
            fr_evidence={},
            target_evidence={},
            resolved_status={
                "row_by_id": {
                    "ASVS:v5.0.0-7.1.1": {
                        "id": "ASVS:v5.0.0-7.1.1",
                        "status": "failed",
                        "scanner_blockers": [
                            {
                                "tool": "semgrep",
                                "mapping_id": "SCM-SEMGREP-ASVS-7-JWT",
                                "source_locator": "src/auth.js:12",
                            }
                        ],
                    }
                },
                "fr_by_id": {},
                "tbt_by_id": {},
                "rows_by_fr": {},
                "rows_by_tbt": {},
            },
            gate_exceptions={
                "controls_by_target": {},
                "decisions_by_target": {
                    "criterion:CRIT-SCANNER": [
                        {
                            "id": "DEC-CRIT-SCANNER",
                            "readiness_status": "partial",
                            "outcome": "Proceed with residual scanner risk.",
                        }
                    ]
                },
            },
        )

        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["scanner_blocker_count"], 0)
        self.assertEqual(state["criteria"][0]["status"], "partial")
        self.assertIn("DEC-CRIT-SCANNER", state["criteria"][0]["reason"])

    def test_process_approved_row_waiver_clears_hard_scanner_blocker_without_passing(self) -> None:
        process_tab = load_script_module(
            "process_tab_for_row_waiver_rollup",
            REPO_ROOT / "scripts" / "process" / "process_tab.py",
        )

        state = process_tab._compute_gate_state(
            {
                "id": "GATE-TEST",
                "required_roles": [],
                "criteria": [
                    {
                        "id": "CRIT-SCANNER",
                        "title": "Scanner mapped row",
                        "required": True,
                        "evidence": [
                            {
                                "type": "ruleset_row",
                                "ref": "ASVS:v5.0.0-7.1.1",
                                "label": "ASVS v5.0.0-7.1.1",
                                "required": True,
                            }
                        ],
                    }
                ],
            },
            role_lookup={},
            target_dir=None,
            fr_catalog=None,
            fr_evidence={},
            target_evidence={},
            resolved_status={
                "row_by_id": {
                    "ASVS:v5.0.0-7.1.1": {
                        "id": "ASVS:v5.0.0-7.1.1",
                        "status": "waived",
                        "scanner_blockers": [
                            {
                                "tool": "semgrep",
                                "mapping_id": "SCM-SEMGREP-ASVS-7-JWT",
                                "source_locator": "src/auth.js:12",
                            }
                        ],
                    }
                },
                "fr_by_id": {},
                "tbt_by_id": {},
                "rows_by_fr": {},
                "rows_by_tbt": {},
            },
        )

        self.assertEqual(state["status"], "manual")
        self.assertEqual(state["scanner_blocker_count"], 0)
        self.assertEqual(state["criteria"][0]["status"], "manual")

    def test_framework_graph_gate_nodes_inherit_scanner_blocker_status(self) -> None:
        from fr.graph import build_graph_data

        class Framework:
            roles: list[dict] = []
            processes = [
                {
                    "id": "PROC-TEST",
                    "title": "Test process",
                    "gates": [
                        {
                            "id": "GATE-TEST",
                            "title": "Test gate",
                            "criteria": [
                                {
                                    "id": "CRIT-SCANNER",
                                    "title": "Scanner mapped row",
                                    "required": True,
                                    "requirements": [
                                        {
                                            "type": "ruleset_row",
                                            "ruleset": "ASVS",
                                            "row": "v5.0.0-7.1.1",
                                            "required": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]

        graph = build_graph_data(
            None,
            assurance_framework=Framework(),
            assurance_status={
                "compliance_rows": [
                    {
                        "id": "ASVS:v5.0.0-7.1.1",
                        "status": "failed",
                        "scanner_blockers": [
                            {
                                "tool": "semgrep",
                                "mapping_id": "SCM-SEMGREP-ASVS-7-JWT",
                                "source_locator": "src/auth.js:12",
                            }
                        ],
                    }
                ],
                "frs": [],
                "tbts": [],
            },
            scanner_compliance_packs=[],
        )

        gate = next(node for node in graph["nodes"] if node["id"] == "gate:PROC-TEST:GATE-TEST")
        criterion = next(node for node in graph["nodes"] if node["id"] == "criterion:PROC-TEST:GATE-TEST:CRIT-SCANNER")
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(criterion["status"], "failed")
        self.assertEqual(gate["scanner_blocker_count"], 1)

    def test_framework_graph_gate_decision_overrides_scanner_blocker_as_partial(self) -> None:
        from fr.graph import build_graph_data

        class Framework:
            roles: list[dict] = []
            processes = [
                {
                    "id": "PROC-TEST",
                    "title": "Test process",
                    "gates": [
                        {
                            "id": "GATE-TEST",
                            "title": "Test gate",
                            "criteria": [
                                {
                                    "id": "CRIT-SCANNER",
                                    "title": "Scanner mapped row",
                                    "required": True,
                                    "requirements": [
                                        {
                                            "type": "ruleset_row",
                                            "ruleset": "ASVS",
                                            "row": "v5.0.0-7.1.1",
                                            "required": True,
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]

        graph = build_graph_data(
            None,
            assurance_framework=Framework(),
            assurance_instance={
                "decisions": [
                    {
                        "id": "DEC-CRIT-SCANNER",
                        "gate": "GATE-TEST",
                        "criterion": "CRIT-SCANNER",
                        "readiness_status": "partial",
                    }
                ]
            },
            assurance_status={
                "compliance_rows": [
                    {
                        "id": "ASVS:v5.0.0-7.1.1",
                        "status": "failed",
                        "scanner_blockers": [
                            {
                                "tool": "semgrep",
                                "mapping_id": "SCM-SEMGREP-ASVS-7-JWT",
                                "source_locator": "src/auth.js:12",
                            }
                        ],
                    }
                ],
                "frs": [],
                "tbts": [],
            },
            scanner_compliance_packs=[],
        )

        gate = next(node for node in graph["nodes"] if node["id"] == "gate:PROC-TEST:GATE-TEST")
        criterion = next(node for node in graph["nodes"] if node["id"] == "criterion:PROC-TEST:GATE-TEST:CRIT-SCANNER")
        self.assertEqual(gate["status"], "partial")
        self.assertEqual(criterion["status"], "partial")
        self.assertEqual(criterion["decision"]["id"], "DEC-CRIT-SCANNER")
        self.assertEqual(gate["scanner_blocker_count"], 0)

    def test_graph_groups_unmapped_scanner_findings_without_compliance_edges(self) -> None:
        load_fr_catalog = load_script_module(
            "load_fr_catalog_for_unmapped_graph",
            REPO_ROOT / "scripts" / "load_fr_catalog.py",
        )
        from fr.graph import build_graph_data

        unmapped_finding = {
            "scanner": "semgrep",
            "rule_id": "unmapped.rule",
            "ruleId": "unmapped.rule",
            "location": "src/other.py:99",
            "message": "General scanner finding with no accepted compliance mapping",
            "path": "src/other.py",
        }
        graph = build_graph_data(
            load_fr_catalog.load_fr_catalog(FR_CATALOG),
            evidence_bundle=json.loads(EVIDENCE_BUNDLE.read_text()),
            scanner_findings=[unmapped_finding],
            scanner_compliance_packs=[json.loads(SCANNER_COMPLIANCE_MAPPING_PACK.read_text())],
        )

        general_nodes = [
            node for node in graph["nodes"]
            if node["id"] == "evidence:scanner-general:semgrep"
        ]
        self.assertEqual(len(general_nodes), 1)
        self.assertEqual(general_nodes[0]["mapping_level"], "general_finding")
        self.assertEqual(general_nodes[0]["traceability_strength"], "unmapped")
        self.assertEqual(general_nodes[0]["matched_finding_count"], 1)
        self.assertEqual(general_nodes[0]["source_locator"], "src/other.py:99")
        self.assertFalse(
            [
                edge for edge in graph["edges"]
                if edge["source"] == "evidence:scanner-general:semgrep"
                or edge["target"] == "evidence:scanner-general:semgrep"
            ]
        )

    def test_graph_materializes_assurance_control_and_decision_audit_nodes(self) -> None:
        load_fr_catalog = load_script_module(
            "load_fr_catalog_for_control_graph",
            REPO_ROOT / "scripts" / "load_fr_catalog.py",
        )
        from fr.graph import build_graph_data

        graph = build_graph_data(
            load_fr_catalog.load_fr_catalog(FR_CATALOG),
            evidence_bundle=json.loads(EVIDENCE_BUNDLE.read_text()),
            assurance_instance=json.loads(ASSURANCE_INSTANCE.read_text()),
        )
        nodes = {node["id"]: node for node in graph["nodes"]}
        edges = {(edge["source"], edge["target"], edge["type"]) for edge in graph["edges"]}

        waiver = nodes["waiver:WVR-FR016-A-TIMEBOX"]
        self.assertEqual(waiver["type"], "waiver")
        self.assertEqual(waiver["status"], "approved")
        self.assertEqual(waiver["status_effect"], "waived")
        self.assertEqual(waiver["signature_ref"], "SIG-WVR-FR016-A")
        self.assertIn(("waiver:WVR-FR016-A-TIMEBOX", "test:TBT-016-ASVS-A", "applies_to"), edges)

        control = nodes["compensating-control:CMP-FR016-SESSION-MONITORING"]
        self.assertEqual(control["type"], "compensating_control")
        self.assertEqual(control["status"], "pending")
        self.assertEqual(control["status_effect"], "compensating_control")
        self.assertIn(
            ("compensating-control:CMP-FR016-SESSION-MONITORING", "fr:FR-016", "applies_to"),
            edges,
        )

        decision = nodes["decision:DEC-GATE-03-ATT-FR016"]
        self.assertEqual(decision["type"], "decision")
        self.assertEqual(decision["readiness_status"], "partial")
        self.assertEqual(decision["decision_ref"], "DECISION-123")
        self.assertIn(("decision:DEC-GATE-03-ATT-FR016", "approval:DECISION-123", "approved_by"), edges)

    def test_graph_materializes_planning_artifacts_and_blueprint_lineage(self) -> None:
        scripts_dir = str(REPO_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from fr.graph import build_graph_data

        blueprint_hash = "sha256:" + "1" * 64
        catalog = SimpleNamespace(
            frs=[
                {
                    "id": "FR-016",
                    "title": "Session timeout and re-authentication",
                    "description": "Session controls are required.",
                    "status": "in_scope",
                    "lifecycle_status": "in_scope",
                    "derived_from": {
                        "source_type": "blueprint_fr",
                        "source_id": "security-core",
                        "source_version": "asvs-5.0.0",
                        "source_path": "data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json",
                        "source_hash": blueprint_hash,
                        "source_item": "FR-BP-ASVS-SESSION-MANAGEMENT-001",
                        "review_status": "accepted",
                    },
                }
            ],
            tbts=[
                {
                    "id": "TBT-016-ASVS-A",
                    "title": "Expired JWT rejection for FR-016",
                    "type": "integration",
                    "proves": ["FR-016"],
                    "lifecycle_status": "planned",
                    "expected_evidence": [{"type": "test_result", "required": True}],
                    "derived_from": {
                        "source_type": "blueprint_tbt",
                        "source_id": "security-core",
                        "source_version": "asvs-5.0.0",
                        "source_path": "data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json",
                        "source_hash": blueprint_hash,
                        "source_item": "TBT-BP-ASVS-SESSION-MANAGEMENT-001-A",
                        "review_status": "accepted",
                    },
                    "compliance": [
                        {"ruleset": "ASVS", "row": "v5.0.0-7.1.1"}
                    ],
                }
            ],
            scope={"frameworks": []},
        )
        graph_manifest = {
            "planning_artifacts": {
                "commitments": [
                    {
                        "path": "data/blueprints/security-core/asvs-5.0.0/fr-catalog.blueprint.json",
                        "role": "blueprint_selection_proposal",
                        "label": "Security core blueprint catalog",
                        "sha256": blueprint_hash,
                        "bytes": 1234,
                        "schema": "fr_catalog",
                        "status": "accepted",
                        "freeze_mode": "content_hash",
                        "immutable": True,
                    }
                ]
            }
        }

        graph = build_graph_data(catalog, graph_manifest=graph_manifest)
        nodes = {node["id"]: node for node in graph["nodes"]}
        edges = {(edge["source"], edge["target"], edge["type"]) for edge in graph["edges"]}

        self.assertEqual(nodes["planning:blueprint_selection_proposal:1111111111111111"]["type"], "planning_artifact")
        self.assertEqual(nodes["blueprint:FR-BP-ASVS-SESSION-MANAGEMENT-001"]["type"], "blueprint")
        self.assertEqual(nodes["blueprint:TBT-BP-ASVS-SESSION-MANAGEMENT-001-A"]["type"], "blueprint")
        self.assertIn(("blueprint:FR-BP-ASVS-SESSION-MANAGEMENT-001", "fr:FR-016", "derived_from"), edges)
        self.assertIn(("blueprint:TBT-BP-ASVS-SESSION-MANAGEMENT-001-A", "test:TBT-016-ASVS-A", "derived_from"), edges)
        self.assertIn(
            (
                "planning:blueprint_selection_proposal:1111111111111111",
                "blueprint:FR-BP-ASVS-SESSION-MANAGEMENT-001",
                "derived_from",
            ),
            edges,
        )

    def test_dashboard_payload_validation_accepts_lineage_node_types(self) -> None:
        load_target_artifacts = load_script_module(
            "load_target_artifacts_for_lineage_payload",
            REPO_ROOT / "scripts" / "load_target_artifacts.py",
        )
        payload = {
            "schema_version": 1,
            "project": "demo",
            "generated_at": "2026-07-09T00:00:00Z",
            "inputs": {},
            "summary": {},
            "graph": {
                "nodes": [
                    {"id": "fr:FR-001", "type": "fr", "label": "FR-001", "status": "in_scope"},
                    {"id": "blueprint:FR-BP-001", "type": "blueprint", "label": "FR-BP-001"},
                    {
                        "id": "planning:blueprint_decision_log:abc123",
                        "type": "planning_artifact",
                        "label": "Blueprint decision log",
                    },
                ],
                "edges": [
                    {"source": "fr:FR-001", "target": "blueprint:FR-BP-001", "type": "derived_from"},
                    {
                        "source": "blueprint:FR-BP-001",
                        "target": "planning:blueprint_decision_log:abc123",
                        "type": "derived_from",
                    },
                ],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dashboard-payload.json"
            path.write_text(json.dumps(payload))
            artifact = load_target_artifacts.load_target_artifact(path, "dashboard_payload")

        self.assertEqual(artifact.raw["graph"]["nodes"][1]["type"], "blueprint")

    def test_dashboard_runtime_assets_are_required_source_files(self) -> None:
        dashboard_assets = load_script_module(
            "dashboard_assets_for_test",
            REPO_ROOT / "scripts" / "dashboard" / "assets.py",
        )

        graph_runtime = dashboard_assets.load_dashboard_asset("10-graph-runtime.js")
        interactions_runtime = dashboard_assets.load_dashboard_asset("20-dashboard-interactions.js")

        self.assertIn("function setupGraph()", graph_runtime)
        self.assertIn("scannerImpactGraph", graph_runtime)
        self.assertIn("scannerUnmappedGraph", graph_runtime)
        self.assertIn("Waiver audit record", graph_runtime)
        self.assertIn("Compensating control audit record", graph_runtime)
        self.assertIn("Decision audit record", graph_runtime)
        self.assertIn("function showPanel", interactions_runtime)
        self.assertIn("setupReviewBoard()", interactions_runtime)

    def test_graph_projection_derives_dashboard_summaries_from_graph(self) -> None:
        projection = load_script_module(
            "graph_projection_for_test",
            REPO_ROOT / "scripts" / "graph_projection.py",
        )
        graph = {
            "nodes": [
                {"id": "fr:FR-001", "type": "fr", "status": "passed"},
                {"id": "ghost:fr:ASVS:v5.0.0-1.1.1", "type": "fr", "status": "missing", "metadata": {"ghost": True}},
                {"id": "test:TBT-001", "type": "tbt", "status": "passed"},
                {"id": "ghost:test:ASVS:v5.0.0-1.1.1", "type": "tbt", "status": "missing", "metadata": {"ghost": True}},
                {
                    "id": "evidence:EVD-001",
                    "type": "evidence",
                    "status": "passed",
                    "metadata": {
                        "evidence_type": "test_result",
                        "source": "reports/junit.xml",
                        "evidence_strength": "strong",
                    },
                },
                {
                    "id": "evidence:scanner-blocker:semgrep:1",
                    "type": "evidence",
                    "status": "failed",
                    "evidence_type": "scanner_result",
                    "scanner": "semgrep",
                    "mapping_level": "compliance_row",
                    "evidence_role": "blocking_if_finding",
                    "ruleset": "ASVS",
                    "row": "v5.0.0-1.1.1",
                    "ref": "SCM-SEMGREP-ASVS-1",
                    "source_locator": "src/app.py:12",
                    "matched_finding_count": 1,
                },
                {
                    "id": "evidence:scanner-supporting:semgrep:2",
                    "type": "evidence",
                    "status": "passed",
                    "evidence_type": "scanner_result",
                    "scanner": "semgrep",
                    "mapping_level": "compliance_row",
                    "evidence_role": "supporting",
                    "ruleset": "ASVS",
                    "row": "v5.0.0-1.1.1",
                    "ref": "SCM-SEMGREP-ASVS-1-SUPPORT",
                    "source_locator": "src/session.py:4",
                    "matched_finding_count": 0,
                },
                {
                    "id": "evidence:scanner-general:gitleaks",
                    "type": "evidence",
                    "status": "manual_review",
                    "evidence_type": "scanner_result",
                    "scanner": "gitleaks",
                    "mapping_level": "general_finding",
                    "traceability_strength": "unmapped",
                },
                {
                    "id": "ASVS:v5.0.0-1.1.1",
                    "type": "ruleset_row",
                    "status": "failed",
                    "ruleset": "ASVS",
                    "row": "v5.0.0-1.1.1",
                    "chapter": "1",
                    "frs": ["FR-001"],
                    "tbts": ["TBT-001"],
                    "scanner_blockers": [{"tool": "semgrep", "mapping_id": "SCM-SEMGREP-ASVS-1"}],
                    "reasons": ["scanner blocker: semgrep"],
                },
                {"id": "gate:GATE-001", "type": "gate", "status": "blocked"},
                {"id": "waiver:WVR-001", "type": "waiver", "status": "approved"},
                {
                    "id": "blueprint:FR-BP-ASVS-SESSION-MANAGEMENT-001",
                    "type": "blueprint",
                    "source_type": "blueprint_fr",
                    "source_version": "asvs-5.0.0",
                },
                {
                    "id": "planning:blueprint_decision_log:abc123",
                    "type": "planning_artifact",
                    "role": "blueprint_decision_log",
                    "path": "blueprint-decisions.json",
                    "sha256": "sha256:" + "a" * 64,
                    "schema": "blueprint_decision_log",
                    "artifact_status": "accepted",
                },
            ],
            "edges": [
                {"source": "fr:FR-001", "target": "test:TBT-001", "type": "requires"},
                {"source": "test:TBT-001", "target": "evidence:EVD-001", "type": "evidences"},
                {"source": "fr:FR-001", "target": "blueprint:FR-BP-ASVS-SESSION-MANAGEMENT-001", "type": "derived_from"},
                {"source": "blueprint:FR-BP-ASVS-SESSION-MANAGEMENT-001", "target": "planning:blueprint_decision_log:abc123", "type": "derived_from"},
            ],
        }

        result = projection.graph_projections(graph)

        self.assertEqual(result["overview"]["node_count"], 13)
        self.assertEqual(result["overview"]["edge_type_counts"]["evidences"], 1)
        self.assertEqual(result["overview"]["edge_type_counts"]["derived_from"], 2)
        self.assertEqual(result["project_frs"]["source"], "runtime_graph")
        self.assertEqual(result["project_frs"]["fr_count"], 1)
        self.assertEqual(result["project_frs"]["tbt_count"], 1)
        self.assertEqual(result["project_frs"]["missing_fr_gap_count"], 1)
        self.assertEqual(result["project_frs"]["missing_tbt_gap_count"], 1)
        self.assertEqual(result["project_frs"]["scanner_evidence_count"], 3)
        self.assertEqual(result["project_frs"]["scanner_direct_blocker_count"], 1)
        self.assertEqual(result["project_frs"]["scanner_unmapped_inventory_count"], 1)
        self.assertEqual(result["scanner_evidence"]["scanner_evidence_count"], 3)
        self.assertEqual(result["scanner_evidence"]["direct_blocker_count"], 1)
        asvs_rows = result["rulesets"]["rulesets"]["ASVS"]["rows"]
        asvs_row = next(row for row in asvs_rows if row["row"] == "v5.0.0-1.1.1")
        self.assertEqual(asvs_row["scanner_evidence_count"], 2)
        self.assertEqual(asvs_row["scanner_blocker_count"], 1)
        self.assertEqual(result["scanner_evidence"]["unmapped_inventory_count"], 1)
        self.assertEqual(result["scanner_evidence"]["scanner_counts"], {"gitleaks": 1, "semgrep": 2})
        self.assertEqual(result["scanner_evidence"]["direct_blockers"][0]["mapping_id"], "SCM-SEMGREP-ASVS-1")
        self.assertEqual(result["rulesets"]["source"], "runtime_graph")
        self.assertEqual(result["rulesets"]["ruleset_count"], 1)
        self.assertEqual(result["rulesets"]["rulesets"]["ASVS"]["row_count"], 1)
        self.assertEqual(result["rulesets"]["rulesets"]["ASVS"]["ui_state_counts"]["failed"], 1)
        self.assertEqual(result["rulesets"]["rulesets"]["ASVS"]["scanner_blocker_count"], 1)
        self.assertEqual(result["evidence_files"]["source"], "runtime_graph")
        self.assertEqual(result["evidence_files"]["evidence_count"], 4)
        self.assertEqual(result["evidence_files"]["scanner_evidence_count"], 3)
        self.assertEqual(result["evidence_files"]["test_result_count"], 1)
        self.assertEqual(result["evidence_files"]["artifact_refs"][0]["ref"], "reports/junit.xml")
        self.assertEqual(result["assurance"]["node_counts"]["gate"], 1)
        self.assertEqual(result["assurance"]["node_counts"]["waiver"], 1)
        self.assertEqual(result["lineage"]["planning_artifact_count"], 1)
        self.assertEqual(result["lineage"]["blueprint_node_count"], 1)
        self.assertEqual(result["lineage"]["project_to_blueprint_edge_count"], 1)
        self.assertEqual(result["lineage"]["blueprint_to_planning_edge_count"], 1)
        self.assertEqual(result["lineage"]["planning_role_counts"], {"blueprint_decision_log": 1})

    def test_evidence_files_page_renders_graph_projection_when_available(self) -> None:
        dashboard = load_script_module(
            "generate_dashboard_for_evidence_projection",
            REPO_ROOT / "scripts" / "generate_dashboard.py",
        )
        evidence_manifest = {
            "evidence_files": [
                {
                    "file": "reports/junit.xml",
                    "bytes": 128,
                    "sha256": "a" * 64,
                }
            ]
        }
        evidence_view = {
            "source": "runtime_graph",
            "evidence_count": 2,
            "scanner_evidence_count": 1,
            "test_result_count": 1,
            "artifact_ref_count": 2,
            "artifact_refs": [
                {
                    "node_id": "evidence:EVD-TBT-001",
                    "ref": "reports/junit.xml",
                    "source": "reports/junit.xml",
                    "evidence_type": "test_result",
                    "status": "passed",
                    "ruleset": "ASVS",
                    "row": "v5.0.0-7.1.1",
                },
                {
                    "node_id": "evidence:scanner-general:gitleaks",
                    "ref": "reports/gitleaks.json",
                    "source": "reports/gitleaks.json",
                    "evidence_type": "scanner_result",
                    "status": "failed",
                    "scanner": "gitleaks",
                },
            ],
        }

        html = dashboard.render_coverage(evidence_manifest, REPO_ROOT, evidence_view)

        self.assertIn("Evidence nodes", html)
        self.assertIn("evidence:EVD-TBT-001", html)
        self.assertIn("ASVS v5.0.0-7.1.1", html)
        self.assertIn("gitleaks", html)
        self.assertIn("aaaaaaaaaaaa", html)

    def test_framework_tab_renders_ruleset_graph_projection_when_available(self) -> None:
        framework_tab = load_script_module(
            "framework_tab_for_ruleset_projection",
            REPO_ROOT / "scripts" / "fr" / "framework_tab.py",
        )
        catalog = SimpleNamespace(
            scope={"ASVS": {}},
            frs=[],
            tbts=[],
            na_rows=[],
        )
        ruleset_projection = {
            "source": "runtime_graph",
            "rows": [
                {
                    "row": "v5.0.0-1.1.1",
                    "status": "failed",
                    "ui_state": "failed",
                    "frs": ["FR-001"],
                    "tbts": ["TBT-001"],
                    "reasons": ["scanner blocker: semgrep"],
                    "scanner_blockers": [
                        {
                            "tool": "semgrep",
                            "mapping_id": "SCM-SEMGREP-ASVS-1",
                            "status": "failed",
                            "rule_id": "auth.jwt",
                            "message": "JWT issue",
                        }
                    ],
                    "scanner_evidence": [
                        {
                            "tool": "semgrep",
                            "mapping_id": "SCM-SEMGREP-ASVS-1",
                            "status": "failed",
                            "rule_id": "auth.jwt",
                            "message": "JWT issue",
                            "assurance_effect": "blocking_if_finding",
                            "strength": "strong",
                            "blocks_compliance": True,
                        },
                        {
                            "tool": "semgrep",
                            "mapping_id": "SCM-SEMGREP-ASVS-1-SUPPORT",
                            "status": "passed",
                            "rule_id": "auth.session",
                            "message": "No matching session finding",
                            "assurance_effect": "supporting",
                            "strength": "supporting",
                            "blocks_compliance": False,
                        },
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            html = framework_tab.render_framework_tab(
                "ASVS",
                catalog,
                Path(tmp),
                ruleset_projection=ruleset_projection,
            )

        self.assertIn("runtime graph projection", html)
        self.assertIn("FR-001", html)
        self.assertIn("TBT-001", html)
        self.assertIn("scanner blocker: semgrep", html)
        self.assertIn("SCM-SEMGREP-ASVS-1", html)
        self.assertIn("Mapped scanner evidence", html)
        self.assertIn("SCM-SEMGREP-ASVS-1-SUPPORT", html)
        self.assertIn("supporting", html)

    def test_artifact_hashing_uses_canonical_json_and_stable_sidecars(self) -> None:
        hashing = load_script_module(
            "artifact_hashing_for_test",
            REPO_ROOT / "scripts" / "artifact_hashing.py",
        )
        left = {"b": [2, 1], "a": {"z": True}}
        right = {"a": {"z": True}, "b": [2, 1]}

        self.assertEqual(hashing.canonical_json_bytes(left), hashing.canonical_json_bytes(right))
        self.assertEqual(
            hashing.canonical_json_sha256(left),
            hashing.canonical_json_sha256(right),
        )
        self.assertTrue(hashing.canonical_json_sha256(left).startswith("sha256:"))
        self.assertEqual(
            hashing.report_hash_filename(Path("generated-tests/VG_TEST_FRAMEWORK/manifest.json")),
            "generated-tests__VG_TEST_FRAMEWORK__manifest.json.sha256",
        )

    def test_graph_manifest_freezes_accepted_config_by_content_hash(self) -> None:
        dashboard = load_script_module(
            "generate_dashboard_for_config_commitment_test",
            REPO_ROOT / "scripts" / "generate_dashboard.py",
        )
        hashing = load_script_module(
            "artifact_hashing_for_config_commitment_test",
            REPO_ROOT / "scripts" / "artifact_hashing.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            fr_catalog = report_dir / "fr-catalog.snapshot.json"
            fr_catalog.write_text(json.dumps({
                "schema_version": 1,
                "project": "demo",
                "scope": {"frameworks": []},
                "frs": [],
                "tbts": [
                    {
                        "id": "TBT-001",
                        "title": "Reviewed test basis",
                        "metadata": {
                            "config_update_review": {
                                "review_status": "accepted",
                                "reviewed_by": "assurance-reviewer",
                                "signature_ref": "SIG-TBT-001",
                            }
                        },
                    }
                ],
            }))
            expected_fr_hash = hashing.file_sha256(fr_catalog, prefixed=True)
            blueprint_decisions = report_dir / "blueprint-decisions.json"
            blueprint_decisions.write_text(json.dumps({
                "schema_version": 1,
                "id": "BLUEPRINT-DECISIONS-demo",
                "project": "demo",
                "proposal": "BLUEPRINT-PROPOSAL-demo",
                "decisions": [
                    {
                        "candidate": "CANDIDATE-FR-BP-ASVS-SESSION-MANAGEMENT-001",
                        "decision": "accepted_as_is",
                        "reviewed_by": "assurance-reviewer",
                        "reason": "Accepted session-management blueprint.",
                    }
                ],
            }))
            expected_planning_hash = hashing.file_sha256(blueprint_decisions, prefixed=True)
            (report_dir / "dashboard-payload.json").write_text(json.dumps({
                "schema_version": 1,
                "project": "demo",
                "generated_at": "2026-07-09T00:00:00Z",
                "inputs": {},
                "summary": {"run_id": "run-1"},
                "graph": {"nodes": [], "edges": []},
            }))
            (report_dir / "evidence-bundle.json").write_text(json.dumps({"schema_version": 1, "project": "demo", "evidence": []}))
            (report_dir / "evidence-manifest.json").write_text(json.dumps({
                "evidence_files": [],
                "run_id": "run-1",
                "tools": {"semgrep": {"image": "semgrep:local", "level": 1}},
                "scanner_health": {"semgrep": {"status": "PASS", "reason": "0 findings"}},
                "test_evidence": {"junit": {"present": True, "tests": 1, "failures": 0}},
            }))

            dashboard.write_graph_manifest(
                report_dir,
                json.loads((report_dir / "dashboard-payload.json").read_text()),
                fr_catalog_path=fr_catalog,
                planning_artifact_paths=[blueprint_decisions],
                evidence_manifest=json.loads((report_dir / "evidence-manifest.json").read_text()),
            )
            manifest = json.loads((report_dir / "graph-manifest.json").read_text())

        commitment = manifest["accepted_config"]["commitments"][0]
        self.assertEqual(commitment["role"], "fr_catalog")
        self.assertEqual(commitment["sha256"], expected_fr_hash)
        self.assertTrue(commitment["freeze"]["immutable"])
        self.assertEqual(commitment["review_summary"]["review_status_counts"], {"accepted": 1})
        self.assertEqual(commitment["review_summary"]["reviewers"], ["assurance-reviewer"])
        self.assertEqual(commitment["review_summary"]["signature_refs"], ["SIG-TBT-001"])
        self.assertEqual(
            manifest["commitments"]["accepted_config_hash"],
            hashing.canonical_json_sha256(manifest["accepted_config"]),
        )
        planning_commitment = manifest["planning_artifacts"]["commitments"][0]
        self.assertEqual(planning_commitment["role"], "blueprint_decision_log")
        self.assertEqual(planning_commitment["sha256"], expected_planning_hash)
        self.assertEqual(
            manifest["commitments"]["planning_artifacts_hash"],
            hashing.canonical_json_sha256(manifest["planning_artifacts"]),
        )
        self.assertEqual(manifest["supported_claims"], ["fr_satisfied", "tbt_satisfied", "compliance_row_satisfied"])
        self.assertEqual(manifest["toolchain"]["scanners"][0]["name"], "semgrep")
        self.assertEqual(manifest["toolchain"]["test_runners"][0]["name"], "junit")
        unsupported = {
            item["claim"]: item["missing_config_roles"]
            for item in manifest["claim_readiness"]["unsupported"]
        }
        self.assertEqual(unsupported["no_blocking_scanner_evidence"], ["scanner_compliance_mapping_pack"])
        self.assertEqual(unsupported["selected_scope_satisfied"], ["assurance_framework"])

    def test_graph_claim_readiness_requires_committed_scanner_mapping_pack(self) -> None:
        dashboard = load_script_module(
            "generate_dashboard_for_claim_readiness_test",
            REPO_ROOT / "scripts" / "generate_dashboard.py",
        )

        without_scanner = dashboard.graph_claim_readiness([
            {"role": "fr_catalog"},
            {"role": "assurance_framework"},
        ])
        with_scanner = dashboard.graph_claim_readiness([
            {"role": "fr_catalog"},
            {"role": "assurance_framework"},
            {"role": "scanner_compliance_mapping_pack"},
        ])

        self.assertNotIn("no_blocking_scanner_evidence", without_scanner["supported"])
        self.assertIn("no_blocking_scanner_evidence", with_scanner["supported"])

    def test_export_assurance_claim_emits_hash_bound_satisfied_tbt_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "graph-manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "mode": "graph_proof_manifest",
                "project": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-09T00:00:00Z",
                "graph": {"node_count": 2, "edge_count": 1, "root_hash": "sha256:" + "a" * 64},
                "artifacts": {"report": [], "config": []},
                "accepted_config": {"policy": "runtime_config_is_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "planning_artifacts": {"policy": "planning_artifacts_are_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "claim_readiness": {"policy": "claims_require_committed_runtime_config", "supported": ["tbt_satisfied"], "unsupported": []},
                "supported_claims": ["tbt_satisfied"],
                "commitments": {
                    "dashboard_payload_hash": "sha256:" + "b" * 64,
                    "evidence_bundle_hash": "sha256:" + "c" * 64,
                    "evidence_manifest_hash": "sha256:" + "d" * 64,
                    "accepted_config_hash": "sha256:" + "e" * 64,
                    "planning_artifacts_hash": "sha256:442730135fb2e63f1e4b4388deee1eeabe67127968ea3bc163b7db52130e3f44",
                    "graph_root_hash": "sha256:" + "a" * 64,
                },
            }))
            (report_dir / "dashboard-payload.json").write_text(json.dumps({
                "schema_version": 1,
                "project": "demo",
                "generated_at": "2026-07-09T00:00:00Z",
                "inputs": {},
                "summary": {"run_id": "run-1"},
                "graph": {
                    "nodes": [
                        {
                            "id": "test:TBT-001",
                            "type": "tbt",
                            "label": "Test basis",
                            "status": "passed",
                            "metadata": {"reasons": ["TBT-001 has sufficient passing evidence."]},
                        },
                        {
                            "id": "evidence:EVD-TBT-001",
                            "type": "evidence",
                            "label": "Evidence",
                            "status": "passed",
                            "metadata": {"ref": "EVD-TBT-001"},
                        },
                    ],
                    "edges": [
                        {"source": "test:TBT-001", "target": "evidence:EVD-TBT-001", "type": "evidences"}
                    ],
                },
            }))
            out_path = report_dir / "claim.json"
            result = run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(out_path),
            )
            claim = json.loads(out_path.read_text())

        self.assertIn("claim: satisfied tbt_satisfied TBT-001", result.stdout)
        self.assertEqual(claim["claim_result"], "satisfied")
        self.assertEqual(claim["evaluation"]["evidence_refs"], ["EVD-TBT-001"])
        self.assertEqual(claim["public_inputs"]["graph_root_hash"], "sha256:" + "a" * 64)

    def test_claim_evaluation_keeps_tbt_pass_but_fr_blocked_by_direct_scanner_evidence(self) -> None:
        claims = load_script_module(
            "assurance_claims_for_scanner_blocker_test",
            REPO_ROOT / "scripts" / "assurance_claims.py",
        )
        graph = {
            "nodes": [
                {"id": "fr:FR-016", "type": "fr", "status": "passed"},
                {"id": "test:TBT-016-ASVS-A", "type": "tbt", "status": "passed"},
                {
                    "id": "ASVS:v5.0.0-7.1.1",
                    "type": "compliance",
                    "status": "failed",
                    "scanner_blockers": [
                        {
                            "tool": "semgrep",
                            "mapping_id": "SCM-SEMGREP-ASVS-7-JWT",
                            "source_locator": "src/auth/session.js:12",
                        }
                    ],
                },
                {
                    "id": "evidence:EVD-TBT-016-ASVS-A",
                    "type": "evidence",
                    "status": "passed",
                    "metadata": {"ref": "EVD-TBT-016-ASVS-A"},
                },
                {
                    "id": "evidence:scanner:semgrep:SCM-SEMGREP-ASVS-7-JWT:ASVS:v5.0.0-7.1.1",
                    "type": "evidence",
                    "status": "failed",
                    "evidence_type": "scanner_result",
                    "scanner": "semgrep",
                    "mapping_level": "compliance_row",
                    "evidence_role": "blocking_if_finding",
                    "ref": "SCM-SEMGREP-ASVS-7-JWT",
                },
            ],
            "edges": [
                {"source": "fr:FR-016", "target": "test:TBT-016-ASVS-A", "type": "verified_by"},
                {"source": "test:TBT-016-ASVS-A", "target": "evidence:EVD-TBT-016-ASVS-A", "type": "evidenced_by"},
                {"source": "ASVS:v5.0.0-7.1.1", "target": "fr:FR-016", "type": "satisfies"},
                {"source": "ASVS:v5.0.0-7.1.1", "target": "evidence:scanner:semgrep:SCM-SEMGREP-ASVS-7-JWT:ASVS:v5.0.0-7.1.1", "type": "evidenced_by"},
            ],
        }

        tbt_claim = claims.evaluate_claim(graph, "tbt_satisfied", "TBT-016-ASVS-A")
        fr_claim = claims.evaluate_claim(graph, "fr_satisfied", "FR-016")
        row_claim = claims.evaluate_claim(graph, "compliance_row_satisfied", "ASVS:v5.0.0-7.1.1")
        no_blocking_claim = claims.evaluate_claim(graph, "no_blocking_scanner_evidence", "FR-016")

        self.assertTrue(tbt_claim["satisfied"])
        self.assertEqual(tbt_claim["scanner_blockers"], [])
        self.assertFalse(fr_claim["satisfied"])
        self.assertEqual(fr_claim["target_status"], "passed")
        self.assertEqual(fr_claim["scanner_blockers"], ["ASVS:v5.0.0-7.1.1:SCM-SEMGREP-ASVS-7-JWT"])
        self.assertIn("Direct scanner blockers", " ".join(fr_claim["reasons"]))
        self.assertFalse(row_claim["satisfied"])
        self.assertEqual(row_claim["scanner_blockers"], ["SCM-SEMGREP-ASVS-7-JWT"])
        self.assertFalse(no_blocking_claim["satisfied"])
        self.assertEqual(no_blocking_claim["scanner_blockers"], ["ASVS:v5.0.0-7.1.1:SCM-SEMGREP-ASVS-7-JWT"])

    def test_export_assurance_claim_refuses_unsupported_claim_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "graph-manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "mode": "graph_proof_manifest",
                "project": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-09T00:00:00Z",
                "graph": {"node_count": 0, "edge_count": 0, "root_hash": "sha256:" + "a" * 64},
                "artifacts": {"report": [], "config": []},
                "accepted_config": {"policy": "runtime_config_is_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "planning_artifacts": {"policy": "planning_artifacts_are_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "claim_readiness": {
                    "policy": "claims_require_committed_runtime_config",
                    "supported": ["tbt_satisfied"],
                    "unsupported": [{"claim": "no_blocking_scanner_evidence", "missing_config_roles": ["scanner_compliance_mapping_pack"]}],
                },
                "supported_claims": ["tbt_satisfied"],
                "commitments": {
                    "dashboard_payload_hash": "sha256:" + "b" * 64,
                    "evidence_bundle_hash": "sha256:" + "c" * 64,
                    "evidence_manifest_hash": "sha256:" + "d" * 64,
                    "accepted_config_hash": "sha256:" + "e" * 64,
                    "planning_artifacts_hash": "sha256:442730135fb2e63f1e4b4388deee1eeabe67127968ea3bc163b7db52130e3f44",
                    "graph_root_hash": "sha256:" + "a" * 64,
                },
            }))
            (report_dir / "dashboard-payload.json").write_text(json.dumps({
                "schema_version": 1,
                "project": "demo",
                "generated_at": "2026-07-09T00:00:00Z",
                "inputs": {},
                "summary": {"run_id": "run-1"},
                "graph": {"nodes": [], "edges": []},
            }))
            result = run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "no_blocking_scanner_evidence",
                "--target",
                "ASVS:v5.0.0-7.1.1",
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported claim type", result.stderr)

    def test_verify_assurance_claim_recomputes_and_catches_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "graph-manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "mode": "graph_proof_manifest",
                "project": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-09T00:00:00Z",
                "graph": {"node_count": 2, "edge_count": 1, "root_hash": "sha256:" + "a" * 64},
                "artifacts": {"report": [], "config": []},
                "accepted_config": {"policy": "runtime_config_is_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "planning_artifacts": {"policy": "planning_artifacts_are_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "claim_readiness": {"policy": "claims_require_committed_runtime_config", "supported": ["tbt_satisfied"], "unsupported": []},
                "supported_claims": ["tbt_satisfied"],
                "commitments": {
                    "dashboard_payload_hash": "sha256:" + "b" * 64,
                    "evidence_bundle_hash": "sha256:" + "c" * 64,
                    "evidence_manifest_hash": "sha256:" + "d" * 64,
                    "accepted_config_hash": "sha256:" + "e" * 64,
                    "planning_artifacts_hash": "sha256:442730135fb2e63f1e4b4388deee1eeabe67127968ea3bc163b7db52130e3f44",
                    "graph_root_hash": "sha256:" + "a" * 64,
                },
            }))
            (report_dir / "dashboard-payload.json").write_text(json.dumps({
                "schema_version": 1,
                "project": "demo",
                "generated_at": "2026-07-09T00:00:00Z",
                "inputs": {},
                "summary": {"run_id": "run-1"},
                "graph": {
                    "nodes": [
                        {"id": "test:TBT-001", "type": "tbt", "label": "Test basis", "status": "passed", "metadata": {}},
                        {"id": "evidence:EVD-TBT-001", "type": "evidence", "label": "Evidence", "status": "passed", "metadata": {"ref": "EVD-TBT-001"}},
                    ],
                    "edges": [{"source": "test:TBT-001", "target": "evidence:EVD-TBT-001", "type": "evidences"}],
                },
            }))
            claim_path = report_dir / "claim.json"
            run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(claim_path),
            )
            ok = run_cmd(
                "scripts/verify-assurance-claim.py",
                str(claim_path),
                "--report-dir",
                str(report_dir),
                "--require-satisfied",
            )
            claim = json.loads(claim_path.read_text())
            claim["claim_result"] = "unsatisfied"
            claim_path.write_text(json.dumps(claim, indent=2))
            tampered = run_cmd(
                "scripts/verify-assurance-claim.py",
                str(claim_path),
                "--report-dir",
                str(report_dir),
                check=False,
            )

        self.assertIn("OK assurance claim: satisfied tbt_satisfied TBT-001", ok.stdout)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("claim_result does not match", tampered.stdout)

    def test_report_validation_verifies_claim_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            (report_dir / "graph-manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "mode": "graph_proof_manifest",
                "project": "demo",
                "run_id": "run-1",
                "generated_at": "2026-07-09T00:00:00Z",
                "graph": {"node_count": 1, "edge_count": 0, "root_hash": "sha256:" + "a" * 64},
                "artifacts": {"report": [], "config": []},
                "accepted_config": {"policy": "runtime_config_is_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "planning_artifacts": {"policy": "planning_artifacts_are_frozen_by_content_hash", "commitment_count": 0, "commitments": []},
                "claim_readiness": {"policy": "claims_require_committed_runtime_config", "supported": ["tbt_satisfied"], "unsupported": []},
                "supported_claims": ["tbt_satisfied"],
                "commitments": {
                    "dashboard_payload_hash": "sha256:" + "b" * 64,
                    "evidence_bundle_hash": "sha256:" + "c" * 64,
                    "evidence_manifest_hash": "sha256:" + "d" * 64,
                    "accepted_config_hash": "sha256:" + "e" * 64,
                    "planning_artifacts_hash": "sha256:442730135fb2e63f1e4b4388deee1eeabe67127968ea3bc163b7db52130e3f44",
                    "graph_root_hash": "sha256:" + "a" * 64,
                },
            }))
            (report_dir / "dashboard-payload.json").write_text(json.dumps({
                "schema_version": 1,
                "project": "demo",
                "generated_at": "2026-07-09T00:00:00Z",
                "inputs": {},
                "summary": {"run_id": "run-1"},
                "graph": {
                    "nodes": [{"id": "test:TBT-001", "type": "tbt", "label": "Test basis", "status": "passed", "metadata": {}}],
                    "edges": [],
                },
            }))
            (report_dir / "evidence-manifest.json").write_text(json.dumps({"evidence_files": []}))
            add_manifest_artifact(report_dir, "graph-manifest.json")
            add_manifest_artifact(report_dir, "dashboard-payload.json")
            claim_path = report_dir / "claims" / "claim.json"
            run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(claim_path),
            )
            ok = run_cmd("scripts/validate-report-artifacts.py", "--report-dir", str(report_dir))
            claim = json.loads(claim_path.read_text())
            claim["claim_result"] = "unsatisfied"
            claim_path.write_text(json.dumps(claim, indent=2))
            tampered = run_cmd(
                "scripts/validate-report-artifacts.py",
                "--report-dir",
                str(report_dir),
                check=False,
            )

        self.assertIn("claims/claim.json", ok.stdout)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("claims/claim.json: claim_result does not match", tampered.stdout)

    def test_export_and_verify_assurance_proof_bundle_with_opening(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            write_satisfied_tbt_report(report_dir)
            claim_path = report_dir / "claims" / "claim.json"
            bundle_path = report_dir / "proof-bundles" / "claim.proof-bundle.json"
            run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(claim_path),
            )
            exported = run_cmd(
                "scripts/export-assurance-proof-bundle.py",
                str(claim_path),
                "--report-dir",
                str(report_dir),
                "--open",
                "reports/junit.xml",
                "--out",
                str(bundle_path),
            )
            verified = run_cmd(
                "scripts/verify-assurance-proof-bundle.py",
                str(bundle_path),
                "--report-dir",
                str(report_dir),
                "--require-satisfied",
            )
            bundle = json.loads(bundle_path.read_text())

        self.assertIn("proof bundle:", exported.stdout)
        self.assertIn("OK proof bundle: satisfied tbt_satisfied TBT-001", verified.stdout)
        self.assertEqual(bundle["evidence_commitments"][0]["id"], "EVD-TBT-001")
        self.assertEqual(bundle["openings"][0]["path"], "reports/junit.xml")

    def test_verify_assurance_proof_bundle_rejects_tampered_opening(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            write_satisfied_tbt_report(report_dir)
            claim_path = report_dir / "claims" / "claim.json"
            bundle_path = report_dir / "proof-bundles" / "claim.proof-bundle.json"
            run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(claim_path),
            )
            run_cmd(
                "scripts/export-assurance-proof-bundle.py",
                str(claim_path),
                "--report-dir",
                str(report_dir),
                "--open",
                "reports/junit.xml",
                "--out",
                str(bundle_path),
            )
            bundle = json.loads(bundle_path.read_text())
            bundle["openings"][0]["content"] = "dGFtcGVyZWQ="
            bundle["openings"][0]["bytes"] = len(b"tampered")
            bundle_path.write_text(json.dumps(bundle, indent=2))
            tampered = run_cmd(
                "scripts/verify-assurance-proof-bundle.py",
                str(bundle_path),
                "--report-dir",
                str(report_dir),
                check=False,
            )

        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("opening reports/junit.xml: sha256 does not match content", tampered.stdout)

    def test_report_validation_verifies_proof_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            write_satisfied_tbt_report(report_dir)
            claim_path = report_dir / "claims" / "claim.json"
            bundle_path = report_dir / "proof-bundles" / "claim.proof-bundle.json"
            run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(claim_path),
            )
            run_cmd(
                "scripts/export-assurance-proof-bundle.py",
                str(claim_path),
                "--report-dir",
                str(report_dir),
                "--out",
                str(bundle_path),
            )
            ok = run_cmd("scripts/validate-report-artifacts.py", "--report-dir", str(report_dir))
            bundle = json.loads(bundle_path.read_text())
            bundle["evidence_commitments"] = []
            bundle_path.write_text(json.dumps(bundle, indent=2))
            tampered = run_cmd(
                "scripts/validate-report-artifacts.py",
                "--report-dir",
                str(report_dir),
                check=False,
            )

        self.assertIn("proof-bundles/claim.proof-bundle.json", ok.stdout)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("proof-bundles/claim.proof-bundle.json: evidence_commitments do not match", tampered.stdout)

    def test_dashboard_refreshes_existing_claim_and_proof_commitments(self) -> None:
        dashboard = load_script_module(
            "generate_dashboard_for_claim_refresh",
            REPO_ROOT / "scripts" / "generate_dashboard.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = Path(tmp)
            write_satisfied_tbt_report(report_dir)
            claim_path = report_dir / "claims" / "claim.json"
            bundle_path = report_dir / "proof-bundles" / "claim.proof-bundle.json"
            run_cmd(
                "scripts/export-assurance-claim.py",
                str(report_dir),
                "--claim-type",
                "tbt_satisfied",
                "--target",
                "TBT-001",
                "--out",
                str(claim_path),
            )
            run_cmd(
                "scripts/export-assurance-proof-bundle.py",
                str(claim_path),
                "--report-dir",
                str(report_dir),
                "--open",
                "reports/junit.xml",
                "--out",
                str(bundle_path),
            )
            manifest = json.loads((report_dir / "graph-manifest.json").read_text())
            manifest["commitments"]["dashboard_payload_hash"] = "sha256:" + "9" * 64
            (report_dir / "graph-manifest.json").write_text(json.dumps(manifest, indent=2))
            stale = run_cmd(
                "scripts/validate-report-artifacts.py",
                "--report-dir",
                str(report_dir),
                check=False,
            )

            dashboard.write_hash_sidecar(report_dir, report_dir / "graph-manifest.json")
            dashboard.remove_report_artifact_manifest_entry(report_dir, "graph-manifest.json")
            dashboard.refresh_existing_assurance_claims_and_proofs(report_dir)
            ok = run_cmd("scripts/validate-report-artifacts.py", "--report-dir", str(report_dir))
            claim = json.loads(claim_path.read_text())
            bundle = json.loads(bundle_path.read_text())

        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("claim public_inputs do not match", stale.stdout)
        self.assertIn("claims/claim.json", ok.stdout)
        self.assertIn("proof-bundles/claim.proof-bundle.json", ok.stdout)
        self.assertEqual(claim["public_inputs"]["dashboard_payload_hash"], "sha256:" + "9" * 64)
        self.assertEqual(bundle["public_commitments"]["dashboard_payload_hash"], "sha256:" + "9" * 64)
        self.assertEqual(bundle["openings"][0]["path"], "reports/junit.xml")

if __name__ == "__main__":
    unittest.main()
