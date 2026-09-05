"""Regression checks for the immutable production application rollout."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_deploy_recreates_server_from_exact_candidate_image() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    deploy_job = workflow.split("\n  deploy:\n", maxsplit=1)[1].split(
        "\n  verify:\n", maxsplit=1
    )[0]

    retag = "docker image tag \"$candidate_ref\" ghcr.io/26457513/assurance-scan-app:latest"
    assert retag in deploy_job
    assert "printf 'services:\\n  server:\\n    image: %s\\n' \"$candidate_ref\"" in deploy_job
    compose_override = 'docker compose -f compose.yaml -f "$candidate_override"'
    assert compose_override in deploy_job
    assert "awk '!/cd \\/root\\/assurance-scan && docker compose pull -q server/'" in deploy_job
    assert "up -d --no-deps --pull never --no-build --force-recreate server" in deploy_job
    assert deploy_job.index(retag) < deploy_job.index(compose_override)
    assert "--format '{{.Config.Image}}'" in deploy_job
    assert "docker inspect assurance-scan-server-1 --format '{{.Image}}'" in deploy_job


def test_verify_checks_github_oauth_handoff() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    verify_job = workflow.split("\n  verify:\n", maxsplit=1)[1]

    assert "oauth_start_status" in verify_job
    assert "http://127.0.0.1:8742/auth/github/start?next=%2Fprojects%2F1" in verify_job
    assert 'if [ "$oauth_status" != 302 ]; then' in verify_job
    assert "public_oauth_start_status" in verify_job
    assert "https://scan.squease.ai/auth/github/start?next=%2Fprojects%2F1" in verify_job


def test_public_health_checks_retry_transient_proxy_errors() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("--retry-all-errors --retry-max-time 60") == 2


def test_schema_verification_uses_the_candidate_image_migration_head() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("ScriptDirectory.from_config") == 2
    assert 'test "$schema_revision" = "$expected_schema_revision"' in workflow
    assert "0038_github_signin_return_paths" not in workflow
