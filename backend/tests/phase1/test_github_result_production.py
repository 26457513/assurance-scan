"""Workflow tests for immutable GitHub v2 bundle production."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from app.infrastructure.ingest_v2_contract import CheckedInEnvelopeSchemaValidator
from app.modules.atomic.scanning.finding_parser import ParsedFinding
from app.modules.atomic.scanning.result_producer import ScannerOutcome
from app.modules.atomic.scanning.scanner_catalog import SEMGREP
from app.modules.workflows.github_result_production import (
    GitHubResultProductionCommand,
    produce_github_result_bundle,
)
from app.modules.workflows.github_scan_execution import ScanExecutionResult
from app.modules.workflows.result_ingest_v2_contract import build_validated_envelope_v2


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "remote", "add", "origin", "https://github.com/example/project.git")
    (root / "app.py").write_text(
        "one\ntwo\nthree\nfour\nfive\npassword=hunter2\nseven\n",
        encoding="utf-8",
    )
    _git(root, "add", "app.py")
    _git(root, "commit", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _environment(commit: str) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": "example/project",
        "GITHUB_REPOSITORY_ID": "101",
        "GITHUB_REPOSITORY_OWNER_ID": "202",
        "GITHUB_RUN_ID": "303",
        "GITHUB_RUN_NUMBER": "26",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": commit,
        "GITHUB_WORKFLOW_REF": (
            "example/project/.github/workflows/assurance-scan.yml@refs/heads/main"
        ),
        "GITHUB_WORKFLOW_SHA": commit,
        "GITHUB_ACTOR": "octocat",
        "GITHUB_ACTOR_ID": "583231",
    }


def test_workflow_scans_snapshot_and_materializes_valid_bundle(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    root, commit = repository
    output = tmp_path / "bundle"
    scanned: list[str] = []

    async def scanner(
        source_snapshot_path: str,
        scanner_snapshot_path: str,
        _image: str | None,
        _sbom_path: Path | None,
    ) -> ScanExecutionResult:
        scanned.append(scanner_snapshot_path)
        assert (Path(source_snapshot_path) / "app.py").is_file()
        return ScanExecutionResult(
            findings=(
                ParsedFinding(
                    "semgrep", "example", "HIGH", "app.py", 6, 6, "unsafe credential"
                ),
            ),
            scanner_outcomes=(
                ScannerOutcome(
                    "semgrep", "completed", 10, SEMGREP.image, SEMGREP.tool_version
                ),
            ),
            sbom=None,
        )

    result = asyncio.run(
        produce_github_result_bundle(
            GitHubResultProductionCommand(
                project_root=root,
                output_root=output,
                scanner_snapshot_path=str(output / ".source-snapshot"),
                environment=_environment(commit),
            ),
            scanner=scanner,
        )
    )

    raw_parts = {
        "metadata": (output / "metadata.json").read_bytes(),
        "findings": (output / "findings.json").read_bytes(),
        "source_contexts": (output / "source-contexts.json").read_bytes(),
        "sarif": (output / "results.sarif").read_bytes(),
    }
    validated = build_validated_envelope_v2(
        raw_parts,
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )
    assert scanned == [str(output / ".source-snapshot")]
    assert not (output / ".source-snapshot").exists()
    assert validated.payload_hash == result.envelope.payload_hash
    assert (output / "envelope.sha256").read_text().strip() == validated.payload_hash
    assert "password=hunter2" not in raw_parts["source_contexts"].decode()


def test_workflow_rejects_non_push_before_creating_output(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    root, commit = repository
    environment = _environment(commit)
    environment["GITHUB_EVENT_NAME"] = "pull_request"
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="only GitHub push events"):
        asyncio.run(
            produce_github_result_bundle(
                GitHubResultProductionCommand(
                    root,
                    output,
                    str(output / ".source-snapshot"),
                    environment,
                )
            )
        )

    assert not output.exists()


def test_workflow_rejects_dirty_checkout_without_running_scanners(
    repository: tuple[Path, str],
    tmp_path: Path,
) -> None:
    root, commit = repository
    (root / "untracked.py").write_text("change", encoding="utf-8")
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="must be clean"):
        asyncio.run(
            produce_github_result_bundle(
                GitHubResultProductionCommand(
                    root,
                    output,
                    str(output / ".source-snapshot"),
                    _environment(commit),
                )
            )
        )

    assert not output.exists()
