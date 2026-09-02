# Production activation and recovery

Status: clean-launch runbook for WS7g.

The former production Droplet is not a migration source. Assurance Scan launches with GitHub-only identity and push-only ingestion; there is no account-linking window, polling overlap, PAT retention, dual-read or rollback to the old identity model.

## Protected production environment

The GitHub Environment `production` is the sole source for runtime configuration. The deployment validates every required value and the decoded App private key before stopping the service. It installs an immutable, root-only runtime configuration release and mounts the key read-only. The repository `.env` and any historical Droplet `.env` are not deployment inputs.

The required names and mappings are listed in the repository README. `APP_ACCESS_ENABLED` must be `true`, the public URL/domain must be the canonical production values, and `APP_ADMIN_GITHUB_IDS` must identify at least one protected administrator.

## Activation order

1. Configure the production GitHub App with callback `/auth/github/callback`, setup return `/api/v2/github/setup-return`, webhook `/api/v2/github/webhook`, expiring user tokens, selected-repository installation, and the minimal permissions in [GitHub App access](../github/app-access.md).
2. Populate and protect the `production` GitHub Environment.
3. Publish the reviewed application and scanner/CLI images by immutable digest.
4. Dispatch `deploy-production` for a full reviewed `main` revision. Confirm configuration validation, backup, migration to the declared schema head, immutable image identity and public health.
5. Sign in using an ID in `APP_ADMIN_GITHUB_IDS`, install the App for pilot repositories, and verify that repository selection and human visibility match GitHub.
6. Enable signed webhooks and exercise installation add/remove/suspend reconciliation.
7. Enable OIDC ingestion and run the standard workflow for a direct default-branch push and a merge-created default-branch push. Confirm feature branches do not upload.
8. Enable local token creation/local ingest and complete one private local scan from an entitled checkout.
9. Verify denied repository visibility, callback replay rejection, OIDC replay rejection, source context, audit evidence, queue health and quotas.

Each feature flag is changed in the protected Environment and deployed through the same validated workflow. A partial or disabled GitHub identity configuration fails closed on hosted deployments.

## Recovery

Before each deployment, retain the verified SQLite backup and prior immutable image identity. If migration or startup fails, keep all ingress closed and restore the matching application/database pair. Do not revive polling, PAT endpoints, Google login or manual project grants. Once a new upload has been accepted, prefer forward recovery; restoring an older database would discard accepted evidence and requires an explicit operator decision.

## Operational controls

- Audit GitHub sign-in/logout, installation changes, token lifecycle, entitlement refresh, uploads and role changes.
- Attach a correlation ID to every upload response and structured log.
- Alert on authentication/replay failures, quota spikes, ingest latency, queue backlog, entitlement-refresh failures, webhook drift and signature verification failures.
- Rotate App, webhook, session and encryption secrets through the protected Environment; preserve the active token-encryption key whenever encrypted user authorizations must remain readable.
- Treat GitHub unavailability as fail-closed for entitlement refresh and new uploads; retained authorized history remains subject to its last valid grant and expiry contract.
