"""Cross-part validation for the disabled source-neutral v2 ingest workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from app.modules.atomic.ingestion.source_context import (
    sanitize_source_contexts,
    validate_source_context_links,
)
from app.modules.shared.contracts.findings import FindingPayload
from app.modules.shared.contracts.ingest_v2 import (
    ENVELOPE_PARTS,
    OPTIONAL_PARTS,
    REQUIRED_PARTS,
    SCHEMA_VERSION,
)
from app.modules.shared.contracts.source_context import SourceContextPayload

from .models import EnvelopeValidationError


def validate_envelope_relationships(parts: Mapping[str, Any | None]) -> None:
    """Validate invariants that cannot be expressed by one part's JSON Schema."""

    names = set(parts)
    if not REQUIRED_PARTS.issubset(names) or not names.issubset(set(ENVELOPE_PARTS)):
        raise EnvelopeValidationError("envelope part set is invalid")
    metadata = _required_object(parts, "metadata")
    findings_document = _required_object(parts, "findings")
    contexts_document = _required_object(parts, "source_contexts")
    if any(
        document.get("schema_version") != SCHEMA_VERSION
        for document in (metadata, findings_document, contexts_document)
    ):
        raise EnvelopeValidationError("all JSON parts must use schema version 2")
    branch = metadata.get("branch")
    ref = metadata.get("ref")
    if (branch is None and ref is not None) or (
        isinstance(branch, str) and ref != f"refs/heads/{branch}"
    ):
        raise EnvelopeValidationError("metadata branch and ref are inconsistent")

    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise EnvelopeValidationError("metadata artifacts are invalid")
    for name in OPTIONAL_PARTS:
        if artifacts.get(name) != (parts.get(name) is not None):
            raise EnvelopeValidationError(f"metadata artifact flag for {name} is inconsistent")

    scanners = findings_document.get("scanners")
    findings = findings_document.get("findings")
    contexts = contexts_document.get("contexts")
    if not isinstance(scanners, list) or not isinstance(findings, list) or not isinstance(contexts, list):
        raise EnvelopeValidationError("findings or source contexts are invalid")
    scanner_kinds = [item.get("kind") for item in scanners if isinstance(item, Mapping)]
    if len(scanner_kinds) != len(scanners) or len(scanner_kinds) != len(set(scanner_kinds)):
        raise EnvelopeValidationError("scanner records must have unique kinds")
    scanner_release = metadata.get("scanner_release")
    release_images = (
        scanner_release.get("images") if isinstance(scanner_release, Mapping) else None
    )
    if not isinstance(release_images, Mapping):
        raise EnvelopeValidationError("scanner release images are invalid")
    for scanner in scanners:
        kind = scanner["kind"]
        if scanner.get("status") != "skipped" and scanner.get("image") != release_images.get(kind):
            raise EnvelopeValidationError("scanner image does not match the release manifest")
    if any(
        not isinstance(finding, Mapping) or finding.get("scanner") not in scanner_kinds
        for finding in findings
    ):
        raise EnvelopeValidationError("every finding must reference a scanner record")
    for finding in findings:
        start = finding.get("line_start")
        end = finding.get("line_end")
        if isinstance(start, int) and isinstance(end, int) and end < start:
            raise EnvelopeValidationError("finding line range is invalid")

    try:
        validate_source_context_links(
            cast(list[FindingPayload], findings),
            cast(list[SourceContextPayload], contexts),
        )
        sanitize_source_contexts(cast(list[SourceContextPayload], contexts))
    except ValueError as exc:
        raise EnvelopeValidationError(str(exc)) from exc
    finding_by_key = {finding["finding_key"]: finding for finding in findings}
    for context in contexts:
        if not context.get("available"):
            continue
        for finding_key in context["finding_keys"]:
            finding = finding_by_key[finding_key]
            if (
                context.get("path") != finding.get("file_path")
                or context.get("highlight_start") != finding.get("line_start")
                or context.get("highlight_end") != finding.get("line_end")
            ):
                raise EnvelopeValidationError("source context does not match its finding")


def _required_object(parts: Mapping[str, Any | None], name: str) -> Mapping[str, Any]:
    value = parts.get(name)
    if not isinstance(value, Mapping):
        raise EnvelopeValidationError(f"required part {name} must be a JSON object")
    return value


__all__ = ["validate_envelope_relationships"]
