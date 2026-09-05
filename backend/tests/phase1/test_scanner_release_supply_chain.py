"""Release-contract checks for the public CLI and pinned scanner set."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from app.modules.atomic.scanning.scanner_catalog import (
    CODE_SCANNERS,
    SCANNER_MANIFEST_PATH,
    SCANNER_RELEASE_SET,
    SEMGREP,
)


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-cli-image.yml"
APP_WORKFLOW = ROOT / ".github" / "workflows" / "publish-app-image.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "publish-ghcr.yml"
CI_TEMPLATE = ROOT / "backend" / "resources" / "templates" / "assurance-scan.yml"
DOCKERFILE = ROOT / "backend" / "Dockerfile.cli"
EXPECTED_IMAGES = {
    "semgrep/semgrep@sha256:f1f7b71861c7b28b6e0f661225a2c4f58a484f5d0f182465c6d6b3b22f972ade",
    "zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f",
    "aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969",
    "anchore/syft@sha256:95fe0835e5bebc6f8b1f8acef68d47d63d594ef4c0f25c097ff853b23cbac74c",
    "anchore/grype@sha256:8a93fc48da96bd6ec5981279d099b69de11541dc68fdf222fb9161f8ff284af7",
    "ghcr.io/google/osv-scanner@sha256:8108ae94eadea5a02c9bec6e646909d5b790b44bd62d7f5b7f0b1d6d0ffc7734",
}


def test_catalog_uses_only_the_six_reviewed_immutable_indexes() -> None:
    assert {scanner.image for scanner in CODE_SCANNERS} == EXPECTED_IMAGES
    for scanner in CODE_SCANNERS:
        assert re.fullmatch(r"[^:]+(?:/[^:]+)*@sha256:[0-9a-f]{64}", scanner.image)
        assert set(scanner.platform_digests) == {"linux/amd64", "linux/arm64"}
        assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in scanner.platform_digests.values())
        assert scanner.tool_version
        assert scanner.timeout_seconds > 0
        assert scanner.read_only
        assert scanner.cap_drop == ("ALL",)
        assert scanner.no_new_privileges


def test_manifest_and_reviewed_semgrep_policy_are_content_addressed() -> None:
    manifest_bytes = SCANNER_MANIFEST_PATH.read_bytes()
    assert SCANNER_RELEASE_SET.schema_version == 1
    assert SCANNER_RELEASE_SET.sha256 == hashlib.sha256(manifest_bytes).hexdigest()
    assert SCANNER_RELEASE_SET.required_platforms == ("linux/amd64", "linux/arm64")
    policy_path = ROOT / SCANNER_RELEASE_SET.semgrep_policy_path
    policy_bytes = policy_path.read_bytes()
    assert hashlib.sha256(policy_bytes).hexdigest() == SCANNER_RELEASE_SET.semgrep_policy_sha256
    assert yaml.safe_load(policy_bytes)["rules"]
    assert "auto" not in SEMGREP.command
    assert any(
        SCANNER_RELEASE_SET.semgrep_policy_container_path in argument
        for argument in SEMGREP.command
    )


def test_release_manifest_locks_public_promotion_and_attestation_semantics() -> None:
    manifest = json.loads(SCANNER_MANIFEST_PATH.read_text())
    release = manifest["cli_release"]
    assert release == {
        "image": "ghcr.io/26457513/assurance-scan-cli",
        "immutable_tag_pattern": "v<semver>",
        "promotion_tag": "stable",
        "promotion_semantics": "retag-tested-digest-only",
        "public_package_required": True,
        "sbom": "spdx-json-attestation",
        "provenance": "slsa-build-provenance",
        "signing": "cosign-keyless",
    }


def test_cli_dockerfile_is_pinned_minimal_and_not_a_server_entrypoint() -> None:
    dockerfile = DOCKERFILE.read_text()
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) == 2
    assert all("@sha256:" in line for line in from_lines)
    assert "ca-certificates git" in dockerfile
    assert "ARG VERSION" in dockerfile and "ARG REVISION" in dockerfile
    assert "org.opencontainers.image.version" in dockerfile
    assert "COPY frontend" not in dockerfile
    assert "COPY backend/app/ " not in dockerfile
    assert 'ENTRYPOINT ["python3", "/opt/assurance-scan/backend/scripts/local-cli.py"]' in dockerfile


def test_release_workflow_builds_then_promotes_the_same_signed_digest() -> None:
    source = WORKFLOW.read_text()
    workflow = yaml.safe_load(source)
    assert workflow[True]["push"]["tags"] == ["v*.*.*"]
    # Tag build plus both dispatch validation gates independently reject a
    # mutable or non-canonical release selector.
    assert source.count(r"^v[0-9]+\.[0-9]+\.[0-9]+$") == 3
    assert "linux/amd64,linux/arm64" in source
    assert "needs: quality-gate" in source
    assert "Verify every pinned scanner index has both qualified platforms" in source
    assert "sbom: true" in source
    assert "provenance: mode=max" in source
    assert "cosign sign --yes" in source
    assert "cosign verify-attestation" not in source
    assert "SEMGREP_POLICY_PATH.read_bytes()" in source
    assert source.count('(index .SBOM \\"$platform\\").SPDX') == 3
    assert source.count('(index .Provenance \\"$platform\\").SLSA') == 3
    assert source.count('sbom.get("SPDXID") == "SPDXRef-DOCUMENT"') == 3
    assert source.count('provenance.get("buildDefinition", {}).get("buildType")') == 2
    assert "docker logout ghcr.io" in source  # proves anonymous/public pull expectation
    assert 'install -d -m 755 "$target"' in source
    assert 'install -m 644 "$stage/latest.json"' in source
    assert 'install -m 644 "$stage/latest.sigstore.json"' in source
    promote = source[source.index("  promote-stable:") :]
    assert "docker/build-push-action" not in promote
    assert "imagetools create --tag \"$IMAGE:stable\" \"$IMAGE@$DIGEST\"" in promote
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", source)
    assert action_refs and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_app_workflow_publishes_a_verified_candidate_without_deploying() -> None:
    source = APP_WORKFLOW.read_text()
    assert "tags: ${{ env.IMAGE }}:sha-${{ github.sha }}" in source
    assert "sbom: true" in source
    assert "provenance: mode=max" in source
    assert "cosign sign --yes" in source
    assert "cosign verify-attestation" not in source
    assert "manifest.json" in source
    assert "exactly one linux/amd64 manifest" in source
    assert "{{ json .SBOM.SPDX }}" in source
    assert "{{ json .Provenance.SLSA }}" in source
    assert 'request_args.get("build-arg:REVISION") == expected_sha' in source
    assert 'request_args.get("build-arg:VERSION") == f"sha-{expected_sha}"' in source
    assert "builder == expected_builder" in source
    assert '"$IMAGE@$platform_digest" --help' in source
    verification = source.index("Verify immutable digest, signature, SBOM, and provenance")
    promotion = source.index("Move candidate to the verified digest without rebuilding")
    assert verification < promotion
    assert 'imagetools create --tag "$IMAGE:candidate" "$IMAGE@$DIGEST"' in source
    assert ":latest" not in source
    assert "ssh " not in source
    assert "deploy" not in yaml.safe_load(source)["jobs"]
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", source)
    assert action_refs and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_ci_workflow_promotes_latest_only_after_verifying_the_digest() -> None:
    source = CI_WORKFLOW.read_text()
    assert "tags: ${{ env.CI_IMAGE }}:sha-${{ github.sha }}" in source
    assert "tags: ${{ env.UPLOAD_IMAGE }}:sha-${{ github.sha }}" in source
    assert source.count("sbom: true") == 2
    assert source.count("provenance: mode=max") == 2
    assert source.count("cosign sign --yes") == 2
    assert source.count("cosign attest --yes --type custom") == 2
    assert source.count("cosign verify-attestation") == 2
    assert '"producer": f"ghcr.io/26457513/assurance-scan-ci@{ci_digest}"' in source
    assert '"uploader": f"ghcr.io/26457513/assurance-scan-ci-upload@{upload_digest}"' in source
    verification = source.index("Verify anonymous pull, signature, SBOM, and provenance")
    promotion = source.index("Move candidate and latest to the verified digest without rebuilding")
    assert verification < promotion
    assert 'imagetools create --tag "$CI_IMAGE:latest" "$CI_IMAGE@$DIGEST"' in source
    assert 'imagetools create --tag "$UPLOAD_IMAGE:latest" "$UPLOAD_IMAGE@$UPLOAD_DIGEST"' in source
    assert "docker/build-push-action" not in source[promotion:]
    assert "ssh " not in source
    assert "deploy" not in yaml.safe_load(source)["jobs"]
    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s#]+)", source)
    assert action_refs and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)


def test_vendored_ci_template_defaults_to_latest_and_documents_digest_pinning() -> None:
    source = CI_TEMPLATE.read_text()
    assert "ghcr.io/26457513/assurance-scan-ci:latest" in source
    assert ":vX.Y.Z" in source
    assert "@sha256:<digest>" in source
