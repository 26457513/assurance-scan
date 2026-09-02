# Webhook and repository sync

Status: binding GitHub state contract.

Implementation status: the additive access-plane schema, exact-byte signature
verification, bounded two-secret overlap, event/action classification and
30-day delivery claim are complete in dormant candidate code. HTTP exposure,
GitHub API fetching and retention scheduling remain disabled until their WS7c
slices pass independently.

## Endpoint security

```http
POST /api/v2/github/webhook
Content-Type: application/json
X-GitHub-Event: <event>
X-GitHub-Delivery: <guid>
X-Hub-Signature-256: sha256=<digest>
```

Reject bodies above 2 MiB before JSON parsing. Compute HMAC-SHA256 over the
unchanged raw body with the environment-specific webhook secret and compare in
constant time before parsing or queueing. Require one syntactically valid
delivery GUID, JSON content type and an allowlisted event/action pair. Never
trust proxy-rewritten bodies or the legacy SHA-1 signature.

Store the delivery GUID and body hash for 30 days. The same GUID and hash is an
idempotent success; the same GUID with another hash is a security event. Rotate
the webhook secret with an explicit two-secret overlap lasting at most one
hour, then erase the previous secret.

## Events

The App receives:

- `installation`: `created`, `deleted`, `suspend`, `unsuspend`,
  `new_permissions_accepted`;
- `installation_repositories`: `added`, `removed`;
- `repository`: `edited`, `renamed`, `transferred`, `archived`, `unarchived`,
  `deleted`;
- `installation_target`: `renamed`.

Unsupported actions are acknowledged without mutation and counted. Every
mutation is idempotent and enqueues a full installation or repository refresh;
payload display names are hints until confirmed through the GitHub API.

## Authoritative refresh

The transaction that projects one already-verified complete installation
snapshot is implemented in candidate code. The fixed-origin API adapter first
proves the linked user can access the returned installation, then signs a
short-lived App JWT, exchanges it for an installation token and fetches the
complete paginated repository scope. The projection creates projects only from
numeric repository IDs, blocks owner/installation reassignment pending audited
rebind, disables removed/transferred repositories, and immediately expires
affected GitHub-derived memberships. Six-hour repair scheduling remains a
separate disabled slice.

Webhooks reduce staleness but are not authorization evidence. Before every
GitHub Actions upload, create a short-lived installation token and call GitHub
`GET /repos/{owner}/{repo}`. Require:

- returned repository and owner numeric IDs equal the signed OIDC claims;
- the repository remains in the active installation scope;
- `ref == refs/heads/{returned default_branch}`;
- the repository and installation are not deleted, suspended, archived or
  disabled.

This one metadata request is authorization-time verification, not scan-result
polling. Failure or GitHub unavailability fails the upload closed. Human page
access continues to use the five-minute user-entitlement projection; local
upload retains its stricter 60-second rule.

Persist repository full name, owner ID, default branch, visibility,
archived/disabled state and `repository_verified_at`. Rename updates display
metadata. Transfer disables the project until an installation under the new
owner is verified and an audited rebind succeeds.

## Repair

A six-hour reconciliation job lists repositories for each active installation
and compares only installation/repository metadata. It neither lists Actions
runs nor downloads scan artifacts or source. It repairs missed webhook state,
records drift and uses ETags, pagination, rate-limit backoff and a per-installation
cursor. Installation deletion/suspension discovered by any request immediately
expires affected memberships and rejects uploads.
