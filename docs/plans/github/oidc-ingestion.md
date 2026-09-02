# GitHub Actions OIDC push ingestion

## Endpoint and issuer

```http
POST /api/v2/ingest/github-actions
Authorization: Bearer <GitHub OIDC JWT>
Idempotency-Key: <repository-id>:<run-id>:<attempt>
Content-Type: multipart/form-data
```

Audience is exactly `${PUBLIC_BASE_URL}/api/v2/ingest/github-actions` with
canonical HTTPS origin and no trailing slash. Each environment has its own exact
audience; wildcards and alternate audiences are rejected.

Issuer is exactly `https://token.actions.githubusercontent.com`. Discovery is
fixed to `https://token.actions.githubusercontent.com/.well-known/openid-configuration`
and JWKS to `https://token.actions.githubusercontent.com/.well-known/jwks`;
neither request follows redirects. Cache keys for at most one hour and refresh
once on an unknown `kid`. After cache expiry, JWKS outage fails closed.

Reject an Authorization header or compact JWT above 16 KiB. Require a JSON JOSE
header with `typ=JWT`, `alg=RS256`, one 1–128 byte ASCII `kid`, and no `jku`,
`x5u` or embedded key. Reject duplicate JSON keys, an audience array and any
audience other than the one exact string. Time claims allow 60 seconds clock
skew and `exp - iat` may not exceed ten minutes.

## Claim policy

Require and exactly validate `sub`, `repository_id`, `repository_owner_id`,
`repository`, `run_id`, `run_number`, `run_attempt`, `sha`, `ref`,
`event_name`, `actor`, `actor_id`, `workflow_ref`, `workflow_sha`, `iat`, `nbf`,
`exp` and `jti`. `job_workflow_ref` is not required because it is a
reusable-workflow claim and the standard integration runs the public container
directly. Repository/owner IDs must match the active installation trust;
duplicated payload metadata must equal signed claims.

Accepted events in v1:

- `push` only when `ref` is the repository's currently verified default branch;
- `pull_request`, `pull_request_target`, `workflow_dispatch`, schedules and all
  other events are rejected.

Require workflow path `.github/workflows/assurance-scan.yml` in `workflow_ref`
and require `workflow_sha == sha`. `workflow_ref` must equal
`{repository}/.github/workflows/assurance-scan.yml@{ref}`. Require `sub` to
equal `repo:{repository}:ref:{ref}`, using GitHub's percent-encoding rules, and
require `ref` to equal `refs/heads/{currently_verified_default_branch}`.
GitHub's numeric identity/run claims are strict positive base-10 digit strings,
parsed into integers within database bounds; `iat`, `nbf` and `exp` are JSON
integers. Actor fields
are provenance, not authorization: repository installation scope and the signed
default-branch workflow identity authorize the workload. Do not authorize from
actor name, repository-name suffix or substring matching.

Before accepting the bundle, perform the authoritative repository verification
in [Webhook and repository sync](webhook-and-repository-sync.md). Repository
transfer follows the audited rebind rule; rename with unchanged IDs updates
display metadata.

Use `jti` as replay evidence, not run identity. Retain consumed `jti` values
until token expiry plus five minutes. A new JWT may replay the same canonical
run/payload after response loss; conflicting content is rejected.

## Secure token transport

The scanner container runs and writes the hashed bundle before OIDC exists. A
small runner-side upload step then:

1. requests a JWT using GitHub's runner-provided OIDC request URL/token and the
   exact audience;
2. masks the JWT immediately;
3. passes it through stdin to an upload-only CLI container;
4. mounts the result bundle read-only and does not mount the Docker socket;
5. closes stdin and discards the JWT after the request.

JWTs and GitHub's OIDC request token never appear in Docker arguments, image
metadata, persisted environment files, artifacts or logs.

## Retry and abuse policy

Retry only network failure, `408`, `429` and `500/502/503/504`. Obtain a fresh
JWT per retry; reuse canonical idempotency key and exact bundle. Use full jitter
at 1, 3 and 9 seconds, maximum three retries and 60 seconds total.

Shipping limits:

- 30 upload attempts/repository/hour;
- 500 attempts/owner/day;
- 2 in-flight/repository and 8/instance;
- 2 GiB accepted bytes/owner/day;
- shared envelope byte/finding limits still apply.

Rate/concurrency returns `429` with `Retry-After`; limits may be configured
downward. Public pre-auth parsing is bounded to the Authorization header and
streaming request ceiling before expensive work.

The instance limit is shared with local ingestion: at most eight total upload
workflows may be active, of which at most four may be local.

## Failure model

Findings do not fail the workflow. Scanner faults remain child statuses when a
valid bundle can be produced. OIDC, authorization, contract, redaction or upload
failure fails the upload step visibly. Assurance Scan downtime requires rerun;
there is no pull recovery. Logs contain only allowlisted IDs/reason codes, never
raw JWT or source.
