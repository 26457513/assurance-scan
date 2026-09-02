# Ingest attempts

Status: binding audit and readiness contract.

## Purpose

An upload attempt is operational evidence, not a scan run. A scan run exists
only after a valid bundle commits successfully. Rejected authentication,
authorization, schema, quota and persistence work never creates a failed or
partial run.

## Persistence boundary

Persist an `ingest_attempt` only after the request has an authenticated
principal and can be bound to an enabled project without trusting payload
identity. Earlier failures produce rate-limited structured logs and metrics but
no project-visible record.

```text
ingest_attempts
  id UUID, correlation_id UUID UNIQUE, origin
  project_id, principal_kind, principal_reference_hash
  canonical_request_key_hash, outcome, reason_code, retryable
  wire_bytes, received_at, completed_at, expires_at
```

Allowed outcomes are `accepted`, `replayed`, `rejected` and `failed_internal`.
Reason codes are allowlisted and contain no source, token selector, JWT, branch,
path, message or payload value. Raw request bodies are never stored here.
Retain attempts for 30 days and aggregate operational metrics without project
or user identifiers after expiry.

The accepted attempt and completed run commit in the same transaction. A
rejected attempt commits independently after bounded request disposal. An
internal failure records an attempt only when doing so is safe and must not
mask the original response. Both local and GitHub uploads return the canonical
correlation ID as `request_id` on success and use that same ID in their safe
operational signals and persisted attempt evidence.

Quota usage is immutable evidence separate from mutable idempotency claims.
Every request that starts new work, including a retry after a failed or stale
claim, creates one usage charge in the same lock-held transaction that acquires
the claim. Completed replays, active duplicates and retained tombstones create
no charge. Local and GitHub reservations serialize through one database-backed
global quota lock so the shared in-flight ceiling remains correct across
processes and SQL dialects.

## Visibility

Project users may see the latest authenticated, project-bound GitHub rejection
as a safe reason, time and correlation ID. Local attempts require the same
project entitlement and exact submitting-user predicate as local runs.
Pre-authentication failures are operator-only and never attributed to a
repository in the UI.

## Request status

Local response-loss recovery uses:

```http
GET /api/v2/ingest/local-scans/requests/{client_request_uuid}
Authorization: Bearer asu_v1_...
```

Any active upload token for the same user may query the user's canonical
request UUID. Responses are `not_seen`, `processing`, `accepted` with run ID,
or `rejected` with safe code; they never return findings or another user's
request existence. Poll at the server-provided `Retry-After`, for at most 60
seconds, then retain the outbox bundle for manual retry.
