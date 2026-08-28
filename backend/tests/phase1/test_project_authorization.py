"""Characterization test for the current application-wide project policy."""

from app.modules.atomic.access.project_authorization import authorize_project_action


def test_current_policy_allows_existing_project_actions() -> None:
    for action in ("read", "create", "update", "delete"):
        decision = authorize_project_action(action)
        assert decision.allowed is True
        assert action in decision.reason
