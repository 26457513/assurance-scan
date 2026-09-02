# Cutover and operations

Status: required runbook for WS7g.

## Pre-production

1. Create the GitHub App with the exact callbacks, permissions, events, and installation policy in [GitHub App access](../github/app-access.md).
2. Configure distinct development, staging, and production App registrations and OIDC audiences.
3. Complete the account-linking window and resolve every blocking preflight item
   in [Migration and data disposition](migration-and-data.md).
4. Apply migrations to a restored production-like backup and record duration,
   free space, row counts, foreign keys and checksums.
5. Exercise OAuth, installation, signed webhooks, missed-delivery repair,
   repository selection, entitlement refresh, OIDC replay rejection, local
   upload, rejected-attempt visibility and visibility denial.
6. Publish the scanner image by immutable digest and prove `latest` resolves and
   verifies to the approved digest.
7. Run the standard workflow against a disposable repository for both a direct
   default-branch push and the default-branch push produced by merging a pull
   request; confirm an unmerged branch does not upload.
8. Commit the new workflow in every pilot repository and classify every other
   production repository as `updated`, `scheduled` or `owner_action_required`.

## Atomic production cutover

1. Announce and enter the maintenance window.
2. Stop schedulers and workers that can poll or import GitHub results.
3. Take and verify a database backup.
4. Run the stopped-database identity preflight and compare it with the rehearsal.
5. Deploy the journalled migration and push-only backend with public ingest
   disabled.
6. Deploy the redesigned frontend and verified scanner/CLI release set.
7. Install or enable the production GitHub App for pilot repositories and
   process a signed repository refresh.
8. Enable GitHub/local ingest, run required smoke tests and inspect correlation
   IDs, ingest attempts, audit events and queue health.
9. Exit maintenance only after allowed and denied visibility checks pass.

Do not run polling and push ingestion concurrently. Old workflow uploads fail closed during maintenance rather than entering a legacy path.

## Removal checklist

- GitHub result poller and scheduler entry removed.
- Pull/import endpoints and jobs removed.
- Stored GitHub PAT fields, secrets, and configuration removed.
- Polling setup controls and copy removed.
- Polling metrics, alerts, and runbooks removed or renamed.
- Repository and deployment search finds no callable polling path.
- Previously stored PATs are revoked after the successful cutover.
- Legacy identity tables are removed only after the rollback window closes.

## Rollback

The rollback window lasts 24 hours from production enablement. During it, legacy
PATs and tables remain encrypted and disabled; polling never runs alongside
push ingestion. A rollback stops all ingress, disables the GitHub App endpoints,
restores the pre-cutover application and verified database backup, and only then
reactivates the former system. This is whole-release recovery, not a fallback in
the new application.

Accepted post-migration payload objects are written under a release-specific
quarantine prefix. Before rollback, preserve its signed manifest of request IDs,
object hashes and run keys for controlled replay after the next cutover; never
merge rows into an older schema ad hoc. Orphan objects remain inaccessible and
are deleted after the replay/retention decision.

At the end of the successful 24-hour window, take a new backup, revoke and erase
legacy PATs, remove legacy tables/configuration, and declare the old system
irreversible. Subsequent incidents use forward recovery; they do not restore
polling.

## Operational controls

- Audit OAuth connect/disconnect, installation changes, token lifecycle, entitlement refresh, accepted/rejected uploads, and administrative actions.
- Attach a correlation ID to every upload response and structured log.
- Alert on sustained authentication failures, replay attempts, quota rejection spikes, ingest latency, queue backlog, and entitlement-refresh failures.
- Cache GitHub entitlements only within the bounds in [GitHub App access](../github/app-access.md).
- Cache JWKS only within the bounds in [OIDC ingestion](../github/oidc-ingestion.md).
- Document key rotation, App suspension, compromised local token, and GitHub outage procedures before production enablement.
- Alert on default-branch metadata drift, webhook reconciliation drift and
  release-manifest/signature verification failure.

## Data lifecycle

OIDC replay records, raw upload objects, normalized findings, source contexts, audit events, and revoked-token records use the retention periods defined by their contracts. A scheduled deletion job must be observable, idempotent, and tested against legal-hold exclusions if those are introduced.
