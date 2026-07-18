from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER_BIN = REPO_ROOT / "bin" / "assurance-scan"


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def setup_repo(repo_dir: Path, dockerfile_rel: str, lockfile_name: str, gitignore_lockfile: bool) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    run_git(repo_dir, "init", "-q")
    run_git(repo_dir, "config", "user.email", "test@test.local")
    run_git(repo_dir, "config", "user.name", "Test")

    if gitignore_lockfile:
        (repo_dir / ".gitignore").write_text(f"{lockfile_name}\n")

    dockerfile_path = repo_dir / dockerfile_rel
    dockerfile_path.parent.mkdir(parents=True, exist_ok=True)
    dockerfile_path.write_text("FROM scratch\n")

    pkg = dockerfile_path.parent / "package.json"
    if not pkg.exists():
        pkg.write_text('{"name": "test"}\n')

    lockfile_path = dockerfile_path.parent / lockfile_name
    lockfile_path.write_text("{}\n")

    run_git(repo_dir, "add", "-A")
    run_git(repo_dir, "commit", "-q", "-m", "initial")


def create_worktree(repo_dir: Path, name: str) -> Path:
    wt_dir = repo_dir.parent / name
    run_git(repo_dir, "worktree", "add", "-q", "-b", f"safe-{name}", str(wt_dir))
    return wt_dir


def invoke_injection(
    worktree_dir: Path,
    repo_root: Path,
    dockerfiles: list[str],
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    dockerfiles_file = worktree_dir / ".dockerfiles.tmp"
    dockerfiles_file.write_text("\n".join(dockerfiles) + "\n")

    env = os.environ.copy()
    env.pop("ASSURANCE_SCAN_INJECT_LOCKFILES", None)
    if env_extra:
        env.update(env_extra)

    script = (
        f"set -euo pipefail\n"
        f"source {SCANNER_BIN!s}\n"
        f'inject_gitignored_lockfiles "{worktree_dir}" "{repo_root}" "{dockerfiles_file}"\n'
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def git_log_subjects(wt_dir: Path) -> str:
    res = subprocess.run(
        ["git", "-C", str(wt_dir), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout


def read_manifest(wt_dir: Path) -> list:
    p = wt_dir / ".assurance-scan" / "runtime" / "injected-lockfiles.json"
    return json.loads(p.read_text())


class TestInjectGitignoredLockfiles(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_gitignored_package_lock_injected(self) -> None:
        repo = self.tmp / "repo"
        setup_repo(repo, "services/foo/Dockerfile", "package-lock.json", gitignore_lockfile=True)
        wt = create_worktree(repo, "wt")

        dockerfiles = [str(wt / "services" / "foo" / "Dockerfile")]
        result = invoke_injection(wt, repo, dockerfiles)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        wt_lock = wt / "services" / "foo" / "package-lock.json"
        self.assertTrue(wt_lock.exists(), "lockfile was not copied into worktree")

        self.assertIn("inject gitignored lockfiles", git_log_subjects(wt))

        manifest = read_manifest(wt)
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["path"], "services/foo/package-lock.json")
        self.assertEqual(manifest[0]["source"], "gitignored_working_tree")

    def test_tracked_lockfile_not_injected(self) -> None:
        repo = self.tmp / "repo"
        setup_repo(repo, "services/foo/Dockerfile", "package-lock.json", gitignore_lockfile=False)
        wt = create_worktree(repo, "wt")

        self.assertTrue((wt / "services" / "foo" / "package-lock.json").exists())

        dockerfiles = [str(wt / "services" / "foo" / "Dockerfile")]
        result = invoke_injection(wt, repo, dockerfiles)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        self.assertNotIn("inject gitignored lockfiles", git_log_subjects(wt))

        self.assertEqual(read_manifest(wt), [])

    def test_opt_out_env(self) -> None:
        repo = self.tmp / "repo"
        setup_repo(repo, "services/foo/Dockerfile", "package-lock.json", gitignore_lockfile=True)
        wt = create_worktree(repo, "wt")

        dockerfiles = [str(wt / "services" / "foo" / "Dockerfile")]
        result = invoke_injection(
            wt, repo, dockerfiles, env_extra={"ASSURANCE_SCAN_INJECT_LOCKFILES": "0"}
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        self.assertFalse((wt / "services" / "foo" / "package-lock.json").exists())

        self.assertEqual(read_manifest(wt), [])

    def test_yarn_and_pnpm(self) -> None:
        for lockfile in ("yarn.lock", "pnpm-lock.yaml"):
            with self.subTest(lockfile=lockfile):
                slug = lockfile.replace(".", "-")
                repo = self.tmp / f"repo-{slug}"
                setup_repo(repo, "services/foo/Dockerfile", lockfile, gitignore_lockfile=True)
                wt = create_worktree(repo, f"wt-{slug}")

                dockerfiles = [str(wt / "services" / "foo" / "Dockerfile")]
                result = invoke_injection(wt, repo, dockerfiles)
                self.assertEqual(result.returncode, 0, msg=result.stderr)

                wt_lock = wt / "services" / "foo" / lockfile
                self.assertTrue(wt_lock.exists(), f"{lockfile} was not copied into worktree")

                manifest = read_manifest(wt)
                self.assertEqual(len(manifest), 1)
                self.assertEqual(manifest[0]["path"], f"services/foo/{lockfile}")

    def test_root_dockerfile(self) -> None:
        repo = self.tmp / "repo"
        setup_repo(repo, "Dockerfile", "package-lock.json", gitignore_lockfile=True)
        wt = create_worktree(repo, "wt")

        dockerfiles = [str(wt / "Dockerfile")]
        result = invoke_injection(wt, repo, dockerfiles)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        self.assertTrue((wt / "package-lock.json").exists())

        manifest = read_manifest(wt)
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["path"], "package-lock.json")


if __name__ == "__main__":
    unittest.main()
