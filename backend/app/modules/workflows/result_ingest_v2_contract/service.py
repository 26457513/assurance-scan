"""Cross-part validation for the disabled source-neutral v2 ingest workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from app.modules.atomic.ingestion.envelope_contract import (
    CanonicalJSONError,
    canonical_json_bytes,
    envelope_payload_hash,
    parse_strict_json,
)

from app.modules.atomic.ingestion.source_context import (
    sanitize_source_contexts,
    validate_source_context_links,
)
from app.modules.shared.contracts.findings import FindingPayload
from app.modules.shared.contracts.ingest_v2 import (
    ENVELOPE_PARTS,
    ENVELOPE_LIMITS_V2,
    OPTIONAL_PARTS,
    REQUIRED_PARTS,
    SCHEMA_VERSION,
)
from app.modules.shared.contracts.source_context import SourceContextPayload

from .models import EnvelopeSchemaValidator, EnvelopeValidationError, ValidatedEnvelopeV2


_PART_LIMITS = {
    "metadata": ENVELOPE_LIMITS_V2.metadata_bytes,
    "findings": ENVELOPE_LIMITS_V2.findings_bytes,
    "source_contexts": ENVELOPE_LIMITS_V2.source_contexts_bytes,
    "sarif": ENVELOPE_LIMITS_V2.sarif_bytes,
    "sbom": ENVELOPE_LIMITS_V2.sbom_bytes,
}


def build_validated_envelope_v2(
    raw_parts: Mapping[str, bytes],
    *,
    schema_validator: EnvelopeSchemaValidator,
) -> ValidatedEnvelopeV2:
    """Parse, schema-check, cross-check and canonicalize one complete v2 envelope."""
    names = set(raw_parts)
    if not REQUIRED_PARTS.issubset(names) or not names.issubset(set(ENVELOPE_PARTS)):
        raise EnvelopeValidationError("envelope part set is invalid", code="unexpected_part")
    if sum(len(value) for value in raw_parts.values()) > ENVELOPE_LIMITS_V2.parsed_bytes:
        raise EnvelopeValidationError("parsed envelope is too large", code="wire_limit_exceeded")

    documents: dict[str, Mapping[str, Any] | None] = {}
    canonical_parts: dict[str, bytes] = {}
    for name in ENVELOPE_PARTS:
        raw = raw_parts.get(name)
        if raw is None:
            documents[name] = None
            continue
        if len(raw) > _PART_LIMITS[name]:
            raise EnvelopeValidationError(f"part {name} is too large", code="wire_limit_exceeded")
        try:
            parsed = parse_strict_json(raw, maximum_depth=ENVELOPE_LIMITS_V2.json_depth)
        except CanonicalJSONError as exc:
            code = "duplicate_json_key" if "duplicate JSON key" in str(exc) else "invalid_json"
            raise EnvelopeValidationError(f"part {name} is invalid JSON", code=code) from exc
        if not isinstance(parsed, Mapping):
            raise EnvelopeValidationError(
                f"part {name} must be a JSON object",
                code="schema_validation_failed",
            )
        document = dict(parsed)
        documents[name] = document
        canonical_parts[name] = canonical_json_bytes(document)

    for part in REQUIRED_PARTS:
        required_document = documents[part]
        if required_document is None or not schema_validator.validate(part, required_document):
            raise EnvelopeValidationError(
                f"part {part} does not satisfy its schema",
                code="schema_validation_failed",
            )
    validate_envelope_relationships(documents)
    hash_parts = {name: documents[name] for name in ENVELOPE_PARTS}
    return ValidatedEnvelopeV2(
        metadata=_required_object(documents, "metadata"),
        findings=_required_object(documents, "findings"),
        source_contexts=_required_object(documents, "source_contexts"),
        sarif=documents["sarif"],
        sbom=documents["sbom"],
        payload_hash=envelope_payload_hash(hash_parts),
        canonical_parts=canonical_parts,
    )


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
    _validate_optional_artifacts(parts)

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


def _validate_optional_artifacts(parts: Mapping[str, Any | None]) -> None:
    sarif = parts.get("sarif")
    if sarif is not None and (
        not isinstance(sarif, Mapping)
        or sarif.get("version") != "2.1.0"
        or not isinstance(sarif.get("runs"), list)
    ):
        raise EnvelopeValidationError(
            "SARIF artifact does not satisfy the supported profile",
            code="schema_validation_failed",
        )
    sbom = parts.get("sbom")
    if sbom is not None and (
        not isinstance(sbom, Mapping)
        or sbom.get("bomFormat") != "CycloneDX"
        or not isinstance(sbom.get("specVersion"), str)
        or not isinstance(sbom.get("components", []), list)
    ):
        raise EnvelopeValidationError(
            "SBOM artifact does not satisfy the supported CycloneDX profile",
            code="schema_validation_failed",
        )


def _required_object(parts: Mapping[str, Any | None], name: str) -> Mapping[str, Any]:
    value = parts.get(name)
    if not isinstance(value, Mapping):
        raise EnvelopeValidationError(f"required part {name} must be a JSON object")
    return value


__all__ = ["build_validated_envelope_v2", "validate_envelope_relationships"]
