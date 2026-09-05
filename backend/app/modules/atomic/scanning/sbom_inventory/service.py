"""Extract a bounded, presentation-neutral inventory from CycloneDX JSON."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from urllib.parse import unquote


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

    vulnerability_inventory = document.get("vulnerabilities")
    has_vulnerability_inventory = isinstance(vulnerability_inventory, list)
    affected = _affected_component_counts(vulnerability_inventory)
    packages: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        name = component.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        bom_ref = _text(component.get("bom-ref"))
        purl = _text(component.get("purl"))
        packages.append({
            "bom_ref": bom_ref,
            "name": name.strip(),
            "version": _text(component.get("version")),
            "ecosystem": _ecosystem(purl),
            "component_type": _text(component.get("type")),
            "purl": purl,
            "licenses": _licenses(component.get("licenses", [])),
            "vulnerability_count": (
                affected[bom_ref] if bom_ref and has_vulnerability_inventory else None
            ),
        })
    return sorted(packages, key=lambda item: (item["name"].lower(), item["version"] or ""))


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _ecosystem(purl: str | None) -> str | None:
    if not purl or not purl.startswith("pkg:"):
        return None
    package_type = purl[4:].split("/", 1)[0].split("@", 1)[0]
    return unquote(package_type) or None


def _licenses(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        expression = _text(entry.get("expression"))
        license_value = entry.get("license")
        label = expression
        if label is None and isinstance(license_value, dict):
            label = _text(license_value.get("id")) or _text(license_value.get("name"))
        if label and label not in found:
            found.append(label)
    return found


def _affected_component_counts(value: object) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not isinstance(value, list):
        return counts
    for vulnerability in value:
        if not isinstance(vulnerability, dict):
            continue
        affects = vulnerability.get("affects", [])
        if not isinstance(affects, list):
            continue
        for affected in affects:
            if isinstance(affected, dict):
                ref = _text(affected.get("ref"))
                if ref:
                    counts[ref] += 1
    return counts
