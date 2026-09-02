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
