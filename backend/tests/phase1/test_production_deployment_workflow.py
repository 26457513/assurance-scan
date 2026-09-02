"""Regression checks for the immutable production application rollout."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "deploy-production.yml"


def test_deploy_recreates_server_after_retargeting_latest_image() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    deploy_job = workflow.split("\n  deploy:\n", maxsplit=1)[1].split(
        "\n  verify:\n", maxsplit=1
    )[0]

    retag = "docker image tag \"$candidate_ref\" ghcr.io/26457513/assurance-scan-app:latest"
    recreate = (
        "docker compose up -d --no-deps --pull never --no-build "
        "--force-recreate server"
    )
    assert retag in deploy_job
    assert recreate in deploy_job
    assert deploy_job.index(retag) < deploy_job.index(recreate)
    assert "docker inspect assurance-scan-server-1 --format '{{.Image}}'" in deploy_job
