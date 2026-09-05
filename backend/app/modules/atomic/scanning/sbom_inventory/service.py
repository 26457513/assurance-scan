"""Extract a bounded, presentation-neutral inventory from CycloneDX JSON."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import unquote

from app.modules.shared.contracts.findings import PACKAGE_IDENTITY_CAPABILITY


MAX_COMPONENTS = 20_000


class SbomInventoryError(ValueError):
    """The persisted SBOM cannot be represented as a package inventory."""


def extract_packages(content: bytes) -> list[dict[str, Any]]:
    """Return normalized packages without trusting arbitrary document fields."""
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SbomInventoryError("SBOM is not valid JSON") from exc
    if not isinstance(document, dict) or document.get("bomFormat") != "CycloneDX":
        raise SbomInventoryError("SBOM is not a CycloneDX document")
    components = document.get("components", [])
    if not isinstance(components, list) or len(components) > MAX_COMPONENTS:
        raise SbomInventoryError("SBOM component inventory is invalid or too large")

    packages: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        name = _bounded_text(component.get("name"), 512)
        if name is None:
            continue
        bom_ref = _bounded_text(component.get("bom-ref"), 1024)
        purl = _bounded_text(component.get("purl"), 1024)
        packages.append({
            "bom_ref": bom_ref,
            "name": name,
            "version": _bounded_text(component.get("version"), 256),
            "ecosystem": _ecosystem(purl),
            "component_type": _bounded_text(component.get("type"), 64),
            "purl": purl,
            "licenses": _licenses(component.get("licenses", [])),
            "security_status": "not_assessed",
            "highest_severity": None,
            "finding_count": 0,
            "finding_ids": [],
        })
    return sorted(packages, key=lambda item: (item["name"].lower(), item["version"] or ""))


def apply_security_status(
    packages: Sequence[dict[str, Any]],
    findings: Sequence[Mapping[str, object]],
    scanner_statuses: Mapping[str, str],
    *,
    package_identity_supported: bool,
) -> list[dict[str, Any]]:
    """Correlate structured dependency findings to inventory components."""
    grype_completed = scanner_statuses.get("grype") == "completed"
    attributed: list[dict[str, Any]] = []
    for package in packages:
        linked = [finding for finding in findings if _same_package(package, finding)]
        severities = [
            severity
            for finding in linked
            if isinstance((severity := finding.get("severity")), str)
        ]
        finding_ids = [
            finding_id
            for finding in linked
            if isinstance((finding_id := finding.get("id")), int)
        ]
        highest = max(severities, key=lambda value: _SEVERITY_WEIGHT.get(value, -1), default=None)
        if highest in {"CRITICAL", "HIGH"}:
            status = "failing"
        elif linked:
            status = "finding"
        elif grype_completed and package_identity_supported:
            status = "clear"
        else:
            status = "not_assessed"
        attributed.append({
            **package,
            "security_status": status,
            "highest_severity": highest,
            "finding_count": len(linked),
            "finding_ids": finding_ids,
        })
    return attributed


def supports_package_identity(content: bytes) -> bool:
    """Return whether a findings artifact explicitly supports package attribution."""
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(document, dict):
        return False
    capabilities = document.get("capabilities")
    return (
        isinstance(capabilities, list)
        and PACKAGE_IDENTITY_CAPABILITY in capabilities
    )


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bounded_text(value: object, limit: int) -> str | None:
    text = _text(value)
    return text[:limit] if text else None


def _ecosystem(purl: str | None) -> str | None:
    if not purl or not purl.startswith("pkg:"):
        return None
    package_type = purl[4:].split("/", 1)[0].split("@", 1)[0]
    return unquote(package_type)[:64] or None


def _licenses(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for entry in value[:16]:
        if not isinstance(entry, dict):
            continue
        expression = _text(entry.get("expression"))
        license_value = entry.get("license")
        label = expression
        if label is None and isinstance(license_value, dict):
            label = _bounded_text(license_value.get("id"), 256) or _bounded_text(
                license_value.get("name"), 256
            )
        elif label is not None:
            label = label[:256]
        if label and label not in found:
            found.append(label)
    return found


_SEVERITY_WEIGHT = {"UNKNOWN": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}


def _same_package(package: Mapping[str, object], finding: Mapping[str, object]) -> bool:
    package_purl = _canonical_purl(_text(package.get("purl")))
    finding_purl = _canonical_purl(_text(finding.get("package_purl")))
    if package_purl and finding_purl:
        return package_purl == finding_purl
    package_name = _fold(package.get("name"))
    finding_name = _fold(finding.get("package_name"))
    package_version = _text(package.get("version"))
    finding_version = _text(finding.get("package_version"))
    if not package_name or package_name != finding_name or not package_version or package_version != finding_version:
        return False
    package_ecosystem = _fold(package.get("ecosystem"))
    finding_ecosystem = _fold(finding.get("package_ecosystem"))
    return not package_ecosystem or not finding_ecosystem or package_ecosystem == finding_ecosystem


def _canonical_purl(value: str | None) -> str | None:
    return value


def _fold(value: object) -> str | None:
    text = _text(value)
    return text.casefold() if text else None
