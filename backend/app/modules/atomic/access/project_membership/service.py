"""Deterministic project permission policy without framework or database coupling."""

from __future__ import annotations

from typing import Literal


ProjectPermission = Literal["view", "upload", "manage"]

_ALLOWED: dict[ProjectPermission, frozenset[str]] = {
    "view": frozenset(("view", "upload", "manage")),
    "upload": frozenset(("upload", "manage")),
    "manage": frozenset(("manage",)),
}


def allowed_permissions(required: ProjectPermission) -> frozenset[str]:
    return _ALLOWED[required]


def permission_allows(granted: str, required: ProjectPermission) -> bool:
    return granted in _ALLOWED[required]


__all__ = ["ProjectPermission", "allowed_permissions", "permission_allows"]
