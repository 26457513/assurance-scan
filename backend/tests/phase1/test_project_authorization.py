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
    ))

    assert decision.allowed is True
    assert "single-tenant" in decision.reason


def test_local_upload_policy_fails_closed_for_every_policy_boundary() -> None:
    contexts = (
        LocalScanProjectContext(False, frozenset({"scans:upload"}), True, False),
        LocalScanProjectContext(True, frozenset(), True, False),
        LocalScanProjectContext(True, frozenset({"scans:upload"}), False, False),
        LocalScanProjectContext(True, frozenset({"scans:upload"}), True, True),
    )

    assert all(not authorize_local_scan_upload(context).allowed for context in contexts)
