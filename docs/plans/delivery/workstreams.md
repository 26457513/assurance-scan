# Delivery workstreams

Status: WS6a–WS7f are implemented and quality-gated. WS7g clean-launch
implementation is in progress; production activation remains deferred.

## Completed foundation

The structural refactor, local scan contracts, local authentication/upload, container runtime, UI integration, and initial rollout work are recorded in [Completed work](../history/completed-work.md). They remain the foundation; this plan does not repeat their implementation detail.

## WS6a — source context parity

Status: complete in the candidate code path (2 September 2026). The gate built
the candidate CI/CLI images locally; neither was released or enabled in
production.

Goal: make findings from GitHub Actions and local scans carry the same bounded, redacted source evidence.

Deliverables:

1. implement the shared source-context extractor and schema;
2. integrate it into the common scanner/result producer;
3. validate and persist contexts through the shared ingest workflow;
4. render the same context component for both origins;
5. add secret-redaction, truncation, malformed-input, and XSS tests;
6. produce a candidate scanner image, but do not enable the new payload in production yet.

Acceptance: the same fixture scanned through both origins produces equivalent findings and context, subject only to run identity and origin metadata.

## WS6b — local bootstrap hardening

Status: complete in the candidate code path (2 September 2026). The verified
CLI release and signed manifest still require the governed release/promotion
process before production use.

Implement [Local bootstrap and trust](../local/bootstrap-and-trust.md), including
signed-manifest verification, wrapper compatibility, local-daemon enforcement,
explicit sibling mounts and socket-GID/rootless tests.

Acceptance: a verified release scans on qualified macOS/Linux hosts; tampered
manifest/image, stale wrapper, remote daemon, unsafe path and inaccessible socket
all fail before scanner execution.

## WS7a — frozen contracts and security fixtures

Status: complete in the disabled candidate code path (2 September 2026). No v2
transport route, producer, authentication adapter or persistence path is enabled.

Freeze v2 JSON Schemas, JCS hashing vectors, OIDC/JWKS fixtures, webhook fixtures,
ingest-attempt reason codes, quotas and API problem responses. No runtime path is
enabled.

Acceptance: producers and server pass the same golden contract corpus and reject
every negative fixture identically.

## WS7b — GitHub identity foundation

Status: superseded by the agreed clean-launch model. Permanent GitHub OAuth with
PKCE, independent pre-authentication state, immutable numeric identity and
digest-only server sessions replaces the temporary Google-account linking and
identity-migration design. No email-based merge or compatibility path ships.

## WS7c — GitHub App access plane

Status: complete in the disabled candidate code path (2 September 2026). The
dormant installation/repository schema, independent
single-use setup state, raw-body webhook authentication/delivery idempotency,
atomic authoritative repository projection, fixed-origin GitHub API client and
setup-return workflow, and raw-body webhook HTTP boundary are complete in
candidate code. Setup and webhook exposure are independently disabled by
default. Authenticated mutations now create installation-ID-bound, lease-safe
durable work with bounded retry state. A restart-safe worker now performs full
App-authenticated refresh, or immediate ID-only suspension/deletion, while the
feature remains disabled. The six-hour full-installation repair loop, 30-day
delivery cleanup and installation-scoped five-minute user-entitlement refresh
are complete in candidate code but are not production-enabled. Repository
changes invalidate both grants and freshness markers, and failed refreshes fail
closed. Explicit GitHub primary and secondary rate-limit deferral and safe
single-page conditional ETag revalidation are complete. Multi-page progress is
persisted and stale-worker fenced; an interrupted traversal restarts from page
one because GitHub pagination is not an immutable snapshot, and partial scope
is never projected.

Implement installation return, signed webhooks, repository reconciliation and
expiring query-time entitlements using the WS7b GitHub identity foundation.

Acceptance: installation/repository/team access changes converge within their
declared bounds, and denied users receive no project existence signal.

## WS7d — push-only ingestion

