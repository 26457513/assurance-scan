"""Characterization test for the current application-wide project policy."""

from app.modules.atomic.access.project_authorization import (
    LocalScanProjectContext,
    authorize_local_scan_upload,
    authorize_project_action,
)


def test_current_policy_allows_existing_project_actions() -> None:
    for action in ("read", "create", "update", "delete"):
        decision = authorize_project_action(action)
        assert decision.allowed is True
        assert action in decision.reason


def test_local_upload_policy_allows_active_scoped_user_on_visible_project() -> None:
    decision = authorize_local_scan_upload(LocalScanProjectContext(
        user_active=True,
        token_scopes=frozenset({"scans:upload"}),
        project_registered=True,
        project_hidden=False,
        user_can_upload=True,
    ))

    assert decision.allowed is True
    assert "project membership" in decision.reason


def test_local_upload_policy_fails_closed_for_every_policy_boundary() -> None:
    contexts = (
        LocalScanProjectContext(False, frozenset({"scans:upload"}), True, False, True),
        LocalScanProjectContext(True, frozenset(), True, False, True),
        LocalScanProjectContext(True, frozenset({"scans:upload"}), False, False, True),
        LocalScanProjectContext(True, frozenset({"scans:upload"}), True, True, True),
        LocalScanProjectContext(True, frozenset({"scans:upload"}), True, False, False),
    )

    assert all(not authorize_local_scan_upload(context).allowed for context in contexts)
