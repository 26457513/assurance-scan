"""Tests for the CI scanner set selection."""
from __future__ import annotations

from server.worker.scanners import CODE_SCANNERS, TRIVY_IMAGE, ci_scanner_set


def test_ci_set_default_includes_syft_excludes_trivy_image() -> None:
    kinds = [s.kind for s in ci_scanner_set()]
    assert "syft" in kinds
    assert "trivy-image" not in kinds
    assert set(kinds) == {s.kind for s in CODE_SCANNERS} - {"trivy-image"}


def test_ci_set_with_image_swaps_tag_only() -> None:
    scanners = ci_scanner_set("app:ci")
    img = scanners[-1]
    assert img.kind == "trivy-image"
    assert img.command[-1] == "app:ci"
    assert img.command[:-1] == TRIVY_IMAGE.command[:-1]
    assert img.command != TRIVY_IMAGE.command
