# Local authentication and upload

## Token lifecycle

Tokens have form `asu_v1_<selector>.<secret>` with independent random 12-byte
selector and 32-byte secret. Store only selector plus SHA-256 secret digest;
compare in constant time and perform a dummy comparison for unknown selectors.

Scope is exactly `scans:upload`. Labels are NFKC-normalized, control-free,
1–64 characters and unique among the user's active tokens. Expiry choices are
30/90/180 days, default 90, maximum 365. Maximum five active tokens/user.
Plaintext appears once. List shows label, scope, creation, expiry, last use and
revocation; deletion is soft revocation so historical audit references remain.

“Machine” is a label and audit aid, not device attestation. The credential is a
bearer token usable wherever copied. Setup and CLI state this plainly and direct
users to revoke it immediately after loss or suspected copying.

Authentication failures for malformed, unknown, expired, revoked and disabled-
user credentials return the same generic `401`. Never log Authorization.
Token creation responses use `Cache-Control: no-store`, `Pragma: no-cache` and
`Referrer-Policy: no-referrer`.

Token creation requires a GitHub-authenticated Assurance Scan account. Browser
mutation uses exact-origin validation and signed double-submit CSRF. Basic/auth-
off deployments disable local token creation and ingest.

Disconnecting GitHub revokes the GitHub App user token and every active local
scan token, hides project/run access and requires new local tokens after the
same immutable GitHub account is reconnected. Historical data remains under
retention but is not visible without restored entitlement.

## CLI validation

```http
GET /api/v2/ingest/whoami
Authorization: Bearer asu_v1_...
```

Return account, immutable GitHub user ID, token label/scope/expiry and whether
local ingest is enabled. Login persists credentials only after success.

## Upload endpoint

```http
POST /api/v2/ingest/local-scans
Authorization: Bearer asu_v1_...
Idempotency-Key: <canonical lowercase UUIDv4>
Content-Type: multipart/form-data
```

The key must equal `metadata.request_id`. Metadata includes repository, branch,
commit/object format, dirty flag, source hash/manifest version,
`cli_installation_id`, CLI/build/image provenance and scanner digests. The
client cannot assert origin, account, permission or project ID.

The route authenticates the Assurance Scan token, resolves the registered
GitHub repository, and revalidates write-or-higher GitHub entitlement no older
than 60 seconds. If GitHub cannot verify after that window, upload fails closed
with a retained, non-automatically-retried outbox bundle. The server assigns
`origin=local`, submitter and private ownership.

Success is `201`; matching replay is `200`; matching in-progress is `202` with
the authenticated request-status URL from [Ingest attempts](../shared/ingest-attempts.md)
and `Retry-After`. Stable errors follow the shared contract.

Automatic retry covers network failure, `408`, `429` and `500/502/503/504` with
full jitter at 1, 3 and 9 seconds, maximum three retries. Validation,
authorization, project and idempotency conflicts remain for manual recovery.

## Abuse controls

- upload attempts: 10/token/hour and 100/user/day;
- concurrency: 1/token, 2/user, 4/instance;
- accepted bytes: 500 MiB/user/day;
- retained raw artifacts: 1 GiB/user, 5 GiB/instance;
- authentication failures: 20/IP and 10/selector per 10 minutes;
- token creation: 5/user/hour.

`429` includes `Retry-After`; wire limit is `413`; retained-storage exhaustion
is `507 storage_quota_exceeded`. Limits may be lowered by deployment config.
The four-local limit sits inside the shared eight-upload instance ceiling.