Status: complete in the disabled candidate code path (2 September 2026).
Strict OIDC verification, single-use JWT replay evidence, live authoritative
repository authorization, the validated v2 envelope, repository/run/attempt
idempotency with five-minute fenced leases, and transactionally bound shared
result persistence are implemented and quality-gated. The strict streaming HTTP
adapter now authenticates OIDC before reading the body, enforces the frozen
multipart limits, binds signed idempotency identity, performs live repository
authorization and invokes that shared persistence path. It is registered but
disabled by default. Repository/hour and owner/day GitHub quotas, the shared
local/GitHub in-flight ceiling, safe project-bound GitHub ingest-attempt
evidence and 30-day evidence expiry are implemented and quality-gated. Accepted
attempts commit with their result graph; replays and rejections commit
independently; internal-failure evidence cannot mask the original failure.
Local and GitHub ingestion now use the same attempt evidence, correlation-ID
contract and SQLite-backed cross-process quota lock. An immutable usage ledger means
failed or stale retries consume fresh capacity while completed replays do not,
and mutable claim cleanup cannot restore spent capacity. Candidate migrations
also retain tombstones when either origin's run is deleted and expire attempts,
tombstones and usage evidence through bounded common-retention batches. Both
HTTP boundaries emit the same allowlisted, secret-free terminal request signal
with the response correlation ID; non-upload local endpoints do not pollute
upload metrics. Deployment may lower, but cannot raise, the frozen per-origin
and shared limits. No production v2 route has been enabled.

Implement strict GitHub OIDC verification, authoritative repository refresh,
shared v2 ingestion, ingest attempts, replay protection and cross-origin limits.
Keep the public endpoint disabled outside test environments.

Acceptance: only an installed repository's verified default-branch push is
accepted; every other issuer/audience/event/ref/replay/identity case fails closed.

## WS7e — producer and standard workflow

Status: implemented in the disabled candidate path; production enablement remains
part of WS7g.

Update the common scanner producer, verified CI image release and generated
default-branch-only workflow. Produce source contexts from the exact scan
snapshot and upload through the OIDC stdin boundary.

Acceptance: direct and merge-created default-branch pushes each yield a
conformant v2 result; unmerged branch pushes run no scan job and make no upload.

## WS7f — Setup and access UI

Status: complete in the disabled candidate code path (2 September 2026).
The typed Setup projection and controller, GitHub/local access lanes, compact
readiness, private-local visibility predicates and replacement navigation are
implemented. Component coverage exercises all nine states; browser checks cover
the feature-gated failure path at desktop and 360 px without overflow or console
errors. Production state-transition verification remains part of WS7g because
GitHub App access is disabled by default.

Implement [Setup experience](../setup/experience.md) and
[Setup state model](../setup/state-model.md), plus project/run query predicates
and compact ingest-attempt readiness.

Acceptance: every state has component, accessibility and browser tests; selection
does not flicker; local data remains invisible to another entitled user.

## WS7g — removal and production cutover

Status: candidate implementation in progress (3 September 2026). Permanent
GitHub sign-in, push-only runtime wiring, legacy route/UI removal and protected
Environment deployment configuration are implemented; full quality gate and
production activation evidence remain.

Goal: replace every polling/pull path with GitHub-authorized, push-only ingestion and ship the redesigned setup experience.

Remove pollers, pull endpoints, scheduler entries, polling UI/configuration and
obsolete tests; validate the clean launch and execute
[Cutover and operations](cutover-and-operations.md).

Acceptance: the full definition of done below passes in production, legacy PAT
storage is absent, and the deployment has no callable scan-result polling path.

Each slice merges only after its own quality gate. New ingestion remains disabled
until WS7g, so incremental implementation creates neither compatibility behavior
nor a dual ingestion mode.

## Cross-workstream invariants

- Project identity and visibility follow [Identity and visibility](../shared/identity-and-visibility.md).
- Upload formats follow [Result contract](../shared/result-contract.md).
- Local authentication follows [Local authentication and upload](../local/authentication-and-upload.md).
- GitHub workload identity follows [OIDC ingestion](../github/oidc-ingestion.md).
- GitHub human access follows [GitHub App access](../github/app-access.md).
- Every slice satisfies [Quality gates](quality-gates.md) before merge.

## Definition of done

WS7g is complete only when production has accepted both a direct default-branch
push and a merged pull request's resulting default-branch push, rejected a
non-push event, and accepted a local scan; visibility has been verified with
allowed and denied users; source context is present for supported findings;
and no production code path can poll GitHub for scan results.
