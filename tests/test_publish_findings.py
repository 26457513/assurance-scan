from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "publish-findings"

sys.path.insert(0, str(SCRIPTS_DIR))

import publish_findings as pf  # noqa: E402
from scanner_parsers import remap_snapshot_path  # noqa: E402


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class RemapSnapshotPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="pathmap-"))
        self.snapshot_root = self.tmp / "snapshot"
        self.source_repo = self.tmp / "repo"
        (self.snapshot_root / "src" / "auth").mkdir(parents=True)
        (self.source_repo / "src" / "auth").mkdir(parents=True)
        (self.snapshot_root / "src" / "auth" / "login.py").write_text("x")
        (self.source_repo / "src" / "auth" / "login.py").write_text("x")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_happy_path(self) -> None:
        rel = remap_snapshot_path(
            "src/auth/login.py",
            snapshot_root=self.snapshot_root,
            source_repo=self.source_repo,
        )
        self.assertEqual(rel, "src/auth/login.py")

    def test_leading_dot_slash(self) -> None:
        rel = remap_snapshot_path(
            "./src/auth/login.py",
            snapshot_root=self.snapshot_root,
            source_repo=self.source_repo,
        )
        self.assertEqual(rel, "src/auth/login.py")

    def test_backslash_paths(self) -> None:
        rel = remap_snapshot_path(
            "src\\auth\\login.py",
            snapshot_root=self.snapshot_root,
            source_repo=self.source_repo,
        )
        self.assertEqual(rel, "src/auth/login.py")

    def test_traversal_raises(self) -> None:
        with self.assertRaises(ValueError):
            remap_snapshot_path(
                "../../etc/passwd",
                snapshot_root=self.snapshot_root,
                source_repo=self.source_repo,
            )

    def test_none_or_empty_returns_none(self) -> None:
        self.assertIsNone(
            remap_snapshot_path(None, snapshot_root=self.snapshot_root, source_repo=self.source_repo)
        )
        self.assertIsNone(
            remap_snapshot_path("", snapshot_root=self.snapshot_root, source_repo=self.source_repo)
        )


class ClassifyFixStrategyTests(unittest.TestCase):
    def test_semgrep_eval_is_auto(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("semgrep", "python.lang.security.audit.eval-with-expression",
                                     file="x.py", snippet="", in_git_history=False),
            "auto",
        )

    def test_semgrep_subprocess_is_auto(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("semgrep", "dangerous-subprocess-use",
                                     file="x.py", snippet="", in_git_history=False),
            "auto",
        )

    def test_trivy_cve_is_assisted(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("trivy-config", "CVE-2024-1234",
                                     file="Dockerfile", snippet="", in_git_history=False),
            "assisted",
        )

    def test_trivy_user_root_is_assisted(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("trivy-config", "DS026-user-root",
                                     file="Dockerfile", snippet="", in_git_history=False),
            "assisted",
        )

    def test_unknown_rule_defaults_to_assisted(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("semgrep", "some-unknown-rule-id",
                                     file="x.py", snippet="", in_git_history=False),
            "assisted",
        )

    def test_hardcoded_secret_is_manual(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("semgrep", "generic-hardcoded-secret",
                                     file="x.py", snippet="api_key='abc'", in_git_history=False),
            "manual",
        )

    def test_gitleaks_in_history_is_manual(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("gitleaks", "aws-access-token",
                                     file="config.yaml", snippet="", in_git_history=True),
            "manual",
        )

    def test_gitleaks_working_copy_is_assisted(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("gitleaks", "aws-access-token",
                                     file="config.yaml", snippet="", in_git_history=False),
            "assisted",
        )

    def test_gitleaks_unknown_defaults_to_manual(self) -> None:
        self.assertEqual(
            pf.classify_fix_strategy("gitleaks", "anything",
                                     file="config.yaml", snippet="", in_git_history=None),
            "manual",
        )


class ThemeForTests(unittest.TestCase):
    def test_semgrep_eval_theme(self) -> None:
        self.assertEqual(pf.theme_for("semgrep", "python.lang.security.audit.eval-with-expression"), "semgrep:eval")

    def test_gitleaks_aws_theme(self) -> None:
        # theme_for takes the last 2 meaningful segments: aws-access-token → "access-token"
        self.assertEqual(pf.theme_for("gitleaks", "aws-access-token"), "gitleaks:access-token")

    def test_trivy_dockerfile_theme(self) -> None:
        self.assertEqual(pf.theme_for("trivy-config", "DS026"), "trivy-config:ds026")

    def test_unknown_scanner_normalised(self) -> None:
        # rule.id.here → last 2 segments → "id-here"
        self.assertEqual(pf.theme_for("Semgrep", "rule.id.here"), "semgrep:id-here")

    def test_empty_rule_id(self) -> None:
        self.assertEqual(pf.theme_for("semgrep", ""), "semgrep:general")


class IsInGitHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="gitprobe-"))
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.email", "t@t")
        run_git(self.repo, "config", "user.name", "T")
        (self.repo / "committed.txt").write_text("tracked\n")
        run_git(self.repo, "add", "committed.txt")
        run_git(self.repo, "commit", "-q", "-m", "init")
        (self.repo / "untracked.txt").write_text("fresh\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_committed_file_is_in_history(self) -> None:
        self.assertTrue(pf.is_in_git_history("committed.txt", self.repo))

    def test_untracked_file_not_in_history(self) -> None:
        self.assertFalse(pf.is_in_git_history("untracked.txt", self.repo))

    def test_none_file_conservative_true(self) -> None:
        self.assertTrue(pf.is_in_git_history(None, self.repo))


class PrStrategyThresholdTests(unittest.TestCase):
    def _payload(self, n_files: int) -> dict:
        return {
            "summary": {
                "distinct_files": n_files,
                "pr_strategy": "single" if n_files <= pf.PR_STRATEGY_SINGLE_FILE_THRESHOLD else "themed",
            },
            "findings": [],
        }

    def test_threshold_constant(self) -> None:
        self.assertEqual(pf.PR_STRATEGY_SINGLE_FILE_THRESHOLD, 15)

    def test_below_threshold(self) -> None:
        p = self._payload(14)
        self.assertEqual(p["summary"]["pr_strategy"], "single")

    def test_at_threshold(self) -> None:
        p = self._payload(15)
        self.assertEqual(p["summary"]["pr_strategy"], "single")

    def test_above_threshold(self) -> None:
        p = self._payload(16)
        self.assertEqual(p["summary"]["pr_strategy"], "themed")


class BuildFindingsJsonShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Build a temp report dir mirroring fixtures/
        self.tmp = Path(tempfile.mkdtemp(prefix="rollup-"))
        self.report_dir = self.tmp / "report"
        self.source_repo = self.tmp / "repo"
        self.snapshot_root = self.tmp / "snapshot"
        shutil.copytree(FIXTURES_DIR, self.report_dir)
        # Mirror reported files into both snapshot and source_repo so path remap works
        for rel in [
            "src/auth/login.py",
            "src/util/run.py",
            "config/prod.yaml",
            "scripts/deploy.sh",
            "Dockerfile",
            "k8s/deploy.yaml",
        ]:
            for root in (self.snapshot_root, self.source_repo):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# fixture\n")
        # Initialise a git repo in source_repo so is_in_git_history works deterministically
        run_git(self.source_repo, "init", "-q")
        run_git(self.source_repo, "config", "user.email", "t@t")
        run_git(self.source_repo, "config", "user.name", "T")
        run_git(self.source_repo, "add", "-A")
        run_git(self.source_repo, "commit", "-q", "-m", "init")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shape_and_counts(self) -> None:
        payload = pf.build_findings_json(
            self.report_dir,
            source_repo=self.source_repo,
            snapshot_root=self.snapshot_root,
        )
        # Top-level schema
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["run_id"], "20260805T120000Z_abc12345")
        self.assertEqual(payload["git_branch"], "main")
        self.assertEqual(payload["git_commit"], "abc1234567890")

        # Summary counts: 2 semgrep + 2 gitleaks + 2 trivy = 6 findings, 6 files
        s = payload["summary"]
        self.assertEqual(s["total_findings"], 6)
        self.assertEqual(s["distinct_files"], 6)
        # All 6 distinct files > threshold of 15? No, 6 <= 15 so single
        self.assertEqual(s["pr_strategy"], "single")
        self.assertEqual(s["by_severity"]["CRITICAL"], 2)  # github-pat + KSV011
        self.assertEqual(s["by_severity"]["HIGH"], 3)      # aws + DS026 + dangerous-subprocess
        self.assertEqual(s["by_severity"]["MEDIUM"], 1)    # eval (warning level)
        self.assertEqual(s["by_scanner"]["semgrep"], 2)
        self.assertEqual(s["by_scanner"]["gitleaks"], 2)
        self.assertEqual(s["by_scanner"]["trivy-config"], 2)

        # Findings shape
        self.assertEqual(len(payload["findings"]), 6)
        f0 = payload["findings"][0]
        for key in [
            "id", "scanner", "rule_id", "rule_desc", "severity",
            "file", "line_start", "line_end", "snippet",
            "remediation", "fix_strategy", "theme", "compliance",
        ]:
            self.assertIn(key, f0)

        # Paths are repo-relative, not snapshot-root-prefixed
        for f in payload["findings"]:
            self.assertFalse(f["file"].startswith(str(self.snapshot_root)))
            self.assertFalse(f["file"].startswith("/"))

        # Stable IDs are 12 chars and unique
        ids = [f["id"] for f in payload["findings"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertEqual(len(i), 12)

        # Compliance join: semgrep eval + trivy DS026 have entries
        semgrep_eval = next(
            f for f in payload["findings"]
            if f["scanner"] == "semgrep" and "eval" in f["rule_id"]
        )
        self.assertTrue(semgrep_eval["compliance"])
        self.assertEqual(semgrep_eval["compliance"][0]["ruleset"], "ASVS")
        self.assertEqual(semgrep_eval["compliance"][0]["row"], "V5.3.4")

    def test_strategy_classification_in_build(self) -> None:
        payload = pf.build_findings_json(
            self.report_dir,
            source_repo=self.source_repo,
            snapshot_root=self.snapshot_root,
        )
        by_scanner_strategy = {}
        for f in payload["findings"]:
            key = (f["scanner"], f["fix_strategy"])
            by_scanner_strategy[key] = by_scanner_strategy.get(key, 0) + 1
        # semgrep → both auto
        self.assertEqual(by_scanner_strategy.get(("semgrep", "auto")), 2)
        # gitleaks files were committed in the test repo → manual
        self.assertEqual(by_scanner_strategy.get(("gitleaks", "manual")), 2)
        # trivy-config → assisted
        self.assertEqual(by_scanner_strategy.get(("trivy-config", "assisted")), 2)


class EnsureGitignoredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="gi-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_appends_block_when_missing(self) -> None:
        (self.repo / ".gitignore").write_text("node_modules/\n")
        status = pf.ensure_gitignored(self.repo, "auto", stdin_tty=False)
        self.assertEqual(status, "appended")
        content = (self.repo / ".gitignore").read_text()
        self.assertIn(pf.GITIGNORE_MARKER, content)
        self.assertEqual(content.count(pf.GITIGNORE_MARKER), 1)

    def test_idempotent_when_present(self) -> None:
        (self.repo / ".gitignore").write_text(
            "node_modules/\n# assurance-scan local reports (do not commit)\n.assurance-scan/reports/\n"
        )
        status = pf.ensure_gitignored(self.repo, "auto", stdin_tty=False)
        self.assertEqual(status, "present")
        content = (self.repo / ".gitignore").read_text()
        self.assertEqual(content.count(pf.GITIGNORE_MARKER), 1)

    def test_skip_mode_does_nothing(self) -> None:
        (self.repo / ".gitignore").write_text("node_modules/\n")
        status = pf.ensure_gitignored(self.repo, "skip")
        self.assertEqual(status, "skipped")
        content = (self.repo / ".gitignore").read_text()
        self.assertNotIn(pf.GITIGNORE_MARKER, content)

    def test_creates_gitignore_if_absent(self) -> None:
        self.assertFalse((self.repo / ".gitignore").exists())
        status = pf.ensure_gitignored(self.repo, "auto", stdin_tty=False)
        self.assertEqual(status, "appended")
        self.assertTrue((self.repo / ".gitignore").exists())


class MaybeInstallAgentSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="skill-"))
        self.script_dir = SCRIPTS_DIR
        self.target = self.repo / pf.AGENT_SKILL_INSTALL_REL_PATH

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_installs_when_missing(self) -> None:
        status = pf.maybe_install_agent_skill(self.repo, self.script_dir)
        self.assertEqual(status, "installed")
        self.assertTrue(self.target.exists())
        self.assertIn("Fix assurance-scan findings", self.target.read_text())

    def test_present_not_overwritten(self) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("# user customisation\n")
        status = pf.maybe_install_agent_skill(self.repo, self.script_dir)
        self.assertEqual(status, "present")
        self.assertEqual(self.target.read_text(), "# user customisation\n")

    def test_force_overwrites(self) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text("# old\n")
        status = pf.maybe_install_agent_skill(self.repo, self.script_dir, force=True)
        self.assertEqual(status, "installed")
        self.assertIn("Fix assurance-scan findings", self.target.read_text())


class StableIdTests(unittest.TestCase):
    def test_stable_id_is_deterministic(self) -> None:
        a = pf._stable_id("semgrep", "rule.x", "src/a.py", 10)
        b = pf._stable_id("semgrep", "rule.x", "src/a.py", 10)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 12)

    def test_stable_id_varies_with_inputs(self) -> None:
        a = pf._stable_id("semgrep", "rule.x", "src/a.py", 10)
        b = pf._stable_id("semgrep", "rule.x", "src/a.py", 11)
        c = pf._stable_id("semgrep", "rule.x", "src/b.py", 10)
        d = pf._stable_id("gitleaks", "rule.x", "src/a.py", 10)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)


if __name__ == "__main__":
    unittest.main()
