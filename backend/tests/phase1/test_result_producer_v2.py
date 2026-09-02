"""Contract tests for the shared source-neutral v2 result producer."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.infrastructure.ingest_v2_contract import CheckedInEnvelopeSchemaValidator
from app.modules.atomic.scanning.finding_parser import ParsedFinding
from app.modules.atomic.scanning.result_producer import (
    GitHubProducerIdentity,
    LocalProducerIdentity,
    ProduceEnvelopeCommand,
    RepositoryProvenance,
    ScannerOutcome,
    ScannerRelease,
    SourceProvenance,
    produce_envelope_v2,
)
from app.modules.workflows.result_ingest_v2_contract import build_validated_envelope_v2


_COMMIT = "1" * 40
_CONTENT_HASH = "2" * 64
_MANIFEST_DIGEST = "3" * 64
_SCANNER_IMAGE = f"docker.io/semgrep/semgrep@sha256:{'4' * 64}"
_CLI_IMAGE = f"ghcr.io/26457513/assurance-scan-cli@sha256:{'6' * 64}"


def _command(root: Path, *, github: bool = False) -> ProduceEnvelopeCommand:
    producer = (
        GitHubProducerIdentity(
            repository_id=424242,
            repository_owner_id=26457513,
            run_id=123456789,
            run_number=26,
            run_attempt=1,
            workflow_ref=(
                "26457513/assurance-scan/.github/workflows/"
                "assurance-scan.yml@refs/heads/main"
            ),
            workflow_sha=_COMMIT,
            actor="octocat",
            actor_id=583231,
        )
        if github
        else LocalProducerIdentity(
            request_id="018f47a2-4c72-4c9e-9f60-780cb70b8fe4",
            cli_installation_id="9d729629-2af3-4498-8342-7ed237f44a6f",
            cli_version="v1.2.3",
            cli_build_revision="5" * 40,
            cli_image=_CLI_IMAGE,
        )
    )
    return ProduceEnvelopeCommand(
        repository=RepositoryProvenance(
            full_name="26457513/assurance-scan",
            commit=_COMMIT,
            git_object_format="sha1",
            branch="main" if github else "feature/contracts",
            working_tree_dirty=not github,
        ),
        source=SourceProvenance(
            snapshot_root=root,
            content_hash=_CONTENT_HASH,
            manifest_version="assurance-snapshot-v1",
            lfs_state="none",
        ),
        scanner_release=ScannerRelease(
            manifest_version=1,
            manifest_digest=_MANIFEST_DIGEST,
            images={"semgrep": _SCANNER_IMAGE},
        ),
        producer=producer,
        scanner_outcomes=(
            ScannerOutcome(
                kind="semgrep",
                status="completed",
                duration_ms=1250,
                image=_SCANNER_IMAGE,
                tool_version="1.130.0",
            ),
        ),
        findings=(
            ParsedFinding(
                scanner_kind="semgrep",
                rule_id="python.lang.security.audit.eval-detected",
                severity="HIGH",
                file_path="src/app.py",
                line_start=6,
                line_end=6,
                message="Avoid dynamic evaluation. AS_CANARY_SECRET_DO_NOT_PERSIST",
                theme="code",
                fix_strategy="code-change",
                compliance_tags=("ASVS-5.3.4", "ASVS-5.3.4"),
            ),
        ),
    )


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    root = tmp_path / "snapshot"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "",
                "def evaluate(value: str) -> object:",
                "    # password=hunter2",
                "    prepared = value.strip()",
                "    return eval(prepared)",
                "",
                "def safe() -> None:",
                "    return None",
            )
        ),
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("github", [False, True])
def test_producer_emits_valid_canonical_v2_envelope(snapshot: Path, github: bool) -> None:
    produced = produce_envelope_v2(_command(snapshot, github=github))

    validated = build_validated_envelope_v2(
        produced.canonical_parts,
        schema_validator=CheckedInEnvelopeSchemaValidator(),
    )

    assert validated.payload_hash == produced.payload_hash
    assert validated.metadata["producer"]["kind"] == (
        "github-actions" if github else "local-cli"
    )
    assert "AS_CANARY_SECRET_DO_NOT_PERSIST" not in b"".join(
        produced.canonical_parts.values()
    ).decode()
    assert "password=hunter2" not in produced.canonical_parts["source_contexts"].decode()
    assert len(validated.findings["findings"]) == 1
    assert validated.source_contexts["contexts"][0]["available"] is True


def test_origins_share_identical_findings_and_context_documents(snapshot: Path) -> None:
    local = produce_envelope_v2(_command(snapshot))
    github = produce_envelope_v2(_command(snapshot, github=True))

    for part in ("findings", "source_contexts", "sarif"):
        assert local.canonical_parts[part] == github.canonical_parts[part]


@pytest.mark.parametrize(
    "outcome",
    [
        ScannerOutcome(
            "semgrep", "completed", 1, _SCANNER_IMAGE, "1.0", error_code="scanner_timeout"
        ),
        ScannerOutcome("semgrep", "failed", 1, _SCANNER_IMAGE, "1.0"),
        ScannerOutcome("semgrep", "skipped", 1, None, "1.0"),
        ScannerOutcome("semgrep", "completed", 1, f"x@sha256:{'7' * 64}", "1.0"),
    ],
)
def test_producer_rejects_inconsistent_scanner_outcomes(
    snapshot: Path,
    outcome: ScannerOutcome,
) -> None:
    command = replace(_command(snapshot), scanner_outcomes=(outcome,))

    with pytest.raises(ValueError):
        produce_envelope_v2(command)


def test_producer_is_deterministic(snapshot: Path) -> None:
    first = produce_envelope_v2(_command(snapshot, github=True))
    second = produce_envelope_v2(_command(snapshot, github=True))

    assert first.canonical_parts == second.canonical_parts
    assert first.payload_hash == second.payload_hash

