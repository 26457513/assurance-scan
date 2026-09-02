# Shared result contract

## Envelope v2

Both origins submit `multipart/form-data` with exactly:

```text
metadata         required JSON
findings         required JSON; includes scanner status/duration records
source_contexts  required JSON; may contain an empty list
sarif            optional, at most one
sbom             optional, at most one
```

There is no separate `scanner_statuses` multipart part. Unknown/duplicate parts,
duplicate JSON keys, unknown schema fields, archives and excessive nesting are
rejected. Filenames are never authority. Checked-in JSON Schemas lock every
required field, scanner/status vocabulary and artifact relationship.

JSON parts use `application/json; charset=utf-8`; SARIF and SBOM declare their
registered JSON media type or `application/json`. Reject transfer/content
encoding and compressed/archive parts. The 32 MiB total wire limit dominates
the individual per-part limits, so maximum-sized optional parts cannot all
appear together.

`asu_v1` identifies the independent local bearer-token format; it does not mean
the upload envelope is v1.

## Limits

Limits are enforced at TLS proxy and application boundaries while streaming:

- 32 MiB total wire; 64 MiB parsed/decompressed aggregate;
- 64 KiB metadata, 10 MiB findings, 16 MiB SARIF, 16 MiB SBOM;
- 20,000 findings, 32 scanner records, JSON depth 20;
- paths 1,024 characters; messages 8,192 characters;
- source-context limits are owned by `source-context.md`.

Configuration may lower but not raise shipping ceilings. Errors use
`application/problem+json` with stable `code`, `retryable`, correlation ID and
safe limit metadata. Payload content and credentials are never echoed.

## Source-neutral ingestion

Authentication adapters produce an `UploadPrincipal`; the common workflow then
performs project resolution, authorization, schema validation, normalization,
redaction, quota reservation, idempotency and one-transaction persistence.
Run, scanner records, artifacts, findings, contexts, accepted ingest attempt
and completed claim commit together.

A newly uploaded run is `completed` when a valid bundle exists even if
individual scanners failed; scanner failures remain explicit children. Bundle
validation, authorization, orchestration or persistence failure creates no run
and is represented by [Ingest attempts](ingest-attempts.md). Retained historical
failed runs remain read-only legacy records.

## Idempotency

Local key: `(submitted_by_user_id, client_request_uuid)`.
GitHub key: `(github_repository_id, github_run_id, run_attempt)`.

JSON schemas forbid non-integer numbers. Canonical JSON uses RFC 8785/JCS UTF-8.
`payload_hash` is SHA-256 over the ASCII domain separator
`assurance-scan-envelope-v2`, followed by NUL-delimited tuples in fixed order
`metadata`, `findings`, `source_contexts`, `sarif`, `sbom`; each tuple contains
part name, byte length and SHA-256 of its validated canonical bytes. Missing
optional parts use an explicit `absent` tuple. Matching replay returns the existing run;
different content returns `409 idempotency_conflict`. A five-minute fenced
lease with heartbeat protects in-progress ingestion. After run deletion, a
content-free tombstone rejects key reuse for 30 days.

## Retention

- Raw SARIF/SBOM/findings/source-context blobs: 30 days.
- Normalized runs/findings/bounded contexts: 365 days.
- Inactive local-token audit metadata: 400 days.
- Ingest-attempt evidence: 30 days.
- Local outbox: seven days and 1 GiB by default.

Run/project deletion hides immediately and purges payload/normalized content
within 24 hours, retaining only bounded audit/idempotency tombstones. Cleanup is
idempotent, observable and tested.
